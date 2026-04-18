# Time: 2026-04-19 01:03
# Description: 校验文档上传正式链路：multipart 单/多文件、解析切分元数据、OCR 状态、embedding 失败降级与幂等行为。
# Author: Feixue

from __future__ import annotations

import io
import json
import zipfile

from src.infrastructure.embedding.providers import BaseEmbeddingProvider, EmbeddingProviderError


def test_multipart_single_file_upload_success(client) -> None:
    """multipart 单文件上传应成功入库并返回逐文件结果。"""
    content = "\n".join(
        [
            "# 监管总则",
            "## 资质要求",
            "这是正文内容。" * 120,
            "列A|列B|列C",
            "值1|值2|值3",
        ]
    )
    files = [
        (
            "files",
            (
                "rules.md",
                content.encode("utf-8"),
                "text/markdown",
            ),
        )
    ]
    data = {
        "source": "manual_upload",
        "metadata": json.dumps({"license_type": "ELECTRIC", "current_node": "evidence"}),
    }

    response = client.post("/api/v1/documents/upload", files=files, data=data)

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert len(body["results"]) == 1

    item = body["results"][0]
    assert item["ok"] is True
    assert item["status"] == "indexed"
    assert item["error_code"] is None
    assert item["asset_id"].startswith("AST-")
    assert item["chunks_count"] >= 2
    assert item["trace_id"]
    assert response.headers["x-trace-id"] == body["trace_id"]

    postgres_repo = client.app.state.postgres
    chunks = postgres_repo.list_document_chunks_snapshot(asset_id=item["asset_id"])
    assert any(chunk["chunk_type"] == "table" for chunk in chunks)
    assert any(chunk["chunk_type"] == "text" for chunk in chunks)

    first_chunk_metadata = chunks[0]["metadata"]
    assert "file_name" in first_chunk_metadata
    assert "file_type" in first_chunk_metadata
    assert "heading_path" in first_chunk_metadata
    assert "page_ref" in first_chunk_metadata
    assert "chunk_type" in first_chunk_metadata
    assert "chunk_index" in first_chunk_metadata


def test_multipart_multi_file_returns_independent_results(client) -> None:
    """多文件上传需按文件返回独立状态与错误码。"""
    files = [
        ("files", ("ok.txt", "H1: 规范\n正文".encode("utf-8"), "text/plain")),
        ("files", ("bad.exe", b"MZ...", "application/octet-stream")),
    ]

    response = client.post("/api/v1/documents/upload", files=files, data={"source": "batch_upload"})

    assert response.status_code == 200
    body = response.json()
    assert len(body["results"]) == 2

    ok_item = next(item for item in body["results"] if item["file_name"] == "ok.txt")
    bad_item = next(item for item in body["results"] if item["file_name"] == "bad.exe")

    assert ok_item["ok"] is True
    assert ok_item["status"] == "indexed"
    assert ok_item["error_code"] is None

    assert bad_item["ok"] is False
    assert bad_item["status"] == "failed"
    assert bad_item["error_code"] == "DOC_UNSUPPORTED_FILE_TYPE"


def test_upload_pdf_docx_txt_md_parse_and_metadata(client) -> None:
    """pdf/docx/txt/md 均应可解析并写入稳定 metadata。"""
    files = [
        ("files", ("plain.txt", "H1: 章节\n文本".encode("utf-8"), "text/plain")),
        (
            "files",
            (
                "guide.md",
                "# 主标题\n## 子标题\n段落内容\n表头A|表头B\n值A|值B".encode("utf-8"),
                "text/markdown",
            ),
        ),
        (
            "files",
            (
                "spec.docx",
                _build_docx_bytes(),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ),
        ),
        ("files", ("sample.pdf", _build_pdf_bytes(), "application/pdf")),
    ]

    response = client.post("/api/v1/documents/upload", files=files, data={"source": "n17_regression"})

    assert response.status_code == 200
    body = response.json()
    assert len(body["results"]) == 4

    by_name = {item["file_name"]: item for item in body["results"]}
    for file_name in ["plain.txt", "guide.md", "spec.docx", "sample.pdf"]:
        assert by_name[file_name]["ok"] is True
        assert by_name[file_name]["status"] == "indexed"

    postgres_repo = client.app.state.postgres
    for file_name, file_type in [
        ("plain.txt", "txt"),
        ("guide.md", "md"),
        ("spec.docx", "docx"),
        ("sample.pdf", "pdf"),
    ]:
        asset_id = by_name[file_name]["asset_id"]
        asset = postgres_repo.get_document_asset_snapshot(asset_id=asset_id)
        chunks = postgres_repo.list_document_chunks_snapshot(asset_id=asset_id)

        assert asset is not None
        assert asset["status"] == "indexed"
        assert asset["file_type"] == file_type
        assert chunks

        first = chunks[0]
        assert first["metadata"]["file_type"] == file_type
        assert "page_ref" in first["metadata"]


