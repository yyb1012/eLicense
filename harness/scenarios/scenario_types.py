# Time: 2026-04-18 19:52
# Description: 定义 Harness 场景样例的结构化模型，约束输入、上下文与验收断言字段。
# Author: Feixue

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ScenarioInput:
    """定义单条场景的请求输入。"""

    session_id: str
    work_order_id: str
    message: str
    user_id: str


@dataclass(frozen=True)
class ScenarioExpectations:
    """定义单条场景的验收断言。"""

    route: str
    must_include_evidence_refs: bool
    max_latency_ms: int


@dataclass(frozen=True)
class ScenarioCase:
    """定义结构化场景：输入、上下文与预期三段式。"""

    id: str
    name: str
    input: ScenarioInput
    context: dict[str, Any]
    expectations: ScenarioExpectations

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ScenarioCase":
        """从原始字典构建场景对象，并执行最小字段校验。"""
        input_payload = payload.get("input", {})
        expectations_payload = payload.get("expectations", {})
        context_payload = payload.get("context", {})

        if not isinstance(input_payload, dict):
            raise ValueError("scenario.input must be a dict")
        if not isinstance(expectations_payload, dict):
            raise ValueError("scenario.expectations must be a dict")
        if not isinstance(context_payload, dict):
            raise ValueError("scenario.context must be a dict")

        scenario_input = ScenarioInput(
            session_id=str(input_payload.get("session_id", "")).strip(),
            work_order_id=str(input_payload.get("work_order_id", "")).strip(),
            message=str(input_payload.get("message", "")).strip(),
            user_id=str(input_payload.get("user_id", "HARNESS")).strip() or "HARNESS",
        )
        expectations = ScenarioExpectations(
            route=str(expectations_payload.get("route", "human_review")).strip() or "human_review",
            must_include_evidence_refs=bool(
                expectations_payload.get("must_include_evidence_refs", False)
            ),
            max_latency_ms=int(expectations_payload.get("max_latency_ms", 6000)),
        )

        if not scenario_input.session_id:
            raise ValueError("scenario.input.session_id is required")
        if not scenario_input.work_order_id:
            raise ValueError("scenario.input.work_order_id is required")
        if not scenario_input.message:
            raise ValueError("scenario.input.message is required")
        if expectations.max_latency_ms <= 0:
            raise ValueError("scenario.expectations.max_latency_ms must be > 0")

        return cls(
            id=str(payload.get("id", "")).strip(),
            name=str(payload.get("name", "")).strip(),
            input=scenario_input,
            context=dict(context_payload),
            expectations=expectations,
        )
