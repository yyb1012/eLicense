# Time: 2026-04-18 19:05
# Description: 提供检索阶段共用的分词与相似度计算函数。
# Author: Feixue

from __future__ import annotations

import re


def tokenize(text: str) -> list[str]:
    """最小分词器：英文按词、中文按单字，确保中英混输可统一处理。"""
    return re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]", text.lower())


def jaccard(left: set[str], right: set[str]) -> float:
    """计算词项 Jaccard 相似度，用于召回与精排共享评分口径。"""
    if not left or not right:
        return 0.0
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)
