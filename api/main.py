import hashlib
import os
import json
import re
import uuid
from pathlib import Path

import uvicorn
from fastapi import (
    BackgroundTasks, Depends, FastAPI, File, Form, Header,
    HTTPException, Query, Request, UploadFile,
)
from fastapi.concurrency import run_in_threadpool
from fastapi.staticfiles import StaticFiles
from contextlib import ExitStack, asynccontextmanager

from dotenv import load_dotenv
load_dotenv(override=True)
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from models.base import ChatResponse, ChatMessage

from pydantic import BaseModel

from session.repository import PostgresSessionRepository
from session.service import SessionService
from session.runs import KeyedLocks, SessionBusyError
from session.memory_jobs import MemoryJobs
from api.streaming import ChatStreamingResponse
from knowledge.documents import KbDocumentRepository
from knowledge.server import KnowledgeService
from utils.logger_tool import logger
from utils.md_to_content_list import md_to_content_list
from agent.runtime import AgentRuntime
from agent.memory import MemoryExtractor
from agent.tools.weather import WeatherTool
from agent.tools.websearch import WebSearchTool
from agent.tools.academic_calendar import AcademicCalendarTool
from agent.tools.knowledge_search import KnowledgeSearchTool
from models.dashscope.Qwen_model import DashScopeProvider
from models.openai.ChatGPT import OpenAIProvider
from utils.prompts_loader import get_prompt

from utils.query_tool import build_query

# ---------- 图片上传 ----------
UPLOAD_DIR = Path(__file__).resolve().parent.parent / "data" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
MAX_IMAGE_BYTES = 10 * 1024 * 1024

# ---------- 知识库文档上传 ----------
KNOWLEDGE_UPLOAD_DIR = Path(__file__).resolve().parent.parent / "data" / "knowledge_uploads"
KNOWLEDGE_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_DOC_TYPES = {".md", ".txt", ".pdf", ".doc", ".docx"}
MAX_DOC_BYTES = 50 * 1024 * 1024
_UNSAFE_CHARS = {chr(c) for c in (92, 47, 58, 42, 63, 34, 60, 62, 124)} | {chr(i) for i in range(32)}


class ChatRequest(BaseModel):
    session_id: str
    text: str
    images: list[str] = []
    reasoning: bool | None = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    dsn = os.getenv("LANGGRAPH_POSTGRES_URI")
    if not dsn:
        raise RuntimeError("缺少 LANGGRAPH_POSTGRES_URI 配置")

    with ExitStack() as resources:
        # checkpoint 连接池
        saver_pool = ConnectionPool(
            dsn,
            min_size = 1,
            max_size = 10,
            open = False,
            kwargs = {
                "autocommit": True,
                "prepare_threshold": 0,
                "row_factory": dict_row
            }
        )
        resources.callback(saver_pool.close)
        # 业务池
        pg_pool = ConnectionPool(
            dsn,
            min_size = 1,
            max_size = 10,
            open = False,
            kwargs = {
                "autocommit": True,
                "row_factory": dict_row
            }
        )
        resources.callback(pg_pool.close)
        saver_pool.open()
        pg_pool.open()
        saver_pool.wait(timeout=10)
        pg_pool.wait(timeout=10)

        saver = PostgresSaver(
            saver_pool,
            serde=JsonPlusSerializer(
                allowed_msgpack_modules=[
                    ChatMessage,
                    ChatResponse
                ]
            )
        )
        saver.setup()

        with pg_pool.connection() as conn:
            PostgresSessionRepository(conn).setup()
            kb_repo = KbDocumentRepository(conn)
            kb_repo.setup()
            stalled = kb_repo.reconcile_after_restart()
            if stalled:
                logger.warning("知识库：%d 个在途任务因服务重启被标记为失败", stalled)

        # 知识库服务只建一次：Milvus 客户端、embedding、reranker、MinerU 解析器都复用。
        # 初始化失败不能拖垮整个服务 —— 聊天照常，知识库接口返回 503。
        try:
            kb_service = KnowledgeService()
            app.state.knowledge = kb_service
            app.state.kb_error = None
            resources.callback(kb_service.close)
        except Exception as exc:
            logger.exception("知识库服务初始化失败")
            kb_service = None
            app.state.knowledge = None
            app.state.kb_error = f"{type(exc).__name__}: {exc}"

        app.state.runs = KeyedLocks()
        app.state.pg_pool = pg_pool
        app.state.runtime = AgentRuntime(
            model = DashScopeProvider(model="qwen3.8-flash"),
            tools = [
                WeatherTool(),
                WebSearchTool(),
                AcademicCalendarTool(),
                KnowledgeSearchTool(kb_service),
            ],
            prompts = get_prompt(),
            checkpointer = saver,
            summary_model = DashScopeProvider(model="qwen3.7-flash"),
        )
        # 记忆抽取用便宜的小模型，与摘要模型共用即可
        app.state.memory_extractor = MemoryExtractor(
            DashScopeProvider(model="qwen3.7-flash")
        )
        app.state.memory_jobs = MemoryJobs(pg_pool, app.state.memory_extractor)
        yield


