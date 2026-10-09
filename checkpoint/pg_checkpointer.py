"""PostgreSQL checkpoint and conversation session helpers."""

from collections.abc import Iterator
from contextlib import contextmanager
import os

from dotenv import load_dotenv
from langgraph.checkpoint.postgres import PostgresSaver

load_dotenv(override=True)

@contextmanager
def postgres_checkpointer(
    dsn: str | None = None,
) -> Iterator[PostgresSaver]:
    connection_string = dsn or os.getenv("LANGGRAPH_POSTGRES_URI")
    if not connection_string:
        raise RuntimeError("缺少 LANGGRAPH_POSTGRES_URI 配置")

    with PostgresSaver.from_conn_string(connection_string) as saver:
        # 首次运行时创建 LangGraph 检查点表；之后可重复调用
        saver.setup()
        yield saver

