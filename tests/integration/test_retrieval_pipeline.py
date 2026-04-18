# Time: 2026-04-18 19:05
# Description: 校验 N06 检索流水线在 Evidence 子图中的端到端行为与可复现性。
# Author: Feixue

from __future__ import annotations

import asyncio

from src.agent.graph.subgraphs.evidence_subgraph import run_evidence_subgraph


def test_retrieval_pipeline_returns_reproducible_context_bundle() -> None:
    state = {
        "trace_id": "trace-retrieval-001",
        "session_id": "S-RET-001",
        "work_order_id": "WO-RET-001",
        "user_input": "请审核营业执照并关注有效期和风险",
        "plan": {
            "retrieval_filter": {"license_type": "营业执照"},
        },
        "errors": [],
    }

    patch_first = asyncio.run(run_evidence_subgraph(state))
    patch_second = asyncio.run(run_evidence_subgraph(state))

    assert patch_first["rag_hits_fts"]
    assert patch_first["rag_hits_vector"]
    assert 1 <= len(patch_first["evidence_bundle"]) <= 10

    first_refs = [item["evidence_ref"] for item in patch_first["evidence_bundle"]]
    second_refs = [item["evidence_ref"] for item in patch_second["evidence_bundle"]]
    assert first_refs == second_refs

    retrieval_summary = patch_first["tool_results"][-1]
    assert retrieval_summary["tool"] == "hybrid_retrieval_pipeline"
    assert retrieval_summary["counts"]["after_rrf"] >= retrieval_summary["counts"]["final_context"]
