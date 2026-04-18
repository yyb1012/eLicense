# Time: 2026-04-19 01:11
# Description: 定义文档上传与 OCR 查询接口，支持 multipart 单/多文件入库并返回逐文件可追踪结果。
# Author: Feixue

from __future__ import annotations

import json
from dataclasses import dataclass
from email.parser import BytesParser
from email.policy import default as default_policy
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from src.application.services.document_ingest_service import DocumentIngestService
from src.interfaces.api.dependencies import get_document_ingest_service
from src.shared.tracing import ensure_trace_id

router = APIRouter(prefix="/api/v1/documents", tags=["documents"])


@dataclass(frozen=True)
class _UploadPayloadItem:
    """上传请求中的单文件载荷。"""

    file_name: str
    content_type: str
    file_bytes: bytes


class DocumentUploadItemResponse(BaseModel):
    """单文件上传结果。"""

    ok: bool
    trace_id: str
    file_name: str
    asset_id: str
    status: str
    error_code: str | None
    idempotent_hit: bool
    chunks_count: int
    message: str


class DocumentUploadBatchResponse(BaseModel):
    """批量上传结果。"""

    ok: bool
    trace_id: str
    results: list[DocumentUploadItemResponse]


class DocumentOcrResponse(BaseModel):
    """OCR 结果查询响应。"""

    trace_id: str
    asset_id: str
    status: str
    ocr_status: str | None
    ocr_provider: str | None
    ocr_model_version: str | None
    avg_confidence: float | None
    raw_text: str
    structured_fields: dict[str, Any]
    error_code: str | None
    message: str | None


@router.post("/upload", response_model=DocumentUploadBatchResponse)
async def upload_documents(
    request: Request,
    service: DocumentIngestService = Depends(get_document_ingest_service),
) -> DocumentUploadBatchResponse:
    """执行文档上传与入库流程，支持 multipart 单文件与多文件。"""
    trace_id = ensure_trace_id()
    files, source, metadata = await _extract_upload_payload(request)

    results: list[DocumentUploadItemResponse] = []
    for item in files:
        ingest_result = await service.ingest_document(
            trace_id=trace_id,
            file_name=item.file_name,
            file_bytes=item.file_bytes,
            content_type=item.content_type,
            source=source,
            metadata=metadata,
        )
        results.append(
            DocumentUploadItemResponse(
                ok=ingest_result.ok,
                trace_id=ingest_result.trace_id,
                file_name=ingest_result.file_name,
                asset_id=ingest_result.asset_id,
                status=ingest_result.status,
                error_code=ingest_result.error_code,
                idempotent_hit=ingest_result.idempotent_hit,
                chunks_count=ingest_result.chunks_count,
                message=ingest_result.message,
            )
        )

    return DocumentUploadBatchResponse(
        ok=all(item.ok for item in results),
        trace_id=trace_id,
        results=results,
    )


@router.get("/{asset_id}/ocr", response_model=DocumentOcrResponse)
async def get_document_ocr(
    asset_id: str,
    service: DocumentIngestService = Depends(get_document_ingest_service),
) -> DocumentOcrResponse:
    """查询指定资产 OCR 审计结果。"""
    trace_id = ensure_trace_id()
    result = await service.get_ocr_result(asset_id=asset_id)
    if result is None:
        raise HTTPException(status_code=404, detail={"code": "DOC_ASSET_NOT_FOUND", "asset_id": asset_id})

    return DocumentOcrResponse(
        trace_id=trace_id,
        asset_id=result["asset_id"],
        status=result["status"],
        ocr_status=result.get("ocr_status"),
        ocr_provider=result.get("ocr_provider"),
        ocr_model_version=result.get("ocr_model_version"),
        avg_confidence=result.get("avg_confidence"),
        raw_text=str(result.get("raw_text") or ""),
        structured_fields=dict(result.get("structured_fields") or {}),
        error_code=result.get("error_code"),
        message=result.get("message"),
    )


async def _extract_upload_payload(
    request: Request,
) -> tuple[list[_UploadPayloadItem], str, dict[str, Any]]:
    """根据请求类型解析上传载荷。"""
    content_type = request.headers.get("content-type", "").lower()
    if content_type.startswith("multipart/form-data"):
        return await _extract_multipart_payload(request=request)

    if content_type.startswith("application/json"):
        return await _extract_json_payload(request=request)

    raise HTTPException(
        status_code=415,
        detail={"code": "DOC_UNSUPPORTED_MEDIA_TYPE", "message": "仅支持 multipart/form-data 或 application/json。"},
    )


