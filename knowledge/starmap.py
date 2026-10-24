"""知识星图：把知识库里的每一枚真实分片映射成一颗星。

设计原则（也是接口契约的一部分）：

1. **唯一真源**：星图只读 Milvus 里的分片（id / file_md5 / chunk_index / text /
   section_path / block_type / page），不读 PostgreSQL 登记表。登记表是派生状态，
   两者不一致时以向量库为准，避免出现"幽灵星"。
2. **三类关系必须可区分**：
   - 真实归属：分片 → 所属文档（file_md5），原样来自库字段；
   - 真实顺序：同一文档内 chunk_index 的先后（前端星链连线依据）；
   - 算法推导：文档质心之间的余弦距离（经典 MDS 降到三维得到星群中心）；
     以及跨文档分片余弦相似度最高的连边（带阈值与条数上限）。
   - 纯视觉：星群内部螺旋项只提供形态，不表示任何知识关系，权重受控且在
     `algorithm.notes` 里显式声明。
3. **完整覆盖**：所有 chunk_index >= 0 的分片都会得到一颗星，分页只是传输方式，
   不允许抽样。前端按 offset 逐页收齐，HUD 显示 loaded/total。
4. **可解释**：每次返回 algorithm 元信息（版本、方法、阈值、上限），前端原样展示。

布局一旦生成就按"指纹"缓存：指纹由 (file_md5, chunk_count) 集合决定，文档增删
或重新入库都会改变指纹，下一次请求自动重建。
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from utils.logger_tool import logger

ALGO_VERSION = "starmap-v3"
POINT_PAGE_DEFAULT = 400
POINT_PAGE_MAX = 800
EDGE_MIN_SCORE = 0.75
EDGE_MAX = 900
CACHE_MAX_AGE = 6 * 3600
_DEFAULT_CACHE_DIR = Path(__file__).resolve().parents[1] / "data" / "starmap"

_CHUNK_FIELDS = (
    "id", "file_md5", "file_name", "file_type", "file_size", "chunk_index",
    "text", "section_path", "block_type", "page",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _normalize(matrix: Any) -> Any:
    import numpy as np

    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


def _classical_mds(points: Any, dims: int = 3) -> Any:
    """经典多维标度：输入已中心化的内积矩阵，输出前 dims 个主坐标。

    这里直接喂 doc 质心之间的余弦距离矩阵，因此坐标的欧氏距离近似语义距离。
    文档数量通常几十，eigendecomposition 开销可以忽略。
    """
    import numpy as np

    n = points.shape[0]
    if n == 0:
        return np.zeros((0, dims), dtype=np.float64)
    if n <= dims + 1:
        # 文档太少时用简单正交排布，避免退化成一条线。
        out = np.zeros((n, dims), dtype=np.float64)
        for i in range(n):
            out[i, i % dims] = 1.0
        return out

    # points 是余弦距离矩阵
    dist2 = points ** 2
    j = np.eye(n) - np.ones((n, n)) / n
    b = -0.5 * j @ dist2 @ j
    b = (b + b.T) / 2
    values, vectors = np.linalg.eigh(b)
    order = np.argsort(values)[::-1][:dims]
    values = np.clip(values[order], 0, None)
    coords = vectors[:, order] * np.sqrt(values)
    if coords.shape[1] < dims:
        coords = np.pad(coords, ((0, 0), (0, dims - coords.shape[1])))
    return coords


def _fix_signs(coords: Any, keys: Sequence[str], dims: int = 3) -> Any:
    """特征向量的符号是任意的；固定成"最大绝对值分量为正"，保证可复现。"""
    import numpy as np

    out = coords.copy()
    for d in range(min(dims, out.shape[1])):
        column = out[:, d]
        if not len(column):
            continue
        idx = int(np.argmax(np.abs(column)))
        if column[idx] < 0:
            out[:, d] = -column
        elif column[idx] == 0:
            # 全零轴用 md5 排序兜底，避免浮点噪声导致抖动
            if keys and keys[0] > keys[-1]:
                out[:, d] = -column
    return out


def _separate(centers: Any, radii: Any, *, gap: float = 1.2, iterations: int = 240) -> Any:
    """星群去重叠：互相侵入时沿连线推开。

    这只是一个*视觉*步骤（避免星群粘成一团），会轻微破坏 MDS 的严格距离，
    语义远近仍以星群之间的整体顺序与连边为准，元信息里如实标注。
    """
    import numpy as np

    pos = centers.astype(np.float64).copy()
    n = pos.shape[0]
    if n < 2:
        return pos
    for _ in range(iterations):
        moved = False
        for i in range(n):
            for j in range(i + 1, n):
                delta = pos[j] - pos[i]
                dist = float(np.linalg.norm(delta))
                minimum = float(radii[i] + radii[j] + gap)
                if dist >= minimum:
                    continue
                if dist < 1e-6:
                    delta = np.array([1.0, 0.4, 0.2]) + 0.01 * (i - j)
                    dist = float(np.linalg.norm(delta))
                push = (minimum - dist) * 0.5
                direction = delta / dist
                pos[i] -= direction * push
                pos[j] += direction * push
                moved = True
        if not moved:
            break
    return pos


def _local_offsets(vectors: Any, radius: float, seed: str) -> Any:
    """文档内部排布：语义主成分 + 顺序螺旋的混合。

    语义项（权重 0.62）来自该文档分片向量局部 PCA 的前三个主成分，
    是真实的语义差异在三维里的投影；
    螺旋项（权重 0.38）只让同一文档的分片在视觉上连成可读的旋臂，
    不表示任何知识关系——这一点在 algorithm.notes 里明确写给前端展示。
    """
    import numpy as np

    n = int(vectors.shape[0])
    if n == 0:
        return np.zeros((0, 3), dtype=np.float64)
    if n == 1:
        return np.zeros((1, 3), dtype=np.float64)

    centered = vectors - vectors.mean(axis=0, keepdims=True)
    # 只取前三维：n×d 的 SVD 用 economy 模式，大文档也只要几十毫秒。
    try:
        _, _, vt = np.linalg.svd(centered, full_matrices=False)
        basis = vt[:3]
        if basis.shape[0] < 3:
            basis = np.pad(basis, ((0, 3 - basis.shape[0]), (0, 0)))
        scores = centered @ basis.T
    except np.linalg.LinAlgError:  # pragma: no cover - 数值异常兜底
        scores = np.zeros((n, 3), dtype=np.float64)

    scale = float(np.percentile(np.abs(scores), 90)) or 1.0
    semantic = np.clip(scores / scale, -2.2, 2.2)
    semantic_norm = np.linalg.norm(semantic, axis=1, keepdims=True)
    semantic_norm[semantic_norm == 0] = 1.0
    semantic = semantic / semantic_norm * np.minimum(
        1.0, np.linalg.norm(semantic, axis=1, keepdims=True) / 1.4
    )

    digest = hashlib.sha256(seed.encode()).digest()
    phase = (digest[0] / 255.0) * math.tau
    tilt = ((digest[1] / 255.0) - 0.5) * 1.2
    turns = 1.1 + (digest[2] / 255.0) * 0.8
    t = (np.arange(n, dtype=np.float64) + 0.5) / n
    angle = t * turns * math.tau + phase
    spiral = np.stack(
        [
            np.cos(angle) * (0.5 + 0.5 * t),
            np.sin(angle) * (0.5 + 0.5 * t) * (0.55 + 0.45 * abs(tilt)),
            (t - 0.5) * 1.35,
        ],
        axis=1,
    )
    spiral_norm = np.linalg.norm(spiral, axis=1, keepdims=True)
    spiral_norm[spiral_norm == 0] = 1.0
    spiral = spiral / spiral_norm

    # 半径再按序号做一次轻微抖动，避免完全等距的机械感。
    jitter = (0.82 + 0.18 * np.sin(np.arange(n) * 2.399 + phase))[:, None]
    combined = semantic * 0.62 + spiral * 0.38
    norms = np.linalg.norm(combined, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    combined = combined / norms * (radius * 0.72 * jitter)
    return combined


def _radius_for(count: int) -> float:
    return 2.1 + 3.3 * (max(count, 1) / 60.0) ** 0.45


def _star_size(chars: int) -> float:
    return round(1.0 + 2.1 * math.sqrt(min(max(chars, 0), 2400) / 900.0), 3)


def _text_preview(text: str, limit: int = 110) -> str:
    flat = " ".join((text or "").split())
    return flat if len(flat) <= limit else flat[:limit] + "…"


class StarMapBuilder:
    """构建并缓存星图。线程安全；缓存命中时只读一次 JSON。"""

    def __init__(self, service: Any, *, cache_dir: str | Path | None = None):
        self.service = service
        self.cache_dir = Path(cache_dir) if cache_dir else _DEFAULT_CACHE_DIR
        self._lock = threading.RLock()
        self._payload: dict[str, Any] | None = None
        self._fingerprint: str | None = None
        self._built_at = 0.0

    # ------------------------------------------------------------------ 基础
    @property
    def collection(self) -> str:
        return getattr(getattr(self.service, "store", None), "collection", "campus_knowledge")

    def _cache_path(self) -> Path:
        return self.cache_dir / "cache.json"

    def _documents(self) -> list[dict[str, Any]]:
        return list(self.service.list_documents())

    def fingerprint(self, documents: Iterable[dict[str, Any]] | None = None) -> str:
        docs = list(documents) if documents is not None else self._documents()
        parts = sorted(f"{d['file_md5']}:{int(d.get('chunk_count') or 0)}" for d in docs)
        raw = "|".join([ALGO_VERSION, self.collection, *parts])
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    # ------------------------------------------------------------------ 对外
    def meta(self, *, force: bool = False) -> dict[str, Any]:
        payload = self._ensure(force=force)
        return {
            "fingerprint": payload["fingerprint"],
            "generated_at": payload["generated_at"],
            "algorithm": payload["algorithm"],
            "documents": payload["documents"],
            "total_chunks": payload["total_chunks"],
            "total_documents": len(payload["documents"]),
            "point_page_size": POINT_PAGE_DEFAULT,
            "edge_count": len(payload["edges"]),
        }

    def points(self, *, offset: int = 0, limit: int = POINT_PAGE_DEFAULT, force: bool = False) -> dict[str, Any]:
        payload = self._ensure(force=force)
        items = payload["points"]
        total = len(items)
        offset = max(0, min(int(offset), total))
        limit = max(1, min(int(limit), POINT_PAGE_MAX))
        page = items[offset: offset + limit]
        next_offset = offset + len(page)
        return {
            "items": page,
            "total": total,
            "offset": offset,
            "limit": limit,
            "next_offset": None if next_offset >= total else next_offset,
            "fingerprint": payload["fingerprint"],
        }

    def edges(self, *, limit: int = EDGE_MAX, force: bool = False) -> dict[str, Any]:
        payload = self._ensure(force=force)
        items = payload["edges"][: max(1, min(int(limit), EDGE_MAX))]
        return {
            "items": items,
            "total": len(payload["edges"]),
            "fingerprint": payload["fingerprint"],
            "algorithm": payload["algorithm"]["semantic_edges"],
        }

    # ------------------------------------------------------------------ 缓存
    def _ensure(self, *, force: bool) -> dict[str, Any]:
        with self._lock:
            if not force and self._payload is not None and self._fresh(self._payload.get("fingerprint", "")):
                return self._payload

            documents = self._documents()
            fingerprint = self.fingerprint(documents)
            if not force and self._payload and self._payload.get("fingerprint") == fingerprint:
                self._built_at = time.time()
                return self._payload

            cached = self._read_cache()
            if not force and cached and cached.get("fingerprint") == fingerprint:
                self._payload = cached
                self._built_at = time.time()
                logger.info("知识星图命中磁盘缓存：%s 颗星", len(cached.get("points", [])))
                return cached

            started = time.perf_counter()
            payload = self._build(documents, fingerprint)
            self._payload = payload
            self._built_at = time.time()
            self._write_cache(payload)
            logger.info(
                "知识星图重建完成：%s 篇文档 / %s 颗星 / %s 条语义连边，耗时 %.2fs",
                len(payload["documents"]), payload["total_chunks"], len(payload["edges"]),
                time.perf_counter() - started,
            )
            return payload

    def _fresh(self, fingerprint: str) -> bool:
        if not fingerprint or time.time() - self._built_at > CACHE_MAX_AGE:
            return False
        try:
            target = self.fingerprint()
        except Exception:  # pragma: no cover - 库暂不可用时继续用内存缓存
            logger.warning("校验星图指纹失败，沿用内存缓存", exc_info=True)
            return True
        return target == fingerprint

    def _read_cache(self) -> dict[str, Any] | None:
        path = self._cache_path()
        try:
            if not path.exists():
                return None
            if time.time() - path.stat().st_mtime > CACHE_MAX_AGE:
                return None
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("algorithm", {}).get("version") != ALGO_VERSION:
                return None
            return data
        except (OSError, ValueError):
            logger.warning("星图缓存不可用，忽略并重建", exc_info=True)
            return None

    def _write_cache(self, payload: dict[str, Any]) -> None:
        path = self._cache_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, path)
        except OSError:
            logger.warning("写入星图缓存失败，不影响本次响应", exc_info=True)

    # ------------------------------------------------------------------ 构建
    def _rows(self) -> list[dict[str, Any]]:
        rows = list(self.service.store.iter_all_chunks(include_vector=True))
        return rows

    def _build(self, documents: list[dict[str, Any]], fingerprint: str) -> dict[str, Any]:
        rows = self._rows()
        by_doc: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            md5 = row.get("file_md5")
            if not isinstance(md5, str) or not md5:
                continue
            by_doc.setdefault(md5, []).append(row)
        for items in by_doc.values():
            items.sort(key=lambda r: int(r.get("chunk_index") or 0))

        docs_meta = {d["file_md5"]: d for d in documents}
        order = sorted(by_doc, key=lambda m: (docs_meta.get(m, {}).get("file_name") or "", m))
        semantic_ready, layout_name, layout_notes = self._layout_enabled(by_doc)
        total = sum(len(by_doc[m]) for m in order)

        positions: dict[str, tuple[float, float, float]] = {}
        centers: dict[str, list[float]] = {}
        radii: dict[str, float] = {}
        point_rows: list[dict[str, Any]] = []

        if semantic_ready:
            import numpy as np

            vectors = np.asarray([r["vector"] for m in order for r in by_doc[m]], dtype=np.float32)
            vectors = _normalize(vectors)
            dim = vectors.shape[1]
            offset = 0
            doc_vectors: dict[str, Any] = {}
            for md5 in order:
                n = len(by_doc[md5])
                doc_vectors[md5] = vectors[offset: offset + n]
                offset += n

            centroids = np.zeros((len(order), dim), dtype=np.float32)
            for idx, md5 in enumerate(order):
                centroid = doc_vectors[md5].mean(axis=0, keepdims=True)
                centroids[idx: idx + 1] = _normalize(centroid)

            dist = np.clip(1.0 - centroids @ centroids.T, 0.0, 2.0)
            np.fill_diagonal(dist, 0.0)
            raw_centers = _classical_mds(dist, dims=3)
            raw_centers = _fix_signs(raw_centers, order)
            doc_radii = np.asarray([_radius_for(len(by_doc[m])) for m in order], dtype=np.float64)
            # 尺度的两步处理，都只是视觉整理：
            # ① 径向压缩：对质心到原点的距离做单调凹变换（u**0.58），
            #    只压缩极端离群值，不改变任何两篇文档的远近次序；
            # ② 星群拆分：按各自的实际半径把互相压住的星群推开，留出可读的空隙。
            if len(raw_centers):
                spans = np.linalg.norm(raw_centers, axis=1)
                span = float(np.max(spans))
                if span > 1e-6:
                    unit = raw_centers / span
                    radius_norm = np.linalg.norm(unit, axis=1, keepdims=True)
                    radius_norm[radius_norm == 0] = 1.0
                    compressed = unit / radius_norm * (radius_norm ** 0.58)
                    target = max(26.0, 20.0 + float(np.sum(doc_radii)) ** 0.5 * 1.55)
                    raw_centers = compressed * target
            placed = _separate(raw_centers, doc_radii * 1.02, gap=0.9, iterations=320)

            for idx, md5 in enumerate(order):
                center = placed[idx]
                radius = float(doc_radii[idx])
                local = _local_offsets(doc_vectors[md5], radius, md5)
                centers[md5] = [round(float(v), 3) for v in center]
                radii[md5] = round(radius, 3)
                for local_idx, row in enumerate(by_doc[md5]):
                    positions[row["id"]] = tuple(
                        round(float(center[d] + local[local_idx][d]), 3) for d in range(3)
                    )

            edge_payload = self._semantic_edges(vectors, order, by_doc, doc_vectors)
        else:
            # 退化为纯视觉排布：文档按名称顺序排在一个环上，链内按顺序沿切线排开。
            count = max(len(order), 1)
            for idx, md5 in enumerate(order):
                angle = idx / count * math.tau
                center = [math.cos(angle) * 34.0, math.sin(angle * 2.0) * 6.0, math.sin(angle) * 34.0]
                radius = _radius_for(len(by_doc[md5]))
                centers[md5] = [round(v, 3) for v in center]
                radii[md5] = round(radius, 3)
                n = len(by_doc[md5])
                for local_idx, row in enumerate(by_doc[md5]):
                    t = (local_idx + 0.5) / max(n, 1)
                    positions[row["id"]] = (
                        round(center[0] + math.cos(t * math.tau) * radius * 0.7, 3),
                        round(center[1] + (t - 0.5) * radius * 1.2, 3),
                        round(center[2] + math.sin(t * math.tau) * radius * 0.7, 3),
                    )
            edge_payload = {"items": [], "method": "unavailable"}

        for md5 in order:
            meta = docs_meta.get(md5, {})
            for row in by_doc[md5]:
                text = str(row.get("text") or "")
                x, y, z = positions[row["id"]]
                point_rows.append(
                    {
                        "id": row["id"],
                        "file_md5": md5,
                        "chunk_index": int(row.get("chunk_index") or 0),
                        "x": x, "y": y, "z": z,
                        "text": text,
                        "preview": _text_preview(text),
                        "section_path": str(row.get("section_path") or ""),
                        "block_type": str(row.get("block_type") or ""),
                        "page": row.get("page") if isinstance(row.get("page"), int) else None,
                        "chars": len(text),
                        "size": _star_size(len(text)),
                    }
                )

        documents_out = []
        for md5 in order:
            meta = docs_meta.get(md5, {})
            documents_out.append(
                {
                    "file_md5": md5,
                    "file_name": meta.get("file_name") or by_doc[md5][0].get("file_name") or md5,
                    "file_type": (meta.get("file_type") or by_doc[md5][0].get("file_type") or "").lower(),
                    "file_size": int(meta.get("file_size") or by_doc[md5][0].get("file_size") or 0),
                    "chunk_count": len(by_doc[md5]),
                    "center": centers[md5],
                    "radius": radii[md5],
                }
            )

        return {
            "fingerprint": fingerprint,
            "generated_at": _utc_now(),
            "algorithm": {
                "version": ALGO_VERSION,
                "layout": layout_name,
                "semantic_edges": {
                    "method": "cross-document cosine nearest neighbour",
                    "min_score": EDGE_MIN_SCORE,
                    "max_edges": EDGE_MAX,
                    "count": len(edge_payload["items"]),
                },
                "notes": layout_notes,
            },
            "documents": documents_out,
            "points": point_rows,
            "edges": edge_payload["items"],
            "total_chunks": total,
        }

    def _layout_enabled(self, by_doc: dict[str, list[dict[str, Any]]]) -> tuple[bool, str, list[str]]:
        notes = [
            "星群中心：文档分片向量的质心，用余弦距离矩阵做经典 MDS 降到三维；"
            "星群之间的远近来自语义相似度，属于算法推导关系。",
            "星群内部：分片向量在该文档内做局部 PCA 后的前三个主成分（权重 0.62）"
            "叠加顺序螺旋项（权重 0.38）；螺旋只提供视觉形态，不表示知识关系。",
            "星链连线：同一文档内 chunk_index 相邻的分片，是库里的真实顺序。",
            f"语义连边：跨文档余弦相似度 ≥ {EDGE_MIN_SCORE} 的最近邻，最多 {EDGE_MAX} 条，属于算法推导关系。",
            "星群坐标为避免重叠做过轻微推挤，语义距离以星群整体顺序与连边为准。",
        ]
        sample = next(iter(by_doc.values()), None)
        if not sample or not sample[0].get("vector"):
            notes.insert(
                0,
                "当前分片没有向量数据，已退化为纯视觉排布：位置不表示任何语义关系。",
            )
            return False, "fallback-order (visual only)", notes
        return True, "doc-centroid MDS (cosine), radial compression, cluster separation + per-document PCA", notes

    def _semantic_edges(self, vectors: Any, order: list[str], by_doc: dict[str, list[dict[str, Any]]], doc_vectors: dict[str, Any]) -> dict[str, Any]:
        import numpy as np

        if vectors.shape[0] < 2:
            return {"items": []}
        doc_of: list[str] = []
        index_of: list[int] = []
        for md5 in order:
            for row in by_doc[md5]:
                doc_of.append(md5)
                index_of.append(int(row.get("chunk_index") or 0))
        doc_array = np.asarray(doc_of)
        similarity = vectors @ vectors.T
        np.fill_diagonal(similarity, -1.0)
        same_doc = doc_array[:, None] == doc_array[None, :]
        similarity[same_doc] = -1.0
        best = np.argmax(similarity, axis=1)
        best_score = similarity[np.arange(len(best)), best]

        edges: dict[tuple[int, int], dict[str, Any]] = {}
        for i, (j, score) in enumerate(zip(best.tolist(), best_score.tolist())):
            if score < EDGE_MIN_SCORE or j < 0 or int(j) == i:
                continue
            a, b = (i, int(j)) if i < int(j) else (int(j), i)
            if (a, b) in edges:
                continue
            edges[(a, b)] = {
                "a": f"{doc_of[a]}:{index_of[a]}",
                "b": f"{doc_of[b]}:{index_of[b]}",
                "score": round(float(score), 4),
            }
        ranked = sorted(edges.values(), key=lambda e: -e["score"])[:EDGE_MAX]
        return {"items": ranked}
