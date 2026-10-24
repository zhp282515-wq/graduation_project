"""知识星图测试：完整性、确定性、缓存与退化路径。

星图是"每个分片一颗星"的承诺，所以最关键的断言是**不丢星**：
分页把每一颗星恰好交付一次，且 id 与权威分片 id 一一对应。
"""

import json
import math
import tempfile
import unittest
from pathlib import Path

import numpy as np

from knowledge.starmap import ALGO_VERSION, StarMapBuilder


def _vector(seed: int, dim: int = 16) -> list[float]:
    rng = np.random.default_rng(seed)
    vec = rng.normal(0, 1, dim)
    return (vec / np.linalg.norm(vec)).round(6).tolist()


def _rows() -> list[dict]:
    """三份文档：A 六个分片、B 四个、C 一个。

    A 与 B 的语义方向接近（模拟"同一主题被两份文档覆盖"），C 完全独立 ——
    这样既能验证跨文档连边，也能验证连边不会落到文档内部。
    """
    rows: list[dict] = []
    dim = 16
    axis_a = np.zeros(dim, dtype=np.float32)
    axis_a[0] = 1.0
    axis_b = np.zeros(dim, dtype=np.float32)
    axis_b[0], axis_b[1] = 0.86, 0.5
    axis_c = np.zeros(dim, dtype=np.float32)
    axis_c[2] = 1.0
    axes = {"md5-a": axis_a, "md5-b": axis_b, "md5-c": axis_c}
    plan = [
        ("md5-a", "校园指南.md", "md", 6),
        ("md5-b", "通知事项.docx", "docx", 4),
        ("md5-c", "历史沿革.md", "md", 1),
    ]
    for md5, name, kind, count in plan:
        base = axes[md5] / np.linalg.norm(axes[md5])
        for index in range(count):
            noise = np.asarray(_vector(index * 7 + len(md5) * 13), dtype=np.float32)
            vec = base + noise * 0.10
            rows.append(
                {
                    "id": f"{md5}:{index}",
                    "file_md5": md5,
                    "file_name": name,
                    "file_type": kind,
                    "file_size": 1024 * (count + index),
                    "chunk_index": index,
                    "text": f"{name} 第 {index} 段正文内容，用于验证星体与分片的映射。" * 3,
                    "section_path": f"第一章 > 第{index}节",
                    "block_type": "text",
                    "page": index,
                    "vector": (vec / np.linalg.norm(vec)).tolist(),
                }
            )
    return rows


class _FakeStore:
    collection = "test_campus"

    def __init__(self, rows: list[dict]):
        self.rows = rows
        self.iter_calls = 0

    def iter_all_chunks(self, *, include_vector: bool = False, batch_size: int = 1000):
        self.iter_calls += 1
        for row in list(self.rows):
            item = dict(row)
            if not include_vector:
                item.pop("vector", None)
            yield item


class _FakeService:
    def __init__(self, rows: list[dict]):
        self.store = _FakeStore(rows)

    def list_documents(self) -> list[dict]:
        grouped: dict[str, dict] = {}
        for row in self.store.rows:
            entry = grouped.setdefault(
                row["file_md5"],
                {
                    "file_md5": row["file_md5"],
                    "file_name": row["file_name"],
                    "file_type": row["file_type"],
                    "file_size": 0,
                    "chunk_count": 0,
                },
            )
            entry["chunk_count"] += 1
            entry["file_size"] = max(entry["file_size"], row["file_size"])
        return list(grouped.values())


class StarMapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cache_dir = Path(self.temp.name) / "starmap"
        rows = _rows()
        self.service = _FakeService(rows)
        self.builder = StarMapBuilder(self.service, cache_dir=self.cache_dir)

    def collect(self, limit: int = 2) -> list[dict]:
        points: list[dict] = []
        offset = 0
        while True:
            page = self.builder.points(offset=offset, limit=limit)
            points.extend(page["items"])
            if page["next_offset"] is None:
                return points
            offset = page["next_offset"]

    # ---------------------------------------------------------------- 完整性
    def test_every_chunk_becomes_exactly_one_star(self):
        meta = self.builder.meta()
        self.assertEqual(meta["total_chunks"], 11)
        self.assertEqual(meta["total_documents"], 3)

        points = self.collect()
        self.assertEqual(len(points), 11)
        self.assertEqual(len({p["id"] for p in points}), 11)
        self.assertEqual({p["id"] for p in points}, {row["id"] for row in self.service.store.rows})

        by_id = {row["id"]: row for row in self.service.store.rows}
        for point in points:
            source = by_id[point["id"]]
            self.assertEqual(point["file_md5"], source["file_md5"])
            self.assertEqual(point["chunk_index"], source["chunk_index"])
            self.assertEqual(point["text"], source["text"])
            self.assertTrue(math.isfinite(point["x"]) and math.isfinite(point["y"]) and math.isfinite(point["z"]))

    def test_points_are_never_duplicated_across_pages(self):
        ids = [p["id"] for p in self.collect(limit=3)]
        self.assertEqual(len(ids), len(set(ids)))

    def test_page_offset_beyond_total_returns_empty(self):
        page = self.builder.points(offset=999, limit=50)
        self.assertEqual(page["items"], [])
        self.assertIsNone(page["next_offset"])
        self.assertEqual(page["total"], 11)

    # ---------------------------------------------------------------- 确定性
    def test_layout_is_deterministic(self):
        other = StarMapBuilder(_FakeService(_rows()), cache_dir=Path(self.temp.name) / "other")
        a = {p["id"]: (p["x"], p["y"], p["z"]) for p in self.collect()}
        b = {p["id"]: (p["x"], p["y"], p["z"]) for p in other.points(offset=0, limit=100)["items"]}
        self.assertEqual(a, b)

    # ---------------------------------------------------------------- 缓存
    def test_cache_hit_avoids_rescanning_vectors(self):
        self.builder.meta()
        self.assertEqual(self.service.store.iter_calls, 1)
        self.builder.meta()
        self.builder.points()
        self.builder.edges()
        self.assertEqual(self.service.store.iter_calls, 1)

    def test_disk_cache_is_reused_by_a_new_builder(self):
        first = StarMapBuilder(_FakeService(_rows()), cache_dir=self.cache_dir)
        first.meta()
        reloaded = StarMapBuilder(_FakeService(_rows()), cache_dir=self.cache_dir)
        meta = reloaded.meta()
        self.assertEqual(meta["total_chunks"], 11)
        self.assertEqual(reloaded.service.store.iter_calls, 0)

    def test_document_change_invalidates_cache(self):
        self.builder.meta()
        self.service.store.rows.append(
            {
                "id": "md5-d:0",
                "file_md5": "md5-d",
                "file_name": "新增文件.md",
                "file_type": "md",
                "file_size": 10,
                "chunk_index": 0,
                "text": "新增文档的唯一分片",
                "section_path": "",
                "block_type": "text",
                "page": 0,
                "vector": _vector(77),
            }
        )
        meta = self.builder.meta()
        self.assertEqual(meta["total_chunks"], 12)
        self.assertEqual(self.service.store.iter_calls, 2)

    def test_corrupted_cache_file_is_ignored(self):
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        (self.cache_dir / "cache.json").write_text("{not json", encoding="utf-8")
        meta = self.builder.meta()
        self.assertEqual(meta["total_chunks"], 11)

    def test_cache_from_other_algorithm_version_is_ignored(self):
        self.builder.meta()
        path = self.cache_dir / "cache.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["algorithm"]["version"] = "starmap-v0"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        rebuilt = StarMapBuilder(_FakeService(_rows()), cache_dir=self.cache_dir)
        rebuilt.meta()
        self.assertEqual(rebuilt.service.store.iter_calls, 1)

    # ---------------------------------------------------------------- 关系
    def test_edges_stay_cross_document_and_respect_floor(self):
        payload = self.builder.edges()
        threshold = payload["algorithm"]["min_score"]
        self.assertGreater(len(payload["items"]), 0, "A/B 语义相近，应当产生跨文档连边")
        by_id = {row["id"]: row for row in self.service.store.rows}
        for edge in payload["items"]:
            self.assertGreaterEqual(edge["score"], threshold)
            self.assertNotEqual(by_id[edge["a"]]["file_md5"], by_id[edge["b"]]["file_md5"])

    def test_document_centers_do_not_overlap(self):
        meta = self.builder.meta()
        docs = meta["documents"]
        for i in range(len(docs)):
            for j in range(i + 1, len(docs)):
                a, b = docs[i], docs[j]
                self.assertGreaterEqual(
                    math.dist(a["center"], b["center"]), a["radius"] + b["radius"] - 1e-6
                )

    def test_algorithm_notes_mark_pure_visual_parts(self):
        meta = self.builder.meta()
        notes = " ".join(meta["algorithm"]["notes"])
        self.assertEqual(meta["algorithm"]["version"], ALGO_VERSION)
        self.assertIn("MDS", notes)
        self.assertIn("不表示知识关系", notes)
        self.assertIn("真实顺序", notes)

    # ---------------------------------------------------------------- 退化
    def test_missing_vectors_fall_back_without_losing_stars(self):
        rows = _rows()
        for row in rows:
            row.pop("vector")
        fallback = StarMapBuilder(_FakeService(rows), cache_dir=Path(self.temp.name) / "fallback")
        meta = fallback.meta()
        self.assertIn("fallback", meta["algorithm"]["layout"])
        self.assertEqual(meta["total_chunks"], 11)
        self.assertEqual(len(fallback.points(offset=0, limit=100)["items"]), 11)
        self.assertEqual(fallback.edges()["items"], [])

    def test_empty_knowledge_base_returns_empty_map(self):
        empty = StarMapBuilder(_FakeService([]), cache_dir=Path(self.temp.name) / "empty")
        meta = empty.meta()
        self.assertEqual(meta["total_chunks"], 0)
        self.assertEqual(meta["documents"], [])
        self.assertEqual(empty.points()["items"], [])


if __name__ == "__main__":
    unittest.main()