async def _extract_multipart_payload(
    *,
    request: Request,
) -> tuple[list[_UploadPayloadItem], str, dict[str, Any]]:
    """使用标准库 email 解析 multipart，避免依赖 python-multipart。"""
    raw_body = await request.body()
    content_type = request.headers.get("content-type", "")

    # 将 HTTP body 包装为 MIME 报文交给 email 解析器处理。
    mime_payload = (
        f"Content-Type: {content_type}\r\n"
        "MIME-Version: 1.0\r\n"
        "\r\n"
    ).encode("utf-8") + raw_body
    message = BytesParser(policy=default_policy).parsebytes(mime_payload)

    if not message.is_multipart():
        raise HTTPException(
            status_code=400,
            detail={"code": "DOC_MULTIPART_INVALID", "message": "multipart 载荷格式无效。"},
        )

    fields: dict[str, str] = {}
    files: list[_UploadPayloadItem] = []

    for part in message.iter_parts():
        disposition = (part.get("Content-Disposition") or "").lower()
        if "form-data" not in disposition:
            continue

        field_name = part.get_param("name", header="Content-Disposition")
        file_name = part.get_param("filename", header="Content-Disposition")
        payload = part.get_payload(decode=True) or b""

        if not field_name:
            continue

        if file_name:
            if field_name not in {"file", "files"}:
                continue
            files.append(
                _UploadPayloadItem(
                    file_name=str(file_name),
                    content_type=str(part.get_content_type() or "application/octet-stream"),
                    file_bytes=payload,
                )
            )
            continue

        fields[field_name] = payload.decode("utf-8", errors="ignore")

    source = fields.get("source", "manual_upload").strip() or "manual_upload"
    metadata = _parse_metadata(raw_value=fields.get("metadata"))

    if not files:
        raise HTTPException(
            status_code=400,
            detail={"code": "DOC_NO_FILES", "message": "未检测到上传文件。"},
        )
    return files, source, metadata


async def _extract_json_payload(
    *,
    request: Request,
) -> tuple[list[_UploadPayloadItem], str, dict[str, Any]]:
    payload = await request.json()
    source = str(payload.get("source") or "manual_upload").strip() or "manual_upload"
    metadata = payload.get("metadata")
    parsed_metadata = metadata if isinstance(metadata, dict) else {}

    files: list[_UploadPayloadItem] = []
    if isinstance(payload.get("files"), list):
        for item in payload["files"]:
            if not isinstance(item, dict):
                continue
            file_name = str(item.get("file_name") or "").strip()
            if not file_name:
                continue
            content = str(item.get("content") or "")
            files.append(
                _UploadPayloadItem(
                    file_name=file_name,
                    content_type=str(item.get("content_type") or "text/plain"),
                    file_bytes=content.encode("utf-8"),
                )
            )
    else:
        file_name = str(payload.get("file_name") or "").strip()
        content = str(payload.get("content") or "")
        if file_name and content:
            files.append(
                _UploadPayloadItem(
                    file_name=file_name,
                    content_type=str(payload.get("content_type") or "text/plain"),
                    file_bytes=content.encode("utf-8"),
                )
            )

    if not files:
        raise HTTPException(
            status_code=400,
            detail={"code": "DOC_NO_FILES", "message": "json 请求未包含可用文件内容。"},
        )
    return files, source, parsed_metadata


def _parse_metadata(*, raw_value: Any) -> dict[str, Any]:
    if raw_value is None:
        return {}
    if isinstance(raw_value, dict):
        return raw_value

    raw_text = str(raw_value).strip()
    if not raw_text:
        return {}
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "DOC_METADATA_INVALID_JSON", "message": "metadata 字段必须是合法 JSON。"},
        ) from exc

    if not isinstance(parsed, dict):
        raise HTTPException(
            status_code=400,
            detail={"code": "DOC_METADATA_INVALID_JSON", "message": "metadata 必须是 JSON 对象。"},
        )
    return parsed
