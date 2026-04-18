-- Time: 2026-04-19 00:47
-- Description: 定义文档入库链路在持久化层的资产、分块与向量表结构，支持状态流转、幂等与审计字段。
-- Author: Feixue

CREATE TABLE IF NOT EXISTS document_assets (
    asset_id VARCHAR(32) PRIMARY KEY,
    trace_id VARCHAR(64) NOT NULL,
    file_name TEXT NOT NULL,
    file_type VARCHAR(32) NOT NULL,
    content_type VARCHAR(128) NOT NULL,
    file_size INTEGER NOT NULL,
    source VARCHAR(128) NOT NULL,
    file_hash VARCHAR(128) NOT NULL,
    idempotency_key VARCHAR(256) NOT NULL UNIQUE,
    status VARCHAR(32) NOT NULL,
    last_stage VARCHAR(32) NOT NULL,
    error_code VARCHAR(64),
    error_message TEXT,
    ocr_status VARCHAR(32),
    page_count INTEGER,
    chunk_count INTEGER NOT NULL DEFAULT 0,
    embedding_count INTEGER NOT NULL DEFAULT 0,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    compensation_json JSONB,
    audit_json JSONB,
    created_at_utc TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at_utc TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS document_chunks (
    chunk_id VARCHAR(32) PRIMARY KEY,
    asset_id VARCHAR(32) NOT NULL REFERENCES document_assets(asset_id),
    chunk_index INTEGER NOT NULL,
    chunk_hash VARCHAR(128) NOT NULL,
    chunk_type VARCHAR(16) NOT NULL,
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
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at_utc TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_document_chunks_asset ON document_chunks(asset_id);
CREATE INDEX IF NOT EXISTS idx_document_chunks_asset_index ON document_chunks(asset_id, chunk_index);
CREATE INDEX IF NOT EXISTS idx_document_chunks_hash ON document_chunks(chunk_hash);

CREATE TABLE IF NOT EXISTS chunk_embeddings (
    embedding_id VARCHAR(32) PRIMARY KEY,
    asset_id VARCHAR(32) NOT NULL REFERENCES document_assets(asset_id),
    chunk_id VARCHAR(32) NOT NULL REFERENCES document_chunks(chunk_id),
    chunk_hash VARCHAR(128) NOT NULL,
    provider VARCHAR(64) NOT NULL,
    model VARCHAR(128) NOT NULL,
    dimension INTEGER NOT NULL,
    embedding_version VARCHAR(32) NOT NULL,
    embedding_json JSONB NOT NULL,
    status VARCHAR(16) NOT NULL,
    error_code VARCHAR(64),
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at_utc TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chunk_embeddings_asset ON chunk_embeddings(asset_id);
CREATE INDEX IF NOT EXISTS idx_chunk_embeddings_hash ON chunk_embeddings(chunk_hash);
CREATE INDEX IF NOT EXISTS idx_chunk_embeddings_lookup
    ON chunk_embeddings(chunk_hash, provider, model, embedding_version, status);
