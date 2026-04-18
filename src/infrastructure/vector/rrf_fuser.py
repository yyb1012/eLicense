# Time: 2026-04-18 19:05
# Description: 负责将 FTS 与向量召回结果按 RRF 规则融合并去重排序。
# Author: Feixue

from __future__ import annotations

from typing import Any


class RrfFuser:
    """实现 N06 的 RRF 融合逻辑。"""

    def __init__(self, rrf_k: int = 60) -> None:
        self._rrf_k = rrf_k

    def fuse(
        self,
        *,
        fts_hits: list[dict[str, Any]],
        vector_hits: list[dict[str, Any]],
        top_n_after_rrf: int,
    ) -> list[dict[str, Any]]:
        """按 RRF 公式融合双路召回结果，并统一候选池。"""
        merged: dict[str, dict[str, Any]] = {}

        for rank, hit in enumerate(fts_hits, start=1):
            self._accumulate(merged=merged, hit=hit, rank=rank, source="fts")

        for rank, hit in enumerate(vector_hits, start=1):
            self._accumulate(merged=merged, hit=hit, rank=rank, source="vector")

        fused = list(merged.values())
        for item in fused:
            item["retrieval_sources"] = sorted(item["retrieval_sources"])

        fused.sort(key=lambda item: (-item["rrf_score"], item["chunk_id"]))
        top_items = fused[:top_n_after_rrf]
        for rank, item in enumerate(top_items, start=1):
            item["rrf_rank"] = rank
        return top_items

    def _accumulate(
        self,
        *,
        merged: dict[str, dict[str, Any]],
        hit: dict[str, Any],
        rank: int,
        source: str,
    ) -> None:
        """聚合同一 chunk 的双路分数并记录来源与原始位次。"""
        chunk_id = hit["chunk_id"]
        if chunk_id not in merged:
            merged[chunk_id] = {
                "chunk_id": chunk_id,
                "content": hit.get("content", ""),
                "metadata": hit.get("metadata", {}),
                "rrf_score": 0.0,
                "score_fts": 0.0,
                "score_vector": 0.0,
                "fts_rank": None,
                "vector_rank": None,
                "retrieval_sources": set(),
            }

        merged[chunk_id]["rrf_score"] += 1.0 / (self._rrf_k + rank)
        merged[chunk_id]["retrieval_sources"].add(source)

        if source == "fts":
            merged[chunk_id]["score_fts"] = hit.get("score_fts", 0.0)
            merged[chunk_id]["fts_rank"] = rank
        else:
            merged[chunk_id]["score_vector"] = hit.get("score_vector", 0.0)
            merged[chunk_id]["vector_rank"] = rank
