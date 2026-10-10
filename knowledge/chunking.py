"""把 MinerU 的 content_list 切成知识块。

切块原则：
- 按 text_level 维护标题栈，得到 section_path；
- 正文按目标大小打包，相邻块重叠，避免答案卡在边界；
- 表格独立成块，过大按行拆且每块重复表头；
- 图片独立成块，只用题注/描述文字（不嵌入图片本身）；
- 过滤页眉页脚页码噪声。
"""

from utils.logger_tool import logger

import html
import re
from dataclasses import asdict, dataclass
from typing import Any

# 噪声 item 类型：页眉、页脚、页码，进向量库会污染检索。
_NOISE_TYPES = {"page_number", "header", "footer"}

_TEXT_TARGET = 500      # 正文块目标字符数
_TEXT_OVERLAP = 80      # 相邻正文块重叠字符数
_TABLE_MAX = 1500       # 表格块超过此长度则按行拆
_LONG_PARA = _TEXT_TARGET * 2   # 单段落超过此长度则按句硬切

_SENTENCE_END = re.compile(r"(?<=[。！？；\n])")
_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
_CELL = re.compile(r"<t([dh])([^>]*)>(.*?)</t\1>", re.S | re.I)
_SPAN = re.compile(r'(colspan|rowspan)\s*=\s*["\']?(\d+)', re.I)
_TAG = re.compile(r"<[^>]+>")


@dataclass
class Chunk:
    text: str              # 用于嵌入和展示的内容（含标题前缀）
    section_path: str      # 标题路径，如 "一、平台入口 > （二）业务办理"
    block_type: str        # text / table / image
    page: int              # 页码，从 1 开始
    chunk_index: int       # 文档内序号


def chunk_content_list(
    content_list: list[dict[str, Any]],
    *,
    doc_title: str = "",
) -> list[Chunk]:
    """把一份 content_list 切成知识块。"""
    chunks: list[Chunk] = []
    heading_stack: list[tuple[int, str]] = []   # [(level, text)]
    buffer: list[str] = []
    buffer_page: int = 1

    def section_path() -> str:
        return " > ".join(text for _, text in heading_stack)

    def build_text(body: str, page: int, block_type: str = "text") -> None:
        path = section_path()
        prefix = " > ".join(part for part in (doc_title, path) if part)
        text = f"{prefix}\n\n{body}" if prefix else body
        chunks.append(Chunk(
            text=text.strip(),
            section_path=path,
            block_type=block_type,
            page=page,
            chunk_index=len(chunks),
        ))

    def flush_text_buffer() -> None:
        nonlocal buffer
        if not buffer:
            return
        body = "\n".join(buffer).strip()
        if body:
            for piece in _split_long_text(body):
                build_text(piece, buffer_page)
        buffer = []

    for item in content_list:
        item_type = item.get("type")

        if item_type in _NOISE_TYPES:
            continue

        page = int(item.get("page_idx") or 0) + 1

        # 标题：更新标题栈，并刷新已积累的正文
        if item_type == "text" and (item.get("text_level") or 0) > 0:
            flush_text_buffer()
            level = int(item["text_level"])
            title = (item.get("text") or "").strip()
            if not title:
                continue
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, title))
            continue

        if item_type == "table":
            flush_text_buffer()
            for piece in _split_table(item):
                build_text(piece, page, block_type="table")
            continue

        if item_type in ("image", "chart"):
            flush_text_buffer()
            desc = _image_text(item)
            if desc:
                build_text(desc, page, block_type="image")
            continue

        # 其余（text / list / equation / code）按正文处理
        body = _plain_text(item)
        if not body:
            continue
        if not buffer:
            buffer_page = page
        buffer.append(body)
        if sum(len(p) for p in buffer) >= _TEXT_TARGET:
            tail = _overlap_tail(buffer)
            flush_text_buffer()
            buffer = tail

    flush_text_buffer()
    logger.info("切块完成：%d 块（doc_title=%s）", len(chunks), doc_title or "-")
    return chunks


def chunks_to_rows(chunks: list[Chunk]) -> list[dict[str, Any]]:
    """转成可写入 Milvus 的 dict 列表。"""
    return [asdict(chunk) for chunk in chunks]


# ---- 内部工具 ----

