import os
import json
import uuid
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request, Depends, HTTPException, Header, UploadFile, File
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager

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
from agent.runtime import AgentRuntime
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

    app.state.pg_pool = pg_pool
    app.state.runtime = AgentRuntime(
        model = DashScopeProvider(model="qwen3.8-flash"),
        tools = [
            WeatherTool(),
            WebSearchTool(),
            AcademicCalendarTool(),
            KnowledgeSearchTool(),
        ],
        prompts = get_prompt(),
        checkpointer = saver,
        summary_model = DashScopeProvider(model="qwen3.7-flash"),
    )
    yield

    pg_pool.close()
    saver_pool.close()

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
            request.app.state.runtime
        )

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
    if not service.delete_session(user["id"], session_id):
        raise HTTPException(status_code=404, detail=f"会话不存在：{session_id}")
    return {"deleted": session_id}


@app.post("/api/chat")
async def chat(
        req: ChatRequest,
        user: dict = Depends(get_current_user),
        service: SessionService = Depends(get_service)
):

    root = Path(__file__).resolve().parent.parent
    abs_images = [(root / p).resolve() for p in req.images]
    # 只允许 data/uploads 下的文件，防止客户端传 ../ 读到任意文件
    for p in abs_images:
        if not str(p).startswith(str(UPLOAD_DIR.resolve())):
            raise HTTPException(status_code=400, detail=f"非法的图片路径：{p.name}")
        if not p.is_file():
            raise HTTPException(status_code=404, detail=f"图片不存在：{p.name}")

    try:
        stream = service.send_message(
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
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    def sse():
        for event in stream:
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(sse(), media_type="text/event-stream")




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


if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8002, reload=True)