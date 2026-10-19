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
    file_md5, file_name, original_name, file_type, file_size,
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
    ) -> None:
        """登记一次新任务。已存在（失败重试）时重置状态。"""
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
                    ingested_at = NULL
                """,
                (file_md5, file_name, original_name, file_type, file_size, source_path),
            )
        self._conn.commit()

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
    ) -> tuple[list[dict[str, Any]], int]:
        conditions = []
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

    def facets(self, q: str = "") -> dict[str, int]:
        """各格式的文档数。只受搜索词影响，不受当前格式筛选影响。"""
        params: list[Any] = []
        where = ""
        if q.strip():
            pattern = _like(q.strip())
            where = "WHERE (file_name ILIKE %s ESCAPE '\\' OR coalesce(original_name, '') ILIKE %s ESCAPE '\\')"
            params.extend([pattern, pattern])

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
        with self._conn.cursor() as cur:
            for d in docs:
                cur.execute(
                    """
                    INSERT INTO kb_documents
                        (file_md5, file_name, original_name, file_type, file_size,
                         status, chunk_count, ingested_at)
                    VALUES (%s, %s, NULL, %s, %s, 'ready', %s, now())
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
            inserted = cur.rowcount
        self._conn.commit()
        return inserted

    def delete_missing(self, alive: set[str]) -> int:
        """删掉 Milvus 里已不存在的登记行。"""
        with self._conn.cursor() as cur:
            if not alive:
                cur.execute("DELETE FROM kb_documents")
            else:
                cur.execute(
                    "DELETE FROM kb_documents WHERE NOT (file_md5 = ANY(%s))",
                    (list(alive),),
                )
            n = cur.rowcount
        self._conn.commit()
        return n
