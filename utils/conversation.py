"""仅从受控上传目录恢复已保存对话中的图片，不接受任意本地路径。"""

from pathlib import Path

from utils.query_tool import build_query

UPLOAD_DIR = Path(__file__).resolve().parent.parent / "data" / "uploads"


def saved_history(messages) -> list[dict]:
    history = []
    for message in messages:
        images = []
        for url in message.images or []:
            if not isinstance(url, str) or not url.startswith("/uploads/"):
                raise ValueError("历史图片路径无效，无法恢复对话")
            path = (UPLOAD_DIR / url.removeprefix("/uploads/")).resolve()
            if not path.is_relative_to(UPLOAD_DIR.resolve()) or not path.is_file():
                raise ValueError("原图片已不存在，无法恢复该轮对话")
            images.append(str(path))
        history.append({"role": message.role, "content": build_query(message.content, images)})
    return history
