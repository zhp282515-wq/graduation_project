"""PostgreSQL checkpoint and conversation session helpers."""

from collections.abc import Iterator
from contextlib import contextmanager
import os

from dotenv import load_dotenv
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from models.base import ChatMessage, ChatResponse

load_dotenv(override=True)


@contextmanager
def postgres_checkpointer(
    dsn: str | None = None,
    *,
    min_size: int = 1,
    max_size: int = 10,
) -> Iterator[PostgresSaver]:
    """进程级连接池 + PostgresSaver。

    pool 让长驻服务复用连接并自动重连；注意 PostgresSaver._cursor 内部持有
    自旋锁，单个 saver 实例的并发已被串行化，pool 的收益在连接复用而非并发。
    """
    connection_string = dsn or os.getenv("LANGGRAPH_POSTGRES_URI")
    if not connection_string:
        raise RuntimeError("缺少 LANGGRAPH_POSTGRES_URI 配置")

    serde = JsonPlusSerializer(
        allowed_msgpack_modules=[ChatMessage, ChatResponse],
    )

    # open=False：先建对象再显式 open，避免连接在 setup 之前就被惰性创建。
    with ConnectionPool(
        connection_string,
        min_size=min_size,
        max_size=max_size,
        open=False,
        kwargs={
            "autocommit": True,
            "prepare_threshold": 0,
            "row_factory": dict_row,
        },
    ) as pool:
        saver = PostgresSaver(pool, serde=serde)
        saver.setup()
        yield saver

