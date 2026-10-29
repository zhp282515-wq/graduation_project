from typing import Any

import psycopg
from psycopg.rows import dict_row

_SCHEMA = """
CREATE TABLE IF NOT EXISTS kb_documents (
    file_md5      VARCHAR(32) PRIMARY KEY,
    file_name     TEXT NOT NULL,
    original_name TEXT,
    file_type     VARCHAR(16) NOT NULL,
    file_size     BIGINT NOT NULL DEFAULT 0,
    status        VARCHAR(16) NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending', 'processing', 'ready', 'failed')),
    stage         VARCHAR(16),
    error         TEXT,
    chunk_count   INTEGER,
    source_path   TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    ingested_at   TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_kb_docs_created ON kb_documents (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_kb_docs_type    ON kb_documents (file_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_kb_docs_status  ON kb_documents (status);
"""

_COLUMNS = """
    file_md5, file_name, original_name, file_type, file_size, visibility,
    status, stage, error, chunk_count, source_path,
    created_at, updated_at, ingested_at
"""


def _like(q: str) -> str:
    """把用户输入转成 ILIKE 模式，转义 LIKE 的特殊字符。"""
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


class KbDocumentRepository:
    """知识库文档登记表。

    Milvus 存向量与正文，这张表只记「有哪些文档、什么时候传的、入库到哪一步」。
    连接由外部注入，生命周期不归它管 —— 与 session/repository.py 同一约定。
    """

    def __init__(self, conn: psycopg.Connection):
        self._conn = conn

    def setup(self) -> None:
        with self._conn.cursor() as cur:
            cur.execute(_SCHEMA)
            cur.execute("ALTER TABLE kb_documents ADD COLUMN IF NOT EXISTS visibility TEXT NOT NULL DEFAULT 'public' CHECK (visibility IN ('public','admin'))")
            cur.execute("ALTER TABLE kb_documents ALTER COLUMN visibility SET DEFAULT 'admin'")
        self._conn.commit()

    def get(self, file_md5: str) -> dict[str, Any] | None:
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"SELECT {_COLUMNS} FROM kb_documents WHERE file_md5 = %s",
                (file_md5,),
            )
            return cur.fetchone()

    def upsert_pending(
        self,
        file_md5: str,
        *,
        file_name: str,
        original_name: str | None,
        file_type: str,
        file_size: int,
        source_path: str | None,
    ) -> bool:
        """原子抢占新任务或失败重试；已有可用/在途任务返回 False。"""
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO kb_documents
                    (file_md5, file_name, original_name, file_type, file_size,
                     status, stage, error, source_path)
                VALUES (%s, %s, %s, %s, %s, 'pending', NULL, NULL, %s)
                ON CONFLICT (file_md5) DO UPDATE SET
                    file_name   = EXCLUDED.file_name,
                    original_name = EXCLUDED.original_name,
                    file_type   = EXCLUDED.file_type,
                    file_size   = EXCLUDED.file_size,
                    status      = 'pending',
                    stage       = NULL,
                    error       = NULL,
                    source_path = EXCLUDED.source_path,
                    updated_at  = now(),
                    ingested_at = NULL,
                    chunk_count = NULL
                WHERE kb_documents.status = 'failed'
                RETURNING file_md5
                """,
                (file_md5, file_name, original_name, file_type, file_size, source_path),
            )
            claimed = cur.fetchone() is not None
        self._conn.commit()
        return claimed

    def set_processing(self, file_md5: str, stage: str) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                UPDATE kb_documents
                SET status = 'processing', stage = %s, updated_at = now()
                WHERE file_md5 = %s
                """,
                (stage, file_md5),
            )
        self._conn.commit()

    def mark_ready(self, file_md5: str, chunk_count: int, *, file_name: str | None = None) -> None:
        if chunk_count <= 0:
            raise ValueError("完整入库必须包含有效切片")
        with self._conn.cursor() as cur:
            cur.execute(
                """
                UPDATE kb_documents
                SET status = 'ready',
                    stage = NULL,
                    error = NULL,
                    chunk_count = %s,
                    file_name = COALESCE(%s, file_name),
                    ingested_at = now(),
                    updated_at = now()
                WHERE file_md5 = %s
                """,
                (chunk_count, file_name, file_md5),
            )
        self._conn.commit()

    def mark_failed(self, file_md5: str, error: str) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                UPDATE kb_documents
                SET status = 'failed', stage = NULL, error = %s, updated_at = now()
                WHERE file_md5 = %s
                """,
                (error[:500], file_md5),
            )
        self._conn.commit()

    def delete(self, file_md5: str) -> bool:
        with self._conn.cursor() as cur:
            cur.execute("DELETE FROM kb_documents WHERE file_md5 = %s", (file_md5,))
            deleted = cur.rowcount > 0
        self._conn.commit()
        return deleted

    def list_page(
        self,
        *,
        q: str = "",
        file_type: str | None = None,
        page: int = 1,
        page_size: int = 10,
        sort: str = "uploaded",
        public_only: bool = False,
    ) -> tuple[list[dict[str, Any]], int]:
        conditions = ["visibility = 'public' AND status = 'ready'"] if public_only else []
        params: list[Any] = []
        if q.strip():
            pattern = _like(q.strip())
            conditions.append("(file_name ILIKE %s ESCAPE '\\' OR coalesce(original_name, '') ILIKE %s ESCAPE '\\')")
            params.extend([pattern, pattern])
        if file_type:
            conditions.append("file_type = %s")
            params.append(file_type)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        order = (
            "file_name ASC"
            if sort == "name"
            else "COALESCE(ingested_at, created_at) DESC, file_name ASC"
        )
        offset = (page - 1) * page_size

        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(f"SELECT count(*) AS total FROM kb_documents {where}", params)
            total = cur.fetchone()["total"]

            cur.execute(
                f"""
                SELECT {_COLUMNS} FROM kb_documents
                {where}
                ORDER BY {order}
                LIMIT %s OFFSET %s
                """,
                [*params, page_size, offset],
            )
            rows = cur.fetchall()

        return rows, total

    def facets(self, q: str = "", *, public_only: bool = False) -> dict[str, int]:
        """各格式的文档数。只受搜索词影响，不受当前格式筛选影响。"""
        params: list[Any] = []
        where = ""
        if q.strip():
            pattern = _like(q.strip())
            where = "WHERE (file_name ILIKE %s ESCAPE '\\' OR coalesce(original_name, '') ILIKE %s ESCAPE '\\')"
            params.extend([pattern, pattern])

        if public_only:
            where += (" AND " if where else "WHERE ") + "visibility = 'public' AND status = 'ready'"
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"""
                SELECT
                    count(*) AS all,
                    count(*) FILTER (WHERE file_type = 'md')   AS md,
                    count(*) FILTER (WHERE file_type = 'doc')  AS doc,
                    count(*) FILTER (WHERE file_type = 'docx') AS docx,
                    count(*) FILTER (WHERE file_type = 'pdf')  AS pdf,
                    count(*) FILTER (WHERE file_type = 'txt')  AS txt
                FROM kb_documents
                {where}
                """,
                params,
            )
            row = cur.fetchone()
        return {k: int(v or 0) for k, v in row.items()}

    def count(self) -> int:
        with self._conn.cursor() as cur:
            cur.execute("SELECT count(*) AS n FROM kb_documents")
            row = cur.fetchone()
            # 连接池统一配了 dict_row，这里按列名取；兼容元组行也顺手处理
            return int(row["n"]) if isinstance(row, dict) else int(row[0])

    def overview(self, *, public_only: bool = False) -> dict[str, Any]:
        """知识库总览：文档数、分片总数、状态分布、最近入库时间。

        分片总数只能求和登记表里的 chunk_count —— Milvus 侧逐文档 count(*) 太慢，
        登记表在 mark_ready 时写入的正是该文档真实入库的分片数。
        """
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT
                    count(*) AS documents,
                    coalesce(sum(chunk_count), 0) AS chunks,
                    count(*) FILTER (WHERE status = 'ready')      AS ready,
                    count(*) FILTER (WHERE status = 'processing') AS processing,
                    count(*) FILTER (WHERE status = 'pending')    AS pending,
                    count(*) FILTER (WHERE status = 'failed')     AS failed,
                    coalesce(sum(file_size), 0) AS bytes,
                    max(coalesce(ingested_at, created_at)) AS latest_at
                FROM kb_documents
                """ + (" WHERE visibility = 'public' AND status = 'ready'" if public_only else "")
            )
            row = cur.fetchone()
        return {
            "documents": int(row["documents"] or 0),
            "chunks": int(row["chunks"] or 0),
            "ready": int(row["ready"] or 0),
            "processing": int(row["processing"] or 0),
            "pending": int(row["pending"] or 0),
            "failed": int(row["failed"] or 0),
            "bytes": int(row["bytes"] or 0),
            "latest_at": row["latest_at"].isoformat() if row["latest_at"] else None,
        }

    def reconcile_after_restart(self) -> int:
        """启动时把残留的在途任务标成失败 —— 后台线程随进程一起没了。"""
        with self._conn.cursor() as cur:
            cur.execute(
                """
                UPDATE kb_documents
                SET status = 'failed',
                    stage = NULL,
                    error = '服务重启，任务已中断，请重新上传',
                    updated_at = now()
                WHERE status IN ('pending', 'processing')
                """
            )
            n = cur.rowcount
        self._conn.commit()
        return n

    def upsert_ready_from_milvus(self, docs: list[dict[str, Any]]) -> int:
        """把 Milvus 里已有的文档补登记为 ready（脚本入库的历史数据、一次性回填）。"""
        if not docs:
            return 0
        inserted = 0
        with self._conn.cursor() as cur:
            for d in docs:
                cur.execute(
                    """
                    INSERT INTO kb_documents
                        (file_md5, file_name, original_name, file_type, file_size,
                         status, chunk_count, ingested_at, visibility)
                    VALUES (%s, %s, NULL, %s, %s, 'ready', %s, now(), 'public')
                    ON CONFLICT (file_md5) DO NOTHING
                    """,
                    (
                        d["file_md5"],
                        d.get("file_name") or "",
                        d.get("file_type") or "",
                        int(d.get("file_size") or 0),
                        int(d.get("chunk_count") or 0),
                    ),
                )
                inserted += cur.rowcount
        self._conn.commit()
        return inserted

    def delete_missing(self, alive: set[str]) -> int:
        """只清理缺失的 ready 登记；保留在途任务与失败记录。"""
        with self._conn.cursor() as cur:
            if not alive:
                cur.execute("DELETE FROM kb_documents WHERE status = 'ready'")
            else:
                cur.execute(
                    "DELETE FROM kb_documents WHERE status = 'ready' AND NOT (file_md5 = ANY(%s))",
                    (list(alive),),
                )
            n = cur.rowcount
        self._conn.commit()
        return n
