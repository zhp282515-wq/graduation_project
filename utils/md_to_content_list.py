"""把本地 markdown 转成 MinerU 形态的 content_list，供 chunk_content_list 切块。

背景：knowledge/chunking.py 只认 MinerU 的 content_list（要 text_level 搭标题栈、
page_idx 记页码），裸 markdown 喂不进去。本模块补齐这一层，让 md 不必绕道
MinerU 解析接口就能入库。

用法：
    from utils.md_to_content_list import md_to_content_list
    from knowledge.server import KnowledgeService

    content_list, title = md_to_content_list("data/手册.md")
    KnowledgeService().load_document("data/手册.md", content_list=content_list, title=title)

命令行预览（只打印统计，不写库）：
    python utils/md_to_content_list.py data/手册.md
"""

from __future__ import annotations

import html
import re
from pathlib import Path

_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})\s*([\w+-]*)\s*$")
_HEADING = re.compile(r"^ {0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")


class MarkdownError(ValueError):
    """markdown 解析失败。"""


def md_to_content_list(
    file_path: str | Path,
    *,
    title: str | None = None,
    page: int = 0,
) -> tuple[list[dict], str]:
    """读 markdown 文件，转成 content_list 与文档标题。

    返回 (content_list, title)。

    标题的取法：显式传入的 title 优先，否则取文首的 H1；两者都没有才退回文件名主干。
    文首 H1 被当作文档标题后，会从 content_list 里摘掉——否则 chunking 会把它拼成
    "标题 > 标题 > 章节" 的重复前缀。

    page 是所有块的 page_idx（md 无分页概念，默认 0 即第 1 页）。
    """
    path = Path(file_path)
    if not path.is_file():
        raise MarkdownError(f"文件不存在：{path}")

    text = path.read_text(encoding="utf-8", errors="replace")
    items = parse_markdown(text, page=page)

    if title:
        return items, title

    if items and items[0].get("text_level") == 1:
        return items[1:], items[0]["text"]
    return items, path.stem


def parse_markdown(text: str, *, page: int = 0) -> list[dict]:
    """正文文本 → content_list。空行分段，围栏代码原样保留。"""
    content_list: list[dict] = []
    paragraph: list[str] = []
    code: list[str] = []
    fence: str | None = None

    def emit_text(value: str, *, level: int = 0) -> None:
        """正文/标题统一入口：唯一承载字段是 text，标题额外带 text_level。"""
        item: dict = {"type": "text", "text": value, "page_idx": page}
        if level:
            item["text_level"] = level
        content_list.append(item)

    def flush_paragraph() -> None:
        if not paragraph:
            return
        body = "\n".join(_strip_inline(line) for line in paragraph if line.strip())
        body = body.strip()
        paragraph.clear()
        if body:
            emit_text(body)

    lines = text.splitlines()
    index = 0

    while index < len(lines):
        line = lines[index]

        # 围栏代码：整体成块，内部不再做任何语法解析
        if fence is None:
            opened = _FENCE.match(line)
        else:
            opened = None
        if opened and fence is None:
            flush_paragraph()
            fence = opened.group(1)[0]
            index += 1
            continue
        if fence is not None:
            if line.strip().startswith(fence * 3):
                body = "\n".join(code).strip("\n")
                if body:
                    emit_text(body)
                code.clear()
                fence = None
            else:
                code.append(line)
            index += 1
            continue

        # 标题
        heading = _HEADING.match(line)
        if heading:
            flush_paragraph()
            value = _strip_inline(heading.group(2))
            if value:
                emit_text(value, level=len(heading.group(1)))
            index += 1
            continue

        # 表格：表头行 + 分隔行
        if _is_table_head(line, lines, index):
            flush_paragraph()
            table_lines, index = _consume_table(lines, index)
            rows = _parse_table_rows(table_lines)
            if rows:
                content_list.append(_table_item(rows, page))
            continue

        # 段落边界：空行
        if not line.strip():
            flush_paragraph()
            index += 1
            continue

        paragraph.append(line)
        index += 1

    # 文件在代码块中途结束，剩余内容也收进去，别静默丢
    if fence is not None and code:
        body = "\n".join(code).strip("\n")
        if body:
            emit_text(body)
    flush_paragraph()

    return content_list