def test_heading_recursive_chunk_and_table_chunk(client) -> None:
    """标题递归切分应保留 heading_path，表格应独立为 table chunk。"""
    content = "\n".join(
        [
            "# H1 总章",
            "## H2 细则A",
            "内容A " * 160,
            "列1|列2",
            "a|b",
            "## H2 细则B",
            "内容B " * 160,
        ]
    )
    files = [("files", ("structure.md", content.encode("utf-8"), "text/markdown"))]

    response = client.post("/api/v1/documents/upload", files=files)
    assert response.status_code == 200

    item = response.json()["results"][0]
    asset_id = item["asset_id"]
    chunks = client.app.state.postgres.list_document_chunks_snapshot(asset_id=asset_id)

    table_chunks = [chunk for chunk in chunks if chunk["chunk_type"] == "table"]
    text_chunks = [chunk for chunk in chunks if chunk["chunk_type"] == "text"]

    assert table_chunks
    assert text_chunks
    assert all(chunk["heading_path"] for chunk in text_chunks)
    assert any("H1 总章 > H2 细则A" == chunk["heading_path"] for chunk in text_chunks)
    assert any("H1 总章 > H2 细则B" == chunk["heading_path"] for chunk in text_chunks)


def test_embedding_failure_writes_failed_status_and_error_code(client) -> None:
    """embedding provider 失败时应落 failed 状态并记录错误码。"""

    class _FailingEmbeddingProvider(BaseEmbeddingProvider):
        def __init__(self) -> None:
            super().__init__(provider="mock", model="mock-model", embedding_version="test-v1")

        async def embed_texts(self, texts: list[str]) -> list[list[float]]:
            raise EmbeddingProviderError(
                code="DOC_EMBEDDING_PROVIDER_DOWN",
                message="mock embedding provider down",
                retryable=True,
            )

    client.app.state.document_ingest_service._embedding_provider = _FailingEmbeddingProvider()

    files = [("files", ("broken.txt", "H1: x\ncontent".encode("utf-8"), "text/plain"))]
    response = client.post("/api/v1/documents/upload", files=files)

    assert response.status_code == 200
    item = response.json()["results"][0]
    assert item["ok"] is False
    assert item["status"] == "failed"
    assert item["error_code"] == "DOC_EMBEDDING_PROVIDER_DOWN"

    asset = client.app.state.postgres.get_document_asset_snapshot(asset_id=item["asset_id"])
    assert asset is not None
    assert asset["status"] == "failed"
    assert asset["error_code"] == "DOC_EMBEDDING_PROVIDER_DOWN"
    assert asset["compensation"]["queued"] is True


def test_idempotent_duplicate_upload_reuses_asset(client) -> None:
    """相同 file_hash+source 上传应命中幂等并复用资产。"""
    files = [("files", ("repeat.txt", "H1: 重复\n内容".encode("utf-8"), "text/plain"))]
    data = {"source": "same_source"}

    first = client.post("/api/v1/documents/upload", files=files, data=data)
    second = client.post("/api/v1/documents/upload", files=files, data=data)

    first_item = first.json()["results"][0]
    second_item = second.json()["results"][0]

    assert first_item["ok"] is True
    assert first_item["idempotent_hit"] is False

    assert second_item["ok"] is True
    assert second_item["idempotent_hit"] is True
    assert second_item["asset_id"] == first_item["asset_id"]


