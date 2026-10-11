import base64
import mimetypes
from pathlib import Path
from urllib.parse import urlsplit

from utils.logger_tool import logger

_MAX_IMAGE_BYTES = 10 * 1024 * 1024


def to_image_url(image: str) -> str:
    """本地路径 → data URL；http(s) 地址原样返回。"""
    parsed = urlsplit(image)
    if parsed.scheme.lower() in {"http", "https"}:
        if not parsed.netloc:
            raise ValueError(f"图片 URL 无效：{image}")
        return image

    path = Path(image).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"本地图片不存在：{path}")

    size = path.stat().st_size
    if size > _MAX_IMAGE_BYTES:
        raise ValueError(f"图片过大（{size / 1024 / 1024:.1f}MB），请压缩后再上传：{path.name}")

    mime_type, _ = mimetypes.guess_type(path.name)
    if not mime_type or not mime_type.startswith("image/"):
        raise ValueError(f"不支持的文件类型：{path.name}")

    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    logger.info("图片 %s 已编码，%.2fMB", path.name, size / 1024 / 1024)
    return f"data:{mime_type};base64,{encoded}"


def build_query(text: str, images: list[str] | None = None) -> list[dict]:

    blocks: list[dict] = [{"type": "text", "text": text}]

    for image in images or []:
        blocks.append({
            "type": "image_url",
            "image_url": {"url": to_image_url(image)[:30]},
        })
    return blocks

if __name__ == '__main__':
    from rich import print as rprint

    rprint(build_query(text="你好",images=["D:\\1oveb\\毕业设计\\项目架构图.png"]))