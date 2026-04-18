# Time: 2026-04-19 00:02
# Description: 实现按 H1/H2 递归切分与二次长度切分策略，输出可审计 metadata 的文本与表格 chunk。
# Author: Feixue

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from src.infrastructure.document.parser import DocumentBlock, ParsedDocument


class DocumentChunkError(Exception):
    """文档切分阶段错误，包含配置与数据边界约束。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ChunkedDocument:
    """统一 chunk 结构，供持久化和 embedding 阶段复用。"""

    chunk_index: int
    chunk_type: str
    content: str
    token_count: int
    start_offset: int
    end_offset: int
    page_ref: dict[str, int | None]
    h1: str | None
    h2: str | None
    heading_path: str
    metadata: dict[str, object]
    chunk_hash: str


@dataclass
class _TextSpan:
    """文本切分前的中间结构，保存文本与页码映射。"""

    text: str
    page_no: int | None


@dataclass
class _SectionBuffer:
    """按标题路径聚合的段落缓冲区。"""

    order: int
    h1: str | None
    h2: str | None
    heading_path: str
    spans: list[_TextSpan] = field(default_factory=list)


class HeadingAwareChunker:
    """标题递归切分器：先按 H1/H2 归组，再执行 token/长度二次切分。"""

    def __init__(
        self,
        *,
        max_tokens: int,
        max_chars: int,
        overlap_tokens: int,
    ) -> None:
        self._max_tokens = int(max_tokens)
        self._max_chars = int(max_chars)
        self._overlap_tokens = int(overlap_tokens)

    def chunk_document(
        self,
        *,
        parsed_document: ParsedDocument,
        source: str,
        file_hash: str,
    ) -> list[ChunkedDocument]:
        """执行标题递归切分，并输出稳定 metadata。"""
        self._validate_config()

        sections: dict[tuple[str | None, str | None], _SectionBuffer] = {}
        section_order: list[tuple[str | None, str | None]] = []
        table_chunks: list[tuple[int, ChunkedDocument]] = []

        current_h1: str | None = None
        current_h2: str | None = None

        for order, block in enumerate(parsed_document.blocks):
            if block.block_type == "heading":
                if block.heading_level == 1:
                    current_h1 = block.text.strip() or None
                    current_h2 = None
                elif block.heading_level == 2:
                    current_h2 = block.text.strip() or None
                continue

            heading_path = self._build_heading_path(current_h1=current_h1, current_h2=current_h2)
            if block.block_type == "table":
                table_chunks.append(
                    (
                        order,
                        self._build_table_chunk(
                            parsed_document=parsed_document,
                            block=block,
                            h1=current_h1,
                            h2=current_h2,
                            heading_path=heading_path,
                            source=source,
                            file_hash=file_hash,
                        ),
                    )
                )
                continue

            key = (current_h1, current_h2)
            section = sections.get(key)
            if section is None:
                section = _SectionBuffer(
                    order=order,
                    h1=current_h1,
                    h2=current_h2,
                    heading_path=heading_path,
                )
                sections[key] = section
                section_order.append(key)
            text = block.text.strip()
            if text:
                section.spans.append(_TextSpan(text=text, page_no=block.page_no))

        text_chunks: list[tuple[float, ChunkedDocument]] = []
        for section_key in section_order:
            section = sections[section_key]
            chunks = self._chunk_section(
                parsed_document=parsed_document,
                section=section,
                source=source,
                file_hash=file_hash,
            )
            for idx, chunk in enumerate(chunks):
                # 用细粒度偏移保持同一 section 内 chunk 顺序稳定。
                text_chunks.append((float(section.order) + (idx / 1000.0), chunk))

        merged: list[tuple[float, ChunkedDocument]] = text_chunks + [
            (float(order), chunk) for order, chunk in table_chunks
        ]
        merged.sort(key=lambda item: item[0])

        final_chunks: list[ChunkedDocument] = []
        for index, (_, chunk) in enumerate(merged):
            final_metadata = dict(chunk.metadata)
            final_metadata["chunk_index"] = index
            final_chunks.append(
                ChunkedDocument(
                    chunk_index=index,
                    chunk_type=chunk.chunk_type,
                    content=chunk.content,
                    token_count=chunk.token_count,
                    start_offset=chunk.start_offset,
                    end_offset=chunk.end_offset,
                    page_ref=dict(chunk.page_ref),
                    h1=chunk.h1,
                    h2=chunk.h2,
                    heading_path=chunk.heading_path,
                    metadata=final_metadata,
                    chunk_hash=chunk.chunk_hash,
                )
            )

        if not final_chunks:
            raise DocumentChunkError(
                code="DOC_NO_VALID_CHUNK",
                message="文档切分后未生成有效 chunk。",
            )
        return final_chunks

    def _validate_config(self) -> None:
        if self._max_tokens <= 0:
            raise DocumentChunkError("DOC_CHUNK_CONFIG_INVALID", "max_tokens 必须大于 0。")
        if self._max_chars <= 0:
            raise DocumentChunkError("DOC_CHUNK_CONFIG_INVALID", "max_chars 必须大于 0。")
        if self._overlap_tokens < 0 or self._overlap_tokens >= self._max_tokens:
            raise DocumentChunkError(
                "DOC_CHUNK_CONFIG_INVALID",
                "overlap_tokens 必须满足 0<=overlap_tokens<max_tokens。",
            )

    def _chunk_section(
        self,
        *,
        parsed_document: ParsedDocument,
        section: _SectionBuffer,
        source: str,
        file_hash: str,
    ) -> list[ChunkedDocument]:
        token_units: list[tuple[str, int | None]] = []
        for span in section.spans:
            for token in _tokenize_text(span.text):
                token_units.append((token, span.page_no))

        if not token_units:
            return []

        chunked: list[ChunkedDocument] = []
        cursor = 0
        while cursor < len(token_units):
            upper = min(cursor + self._max_tokens, len(token_units))
            window = token_units[cursor:upper]
            # 保证字符上限，避免仅 token 阈值导致异常长 chunk。
            while window and len(" ".join(token for token, _ in window)) > self._max_chars:
                upper -= 1
                window = token_units[cursor:upper]

            if not window:
                upper = min(cursor + 1, len(token_units))
                window = token_units[cursor:upper]

            chunk_text = " ".join(token for token, _ in window).strip()
            if chunk_text:
                page_ref = _build_page_ref(page_nos=[page_no for _, page_no in window])
                metadata = {
                    "file_name": parsed_document.file_name,
                    "file_type": parsed_document.file_type,
                    "h1": section.h1,
                    "h2": section.h2,
                    "heading_path": section.heading_path,
                    "page_ref": page_ref,
                    "chunk_type": "text",
                    "source": source,
                    "file_hash": file_hash,
                }
                chunk_hash = _build_chunk_hash(
                    file_hash=file_hash,
                    heading_path=section.heading_path,
                    chunk_type="text",
                    content=chunk_text,
                )
                chunked.append(
                    ChunkedDocument(
                        chunk_index=len(chunked),
                        chunk_type="text",
                        content=chunk_text,
                        token_count=len(window),
                        start_offset=cursor,
                        end_offset=upper,
                        page_ref=page_ref,
                        h1=section.h1,
                        h2=section.h2,
                        heading_path=section.heading_path,
                        metadata=metadata,
                        chunk_hash=chunk_hash,
                    )
                )

            if upper >= len(token_units):
                break
            next_cursor = upper - self._overlap_tokens
            if next_cursor <= cursor:
                next_cursor = upper
            cursor = next_cursor

        return chunked

    def _build_table_chunk(
        self,
        *,
        parsed_document: ParsedDocument,
        block: DocumentBlock,
        h1: str | None,
        h2: str | None,
        heading_path: str,
        source: str,
        file_hash: str,
    ) -> ChunkedDocument:
        table_text = block.text.strip()
        page_ref = _build_page_ref(page_nos=[block.page_no])
        metadata = {
            "file_name": parsed_document.file_name,
            "file_type": parsed_document.file_type,
            "h1": h1,
            "h2": h2,
            "heading_path": heading_path,
            "page_ref": page_ref,
            "chunk_type": "table",
            "source": source,
            "file_hash": file_hash,
            "table_rows": block.table_rows,
        }
        return ChunkedDocument(
            chunk_index=0,
            chunk_type="table",
            content=table_text,
            token_count=max(1, len(_tokenize_text(table_text))),
            start_offset=0,
            end_offset=len(table_text),
            page_ref=page_ref,
            h1=h1,
            h2=h2,
            heading_path=heading_path,
            metadata=metadata,
            chunk_hash=_build_chunk_hash(
                file_hash=file_hash,
                heading_path=heading_path,
                chunk_type="table",
                content=table_text,
            ),
        )

    def _build_heading_path(self, *, current_h1: str | None, current_h2: str | None) -> str:
        parts: list[str] = []
        if current_h1:
            parts.append(current_h1)
        if current_h2:
            parts.append(current_h2)
        return " > ".join(parts)


def _tokenize_text(text: str) -> list[str]:
    # 兼容中英文：英文按词，中文按字，避免无空格文本无法切分。
    return re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]|[^\s]", text)


def _build_page_ref(*, page_nos: list[int | None]) -> dict[str, int | None]:
    normalized = sorted({page for page in page_nos if page is not None})
    if not normalized:
        return {"start": None, "end": None, "page_no": None}
    if len(normalized) == 1:
        return {"start": normalized[0], "end": normalized[0], "page_no": normalized[0]}
    return {"start": normalized[0], "end": normalized[-1], "page_no": None}


def _build_chunk_hash(*, file_hash: str, heading_path: str, chunk_type: str, content: str) -> str:
    digest = hashlib.sha256()
    digest.update(file_hash.encode("utf-8"))
    digest.update(b"|")
    digest.update(heading_path.encode("utf-8"))
    digest.update(b"|")
    digest.update(chunk_type.encode("utf-8"))
    digest.update(b"|")
    digest.update(content.encode("utf-8"))
    return digest.hexdigest()
