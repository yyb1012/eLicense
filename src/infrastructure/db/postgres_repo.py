# Time: 2026-04-19 00:24
# Description: 提供文档入库所需的持久化仓储能力，落地 document_assets/document_chunks/chunk_embeddings 的可审计存储。
# Author: Feixue

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.shared.logger import get_logger

logger = get_logger(__name__)


class PostgresRepository:
    """文档入库仓储适配器（当前落地为 SQLite 持久化路径）。"""

    def __init__(self, dsn: str, *, sqlite_path: str = ".runtime/document_ingest.db") -> None:
        self._dsn = dsn
        self._sqlite_path = sqlite_path
        self._connected = False
        self._connection: sqlite3.Connection | None = None
        self._lock = threading.RLock()

    async def connect(self) -> None:
        """初始化持久化连接并创建必需表结构。"""
        with self._lock:
            if self._connected and self._connection is not None:
                return

            database_path = Path(self._sqlite_path)
            if not database_path.is_absolute():
                database_path = Path.cwd() / database_path
            database_path.parent.mkdir(parents=True, exist_ok=True)

            connection = sqlite3.connect(str(database_path), check_same_thread=False)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA journal_mode=WAL;")
            connection.execute("PRAGMA foreign_keys=ON;")
            self._connection = connection
            self._ensure_schema(connection=connection)
            self._connected = True

            logger.info(
                "postgres_connect_sqlite",
                extra={
                    "extra_fields": {
                        "dsn_configured": bool(self._dsn),
                        "sqlite_path": str(database_path),
                    }
                },
            )

    async def disconnect(self) -> None:
        """关闭连接并释放资源。"""
        with self._lock:
            if self._connection is not None:
                self._connection.commit()
                self._connection.close()
            self._connection = None
            self._connected = False
            logger.info("postgres_disconnect_sqlite")

    async def ping(self) -> bool:
        """返回当前连接状态。"""
        return self._connected and self._connection is not None

    async def create_or_get_document_asset(
        self,
        *,
        trace_id: str,
        file_name: str,
        file_type: str,
        content_type: str,
        file_size: int,
        source: str,
        file_hash: str,
        idempotency_key: str,
        metadata: dict[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        """按幂等键创建资产，重复请求直接复用历史资产。"""
        with self._lock:
            connection = self._require_connection()
            existing = connection.execute(
                "SELECT * FROM document_assets WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if existing is not None:
                connection.execute(
                    "UPDATE document_assets SET updated_at_utc = ? WHERE asset_id = ?",
                    (_utc_now(), existing["asset_id"]),
                )
                connection.commit()
                return self._asset_row_to_dict(
                    connection.execute(
                        "SELECT * FROM document_assets WHERE asset_id = ?",
                        (existing["asset_id"],),
                    ).fetchone()
                ), False

            asset_id = _new_id(prefix="AST")
            now = _utc_now()
            connection.execute(
                """
                INSERT INTO document_assets (
                    asset_id, trace_id, file_name, file_type, content_type, file_size,
                    source, file_hash, idempotency_key, status, last_stage,
                    error_code, error_message, ocr_status, page_count,
                    chunk_count, embedding_count, metadata_json,
                    compensation_json, audit_json, created_at_utc, updated_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    asset_id,
                    trace_id,
                    file_name,
                    file_type,
                    content_type,
                    int(file_size),
                    source,
                    file_hash,
                    idempotency_key,
                    "received",
                    "received",
                    None,
                    None,
                    None,
                    None,
                    0,
                    0,
                    _json_dumps(metadata),
                    None,
                    _json_dumps({"events": [{"stage": "received", "at": now, "trace_id": trace_id}]}),
                    now,
                    now,
                ),
            )
            connection.commit()

            row = connection.execute(
                "SELECT * FROM document_assets WHERE asset_id = ?",
                (asset_id,),
            ).fetchone()
            return self._asset_row_to_dict(row), True

    async def update_document_asset_status(
        self,
        *,
        asset_id: str,
        status: str,
        stage: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        compensation: dict[str, Any] | None = None,
        metadata_patch: dict[str, Any] | None = None,
        ocr_status: str | None = None,
        page_count: int | None = None,
        audit_event: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """更新资产状态并写入审计/补偿字段。"""
        with self._lock:
            connection = self._require_connection()
            row = connection.execute(
                "SELECT * FROM document_assets WHERE asset_id = ?",
                (asset_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"asset_not_found:{asset_id}")

            metadata = _json_loads(row["metadata_json"], default={})
            if metadata_patch:
                metadata.update(metadata_patch)

            audit_payload = _json_loads(row["audit_json"], default={"events": []})
            audit_events = audit_payload.get("events")
            if not isinstance(audit_events, list):
                audit_events = []
            if audit_event:
                audit_events.append(dict(audit_event))
            audit_payload["events"] = audit_events

            connection.execute(
                """
                UPDATE document_assets
                SET status = ?,
                    last_stage = ?,
                    error_code = ?,
                    error_message = ?,
                    compensation_json = ?,
                    metadata_json = ?,
                    ocr_status = COALESCE(?, ocr_status),
                    page_count = COALESCE(?, page_count),
                    audit_json = ?,
                    updated_at_utc = ?
                WHERE asset_id = ?
                """,
                (
                    status,
                    stage or status,
                    error_code,
                    error_message,
                    _json_dumps(compensation) if compensation is not None else row["compensation_json"],
                    _json_dumps(metadata),
                    ocr_status,
                    page_count,
                    _json_dumps(audit_payload),
                    _utc_now(),
                    asset_id,
                ),
            )
            connection.commit()
            return self._asset_row_to_dict(
                connection.execute(
                    "SELECT * FROM document_assets WHERE asset_id = ?",
                    (asset_id,),
                ).fetchone()
            )

    async def replace_document_chunks(
        self,
        *,
        asset_id: str,
        chunks: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """覆盖写入 chunk 数据，确保同资产不累计脏记录。"""
        with self._lock:
            connection = self._require_connection()
            self._require_asset_exists(connection=connection, asset_id=asset_id)

            connection.execute("DELETE FROM chunk_embeddings WHERE asset_id = ?", (asset_id,))
            connection.execute("DELETE FROM document_chunks WHERE asset_id = ?", (asset_id,))

            inserted: list[dict[str, Any]] = []
            now = _utc_now()
            for chunk in chunks:
                chunk_id = _new_id(prefix="CHK")
                connection.execute(
                    """
                    INSERT INTO document_chunks (
                        chunk_id, asset_id, chunk_index, chunk_hash, chunk_type,
                        content, token_count, start_offset, end_offset,
                        start_page, end_page, page_no,
                        h1, h2, heading_path, metadata_json, created_at_utc
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chunk_id,
                        asset_id,
                        int(chunk["chunk_index"]),
                        str(chunk["chunk_hash"]),
                        str(chunk["chunk_type"]),
                        str(chunk["content"]),
                        int(chunk.get("token_count", 0)),
                        int(chunk.get("start_offset", 0)),
                        int(chunk.get("end_offset", 0)),
                        chunk.get("start_page"),
                        chunk.get("end_page"),
                        chunk.get("page_no"),
                        chunk.get("h1"),
                        chunk.get("h2"),
                        chunk.get("heading_path", ""),
                        _json_dumps(chunk.get("metadata", {})),
                        now,
                    ),
                )
                inserted.append(
                    {
                        "chunk_id": chunk_id,
                        "asset_id": asset_id,
                        "chunk_index": int(chunk["chunk_index"]),
                        "chunk_hash": str(chunk["chunk_hash"]),
                        "chunk_type": str(chunk["chunk_type"]),
                        "content": str(chunk["content"]),
                        "token_count": int(chunk.get("token_count", 0)),
                        "start_offset": int(chunk.get("start_offset", 0)),
                        "end_offset": int(chunk.get("end_offset", 0)),
                        "start_page": chunk.get("start_page"),
                        "end_page": chunk.get("end_page"),
                        "page_no": chunk.get("page_no"),
                        "h1": chunk.get("h1"),
                        "h2": chunk.get("h2"),
                        "heading_path": chunk.get("heading_path", ""),
                        "metadata": dict(chunk.get("metadata", {})),
                        "created_at_utc": now,
                    }
                )

            connection.execute(
                "UPDATE document_assets SET chunk_count = ?, embedding_count = 0, updated_at_utc = ? WHERE asset_id = ?",
                (len(inserted), _utc_now(), asset_id),
            )
            connection.commit()
            return inserted

    async def find_reusable_embedding(
        self,
        *,
        chunk_hash: str,
        provider: str,
        model: str,
        embedding_version: str,
    ) -> dict[str, Any] | None:
        """按 chunk_hash 复用历史向量，避免重复调用 embedding provider。"""
        with self._lock:
            connection = self._require_connection()
            row = connection.execute(
                """
                SELECT e.embedding_json, e.dimension, e.provider, e.model, e.embedding_version,
                       e.chunk_id AS source_chunk_id
                FROM chunk_embeddings e
                WHERE e.chunk_hash = ?
                  AND e.provider = ?
                  AND e.model = ?
                  AND e.embedding_version = ?
                  AND e.status = 'ok'
                ORDER BY e.created_at_utc DESC
                LIMIT 1
                """,
                (chunk_hash, provider, model, embedding_version),
            ).fetchone()
            if row is None:
                return None
            return {
                "vector": _json_loads(row["embedding_json"], default=[]),
                "dimension": int(row["dimension"]),
                "provider": str(row["provider"]),
                "model": str(row["model"]),
                "embedding_version": str(row["embedding_version"]),
                "source_chunk_id": str(row["source_chunk_id"]),
            }

    async def replace_chunk_embeddings(
        self,
        *,
        asset_id: str,
        embeddings: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """覆盖写入 chunk embeddings。"""
        with self._lock:
            connection = self._require_connection()
            self._require_asset_exists(connection=connection, asset_id=asset_id)

            connection.execute("DELETE FROM chunk_embeddings WHERE asset_id = ?", (asset_id,))

            inserted: list[dict[str, Any]] = []
            now = _utc_now()
            for item in embeddings:
                embedding_id = _new_id(prefix="EMB")
                status = str(item.get("status", "ok"))
                error_code = item.get("error_code")
                connection.execute(
                    """
                    INSERT INTO chunk_embeddings (
                        embedding_id, asset_id, chunk_id, chunk_hash,
                        provider, model, dimension, embedding_version,
                        embedding_json, status, error_code, metadata_json, created_at_utc
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        embedding_id,
                        asset_id,
                        str(item["chunk_id"]),
                        str(item["chunk_hash"]),
                        str(item["provider"]),
                        str(item["model"]),
                        int(item["dimension"]),
                        str(item["embedding_version"]),
                        _json_dumps(item["vector"]),
                        status,
                        error_code,
                        _json_dumps(item.get("metadata", {})),
                        now,
                    ),
                )
                inserted.append(
                    {
                        "embedding_id": embedding_id,
                        "asset_id": asset_id,
                        "chunk_id": str(item["chunk_id"]),
                        "chunk_hash": str(item["chunk_hash"]),
                        "provider": str(item["provider"]),
                        "model": str(item["model"]),
                        "dimension": int(item["dimension"]),
                        "embedding_version": str(item["embedding_version"]),
                        "vector": list(item["vector"]),
                        "status": status,
                        "error_code": error_code,
                        "metadata": dict(item.get("metadata", {})),
                        "created_at_utc": now,
                    }
                )

            connection.execute(
                "UPDATE document_assets SET embedding_count = ?, updated_at_utc = ? WHERE asset_id = ?",
                (len(inserted), _utc_now(), asset_id),
            )
            connection.commit()
            return inserted

    async def get_document_asset(self, *, asset_id: str) -> dict[str, Any] | None:
        """按资产 ID 查询资产记录。"""
        with self._lock:
            connection = self._require_connection()
            row = connection.execute(
                "SELECT * FROM document_assets WHERE asset_id = ?",
                (asset_id,),
            ).fetchone()
            return self._asset_row_to_dict(row) if row is not None else None

    async def find_document_asset_by_idempotency_key(
        self,
        *,
        idempotency_key: str,
    ) -> dict[str, Any] | None:
        """按幂等键查询资产。"""
        with self._lock:
            connection = self._require_connection()
            row = connection.execute(
                "SELECT * FROM document_assets WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            return self._asset_row_to_dict(row) if row is not None else None

    async def list_document_chunks(self, *, asset_id: str) -> list[dict[str, Any]]:
        """查询指定资产的 chunk 列表。"""
        with self._lock:
            connection = self._require_connection()
            rows = connection.execute(
                "SELECT * FROM document_chunks WHERE asset_id = ? ORDER BY chunk_index ASC",
                (asset_id,),
            ).fetchall()
            return [self._chunk_row_to_dict(row) for row in rows]

    async def list_chunk_embeddings(self, *, asset_id: str) -> list[dict[str, Any]]:
        """查询指定资产的 embedding 列表。"""
        with self._lock:
            connection = self._require_connection()
            rows = connection.execute(
                "SELECT * FROM chunk_embeddings WHERE asset_id = ? ORDER BY created_at_utc ASC",
                (asset_id,),
            ).fetchall()
            return [self._embedding_row_to_dict(row) for row in rows]

    def get_document_asset_snapshot(self, *, asset_id: str) -> dict[str, Any] | None:
        """测试与调试用：同步读取资产快照。"""
        with self._lock:
            connection = self._require_connection()
            row = connection.execute(
                "SELECT * FROM document_assets WHERE asset_id = ?",
                (asset_id,),
            ).fetchone()
            return self._asset_row_to_dict(row) if row is not None else None

    def list_document_chunks_snapshot(self, *, asset_id: str) -> list[dict[str, Any]]:
        """测试与调试用：同步读取 chunk 快照。"""
        with self._lock:
            connection = self._require_connection()
            rows = connection.execute(
                "SELECT * FROM document_chunks WHERE asset_id = ? ORDER BY chunk_index ASC",
                (asset_id,),
            ).fetchall()
            return [self._chunk_row_to_dict(row) for row in rows]

    def list_chunk_embeddings_snapshot(self, *, asset_id: str) -> list[dict[str, Any]]:
        """测试与调试用：同步读取 embedding 快照。"""
        with self._lock:
            connection = self._require_connection()
            rows = connection.execute(
                "SELECT * FROM chunk_embeddings WHERE asset_id = ? ORDER BY created_at_utc ASC",
                (asset_id,),
            ).fetchall()
            return [self._embedding_row_to_dict(row) for row in rows]

    def _require_connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("postgres_repo_not_connected")
        return self._connection

    def _require_asset_exists(self, *, connection: sqlite3.Connection, asset_id: str) -> None:
        row = connection.execute(
            "SELECT asset_id FROM document_assets WHERE asset_id = ?",
            (asset_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"asset_not_found:{asset_id}")

    def _asset_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "asset_id": str(row["asset_id"]),
            "trace_id": str(row["trace_id"]),
            "file_name": str(row["file_name"]),
            "file_type": str(row["file_type"]),
            "content_type": str(row["content_type"]),
            "file_size": int(row["file_size"]),
            "source": str(row["source"]),
            "file_hash": str(row["file_hash"]),
            "idempotency_key": str(row["idempotency_key"]),
            "status": str(row["status"]),
            "last_stage": str(row["last_stage"]),
            "error_code": row["error_code"],
            "error_message": row["error_message"],
            "ocr_status": row["ocr_status"],
            "page_count": row["page_count"],
            "chunk_count": int(row["chunk_count"]),
            "embedding_count": int(row["embedding_count"]),
            "metadata": _json_loads(row["metadata_json"], default={}),
            "compensation": _json_loads(row["compensation_json"], default=None),
            "audit": _json_loads(row["audit_json"], default={}),
            "created_at_utc": str(row["created_at_utc"]),
            "updated_at_utc": str(row["updated_at_utc"]),
        }

    def _chunk_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "chunk_id": str(row["chunk_id"]),
            "asset_id": str(row["asset_id"]),
            "chunk_index": int(row["chunk_index"]),
            "chunk_hash": str(row["chunk_hash"]),
            "chunk_type": str(row["chunk_type"]),
            "content": str(row["content"]),
            "token_count": int(row["token_count"]),
            "start_offset": int(row["start_offset"]),
            "end_offset": int(row["end_offset"]),
            "start_page": row["start_page"],
            "end_page": row["end_page"],
            "page_no": row["page_no"],
            "h1": row["h1"],
            "h2": row["h2"],
            "heading_path": row["heading_path"] or "",
            "metadata": _json_loads(row["metadata_json"], default={}),
            "created_at_utc": str(row["created_at_utc"]),
        }

    def _embedding_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        vector = _json_loads(row["embedding_json"], default=[])
        return {
            "embedding_id": str(row["embedding_id"]),
            "asset_id": str(row["asset_id"]),
            "chunk_id": str(row["chunk_id"]),
            "chunk_hash": str(row["chunk_hash"]),
            "provider": str(row["provider"]),
            "model": str(row["model"]),
            "dimension": int(row["dimension"]),
            "embedding_version": str(row["embedding_version"]),
            "vector": list(vector),
            "status": str(row["status"]),
            "error_code": row["error_code"],
            "metadata": _json_loads(row["metadata_json"], default={}),
            "created_at_utc": str(row["created_at_utc"]),
        }

    def _ensure_schema(self, *, connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS document_assets (
                asset_id TEXT PRIMARY KEY,
                trace_id TEXT NOT NULL,
                file_name TEXT NOT NULL,
                file_type TEXT NOT NULL,
                content_type TEXT NOT NULL,
                file_size INTEGER NOT NULL,
                source TEXT NOT NULL,
                file_hash TEXT NOT NULL,
                idempotency_key TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL,
                last_stage TEXT NOT NULL,
                error_code TEXT,
                error_message TEXT,
                ocr_status TEXT,
                page_count INTEGER,
                chunk_count INTEGER NOT NULL DEFAULT 0,
                embedding_count INTEGER NOT NULL DEFAULT 0,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                compensation_json TEXT,
                audit_json TEXT,
                created_at_utc TEXT NOT NULL,
                updated_at_utc TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS document_chunks (
                chunk_id TEXT PRIMARY KEY,
                asset_id TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                chunk_hash TEXT NOT NULL,
                chunk_type TEXT NOT NULL,
                content TEXT NOT NULL,
                token_count INTEGER NOT NULL,
                start_offset INTEGER NOT NULL,
                end_offset INTEGER NOT NULL,
                start_page INTEGER,
                end_page INTEGER,
                page_no INTEGER,
                h1 TEXT,
                h2 TEXT,
                heading_path TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at_utc TEXT NOT NULL,
                FOREIGN KEY(asset_id) REFERENCES document_assets(asset_id)
            );

            CREATE INDEX IF NOT EXISTS idx_document_chunks_asset ON document_chunks(asset_id);
            CREATE INDEX IF NOT EXISTS idx_document_chunks_asset_idx ON document_chunks(asset_id, chunk_index);
            CREATE INDEX IF NOT EXISTS idx_document_chunks_hash ON document_chunks(chunk_hash);

            CREATE TABLE IF NOT EXISTS chunk_embeddings (
                embedding_id TEXT PRIMARY KEY,
                asset_id TEXT NOT NULL,
                chunk_id TEXT NOT NULL,
                chunk_hash TEXT NOT NULL,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                dimension INTEGER NOT NULL,
                embedding_version TEXT NOT NULL,
                embedding_json TEXT NOT NULL,
                status TEXT NOT NULL,
                error_code TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at_utc TEXT NOT NULL,
                FOREIGN KEY(asset_id) REFERENCES document_assets(asset_id),
                FOREIGN KEY(chunk_id) REFERENCES document_chunks(chunk_id)
            );

            CREATE INDEX IF NOT EXISTS idx_chunk_embeddings_asset ON chunk_embeddings(asset_id);
            CREATE INDEX IF NOT EXISTS idx_chunk_embeddings_hash ON chunk_embeddings(chunk_hash);
            CREATE INDEX IF NOT EXISTS idx_chunk_embeddings_lookup
                ON chunk_embeddings(chunk_hash, provider, model, embedding_version, status);
            """
        )
        connection.commit()


def _new_id(*, prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12].upper()}"


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _json_loads(value: str | None, *, default: Any) -> Any:
    if value is None:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()
