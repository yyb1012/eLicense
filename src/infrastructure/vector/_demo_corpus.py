# Time: 2026-04-18 19:05
# Description: 提供 N06 阶段本地可运行的示例语料，便于离线联调检索链路。
# Author: Feixue

from __future__ import annotations

from typing import Any

DEFAULT_DEMO_CORPUS: list[dict[str, Any]] = [
    {
        "chunk_id": "DOC-001",
        "content": "营业执照审核时需要核验证照有效期、统一社会信用代码与企业名称一致性。",
        "metadata": {
            "license_type": "营业执照",
            "current_node": "初审",
            "effective_date": "2026-12-31",
            "risk_tag": "normal",
        },
    },
    {
        "chunk_id": "DOC-002",
        "content": "合规审查应重点检查历史违规记录、风险标签以及整改完成证明。",
        "metadata": {
            "license_type": "通用",
            "current_node": "复审",
            "effective_date": "2027-06-30",
            "risk_tag": "high",
        },
    },
    {
        "chunk_id": "DOC-003",
        "content": "材料补件场景需要明确缺失材料清单，并在提交后再次执行完整性校验。",
        "metadata": {
            "license_type": "营业执照",
            "current_node": "补件",
            "effective_date": "2026-10-01",
            "risk_tag": "normal",
        },
    },
    {
        "chunk_id": "DOC-004",
        "content": "进度查询应返回当前节点、预计完成时间和待办动作，避免只返回笼统状态。",
        "metadata": {
            "license_type": "通用",
            "current_node": "处理中",
            "effective_date": "2026-08-20",
            "risk_tag": "normal",
        },
    },
    {
        "chunk_id": "DOC-005",
        "content": "当证照有效期临近或已过期时，应提升风险等级并建议人工复核。",
        "metadata": {
            "license_type": "营业执照",
            "current_node": "复核",
            "effective_date": "2025-12-31",
            "risk_tag": "critical",
        },
    },
    {
        "chunk_id": "DOC-006",
        "content": "证据引用必须可追溯，结论中应携带 evidence_refs 并记录来源片段编号。",
        "metadata": {
            "license_type": "通用",
            "current_node": "审查",
            "effective_date": "2028-01-01",
            "risk_tag": "normal",
        },
    },
]
