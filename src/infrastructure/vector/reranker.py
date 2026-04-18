# Time: 2026-04-18 19:05
# Description: 对融合候选执行精排并标记最终上下文入选结果。
# Author: Feixue

from __future__ import annotations

import time
from typing import Any

from src.infrastructure.vector._text_utils import jaccard, tokenize


class SimpleReranker:
    """N06 阶段精排器：提供可复现排序，并支持权重可配置。"""

    def __init__(self, *, lexical_weight: float = 0.7, rrf_weight: float = 0.3) -> None:
        total_weight = lexical_weight + rrf_weight
        if total_weight <= 0:
            raise ValueError("lexical_weight + rrf_weight must be positive")

        # 统一归一化，避免调用方传入任意比例后影响分值尺度。
        self._lexical_weight = lexical_weight / total_weight
        self._rrf_weight = rrf_weight / total_weight

    def rerank(
        self,
        *,
        query: str,
        candidates: list[dict[str, Any]],
        top_n_final: int,
    ) -> dict[str, Any]:
        """计算 rerank_score 并产出 final_rank 与 selected_for_context。"""
        start = time.perf_counter()
        query_tokens = set(tokenize(query))

        reranked: list[dict[str, Any]] = []
        for item in candidates:
            content_tokens = set(tokenize(item.get("content", "")))
            lexical_score = jaccard(query_tokens, content_tokens)
            rrf_score = float(item.get("rrf_score", 0.0))
            rerank_score = round(
                (self._lexical_weight * lexical_score) + (self._rrf_weight * rrf_score),
                6,
            )
            reranked.append(
                {
                    **item,
                    "rerank_score": rerank_score,
                }
            )

        reranked.sort(
            key=lambda item: (
                -item["rerank_score"],
                -float(item.get("rrf_score", 0.0)),
                item.get("chunk_id", ""),
            )
        )

        for rank, item in enumerate(reranked, start=1):
            item["final_rank"] = rank
            item["selected_for_context"] = rank <= top_n_final

        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        return {
            "items": reranked,
            "latency_ms": latency_ms,
        }
