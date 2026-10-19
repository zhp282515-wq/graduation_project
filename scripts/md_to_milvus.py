"""把 data/*.md 批量入库。

这些 md 不是 MinerU 产物，所以用 utils.md_to_content_list 先转成 content_list
再交给 load_document —— 给了 content_list 就绕开 MinerU 解析。

md5 去重由 load_document 保证，重复跑只会跳过，不会写重复数据。

用法（注意用 conda 的 Graduation-Project 环境）：
    python scripts/md_to_milvus.py --dry-run
    python scripts/md_to_milvus.py
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from knowledge.server import KnowledgeService
from utils.md_to_content_list import md_to_content_list
from utils.logger_tool import logger

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

# 00-总览是索引与缺口清单，不是知识，别入库
SKIP = ("00-",)

# 社交媒体文件要标成主观体验，将来可按此过滤
SOCIAL_PREFIX = ("04-", "07-")


def metadata_for(name: str) -> dict:
    if name.startswith(SOCIAL_PREFIX):
        return {"info_type": "experience", "source_kind": "social_media"}
    return {"info_type": "official", "source_kind": "official_site"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只切块统计，不写库、不调嵌入")
    args = ap.parse_args()

    files = [f for f in sorted(DATA.glob("*.md"))
             if not f.name.startswith(SKIP)]
    if not files:
        print(f"{DATA} 下没有可入库的 md")
        return

    service = None if args.dry_run else KnowledgeService()
    started = time.perf_counter()
    ok = skipped = failed = 0

    for path in files:
        try:
            items, title = md_to_content_list(path)
            meta = metadata_for(path.name)
            if args.dry_run:
                print(f"  [预演] {path.name[:44]:<46} {len(items):>4} 条  {meta['info_type']}")
                continue

            result = service.load_document(path, content_list=items, title=title,
                                           metadata=meta)
            if result.get("skipped"):
                skipped += 1
                print(f"  跳过(已入库) {path.name}")
            else:
                ok += 1
                print(f"  入库 {path.name[:44]:<46} {result['inserted']:>4} 块")
        except Exception as exc:
            failed += 1
            logger.error("入库失败 %s: %s", path.name, exc)
            print(f"  失败 {path.name}: {type(exc).__name__} {exc}")

    if args.dry_run:
        print("\n以上为预演，未写库。")
        return

    print(f"\n完成：入库 {ok}，跳过 {skipped}，失败 {failed}，"
          f"耗时 {time.perf_counter() - started:.0f}s")
    docs = service.list_documents()
    print(f"库中现有 {len(docs)} 个文档，共 {sum(d['chunk_count'] for d in docs)} 块")


if __name__ == "__main__":
    main()