def get_current_user(x_user_id: str | None = Header(default=None)) -> dict:

    if not x_user_id:
        raise HTTPException(
            status_code = 401,
            detail = "缺少用户标识"
        )
    return {
        "id": x_user_id
    }

def get_service(request: Request):
    pool: ConnectionPool = request.app.state.pg_pool

    with pool.connection() as conn:
        yield SessionService(
            PostgresSessionRepository(conn),
            request.app.state.runtime,
            runs=request.app.state.runs,
        )


def get_knowledge(request: Request) -> KnowledgeService:
    service = getattr(request.app.state, "knowledge", None)
    if service is None:
        raise HTTPException(
            status_code=503,
            detail=f"知识库未就绪：{getattr(request.app.state, 'kb_error', '未知原因')}",
        )
    return service


def get_kb_repo(request: Request):
    pool: ConnectionPool = request.app.state.pg_pool
    with pool.connection() as conn:
        yield KbDocumentRepository(conn)

app = FastAPI(lifespan=lifespan)

@app.get("/api/sessions")
async def list_sessions(
        user: dict = Depends(get_current_user),
        service: SessionService = Depends(get_service)
):
    return service.list_sessions(user["id"])


@app.post("/api/sessions")
async def create_session(
        user: dict = Depends(get_current_user),
        service: SessionService = Depends(get_service)
):
    return service.create_session(user["id"])


@app.get("/api/sessions/{session_id}/messages")
async def get_messages(
        session_id: str,
        user: dict = Depends(get_current_user),
        service: SessionService = Depends(get_service)
):
    if service.get_session(user["id"], session_id) is None:
        raise HTTPException(status_code=404, detail=f"会话不存在：{session_id}")
    return service.history(user["id"], session_id)


@app.delete("/api/sessions/{session_id}")
async def delete_session(
        session_id: str,
        user: dict = Depends(get_current_user),
        service: SessionService = Depends(get_service)
):
    try:
        deleted = service.delete_session(user["id"], session_id)
    except SessionBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail=f"会话不存在：{session_id}")
    return {"deleted": session_id}


@app.post("/api/chat")
async def chat(
        req: ChatRequest,
        request: Request,
        background: BackgroundTasks,
        user: dict = Depends(get_current_user),
):

    root = Path(__file__).resolve().parent.parent
    abs_images = [(root / p).resolve() for p in req.images]
    # 只允许 data/uploads 下的文件，防止客户端传 ../ 读到任意文件
    for p in abs_images:
        if not str(p).startswith(str(UPLOAD_DIR.resolve())):
            raise HTTPException(status_code=400, detail=f"非法的图片路径：{p.name}")
        if not p.is_file():
            raise HTTPException(status_code=404, detail=f"图片不存在：{p.name}")

    resources = ExitStack()

    def prepare_run():
        conn = resources.enter_context(request.app.state.pg_pool.connection())
        service = SessionService(
            PostgresSessionRepository(conn), request.app.state.runtime,
            runs=request.app.state.runs,
            on_complete=lambda uid, text, answer: background.add_task(
                request.app.state.memory_jobs.run, uid, text, answer,
            ),
        )
        return service.send_message(
            user["id"],
            req.session_id,
            build_query(
                text = req.text,
                images = [str(p) for p in abs_images],
            ),
            text = req.text,
            images = [str(p) for p in abs_images],
            image_urls = [f"/uploads/{Path(p).name}" for p in req.images],
            reasoning = req.reasoning,
        )

    try:
        stream = await run_in_threadpool(prepare_run)
    except SessionBusyError as exc:
        resources.close()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        resources.close()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except BaseException:
        resources.close()
        raise

    def sse():
        for event in stream:
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return ChatStreamingResponse(
        sse(), run=stream, cleanup=resources.close,
        background=background, media_type="text/event-stream",
    )