# ---- 内部工具 ----


def _is_table_head(line: str, lines: list[str], index: int) -> bool:
    """当前行与下一行构成 markdown 表格头（| a | b | 后跟 | --- | --- |）。"""
    if "|" not in line or index + 1 >= len(lines):
        return False
    return bool(_TABLE_SEP.match(lines[index + 1])) and bool(line.strip().strip("|"))


def _consume_table(lines: list[str], index: int) -> tuple[list[str], int]:
    """吞掉连续的表格行，返回 (表格文本行, 下一行下标)。"""
    block: list[str] = []
    while index < len(lines) and "|" in lines[index] and lines[index].strip():
        block.append(lines[index])
        index += 1
    return block, index


def _parse_table_rows(block: list[str]) -> list[list[str]]:
    """表格文本行 → 二维单元格。跳过分隔行。"""
    rows: list[list[str]] = []
    for offset, line in enumerate(block):
        if offset == 1 and _TABLE_SEP.match(line):
            continue
        cells = [_strip_inline(cell) for cell in line.strip().strip("|").split("|")]
        rows.append(cells)
    return rows


def _table_item(rows: list[list[str]], page: int) -> dict:
    """按 MinerU 的字段名产出表格块，chunking._split_table 认 table_body 里的 HTML。"""
    return {
        "type": "table",
        "table_caption": [],
        "table_footnote": [],
        "table_body": _rows_to_html(rows),
        "page_idx": page,
    }


def _rows_to_html(rows: list[list[str]]) -> str:
    """二维单元格 → <table> HTML。首行放 <thead>，其余放 <tbody>。"""
    head, *body = rows

    def render(row: list[str], tag: str) -> str:
        cells = "".join(
            f"<{tag}>{html.escape(cell)}</{tag}>" for cell in row
        )
        return f"<tr>{cells}</tr>"

    parts = ["<table>"]
    parts.append(f"<thead>{render(head, 'th')}</thead>")
    if body:
        parts.append("<tbody>" + "".join(render(row, "td") for row in body) + "</tbody>")
    parts.append("</table>")
    return "".join(parts)


def _strip_inline(value: str) -> str:
    """抹掉行内 markdown 记号，只留纯文本（向量化不需要记号，留着反而干扰 BM25）。"""
    value = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", value)   # 图片 → alt
    value = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", value)     # 链接 → 文字
    value = re.sub(r"(`{1,3})(.*?)\1", r"\2", value)           # 行内代码
    value = re.sub(r"(\*\*|__)(.*?)\1", r"\2", value)          # 加粗
    # 斜体：* 不带边界要求，_ 必须两侧非标识符字符，否则 snake_case 会被吃掉
    value = re.sub(r"\*(.*?)\*", r"\1", value)
    value = re.sub(r"(?<![\w])_(.+?)_(?![\w])", r"\1", value)
    value = re.sub(r"~~(.*?)~~", r"\1", value)                 # 删除线
    value = re.sub(r"^\s{0,3}#{1,6}\s+", "", value)            # 残留的标题记号
    return " ".join(value.split())


if __name__ == "__main__":
    import sys
    from collections import Counter
    from pathlib import Path as _Path

    # 直接以脚本运行时项目根不在 sys.path，显式补上再引 utils.*
    sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

    from rich import print as rprint

    from utils.path_tool import get_abs_path

    target = sys.argv[1] if len(sys.argv) > 1 else "技术验证记录.md"
    path = Path(target) if Path(target).is_file() else Path(get_abs_path(target))

    items, doc_title = md_to_content_list(path)
    kinds = Counter(item["type"] for item in items)
    levels = Counter(item.get("text_level", 0) for item in items if item["type"] == "text")

    rprint(f"文档标题：{doc_title}")
    rprint(f"内容块数：{len(items)}  类型分布：{dict(kinds)}")
    rprint(f"标题层级分布（0 为非标题正文）：{dict(sorted(levels.items()))}")
    rprint("\n=== 前 5 块 ===")
    for item in items[:5]:
        preview = item.get("text") or item.get("table_body") or ""
        rprint({"type": item["type"], "text_level": item.get("text_level"),
                "preview": preview[:70]})
