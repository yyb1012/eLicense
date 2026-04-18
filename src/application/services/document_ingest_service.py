# Time: 2026-04-19 00:35
# Description: 编排文档入库全链路，负责解析、标题递归切分、向量化、幂等去重、状态流转与失败补偿审计。
# Author: Feixue

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.infrastructure.db.postgres_repo import PostgresRepository
from src.infrastructure.document.chunker import ChunkedDocument, DocumentChunkError, HeadingAwareChunker
from src.infrastructure.document.parser import (
    DocumentParseError,
    DocumentParserRegistry,
    ParsedDocument,
)
from src.infrastructure.embedding.providers import BaseEmbeddingProvider, EmbeddingProviderError
from src.infrastructure.ocr.adapters import BaseOcrAdapter
from src.shared.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class DocumentIngestResult:
    """单文件入库结果。"""

    ok: bool
    trace_id: str
    file_name: str
    asset_id: str
    status: str
    idempotent_hit: bool
    chunks_count: int
    error_code: str | None
    message: str
    metadata: dict[str, Any]


class DocumentIngestError(Exception):
    """文档入库过程中可预期的业务错误。"""

    def __init__(self, code: str, message: str, *, stage: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.stage = stage
        self.retryable = retryable


class DocumentIngestService:
    """文档入库应用服务。"""

    def __init__(
        self,
        *,
        postgres_repo: PostgresRepository,
        parser_registry: DocumentParserRegistry,
        chunker: HeadingAwareChunker,
        embedding_provider: BaseEmbeddingProvider,
        ocr_adapter: BaseOcrAdapter,
    ) -> None:
        self._postgres_repo = postgres_repo
        self._parser_registry = parser_registry
        self._chunker = chunker
        self._embedding_provider = embedding_provider
        self._ocr_adapter = ocr_adapter

    async def ingest_document(
        self,
        *,
        trace_id: str,
        file_name: str,
        file_bytes: bytes,
        content_type: str,
        source: str,
        metadata: dict[str, Any] | None = None,
    ) -> DocumentIngestResult:
        """执行单文件入库主流程。"""
        sanitized_metadata = self._sanitize_metadata(metadata)
        normalized_source = source.strip() or "manual_upload"
        normalized_file_name = file_name.strip() or "unknown.txt"
        normalized_content_type = content_type.strip() or "application/octet-stream"
        file_type = Path(normalized_file_name).suffix.lower().lstrip(".")

        file_hash = hashlib.sha256(file_bytes).hexdigest()
        idempotency_key = f"{file_hash}:{normalized_source}"

        asset, created = await self._postgres_repo.create_or_get_document_asset(
            trace_id=trace_id,
            file_name=normalized_file_name,
            file_type=file_type or "unknown",
            content_type=normalized_content_type,
            file_size=len(file_bytes),
            source=normalized_source,
            file_hash=file_hash,
            idempotency_key=idempotency_key,
            metadata=sanitized_metadata,
        )
        asset_id = str(asset["asset_id"])

        if not created:
            existing_status = str(asset.get("status", "received"))
            existing_chunks = await self._postgres_repo.list_document_chunks(asset_id=asset_id)
            return DocumentIngestResult(
                ok=existing_status != "failed",
                trace_id=trace_id,
                file_name=normalized_file_name,
                asset_id=asset_id,
                status=existing_status,
                idempotent_hit=True,
                chunks_count=len(existing_chunks),
                error_code=asset.get("error_code"),
                message="idempotent_request_reused_existing_asset",
                metadata=asset.get("metadata", {}),
            )

        try:
            parsed_document = self._parse_document(
                trace_id=trace_id,
                file_name=normalized_file_name,
                file_bytes=file_bytes,
                content_type=normalized_content_type,
            )

            parsed_document = await self._handle_ocr_if_needed(
                trace_id=trace_id,
                asset_id=asset_id,
                file_name=normalized_file_name,
                file_bytes=file_bytes,
                parsed_document=parsed_document,
            )

            await self._postgres_repo.update_document_asset_status(
                asset_id=asset_id,
                status="parsed",
                stage="parsed",
                page_count=parsed_document.page_count,
                metadata_patch={
                    "file_name": normalized_file_name,
                    "file_type": parsed_document.file_type,
                    "page_count": parsed_document.page_count,
                    "source": normalized_source,
                    "file_hash": file_hash,
                },
                audit_event=self._build_audit_event(trace_id=trace_id, stage="parsed"),
            )

            chunk_items = self._chunk_document(
                parsed_document=parsed_document,
                source=normalized_source,
                file_hash=file_hash,
            )
            stored_chunks = await self._postgres_repo.replace_document_chunks(
                asset_id=asset_id,
                chunks=chunk_items,
            )
            await self._postgres_repo.update_document_asset_status(
                asset_id=asset_id,
                status="chunked",
                stage="chunked",
                audit_event=self._build_audit_event(trace_id=trace_id, stage="chunked"),
            )

            embeddings = await self._embed_chunks(
                trace_id=trace_id,
                stored_chunks=stored_chunks,
            )
            await self._postgres_repo.replace_chunk_embeddings(
                asset_id=asset_id,
                embeddings=embeddings,
            )
            await self._postgres_repo.update_document_asset_status(
                asset_id=asset_id,
                status="embedded",
                stage="embedded",
                audit_event=self._build_audit_event(trace_id=trace_id, stage="embedded"),
            )

            final_asset = await self._postgres_repo.update_document_asset_status(
                asset_id=asset_id,
                status="indexed",
                stage="indexed",
                audit_event=self._build_audit_event(trace_id=trace_id, stage="indexed"),
            )
            return DocumentIngestResult(
                ok=True,
                trace_id=trace_id,
                file_name=normalized_file_name,
                asset_id=asset_id,
                status=str(final_asset["status"]),
                idempotent_hit=False,
                chunks_count=len(stored_chunks),
                error_code=None,
                message="document_ingest_success",
                metadata=final_asset.get("metadata", {}),
            )

        except DocumentIngestError as exc:
            return await self._handle_ingest_failure(
                trace_id=trace_id,
                file_name=normalized_file_name,
                asset_id=asset_id,
                metadata=sanitized_metadata,
                error=exc,
            )
        except Exception as exc:  # noqa: BLE001
            return await self._handle_ingest_failure(
                trace_id=trace_id,
                file_name=normalized_file_name,
                asset_id=asset_id,
                metadata=sanitized_metadata,
                error=DocumentIngestError(
                    code="DOC_INGEST_INTERNAL_ERROR",
                    message=str(exc),
                    stage="internal",
                    retryable=False,
                ),
            )

    async def get_ocr_result(self, *, asset_id: str) -> dict[str, Any] | None:
        """查询资产 OCR 审计信息。"""
        asset = await self._postgres_repo.get_document_asset(asset_id=asset_id)
        if asset is None:
            return None

        metadata = asset.get("metadata", {})
        ocr_info = metadata.get("ocr", {}) if isinstance(metadata, dict) else {}
        return {
            "asset_id": asset_id,
            "trace_id": asset.get("trace_id", ""),
            "status": asset.get("status", "unknown"),
            "ocr_status": asset.get("ocr_status"),
            "ocr_provider": ocr_info.get("provider"),
            "ocr_model_version": ocr_info.get("model_version"),
            "avg_confidence": ocr_info.get("avg_confidence"),
            "raw_text": ocr_info.get("raw_text", ""),
            "structured_fields": ocr_info.get("structured_fields", {}),
            "error_code": ocr_info.get("error_code"),
            "message": ocr_info.get("message"),
        }

    def _parse_document(
        self,
        *,
        trace_id: str,
        file_name: str,
        file_bytes: bytes,
        content_type: str,
    ) -> ParsedDocument:
        try:
            return self._parser_registry.parse(
                file_name=file_name,
                file_bytes=file_bytes,
                content_type=content_type,
                trace_id=trace_id,
            )
        except DocumentParseError as exc:
            raise DocumentIngestError(
                code=exc.code,
                message=exc.message,
                stage="parsed",
                retryable=False,
            ) from exc

    async def _handle_ocr_if_needed(
        self,
        *,
        trace_id: str,
        asset_id: str,
        file_name: str,
        file_bytes: bytes,
        parsed_document: ParsedDocument,
    ) -> ParsedDocument:
        """处理 PDF 文本不可提取场景，预埋 OCR 状态并保证可审计。"""
        if not parsed_document.needs_ocr:
            return parsed_document

        ocr_result = await self._ocr_adapter.extract_from_pdf(
            file_name=file_name,
            file_bytes=file_bytes,
            trace_id=trace_id,
        )

        await self._postgres_repo.update_document_asset_status(
            asset_id=asset_id,
            status="parsed",
            stage="parsed",
            ocr_status=ocr_result.status,
            metadata_patch={
                "ocr": {
                    "provider": self._ocr_adapter.adapter_name,
                    "model_version": ocr_result.model_version,
                    "avg_confidence": ocr_result.avg_confidence,
                    "raw_text": ocr_result.raw_text,
                    "structured_fields": ocr_result.structured_fields,
                    "error_code": ocr_result.error_code,
                    "message": ocr_result.message,
                }
            },
            audit_event=self._build_audit_event(
                trace_id=trace_id,
                stage="parsed",
                extra={"ocr_status": ocr_result.status},
            ),
        )

        if not ocr_result.raw_text.strip():
            raise DocumentIngestError(
                code="DOC_PDF_TEXT_UNAVAILABLE",
                message="pdf 文本不可提取，已进入 OCR 审计状态。",
                stage="parsed",
                retryable=ocr_result.status == "ocr_pending",
            )
        return parsed_document

    def _chunk_document(
        self,
        *,
        parsed_document: ParsedDocument,
        source: str,
        file_hash: str,
    ) -> list[dict[str, Any]]:
        try:
            chunked_documents = self._chunker.chunk_document(
                parsed_document=parsed_document,
                source=source,
                file_hash=file_hash,
            )
        except DocumentChunkError as exc:
            raise DocumentIngestError(
                code=exc.code,
                message=exc.message,
                stage="chunked",
                retryable=False,
            ) from exc

        chunks: list[dict[str, Any]] = []
        for item in chunked_documents:
            chunks.append(self._chunk_to_repo_payload(item=item))
        return chunks

    async def _embed_chunks(
        self,
        *,
        trace_id: str,
        stored_chunks: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        provider_meta = self._embedding_provider.meta

        reuse_vectors: dict[int, tuple[list[float], str | None]] = {}
        pending_indices: list[int] = []
        pending_texts: list[str] = []

        for idx, chunk in enumerate(stored_chunks):
            reusable = await self._postgres_repo.find_reusable_embedding(
                chunk_hash=str(chunk["chunk_hash"]),
                provider=provider_meta.provider,
                model=provider_meta.model,
                embedding_version=provider_meta.embedding_version,
            )
            if reusable is not None:
                reuse_vectors[idx] = (
                    list(reusable["vector"]),
                    str(reusable.get("source_chunk_id") or ""),
                )
                continue
            pending_indices.append(idx)
            pending_texts.append(str(chunk["content"]))

        generated_vectors: dict[int, list[float]] = {}
        if pending_texts:
            try:
                vectors = await self._embedding_provider.embed_texts(pending_texts)
            except EmbeddingProviderError as exc:
                raise DocumentIngestError(
                    code=exc.code,
                    message=exc.message,
                    stage="embedded",
                    retryable=exc.retryable,
                ) from exc

            if len(vectors) != len(pending_indices):
                raise DocumentIngestError(
                    code="DOC_EMBEDDING_RESPONSE_COUNT_MISMATCH",
                    message="embedding 返回数量与待处理 chunk 数量不一致。",
                    stage="embedded",
                    retryable=False,
                )
            for pos, vector in enumerate(vectors):
                generated_vectors[pending_indices[pos]] = list(vector)

        embedding_payloads: list[dict[str, Any]] = []
        for idx, chunk in enumerate(stored_chunks):
            reused_from_chunk_id: str | None = None
            if idx in reuse_vectors:
                vector, reused_from_chunk_id = reuse_vectors[idx]
            else:
                vector = generated_vectors.get(idx, [])

            if not vector:
                raise DocumentIngestError(
                    code="DOC_EMBEDDING_EMPTY_VECTOR",
                    message="embedding 结果为空向量。",
                    stage="embedded",
                    retryable=False,
                )

            embedding_payloads.append(
                {
                    "chunk_id": chunk["chunk_id"],
                    "chunk_hash": chunk["chunk_hash"],
                    "vector": vector,
                    "provider": provider_meta.provider,
                    "model": provider_meta.model,
                    "dimension": len(vector),
                    "embedding_version": provider_meta.embedding_version,
                    "status": "ok",
                    "error_code": None,
                    "metadata": {
                        "trace_id": trace_id,
                        "chunk_index": chunk.get("chunk_index"),
                        "reused_from_chunk_id": reused_from_chunk_id,
                    },
                }
            )

        return embedding_payloads

    async def _handle_ingest_failure(
        self,
        *,
        trace_id: str,
        file_name: str,
        asset_id: str,
        metadata: dict[str, Any],
        error: DocumentIngestError,
    ) -> DocumentIngestResult:
        await self._postgres_repo.update_document_asset_status(
            asset_id=asset_id,
            status="failed",
            stage=error.stage,
            error_code=error.code,
            error_message=error.message,
            compensation=self._build_compensation_payload(error=error),
            audit_event=self._build_audit_event(
                trace_id=trace_id,
                stage="failed",
                extra={"error_code": error.code, "failed_stage": error.stage},
            ),
        )
        self._log_stage(
            trace_id=trace_id,
            asset_id=asset_id,
            stage="failed",
            error_code=error.code,
        )
        return DocumentIngestResult(
            ok=False,
            trace_id=trace_id,
            file_name=file_name,
            asset_id=asset_id,
            status="failed",
            idempotent_hit=False,
            chunks_count=0,
            error_code=error.code,
            message=error.message,
            metadata=metadata,
        )

    def _chunk_to_repo_payload(self, *, item: ChunkedDocument) -> dict[str, Any]:
        page_ref = item.page_ref
        return {
            "chunk_index": item.chunk_index,
            "chunk_hash": item.chunk_hash,
            "chunk_type": item.chunk_type,
            "content": item.content,
            "token_count": item.token_count,
            "start_offset": item.start_offset,
            "end_offset": item.end_offset,
            "start_page": page_ref.get("start"),
            "end_page": page_ref.get("end"),
            "page_no": page_ref.get("page_no"),
            "h1": item.h1,
            "h2": item.h2,
            "heading_path": item.heading_path,
            "metadata": dict(item.metadata),
        }

    def _sanitize_metadata(self, metadata: dict[str, Any] | None) -> dict[str, Any]:
        if not metadata:
            return {}
        sanitized: dict[str, Any] = {}
        for key, value in metadata.items():
            normalized_key = str(key)
            if isinstance(value, (str, int, float, bool)) or value is None:
                sanitized[normalized_key] = value
            else:
                sanitized[normalized_key] = str(value)
        return sanitized

    def _build_compensation_payload(self, *, error: DocumentIngestError) -> dict[str, Any]:
        """构建失败补偿占位，保证后续人工或任务补偿可追踪。"""
        return {
            "queued": True,
            "action": "manual_reingest_required",
            "reason": error.code,
            "stage": error.stage,
            "retryable": error.retryable,
        }

    def _build_audit_event(
        self,
        *,
        trace_id: str,
        stage: str,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = {"trace_id": trace_id, "stage": stage}
        if extra:
            payload.update(extra)
        return payload

    def _log_stage(
        self,
        *,
        trace_id: str,
        asset_id: str,
        stage: str,
        error_code: str | None = None,
    ) -> None:
        level = logger.warning if error_code else logger.info
        level(
            "document_ingest_stage",
            extra={
                "extra_fields": {
                    "trace_id": trace_id,
                    "asset_id": asset_id,
                    "stage": stage,
                    "error_code": error_code,
                }
            },
        )
