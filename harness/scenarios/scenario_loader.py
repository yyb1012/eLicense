# Time: 2026-04-18 19:52
# Description: 提供 Harness 场景样例加载能力，支持从 JSON 文件读取并校验格式。
# Author: Feixue

from __future__ import annotations

import json
from pathlib import Path

from harness.scenarios.scenario_types import ScenarioCase

_DEFAULT_SCENARIO_FILE = Path(__file__).with_name("minimal_cases.json")


def load_scenarios(path: str | Path | None = None) -> list[ScenarioCase]:
    """加载场景文件并转换为结构化 ScenarioCase 列表。"""
    scenario_path = Path(path) if path is not None else _DEFAULT_SCENARIO_FILE
    payload = json.loads(scenario_path.read_text(encoding="utf-8-sig"))

    if isinstance(payload, dict):
        raw_cases = payload.get("cases", [])
    elif isinstance(payload, list):
        raw_cases = payload
    else:
        raise ValueError("scenario file must be a dict or list")

    if not isinstance(raw_cases, list):
        raise ValueError("scenario.cases must be a list")

    cases = [ScenarioCase.from_dict(item) for item in raw_cases]
    if not cases:
        raise ValueError("scenario list is empty")
    return cases
