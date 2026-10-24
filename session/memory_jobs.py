"""响应结束后抽取记忆；模型调用期间不借用数据库连接。"""

from session.repository import PostgresSessionRepository
from session.runs import KeyedLocks
from utils.logger_tool import logger


class MemoryJobs:
    def __init__(self, pool, extractor):
        self._pool, self._extractor = pool, extractor
        self._users = KeyedLocks()

    def run(self, user_id: str, user_text: str, answer: str) -> None:
        try:
            with self._users.acquire(user_id, blocking=True):
                with self._pool.connection() as conn:
                    known = [m.content for m in PostgresSessionRepository(conn).list_memories(user_id)]
                items = self._extractor.extract(
                    user_text=user_text, assistant_text=answer, known=known,
                )
                if not items:
                    return
                with self._pool.connection() as conn:
                    repo = PostgresSessionRepository(conn)
                    current = {m.content for m in repo.list_memories(user_id)}
                    for item in items:
                        if item["content"] not in current and item["content"] not in known:
                            repo.add_memory(user_id, item["content"], item["category"])
                            current.add(item["content"])
        except Exception:
            logger.exception("用户 %s 的后台记忆抽取失败（回答已保存）", user_id)
