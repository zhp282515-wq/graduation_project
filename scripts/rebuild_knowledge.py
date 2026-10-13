"""重建知识库：丢弃旧集合（旧 schema 无 BM25 稀疏字段）并重新入库。

旧集合的向量字段与稀疏字段结构不同，无法原地升级，必须重建。

重建会重新调用 MinerU 解析 + 嵌入接口，有 API 成本与耗时。
用法（默认只预览，不真删）：
    python scripts/rebuild_knowledge.py            # 只列出当前状态
    python scripts/rebuild_knowledge.py --yes      # 确认后执行重建
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from knowledge.server import KnowledgeService

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def main() -> None:
    confirm = "--yes" in sys.argv
    service = KnowledgeService()

    existing = service.list_documents()
    print(f"当前集合有 {len(existing)} 个文档：")
    for doc in existing:
        print(f"  {doc['file_name']}  ({doc['chunk_count']} 块)")

    files = sorted(f for f in DATA_DIR.glob("*") if f.is_file())
    print(f"\n{DATA_DIR} 下有 {len(files)} 个源文件：")
    for f in files:
        print(f"  {f.name}")

    if not confirm:
        print("\n以上为预览。确认无误后加 --yes 执行重建：")
        print("  python scripts/rebuild_knowledge.py --yes")
        return

    print("\n开始重建...")
    started = time.perf_counter()
    service.store.drop_collection()
    service.store.ensure_collection()

    ok = failed = 0
    for f in files:
        try:
            result = service.load_document(f)
            print(f"  {f.name} -> {result}")
            ok += 1
        except Exception as exc:
            print(f"  {f.name} 失败: {exc}")
            failed += 1

    print(
        f"\n完成：成功 {ok}，失败 {failed}，"
        f"耗时 {time.perf_counter() - started:.1f}s"
    )


if __name__ == "__main__":
    main()