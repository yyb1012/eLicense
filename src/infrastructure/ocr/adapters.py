# Time: 2026-04-19 00:10
# Description: 定义 OCR 适配器接口与 PaddleOCR 预埋占位实现，保障文本不可提取场景的状态流转与审计。
# Author: Feixue

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class OcrResult:
    """OCR 执行结果，统一结构便于审计字段落库。"""

    status: str
    raw_text: str
    structured_fields: dict[str, Any]
    avg_confidence: float | None
    error_code: str | None
    message: str
    model_version: str


class BaseOcrAdapter(ABC):
    """OCR adapter 抽象，后续可替换为真实 PaddleOCR 实现。"""

    @property
    @abstractmethod
    def adapter_name(self) -> str:
        """返回 OCR adapter 名称。"""

    @abstractmethod
    async def extract_from_pdf(
        self,
        *,
        file_name: str,
        file_bytes: bytes,
        trace_id: str,
    ) -> OcrResult:
        """对文本不可提取的 PDF 执行 OCR。"""


class PaddleOcrSlotAdapter(BaseOcrAdapter):
    """PaddleOCR 插槽：当前仅负责状态标记，不执行真实 OCR 引擎。"""

    def __init__(self, *, enabled: bool, model_version: str = "paddleocr-slot-v1") -> None:
        self._enabled = bool(enabled)
        self._model_version = model_version

    @property
    def adapter_name(self) -> str:
        return "paddleocr"

    async def extract_from_pdf(
        self,
        *,
        file_name: str,
        file_bytes: bytes,
        trace_id: str,
    ) -> OcrResult:
        del file_name
        del file_bytes
        del trace_id

        if self._enabled:
            # 保留可审计状态，等待 N20 接入真实 OCR 引擎。
            return OcrResult(
                status="ocr_pending",
                raw_text="",
                structured_fields={},
                avg_confidence=None,
                error_code=None,
                message="ocr_adapter_slot_pending",
                model_version=self._model_version,
            )

        return OcrResult(
            status="ocr_skipped",
            raw_text="",
            structured_fields={},
            avg_confidence=None,
            error_code="DOC_OCR_DISABLED",
            message="ocr_adapter_disabled",
            model_version=self._model_version,
        )


def build_default_ocr_adapter(*, enabled: bool) -> BaseOcrAdapter:
    """构建默认 OCR adapter。"""
    return PaddleOcrSlotAdapter(enabled=enabled)
