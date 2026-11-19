"""Persist only dashboard-safe events. Never format a raw application log for storage."""
import hashlib
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from utils.logger_tool import LOG_DIR, logger

SCHEMA = """
CREATE TABLE IF NOT EXISTS admin_log_events (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 occurred_at timestamptz NOT NULL, category text NOT NULL, source text NOT NULL,
 event text NOT NULL, level text, actor_id text, outcome text, history_key text UNIQUE
);
CREATE INDEX IF NOT EXISTS admin_log_time ON admin_log_events(category, occurred_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS admin_log_actor ON admin_log_events(actor_id, occurred_at DESC) WHERE actor_id IS NOT NULL;
CREATE TABLE IF NOT EXISTS admin_log_install (
 singleton boolean PRIMARY KEY CHECK(singleton), started_at timestamptz NOT NULL DEFAULT now(),
 imported boolean NOT NULL DEFAULT false
);
INSERT INTO admin_log_install(singleton) VALUES(true) ON CONFLICT DO NOTHING;
"""
INSERT = """INSERT INTO admin_log_events
 (occurred_at,category,source,event,level,actor_id,outcome,history_key)
 VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(history_key) DO NOTHING"""
diagnostics = logging.getLogger(__name__)
SOURCES = {
    "deepseek.py": "DeepSeek", "Qwen_model.py": "通义千问", "ChatGPT.py": "OpenAI",
    "embedding.py": "向量化", "reranker.py": "重排", "service.py": "会话服务",
    "main.py": "API", "executor.py": "工具执行", "memory.py": "记忆",
    "server.py": "知识库", "starmap.py": "知识星图", "mineru_parser.py": "文档解析",
    "usage.py": "用量统计", "nodes.py": "对话流程",
}
# Only predefined labels cross the dashboard boundary, including on unknown messages.
PREFIXES = {prefix: label for prefix, label in (
    ("[流式请求]", "开始流式调用"), ("[流式响应]", "收到流式响应"),
    ("[请求]", "发起模型请求"), ("[响应]", "收到服务响应"), ("[错误]", "服务请求失败"),
    ("[流式错误]", "流式调用失败"), ("[解析]", "处理模型响应"),
    ("[嵌入", "向量化调用"), ("[重排", "重排调用"), ("[模型]", "模型返回结果"),
    ("知识库服务初始化失败", "知识库初始化失败"), ("知识库入库完成", "文档入库完成"),
    ("知识库入库失败", "文档入库失败"), ("Token 用量写入失败", "用量记录写入失败"),
    ("记忆抽取失败", "记忆抽取失败"),
)}
LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
HEADER = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) - FFan - (DEBUG|INFO|WARNING|ERROR|CRITICAL) - ([\w.-]+\.py):\d+ - (.*)")


def runtime_row(when, filename, level, text, key=None):
    source = SOURCES.get(filename, "应用")
    label = next((v for k, v in PREFIXES.items() if text.startswith(k)), None)
    if label is None:
        label = {"ERROR": "执行出错", "CRITICAL": "严重错误", "WARNING": "运行警告"}.get(level, "运行记录")
    return (when, "runtime", source, label, level, None, None, key)


def import_history(pool, directory):
    """Import the available pre-install file headers once, using their producer's local timezone."""
    with pool.connection() as conn, conn.transaction():
        marker = conn.execute("SELECT * FROM admin_log_install FOR UPDATE").fetchone()
        if marker["imported"]:
            return
        for path in sorted(Path(directory).glob("FFan_????-??-??.log")):
            with path.open("r", encoding="utf-8", errors="replace") as lines:
                batch = []
                for index, line in enumerate(lines):
                    match = HEADER.match(line)
                    if not match:
                        continue
                    stamp, level, source, message = match.groups()
                    try:
                        instant = datetime.fromisoformat(stamp).astimezone()
                    except ValueError:
                        continue
                    if instant >= marker["started_at"].replace(microsecond=0):
                        continue
                    key = hashlib.sha256(f"{path.name}:{index}".encode()).hexdigest()
                    batch.append(runtime_row(instant, source, level, message, key))
                    if len(batch) == 500:
                        conn.cursor().executemany(INSERT, batch)
                        batch.clear()
                if batch:
                    conn.cursor().executemany(INSERT, batch)
        conn.execute("UPDATE admin_log_install SET imported=true")


class DashboardLogs(logging.Handler):
    def __init__(self, pool):
        super().__init__()
        self.pool = pool
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="admin-logs")

    def submit(self, row):
        self.worker.submit(self.write, row)

    def write(self, row):
        try:
            with self.pool.connection() as conn:
                conn.execute(INSERT, row)
        except Exception:
            diagnostics.error("管理员日志写入失败")

    def emit(self, record):
        try:
            if record.levelname in LEVELS:
                msg = record.msg if isinstance(record.msg, str) else ""
                self.submit(runtime_row(datetime.fromtimestamp(record.created, timezone.utc),
                                        record.filename, record.levelname, msg))
        except Exception:
            diagnostics.error("管理员运行日志采集失败")

    def stop(self):
        logger.removeHandler(self)
        logging.getLogger("session.usage").removeHandler(self)
        self.worker.shutdown(wait=True)

    def history(self):
        try:
            import_history(self.pool, LOG_DIR)
        except Exception:
            diagnostics.error("历史运行日志读取失败")


def start_logs(pool):
    with pool.connection() as conn:
        conn.execute(SCHEMA)
    handler = DashboardLogs(pool)
    logger.addHandler(handler)
    logging.getLogger("session.usage").addHandler(handler)
    handler.worker.submit(handler.history)
    handler.submit((datetime.now(timezone.utc), "runtime", "API", "日志采集启动", "INFO", None, None, None))
    return handler