@app.post("/api/upload")
async def upload_image(
        file: UploadFile = File(...),
        user: dict = Depends(get_current_user),
):
    """接收图片，存到 data/uploads/，返回服务端生成的相对路径。

    文件名由服务端生成（uuid），杜绝客户端用 ../ 做目录穿越，
    也避免同名覆盖。
    """
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"不支持的图片格式：{file.content_type}",
        )

    data = await file.read()
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"图片过大（{len(data) / 1024 / 1024:.1f}MB），上限 10MB",
        )

    ext = Path(file.filename or "").suffix.lower()
    if ext not in {".jpg", ".jpeg", ".png", ".gif", ".webp"}:
        ext = {"image/jpeg": ".jpg", "image/png": ".png",
               "image/gif": ".gif", "image/webp": ".webp"}[file.content_type]

    name = f"{uuid.uuid4().hex}{ext}"
    path = UPLOAD_DIR / name
    path.write_bytes(data)

    # path 给后续 /api/chat 用（服务端再拼成绝对路径），url 给前端 <img>
    return {
        "name": file.filename,
        "path": f"data/uploads/{name}",
        "url": f"/uploads/{name}",
    }


# 静态托管上传目录，前端可直接用 url 显示
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")


# ---------- 长期记忆 ----------
class MemoryUpdate(BaseModel):
    content: str


@app.get("/api/memories")
async def list_memories(
        user: dict = Depends(get_current_user),
        service: SessionService = Depends(get_service),
):
    return service.list_memories(user["id"])


@app.put("/api/memories/{memory_id}")
async def update_memory(
        memory_id: str,
        body: MemoryUpdate,
        user: dict = Depends(get_current_user),
        service: SessionService = Depends(get_service),
):
    content = body.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="内容不能为空")
    updated = service.update_memory(user["id"], memory_id, content)
    if updated is None:
        raise HTTPException(status_code=404, detail="记忆不存在")
    return updated


@app.delete("/api/memories/{memory_id}")
async def delete_memory(
        memory_id: str,
        user: dict = Depends(get_current_user),
        service: SessionService = Depends(get_service),
):
    if not service.delete_memory(user["id"], memory_id):
        raise HTTPException(status_code=404, detail="记忆不存在")
    return {"deleted": memory_id}


# ============================================================
# 知识库管理
# ============================================================

