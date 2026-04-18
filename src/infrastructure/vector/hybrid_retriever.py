# Time: 2026-04-18 19:05
# Description: 提供硬过滤与双路召回能力，输出可供融合与精排使用的候选集合。
# Author: Feixue

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

from src.infrastructure.vector._demo_corpus import DEFAULT_DEMO_CORPUS
from src.infrastructure.vector._text_utils import jaccard, tokenize


@dataclass(frozen=True)
class RetrievalConfig:
    """定义 N06 检索默认参数。"""

    m: int = 16
    ef_construction: int = 200
    ef_search: int = 100
    top_k_fts: int = 50
    top_k_vector: int = 50
    top_n_after_rrf: int = 80
    top_n_final: int = 10


class HybridRetriever:
    """执行 Hard Filter + 双路召回，并输出召回层可观测信息。"""

    def __init__(self, config: RetrievalConfig | None = None) -> None:
        self.config = config or RetrievalConfig()

    async def retrieve(
        self,
        *,
        query: str,
        filters: dict[str, Any] | None = None,
        corpus: list[dict[str, Any]] | None = None,
        simulate_fail_fts: bool = False,
        simulate_fail_vector: bool = False,
    ) -> dict[str, Any]:
        """执行召回，并对单路/双路失败给出降级信号。"""
        start = time.perf_counter()
        scoped_corpus = self._hard_filter(corpus or DEFAULT_DEMO_CORPUS, filters or {})

        fts_result, vector_result = await asyncio.gather(
            self._recall_fts(query=query, corpus=scoped_corpus, simulate_fail=simulate_fail_fts),
            self._recall_vector(
                query=query,
                corpus=scoped_corpus,
                simulate_fail=simulate_fail_vector,
            ),
            return_exceptions=True,
        )

        fts_failed = isinstance(fts_result, Exception)
        vector_failed = isinstance(vector_result, Exception)
        fts_hits = [] if fts_failed else fts_result
        vector_hits = [] if vector_failed else vector_result

        degrade_mode = "dual_path"
        should_human_review = False

        # 降级策略：单路失败走另一条召回；双路失败或双空召回提示人工复核。
        if fts_failed and vector_failed:
            degrade_mode = "human_review"
            should_human_review = True
        elif fts_failed or (not fts_hits and vector_hits):
            degrade_mode = "vector_only"
        elif vector_failed or (not vector_hits and fts_hits):
            degrade_mode = "fts_only"
        elif not fts_hits and not vector_hits:
            degrade_mode = "human_review"
            should_human_review = True

        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        return {
            "fts_hits": fts_hits,
            "vector_hits": vector_hits,
            "degrade_mode": degrade_mode,
            "should_human_review": should_human_review,
            "recall_latency_ms": latency_ms,
            "metrics": {
                "corpus_size_after_filter": len(scoped_corpus),
                "fts_count": len(fts_hits),
                "vector_count": len(vector_hits),
                "fts_failed": fts_failed,
                "vector_failed": vector_failed,
            },
        }

    async def _recall_fts(
        self,
        *,
        query: str,
        corpus: list[dict[str, Any]],
        simulate_fail: bool,
    ) -> list[dict[str, Any]]:
        """FTS 路径：基于关键词重叠做召回评分。"""
        if simulate_fail:
            raise RuntimeError("fts_recall_failed")

        query_tokens = set(tokenize(query))
        hits: list[dict[str, Any]] = []
        for item in corpus:
            content_tokens = set(tokenize(item.get("content", "")))
            overlap = len(query_tokens & content_tokens)
            if overlap <= 0:
                continue
            hits.append(
                {
                    "chunk_id": item["chunk_id"],
                    "content": item["content"],
                    "metadata": item.get("metadata", {}),
                    "score_fts": float(overlap),
                }
            )

        hits.sort(key=lambda hit: (-hit["score_fts"], hit["chunk_id"]))
        top_hits = hits[: self.config.top_k_fts]
        for index, hit in enumerate(top_hits, start=1):
            hit["fts_rank"] = index
        await asyncio.sleep(0)
        return top_hits

    async def _recall_vector(
        self,
        *,
        query: str,
        corpus: list[dict[str, Any]],
        simulate_fail: bool,
    ) -> list[dict[str, Any]]:
        """向量路径：用 Jaccard 近似语义召回，先保证可运行与可替换。"""
        if simulate_fail:
            raise RuntimeError("vector_recall_failed")

        query_tokens = set(tokenize(query))
        hits: list[dict[str, Any]] = []
        for item in corpus:
            content_tokens = set(tokenize(item.get("content", "")))
            score = jaccard(query_tokens, content_tokens)
            if score <= 0:
                continue
            hits.append(
                {
                    "chunk_id": item["chunk_id"],
                    "content": item["content"],
                    "metadata": item.get("metadata", {}),
                    "score_vector": round(score, 6),
                }
            )

        hits.sort(key=lambda hit: (-hit["score_vector"], hit["chunk_id"]))
        top_hits = hits[: self.config.top_k_vector]
        for index, hit in enumerate(top_hits, start=1):
            hit["vector_rank"] = index
        await asyncio.sleep(0)
        return top_hits

    def _hard_filter(
        self,
        corpus: list[dict[str, Any]],
        filters: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """执行检索前硬过滤，只保留业务条件命中的候选。"""
        if not filters:
            return corpus

        effective_filters = {
            key: value
            for key, value in filters.items()
            if key in {"license_type", "current_node", "effective_date", "risk_tag"}
        }
        if not effective_filters:
            return corpus

        filtered: list[dict[str, Any]] = []
        for item in corpus:
            metadata = item.get("metadata", {})
            if all(_match_filter(metadata.get(key), value) for key, value in effective_filters.items()):
                filtered.append(item)
        return filtered


def _match_filter(actual: Any, expected: Any) -> bool:
    """支持标量与列表过滤条件，保持过滤逻辑可扩展。"""
    if isinstance(expected, (list, tuple, set)):
        return actual in expected
    return actual == expected
