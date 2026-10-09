"""session 闭环驱动脚本：建会话 -> 发消息 -> 打印事件流 -> 看落库结果。"""

import os

import psycopg
from dotenv import load_dotenv

from agent.runtime import AgentRuntime
from agent.tools.weather import WeatherTool
from agent.tools.websearch import WebSearchTool
from checkpoint.pg_checkpointer import postgres_checkpointer
from models.dashscope.Qwen_model import DashScopeProvider
from session.repository import PostgresSessionRepository
from session.service import SessionService
from utils.prompts_loader import get_prompt

load_dotenv(override=True)


def main(
        session_id: str | None = None,
        query: str | None = None,
) -> None:

        if session_id is None:
            session = service.create_session()
            print(f"新建会话：{session.id}\n")

            for event in service.send_message(session.id, query):
                from rich import print as rprint
                rprint(event)
        else:
            for event in service.send_message(session_id, query):
                from rich import print as rprint
                rprint(event)


if __name__ == "__main__":
    dsn = os.getenv("LANGGRAPH_POSTGRES_URI")

    # checkpointer 自己管一个连接，业务表用另一个，指向同一个库。
    with postgres_checkpointer() as checkpointer:
        with psycopg.connect(dsn) as conn:
            repo = PostgresSessionRepository(conn)
            repo.setup()

            runtime = AgentRuntime(
                model=DashScopeProvider(model="qwen3.7-max"),
                tools=[WeatherTool(), WebSearchTool()],
                prompts=get_prompt(),
                checkpointer=checkpointer,
            )
            service = SessionService(repo, runtime)

            while True:
                user_in = input("输入：")

                main(
                    query=user_in,
                    session_id="c14e0c8977184a8a853cb760d999349f",
                )