def _plain_text(item: dict[str, Any]) -> str:
    """取正文文本。text/list/equation/code 都可能用 text 字段承载。"""
    for key in ("text", "code_body", "content", "equation"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _image_text(item: dict[str, Any]) -> str:
    """图片块的替代文字：题注 + 脚注 + MinerU 的图片描述。"""
    parts: list[str] = []
    for key in ("image_caption", "image_footnote", "chart_caption", "chart_footnote"):
        value = item.get(key)
        if isinstance(value, list):
            parts.extend(str(x).strip() for x in value if str(x).strip())
    content = item.get("content")
    if isinstance(content, str) and content.strip():
        parts.append(content.strip())
    return "\n".join(parts)

def _html_table_to_grid(table_html: str) -> list[list[str]]:
    """把表格 HTML 解析成二维网格，rowspan/colspan 通过复制单元格展开。

    展开后每行自包含：模型不需要回溯上一行才知道某格属于哪一列。
    """
    grid: list[list[str]] = []
    # pending[col] = [值, 还需向下占用的行数]
    pending: dict[int, list] = {}

    def fill(row: list[str], col: int) -> int:
        """把上方 rowspan 延续到本行的单元格补进来，返回新的列号。"""
        while col in pending:
            value, remaining = pending[col]
            row.append(value)
            if remaining <= 1:
                del pending[col]
            else:
                pending[col] = [value, remaining - 1]
            col += 1
        return col

    for row_html in _ROW.findall(table_html):
        row: list[str] = []
        col = 0

        for _kind, attrs, inner in _CELL.findall(row_html):
            col = fill(row, col)
            text = " ".join(html.unescape(_TAG.sub("", inner)).split())
            spans = {k.lower(): int(v) for k, v in _SPAN.findall(attrs)}
            colspan = spans.get("colspan", 1)
            rowspan = spans.get("rowspan", 1)

            for _ in range(colspan):
                row.append(text)
                if rowspan > 1:
                    pending[col] = [text, rowspan - 1]
                col += 1

        fill(row, col)
        if any(cell for cell in row):
            grid.append(row)

    return grid


def _grid_to_markdown(grid: list[list[str]]) -> str:
    """网格渲染成 markdown 表。首行当表头（数据表通常如此）。"""
    if not grid:
        return ""
    width = max(len(row) for row in grid)
    rows = [row + [""] * (width - len(row)) for row in grid]
    lines = [
        "| " + " | ".join(rows[0]) + " |",
        "| " + " | ".join(["---"] * width) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in rows[1:])
    return "\n".join(lines)

def _split_table(item: dict[str, Any]) -> list[str]:
    """表格块。HTML 转 markdown 表，过长则按行拆，每块重复表头。"""
    grid = _html_table_to_grid(item.get("table_body") or "")
    if not grid:
        return []

    caption = "".join(item.get("table_caption") or []).strip()
    footnote = "".join(item.get("table_footnote") or []).strip()
    header, *body_rows = grid

    pieces: list[list[list[str]]] = []
    current = [header]
    current_len = sum(len(c) for c in header)

    for row in body_rows:
        row_len = sum(len(c) for c in row)
        if current_len + row_len > _TABLE_MAX and len(current) > 1:
            pieces.append(current)
            current = [header, row]
            current_len = sum(len(c) for c in header) + row_len
        else:
            current.append(row)
            current_len += row_len
    pieces.append(current)

    result: list[str] = []
    for piece in pieces:
        block = "\n".join(
            part for part in (caption, _grid_to_markdown(piece), footnote) if part
        )
        result.append(block)
    return result


def _split_long_text(text: str) -> list[str]:
    """单块超过阈值时按句号硬切，避免一个巨大的 chunk。"""
    if len(text) <= _LONG_PARA:
        return [text]

    sentences = [s for s in _SENTENCE_END.split(text) if s]
    pieces: list[str] = []
    current = ""
    for sentence in sentences:
        if len(current) + len(sentence) > _TEXT_TARGET and current:
            pieces.append(current)
            current = sentence
        else:
            current += sentence
    if current:
        pieces.append(current)
    return pieces


def _overlap_tail(buffer: list[str]) -> list[str]:
    """取缓冲区尾部若干段作为下一块的开头，实现重叠。"""
    tail: list[str] = []
    total = 0
    for paragraph in reversed(buffer):
        if total + len(paragraph) > _TEXT_OVERLAP:
            break
        tail.insert(0, paragraph)
        total += len(paragraph)
    return tail

if __name__ == '__main__':
    import json
    from rich import print as rprint
    d = json.load(open("../knowledge/parser_data/2026年软考工作安排的通知/content_list.json"))
    for c in chunk_content_list(d):
        if c.block_type == 'table':
            print(c.text[:900])
