# Time: 2026-04-18 18:05
# Description: 校验混合检索在双路召回与降级场景下的核心行为。
# Author: Feixue

from __future__ import annotations

import asyncio

from src.infrastructure.vector.hybrid_retriever import HybridRetriever


def test_hybrid_retriever_dual_path_recall() -> None:
    retriever = HybridRetriever()
    result = asyncio.run(retriever.retrieve(query="营业执照 审核 有效期"))

    assert result["degrade_mode"] == "dual_path"
    assert result["metrics"]["fts_count"] > 0
    assert result["metrics"]["vector_count"] > 0
    assert result["should_human_review"] is False


def test_hybrid_retriever_single_path_failure_degrades() -> None:
    retriever = HybridRetriever()
    result = asyncio.run(
        retriever.retrieve(
            query="营业执照 审核",
            simulate_fail_vector=True,
        )
    )

    assert result["degrade_mode"] == "fts_only"
    assert result["metrics"]["fts_count"] > 0
    assert result["metrics"]["vector_failed"] is True
    assert result["should_human_review"] is False


def test_hybrid_retriever_double_failure_human_review_hint() -> None:
    retriever = HybridRetriever()
    result = asyncio.run(
        retriever.retrieve(
            query="营业执照",
            simulate_fail_fts=True,
            simulate_fail_vector=True,
        )
    )

    assert result["degrade_mode"] == "human_review"
    assert result["should_human_review"] is True
