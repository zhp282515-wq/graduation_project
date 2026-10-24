"""将工具资料转换成可保存、可重放的来源快照。"""

from hashlib import sha256
from typing import Any
from urllib.parse import urlsplit, urlunsplit


def safe_web_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parts = urlsplit(value.strip())
        if parts.scheme.lower() not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
            return None
        parts.port  # 同时校验端口。
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, parts.query, parts.fragment))
    except ValueError:
        return None


def normalize_sources(items: Any, tool_name: str) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    result = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        if tool_name == "knowledge_search":
            md5, chunk_id, index = item.get("file_md5"), item.get("chunk_id"), item.get("chunk_index")
            if not isinstance(md5, str) or not md5 or not isinstance(item.get("text"), str):
                continue
            if not isinstance(index, int) or isinstance(index, bool) or index < 0:
                continue
            source_id = f"knowledge:{md5}:{chunk_id or index}"
            file_type = str(item.get("file_type") or "").lower()
            page = item.get("page")
            page = page if file_type == "pdf" and type(page) is int and page > 0 else None
            source = {
                "id": source_id, "kind": "knowledge", "title": item.get("file_name") or "未命名文档",
                "file_md5": md5, "chunk_id": chunk_id, "chunk_index": index,
                "file_type": file_type, "section_path": item.get("section_path") or "",
                "page": page, "text": item["text"], "url": safe_web_url(item.get("url")),
            }
        elif tool_name == "websearch":
            url = safe_web_url(item.get("url"))
            if not url:
                continue
            canonical = url.split("#", 1)[0]
            source_id = "web:" + sha256(canonical.encode()).hexdigest()[:24]
            source = {
                "id": source_id, "kind": "web", "title": item.get("title") or urlsplit(url).hostname,
                "url": url, "text": str(item.get("text") or item.get("description") or ""),
            }
        else:
            continue
        result.setdefault(source_id, source)
    return list(result.values())
