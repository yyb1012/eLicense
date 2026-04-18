# Time: 2026-04-18 21:42
# Description: 提供跨模块复用的安全类型转换工具函数。
# Author: Feixue

from __future__ import annotations

from typing import Any


def safe_float(value: Any) -> float:
    """安全解析浮点数，异常时回退 0.0，保证调用方链路可持续执行。"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def safe_int(value: Any) -> int:
    """安全解析整数，异常时回退 0。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