def _serialize_doc(row: dict) -> dict:
    return {
        "file_md5": row["file_md5"],
        "file_name": row["file_name"],
        "original_name": row.get("original_name"),
        "file_type": row["file_type"],
        "file_size": int(row.get("file_size") or 0),
        "chunk_count": row.get("chunk_count"),
        "status": row["status"],
        "stage": row.get("stage"),
        "error": row.get("error"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "ingested_at": row.get("ingested_at"),
    }


def _bootstrap_registry(repo: KbDocumentRepository, service: KnowledgeService) -> None:
    """登记表为空时，用 Milvus 现有文档回填一次（脚本入库的历史数据）。"""
    with service.registry_lock:
        docs = service.list_documents()
        if docs:
            repo.upsert_ready_from_milvus(docs)
            logger.info("知识库登记表已回填 %d 份文档", len(docs))


@app.get("/api/knowledge/documents")
def list_knowledge_documents(
        q: str = "",
        type: str | None = None,
        page: int = Query(1, ge=1),
        page_size: int = Query(10, ge=1, le=50),
        sort: str = "uploaded",
        service: KnowledgeService = Depends(get_knowledge),
        repo: KbDocumentRepository = Depends(get_kb_repo),
):
    if repo.count() == 0:
        _bootstrap_registry(repo, service)

    items, total = repo.list_page(
        q=q, file_type=type, page=page, page_size=page_size, sort=sort
    )
    return {
        "items": [_serialize_doc(r) for r in items],
        "total": total,
        "page": page,
        "page_size": page_size,
        "facets": repo.facets(q),
    }


@app.get("/api/knowledge/documents/{file_md5}/chunks")
def list_knowledge_chunks(
        file_md5: str,
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=100),
        service: KnowledgeService = Depends(get_knowledge),
        repo: KbDocumentRepository = Depends(get_kb_repo),
):
    doc = repo.get(file_md5)
    if doc is None:
        milvus_doc = service.get_document(file_md5)
        if milvus_doc is None:
            raise HTTPException(status_code=404, detail="文档不存在")
        doc = {
            **milvus_doc,
            "status": "ready",
            "original_name": None,
            "created_at": None,
            "updated_at": None,
            "ingested_at": None,
            "stage": None,
            "error": None,
        }

    rows = service.list_chunks(
        file_md5, offset=(page - 1) * page_size, limit=page_size
    )
    if not rows:
        # 没有取到块时用 Strong 再确认一次：刚删完的文档在 Bounded 视图里可能还"存在"
        live = service.store.get_doc_status(file_md5, consistency_level="Strong")
        if live is None:
            raise HTTPException(status_code=404, detail="文档不存在")
        total = int(live.get("chunk_count") or 0)
    else:
        total = int(doc.get("chunk_count") or 0)
        if total <= 0:
            live = service.store.get_doc_status(file_md5, consistency_level="Strong")
            total = int((live or {}).get("chunk_count") or 0)

    return {
        "document": _serialize_doc(doc),
        "items": [
            {
                "chunk_index": r.get("chunk_index", 0),
                "text": r.get("text") or "",
                "section_path": r.get("section_path"),
                "page": r.get("page"),
                "block_type": r.get("block_type"),
                "char_count": len(r.get("text") or ""),
            }
            for r in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@app.get("/api/knowledge/jobs/{file_md5}")
def get_knowledge_job(
        file_md5: str,
        service: KnowledgeService = Depends(get_knowledge),
        repo: KbDocumentRepository = Depends(get_kb_repo),
):
    doc = repo.get(file_md5)
    if doc is not None:
        return _serialize_doc(doc)

    # 历史上的脚本入库没有登记行，按 Milvus 现状合成一个 ready
    milvus_doc = service.get_document(file_md5)
    if milvus_doc is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    return {
        **milvus_doc,
        "original_name": None,
        "status": "ready",
        "stage": None,
        "error": None,
        "created_at": None,
        "updated_at": None,
        "ingested_at": None,
    }


@app.post("/api/knowledge/sync")
def sync_knowledge(
        service: KnowledgeService = Depends(get_knowledge),
        repo: KbDocumentRepository = Depends(get_kb_repo),
):
    with service.registry_lock:
        docs = service.list_documents()
        upserted = repo.upsert_ready_from_milvus(docs)
        removed = repo.delete_missing({d["file_md5"] for d in docs})
        return {"scanned": len(docs), "upserted": upserted, "removed": removed}


@app.delete("/api/knowledge/documents/{file_md5}")
def delete_knowledge_document(
        file_md5: str,
        service: KnowledgeService = Depends(get_knowledge),
        repo: KbDocumentRepository = Depends(get_kb_repo),
):
    with service.registry_lock:
        doc = repo.get(file_md5)
        if doc and doc["status"] in ("pending", "processing"):
            raise HTTPException(status_code=409, detail="文档正在处理中，请稍后再试")

        # del_document 返回 bool（是否删到了行），块数用删除前查到的 chunk_count
        removed = service.del_document(file_md5)
        repo.delete(file_md5)
        if not removed and doc is None:
            raise HTTPException(status_code=404, detail="文档不存在")
        chunks = int((doc or {}).get("chunk_count") or 0)

        # 只删上传目录里的源文件；历史脚本入库的文件不在这个目录下，不碰
        source = (doc or {}).get("source_path")
        if source:
            path = Path(source).resolve()
            try:
                if path.is_file() and path.is_relative_to(KNOWLEDGE_UPLOAD_DIR.resolve()):
                    path.unlink()
            except OSError:
                logger.warning("删除源文件失败：%s", path, exc_info=True)

        return {"deleted": file_md5, "chunks_deleted": chunks}


def run_ingest_job(
        pool: ConnectionPool,
        service: KnowledgeService,
        file_md5: str,
        source_path: Path,
        title: str | None,
        display_name: str,
        retry_failed: bool = False,
) -> None:
    """后台入库。同步函数由 Starlette 丢进线程池，不会阻塞事件循环。

    每次状态更新都从连接池现借连接 —— 请求期的那条连接在响应返回时已经归还。
    """
    def stage(name: str) -> None:
        with pool.connection() as conn:
            KbDocumentRepository(conn).set_processing(file_md5, name)

    try:
        suffix = source_path.suffix.lower()
        if suffix in {".md", ".txt"}:
            # md/txt 跳过 MinerU：本地转 content_list 快且稳定
            items, h1 = md_to_content_list(source_path, title=title)
            doc = service.load_document(
                source_path,
                content_list=items,
                title=title or h1,
                on_stage=stage,
                replace_existing=retry_failed,
            )
        else:
            doc = service.load_document(
                source_path, title=title, on_stage=stage, replace_existing=retry_failed,
            )

        count = int(doc.get("chunk_count") or 0)
        if count <= 0:
            raise RuntimeError("入库结果未确认有效切片")
        resolved_name = (doc or {}).get("file_name") or display_name
        with pool.connection() as conn, service.registry_lock:
            KbDocumentRepository(conn).mark_ready(
                file_md5, count, file_name=resolved_name
            )
        logger.info("知识库入库完成：%s（%d 块）", resolved_name, count)
    except Exception as exc:
        logger.exception("知识库入库失败 file_md5=%s", file_md5)
        try:
            with pool.connection() as conn:
                KbDocumentRepository(conn).mark_failed(
                    file_md5, f"{type(exc).__name__}: {exc}"
                )
        except Exception:
            logger.exception("写入失败状态时出错 file_md5=%s", file_md5)


@app.post("/api/knowledge/upload", status_code=202)
async def upload_knowledge_document(
        background: BackgroundTasks,
        request: Request,
        file: UploadFile = File(...),
        title: str | None = Form(None),
        service: KnowledgeService = Depends(get_knowledge),
        repo: KbDocumentRepository = Depends(get_kb_repo, scope="function"),
):
    original = Path(file.filename or "document")
    suffix = original.suffix.lower()
    if suffix not in ALLOWED_DOC_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"不支持的文档格式：{suffix or '未知'}",
        )

    safe_stem = "".join("_" if ch in _UNSAFE_CHARS else ch for ch in original.stem)[:60] or "document"

    # 边落盘边算 md5，同时卡住大小上限
    digest = hashlib.md5()
    total = 0
    tmp_path = KNOWLEDGE_UPLOAD_DIR / f".uploading-{uuid.uuid4().hex}{suffix}"
    try:
        with tmp_path.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_DOC_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"文件超过 {MAX_DOC_BYTES // 1024 // 1024}MB 上限",
                    )
                digest.update(chunk)
                out.write(chunk)
    except HTTPException:
        tmp_path.unlink(missing_ok=True)
        raise
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
    finally:
        await file.close()

    if total == 0:
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="文件为空")

    file_md5 = digest.hexdigest()
    final_path = KNOWLEDGE_UPLOAD_DIR / f"{file_md5}-{uuid.uuid4().hex}-{safe_stem}{suffix}"
    display_name = title or original.name

    def claim_upload():
        with service.registry_lock:
            existing = repo.get(file_md5)
            retry_failed = bool(existing and existing["status"] == "failed")
            claimed = repo.upsert_pending(
                file_md5, file_name=display_name, original_name=original.name,
                file_type=suffix.lstrip("."), file_size=total, source_path=str(final_path),
            )
            if not claimed:
                raise HTTPException(status_code=409, detail="该文档已入库或正在处理中")
            try:
                tmp_path.replace(final_path)
            except Exception as exc:
                repo.mark_failed(file_md5, f"保存上传文件失败：{exc}")
                raise
            return retry_failed

    try:
        retry_failed = await run_in_threadpool(claim_upload)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
    background.add_task(
        run_ingest_job,
        request.app.state.pg_pool,
        service,
        file_md5,
        final_path,
        title,
        display_name,
        retry_failed,
    )
    return {
        "file_md5": file_md5,
        "file_name": display_name,
        "status": "pending",
    }


if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8002, reload=True)
