# Time: 2026-04-18 23:58
# Description: 提供文档解析注册中心与多格式解析器，实现 pdf/docx/txt/md 到统一 blocks 结构的转换。
# Author: Feixue

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol
from xml.etree import ElementTree as ET


class DocumentParseError(Exception):
    """文档解析阶段的业务错误，统一附带错误码便于审计与补偿。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class DocumentBlock:
    """统一文档块结构，供后续标题递归切分与 metadata 组装使用。"""

    block_type: str  # heading/paragraph/table
    text: str
    page_no: int | None = None
    heading_level: int | None = None
    table_rows: list[list[str]] = field(default_factory=list)


@dataclass(frozen=True)
class ParsedDocument:
    """解析后的统一文档结构。"""

    file_name: str
    file_type: str
    content_type: str
    page_count: int
    blocks: list[DocumentBlock]
    needs_ocr: bool = False


class DocumentParser(Protocol):
    """文档解析器协议，保证不同解析器输出一致结构。"""

    supported_file_types: set[str]

    def parse(
        self,
        *,
        file_name: str,
        file_bytes: bytes,
        content_type: str,
        trace_id: str,
    ) -> ParsedDocument: ...


class DocumentParserRegistry:
    """按文件类型分发解析器，避免业务层依赖具体解析实现。"""

    def __init__(self, parsers: list[DocumentParser]) -> None:
        self._parsers: dict[str, DocumentParser] = {}
        for parser in parsers:
            for file_type in parser.supported_file_types:
                self._parsers[file_type] = parser

    def parse(
        self,
        *,
        file_name: str,
        file_bytes: bytes,
        content_type: str,
        trace_id: str,
    ) -> ParsedDocument:
        file_type = _infer_file_type(file_name=file_name)
        parser = self._parsers.get(file_type)
        if parser is None:
            raise DocumentParseError(
                code="DOC_UNSUPPORTED_FILE_TYPE",
                message=f"不支持的文件类型: {file_type or 'unknown'}",
            )
        return parser.parse(
            file_name=file_name,
            file_bytes=file_bytes,
            content_type=content_type,
            trace_id=trace_id,
        )


class TextLikeDocumentParser:
    """解析 txt/md 文件，并尽可能保留标题与表格路径信息。"""

    supported_file_types = {"txt", "md"}

    def parse(
        self,
        *,
        file_name: str,
        file_bytes: bytes,
        content_type: str,
        trace_id: str,
    ) -> ParsedDocument:
        del trace_id  # 当前解析逻辑不依赖 trace_id，保留参数用于统一接口。

        file_type = _infer_file_type(file_name=file_name)
        decoded = _decode_text(file_bytes=file_bytes)
        if not decoded.strip():
            raise DocumentParseError(
                code="DOC_EMPTY_CONTENT",
                message="文档内容为空，无法执行解析。",
            )

        blocks = _parse_text_like_blocks(text=decoded, file_type=file_type)
        return ParsedDocument(
            file_name=file_name,
            file_type=file_type,
            content_type=content_type,
            page_count=1,
            blocks=blocks,
            needs_ocr=False,
        )


class DocxDocumentParser:
    """解析 docx 文件中的 H1/H2、段落与表格，输出统一 block 列表。"""

    supported_file_types = {"docx"}

    _W_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    _W_VAL = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val"

    def parse(
        self,
        *,
        file_name: str,
        file_bytes: bytes,
        content_type: str,
        trace_id: str,
    ) -> ParsedDocument:
        del trace_id

        try:
            with zipfile.ZipFile(io.BytesIO(file_bytes)) as archive:
                document_xml = archive.read("word/document.xml")
        except KeyError as exc:
            raise DocumentParseError(
                code="DOC_DOCX_INVALID_ARCHIVE",
                message="docx 缺少 word/document.xml，无法解析。",
            ) from exc
        except zipfile.BadZipFile as exc:
            raise DocumentParseError(
                code="DOC_DOCX_INVALID_ARCHIVE",
                message="docx 文件结构损坏，无法解析。",
            ) from exc

        root = ET.fromstring(document_xml)  # noqa: S314
        body = root.find("w:body", self._W_NS)
        if body is None:
            raise DocumentParseError(
                code="DOC_DOCX_EMPTY_BODY",
                message="docx 未找到正文内容。",
            )

        blocks: list[DocumentBlock] = []
        for element in list(body):
            local_name = _xml_local_name(element.tag)
            if local_name == "p":
                paragraph_text = self._collect_text(element)
                if not paragraph_text:
                    continue
                heading_level = self._detect_heading_level(element)
                if heading_level in {1, 2}:
                    blocks.append(
                        DocumentBlock(
                            block_type="heading",
                            text=paragraph_text,
                            heading_level=heading_level,
                        )
                    )
                else:
                    blocks.append(DocumentBlock(block_type="paragraph", text=paragraph_text))
            elif local_name == "tbl":
                table_rows = self._collect_table_rows(element)
                if not table_rows:
                    continue
                blocks.append(
                    DocumentBlock(
                        block_type="table",
                        text=_table_rows_to_text(table_rows),
                        table_rows=table_rows,
                    )
                )

        if not blocks:
            raise DocumentParseError(
                code="DOC_DOCX_NO_BLOCKS",
                message="docx 未提取到有效段落或表格。",
            )

        return ParsedDocument(
            file_name=file_name,
            file_type="docx",
            content_type=content_type,
            page_count=1,
            blocks=blocks,
            needs_ocr=False,
        )

    def _collect_text(self, element: ET.Element) -> str:
        texts: list[str] = []
        for text_node in element.findall(".//w:t", self._W_NS):
            if text_node.text:
                texts.append(text_node.text)
        return "".join(texts).strip()

    def _detect_heading_level(self, paragraph: ET.Element) -> int | None:
        style = paragraph.find("./w:pPr/w:pStyle", self._W_NS)
        if style is None:
            return None
        style_value = (style.attrib.get(self._W_VAL) or "").strip().lower().replace(" ", "")
        if "heading1" in style_value or "标题1" in style_value:
            return 1
        if "heading2" in style_value or "标题2" in style_value:
            return 2
        return None

    def _collect_table_rows(self, table: ET.Element) -> list[list[str]]:
        rows: list[list[str]] = []
        for row in table.findall("./w:tr", self._W_NS):
            cells: list[str] = []
            for cell in row.findall("./w:tc", self._W_NS):
                cell_text = self._collect_text(cell)
                cells.append(cell_text)
            if any(cell.strip() for cell in cells):
                rows.append(cells)
        return rows


class PdfDocumentParser:
    """解析 pdf 文本、页码与表格；文本不可提取时返回 OCR 待处理信号。"""

    supported_file_types = {"pdf"}

    def parse(
        self,
        *,
        file_name: str,
        file_bytes: bytes,
        content_type: str,
        trace_id: str,
    ) -> ParsedDocument:
        del trace_id

        pages = self._extract_pages(file_bytes=file_bytes)
        page_count = max(1, len(pages))
        blocks: list[DocumentBlock] = []
        for page_no, page_text in pages:
            page_blocks = _parse_text_like_blocks(
                text=page_text,
                file_type="pdf",
                page_no=page_no,
            )
            blocks.extend(page_blocks)

        has_text = any(
            block.text.strip()
            for block in blocks
            if block.block_type in {"heading", "paragraph", "table"}
        )
        return ParsedDocument(
            file_name=file_name,
            file_type="pdf",
            content_type=content_type,
            page_count=page_count,
            blocks=blocks,
            needs_ocr=not has_text,
        )

    def _extract_pages(self, *, file_bytes: bytes) -> list[tuple[int, str]]:
        try:
            from pypdf import PdfReader  # type: ignore
        except Exception:  # noqa: BLE001
            return self._extract_pages_fallback(file_bytes=file_bytes)

        try:
            reader = PdfReader(io.BytesIO(file_bytes))
        except Exception as exc:  # noqa: BLE001
            raise DocumentParseError(
                code="DOC_PDF_PARSE_FAILED",
                message=f"pdf 解析失败: {exc}",
            ) from exc

        pages: list[tuple[int, str]] = []
        for index, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            pages.append((index, text))
        return pages

    def _extract_pages_fallback(self, *, file_bytes: bytes) -> list[tuple[int, str]]:
        raw_text = file_bytes.decode("latin-1", errors="ignore")
        page_markers = re.findall(r"/Type\s*/Page(?!s)", raw_text)
        page_count = max(1, len(page_markers))

        literal_matches = re.findall(r"\(([^()]*)\)", raw_text)
        decoded_literals = [_decode_pdf_literal(value=value) for value in literal_matches]
        joined_text = "\n".join(part for part in decoded_literals if part.strip())
        if not joined_text.strip():
            return [(page_no, "") for page_no in range(1, page_count + 1)]

        pages: list[tuple[int, str]] = []
        for page_no in range(1, page_count + 1):
            # 回退解析无法精准恢复页码，将文本落在首页并保持页计数可审计。
            pages.append((page_no, joined_text if page_no == 1 else ""))
        return pages


def build_default_document_parser_registry() -> DocumentParserRegistry:
    """构建默认解析器注册中心。"""
    return DocumentParserRegistry(
        parsers=[
            TextLikeDocumentParser(),
            DocxDocumentParser(),
            PdfDocumentParser(),
        ]
    )


def _infer_file_type(*, file_name: str) -> str:
    return Path(file_name).suffix.lower().lstrip(".")


def _decode_text(*, file_bytes: bytes) -> str:
    for encoding in ("utf-8", "utf-8-sig", "gb18030", "latin-1"):
        try:
            return file_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
    return file_bytes.decode("utf-8", errors="ignore")


def _table_rows_to_text(table_rows: list[list[str]]) -> str:
    lines: list[str] = []
    for row in table_rows:
        lines.append(" | ".join(cell.strip() for cell in row))
    return "\n".join(lines).strip()


def _parse_text_like_blocks(
    *,
    text: str,
    file_type: str,
    page_no: int | None = None,
) -> list[DocumentBlock]:
    blocks: list[DocumentBlock] = []
    paragraph_buffer: list[str] = []
    table_buffer: list[list[str]] = []

    def flush_paragraph() -> None:
        if not paragraph_buffer:
            return
        paragraph_text = " ".join(part for part in paragraph_buffer if part).strip()
        paragraph_buffer.clear()
        if paragraph_text:
            blocks.append(DocumentBlock(block_type="paragraph", text=paragraph_text, page_no=page_no))

    def flush_table() -> None:
        if not table_buffer:
            return
        table_rows = [row[:] for row in table_buffer]
        table_buffer.clear()
        blocks.append(
            DocumentBlock(
                block_type="table",
                text=_table_rows_to_text(table_rows),
                page_no=page_no,
                table_rows=table_rows,
            )
        )

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            flush_paragraph()
            flush_table()
            continue

        heading_level, heading_text = _detect_heading_line(line=line, file_type=file_type)
        if heading_level is not None and heading_text:
            flush_paragraph()
            flush_table()
            blocks.append(
                DocumentBlock(
                    block_type="heading",
                    text=heading_text,
                    page_no=page_no,
                    heading_level=heading_level,
                )
            )
            continue

        table_row = _parse_table_row(line=line)
        if table_row:
            flush_paragraph()
            table_buffer.append(table_row)
            continue

        flush_table()
        paragraph_buffer.append(line)

    flush_paragraph()
    flush_table()
    return blocks


def _detect_heading_line(*, line: str, file_type: str) -> tuple[int | None, str | None]:
    if file_type in {"md", "pdf"}:
        if line.startswith("# "):
            return 1, line[2:].strip()
        if line.startswith("## "):
            return 2, line[3:].strip()

    if line.lower().startswith("h1:"):
        return 1, line[3:].strip()
    if line.lower().startswith("h2:"):
        return 2, line[3:].strip()
    return None, None


def _parse_table_row(*, line: str) -> list[str]:
    if "|" not in line:
        return []
    raw_cells = [cell.strip() for cell in line.split("|")]
    cells = [cell for cell in raw_cells if cell]
    return cells if len(cells) >= 2 else []


def _xml_local_name(tag_name: str) -> str:
    return tag_name.split("}", maxsplit=1)[-1]


def _decode_pdf_literal(*, value: str) -> str:
    # 统一处理 PDF 文本字面量中的常见转义。
    return (
        value.replace("\\n", "\n")
        .replace("\\r", "\r")
        .replace("\\t", "\t")
        .replace("\\(", "(")
        .replace("\\)", ")")
        .replace("\\\\", "\\")
    )