def test_pdf_text_unavailable_marks_ocr_state_and_audit(client) -> None:
    """PDF 文本不可提取时应标记 ocr_pending/ocr_skipped 并可通过 OCR 接口审计。"""
    files = [("files", ("scan.pdf", _build_empty_pdf_bytes(), "application/pdf"))]

    response = client.post("/api/v1/documents/upload", files=files)
    assert response.status_code == 200
    item = response.json()["results"][0]

    assert item["ok"] is False
    assert item["status"] == "failed"
    assert item["error_code"] == "DOC_PDF_TEXT_UNAVAILABLE"

    ocr_response = client.get(f"/api/v1/documents/{item['asset_id']}/ocr")
    assert ocr_response.status_code == 200
    body = ocr_response.json()
    assert body["ocr_status"] in {"ocr_pending", "ocr_skipped"}


# ----------------------------
# 测试数据构造工具
# ----------------------------

def _build_docx_bytes() -> bytes:
    document_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:body>
        <w:p>
          <w:pPr><w:pStyle w:val="Heading1"/></w:pPr>
          <w:r><w:t>章标题</w:t></w:r>
        </w:p>
        <w:p>
          <w:pPr><w:pStyle w:val="Heading2"/></w:pPr>
          <w:r><w:t>节标题</w:t></w:r>
        </w:p>
        <w:p><w:r><w:t>正文段落内容</w:t></w:r></w:p>
        <w:tbl>
          <w:tr>
            <w:tc><w:p><w:r><w:t>字段</w:t></w:r></w:p></w:tc>
            <w:tc><w:p><w:r><w:t>值</w:t></w:r></w:p></w:tc>
          </w:tr>
          <w:tr>
            <w:tc><w:p><w:r><w:t>编号</w:t></w:r></w:p></w:tc>
            <w:tc><w:p><w:r><w:t>001</w:t></w:r></w:p></w:tc>
          </w:tr>
        </w:tbl>
      </w:body>
    </w:document>
    """.strip()

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", document_xml)
    return buffer.getvalue()


def _build_pdf_bytes() -> bytes:
    lines = [
        "# PDF Title",
        "## PDF Section",
        "First paragraph",
        "ColA|ColB",
        "v1|v2",
    ]
    return _build_pdf_with_lines(lines=lines)


def _build_empty_pdf_bytes() -> bytes:
    return _build_pdf_with_lines(lines=[])


def _build_pdf_with_lines(*, lines: list[str]) -> bytes:
    stream_lines = ["BT", "/F1 12 Tf", "72 720 Td"]
    first = True
    for line in lines:
        escaped = (
            line.replace("\\", "\\\\")
            .replace("(", "\\(")
            .replace(")", "\\)")
        )
        if not first:
            stream_lines.append("0 -18 Td")
        stream_lines.append(f"({escaped}) Tj")
        first = False
    stream_lines.append("ET")
    content_stream = "\n".join(stream_lines).encode("latin-1")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(content_stream)).encode("ascii") + b" >>\nstream\n" + content_stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]

    parts: list[bytes] = [b"%PDF-1.4\n"]
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(sum(len(part) for part in parts))
        parts.append(f"{index} 0 obj\n".encode("ascii"))
        parts.append(obj)
        parts.append(b"\nendobj\n")

    xref_start = sum(len(part) for part in parts)
    xref_lines = [f"xref\n0 {len(objects) + 1}\n", "0000000000 65535 f \n"]
    for offset in offsets[1:]:
        xref_lines.append(f"{offset:010d} 00000 n \n")

    trailer = (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_start}\n%%EOF\n"
    )

    pdf_bytes = b"".join(parts) + "".join(xref_lines).encode("ascii") + trailer.encode("ascii")
    return pdf_bytes

def test_chunk_hash_reuse_avoids_duplicate_embedding_call(client) -> None:
    """不同 source 触发新资产时，应通过 chunk_hash 复用历史向量，避免重复向量化。"""
    files = [("files", ("same.txt", "H1: 标题\n重复内容".encode("utf-8"), "text/plain"))]

    first = client.post("/api/v1/documents/upload", files=files, data={"source": "source_a"})
    second = client.post("/api/v1/documents/upload", files=files, data={"source": "source_b"})

    first_item = first.json()["results"][0]
    second_item = second.json()["results"][0]

    assert first_item["ok"] is True
    assert second_item["ok"] is True
    assert first_item["asset_id"] != second_item["asset_id"]

    embeddings = client.app.state.postgres.list_chunk_embeddings_snapshot(asset_id=second_item["asset_id"])
    assert embeddings
    assert all(embedding["metadata"].get("reused_from_chunk_id") for embedding in embeddings)

