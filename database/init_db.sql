-- AlphaHub clean database initialization.
-- Execute against a newly-created alpha_hub database.

ALTER DATABASE alpha_hub SET timezone TO 'Asia/Shanghai';

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE users (
    id BIGINT PRIMARY KEY,
    username VARCHAR(100) NOT NULL UNIQUE,
    password VARCHAR(255) NOT NULL,
    create_time TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    create_by BIGINT NOT NULL,
    update_time TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_by BIGINT NOT NULL
);

INSERT INTO users (id, username, password, create_by, update_by)
VALUES (132634000000000001, 'test', crypt('test_dev', gen_salt('bf', 12)),
        132634000000000001, 132634000000000001);

CREATE TABLE strategy (
    id BIGINT PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    code VARCHAR(100) NOT NULL UNIQUE,
    category VARCHAR(100) NOT NULL DEFAULT 'core_strategy',
    description TEXT,
    version VARCHAR(50) NOT NULL DEFAULT '1.0',
    status VARCHAR(50) NOT NULL DEFAULT 'active',
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    create_time TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    create_by BIGINT NOT NULL,
    update_time TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_by BIGINT NOT NULL,
    CONSTRAINT ck_strategy_status CHECK (status IN ('active', 'inactive', 'draft'))
);

COMMENT ON TABLE strategy IS 'Confirmed strategies; LLMs may only propose candidates';

INSERT INTO strategy (
    id, name, code, category, description, version, status, create_by, update_by
)
VALUES
    (132634000000001001, '分歧买龙', 'divergence_leader', 'core_strategy',
     '分歧买龙核心短线交易战术', '1.0', 'active', 132634000000000001, 132634000000000001),
    (132634000000001002, '自然换手板', 'natural_turnover', 'core_strategy',
     '自然换手板核心短线交易战术', '1.0', 'active', 132634000000000001, 132634000000000001),
    (132634000000001003, '低吸暴利潜伏', 'low_buy_ambush', 'core_strategy',
     '低吸暴利潜伏核心短线交易战术', '1.0', 'active', 132634000000000001, 132634000000000001),
    (132634000000001004, 'N字战法', 'n_pattern', 'core_strategy',
     'N字形态短线交易战术', '1.0', 'active', 132634000000000001, 132634000000000001);

CREATE TABLE knowledge_document (
    id BIGINT PRIMARY KEY,
    knowledge_base_id BIGINT NOT NULL,
    strategy_id BIGINT,
    name VARCHAR(500) NOT NULL,
    file_type VARCHAR(50) NOT NULL,
    minio_bucket VARCHAR(255),
    minio_object_key VARCHAR(1000),
    original_filename VARCHAR(500),
    source_type VARCHAR(100),
    source_name VARCHAR(255),
    category VARCHAR(100),
    status VARCHAR(50) NOT NULL DEFAULT 'UPLOADED',
    summary TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    create_time TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    create_by BIGINT NOT NULL,
    update_time TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_by BIGINT NOT NULL,
    CONSTRAINT fk_document_strategy
        FOREIGN KEY (strategy_id) REFERENCES strategy(id) ON DELETE SET NULL,
    CONSTRAINT fk_document_knowledge_base_owner
        FOREIGN KEY (knowledge_base_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT ck_document_status
        CHECK (status IN ('UPLOADED', 'PROCESSING', 'INDEXED', 'FAILED')),
    CONSTRAINT ck_document_file_type
        CHECK (file_type IN ('docx', 'pdf', 'image', 'video', 'audio', 'text')),
    CONSTRAINT ck_document_metadata_object CHECK (jsonb_typeof(metadata) = 'object')
);

COMMENT ON TABLE knowledge_document IS
'Document ledger; metadata stores document_context, processing_stage and error details';

CREATE TABLE knowledge_chunk (
    id BIGINT PRIMARY KEY,
    knowledge_base_id BIGINT NOT NULL,
    document_id BIGINT NOT NULL,
    strategy_id BIGINT,
    chunk_type VARCHAR(100) NOT NULL DEFAULT 'other',
    title VARCHAR(500) NOT NULL DEFAULT '',
    content TEXT NOT NULL,
    context VARCHAR(200),
    summary TEXT,
    chunk_index INTEGER NOT NULL,
    page_no INTEGER,
    qdrant_point_id VARCHAR(255),
    image_keys JSONB NOT NULL DEFAULT '[]'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    analysis_status VARCHAR(50) NOT NULL DEFAULT 'draft',
    retrieval_status VARCHAR(50) NOT NULL DEFAULT 'active',
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    create_time TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    create_by BIGINT NOT NULL,
    update_time TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_by BIGINT NOT NULL,
    CONSTRAINT fk_chunk_document
        FOREIGN KEY (document_id) REFERENCES knowledge_document(id) ON DELETE CASCADE,
    CONSTRAINT fk_chunk_knowledge_base_owner
        FOREIGN KEY (knowledge_base_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT fk_chunk_strategy
        FOREIGN KEY (strategy_id) REFERENCES strategy(id) ON DELETE SET NULL,
    CONSTRAINT uq_chunk_document_index UNIQUE (document_id, chunk_index),
    CONSTRAINT ck_chunk_index CHECK (chunk_index >= 0),
    CONSTRAINT ck_chunk_type CHECK (chunk_type IN (
        'principle', 'market_environment', 'stock_selection', 'entry_rule',
        'exit_rule', 'position_management', 'risk_management', 'intraday',
        'case', 'review', 'asset_allocation', 'fund', 'futures', 'macro',
        'industry', 'other'
    )),
    CONSTRAINT ck_chunk_analysis_status CHECK (analysis_status IN ('draft', 'reviewed')),
    CONSTRAINT ck_chunk_retrieval_status CHECK (retrieval_status IN ('active', 'disabled')),
    CONSTRAINT ck_chunk_status
        CHECK (status IN ('pending', 'embedding', 'embedded', 'pending_retry', 'failed')),
    CONSTRAINT ck_chunk_image_keys_array CHECK (jsonb_typeof(image_keys) = 'array'),
    CONSTRAINT ck_chunk_metadata_object CHECK (jsonb_typeof(metadata) = 'object')
);

COMMENT ON TABLE knowledge_chunk IS
'Authoritative non-overlapping chunks reconstructable by document_id and chunk_index';
COMMENT ON COLUMN knowledge_chunk.context IS
'AI retrieval context; application validation limits it to 100 Chinese characters';
COMMENT ON COLUMN knowledge_chunk.analysis_status IS 'Human review state: draft or reviewed';
COMMENT ON COLUMN knowledge_chunk.retrieval_status IS 'Retrieval state: active or disabled';

CREATE TABLE knowledge_tag (
    id BIGINT PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    category VARCHAR(100),
    description TEXT,
    create_time TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    create_by BIGINT NOT NULL
);

CREATE TABLE chunk_tag (
    chunk_id BIGINT NOT NULL,
    tag_id BIGINT NOT NULL,
    create_time TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (chunk_id, tag_id),
    CONSTRAINT fk_chunk_tag_chunk
        FOREIGN KEY (chunk_id) REFERENCES knowledge_chunk(id) ON DELETE CASCADE,
    CONSTRAINT fk_chunk_tag_tag
        FOREIGN KEY (tag_id) REFERENCES knowledge_tag(id) ON DELETE CASCADE
);

CREATE INDEX idx_document_strategy ON knowledge_document(strategy_id);
CREATE INDEX idx_document_knowledge_base ON knowledge_document(knowledge_base_id);
CREATE INDEX idx_document_status ON knowledge_document(status);
CREATE INDEX idx_document_processing_stage ON knowledge_document((metadata ->> 'processing_stage'));
CREATE INDEX idx_document_category ON knowledge_document(category);
CREATE INDEX idx_document_source ON knowledge_document(source_name);
CREATE INDEX idx_document_file_type ON knowledge_document(file_type);
CREATE INDEX idx_document_create_time ON knowledge_document(create_time DESC);
CREATE INDEX idx_document_metadata_gin ON knowledge_document USING GIN(metadata);

CREATE INDEX idx_strategy_status ON strategy(status);
CREATE INDEX idx_strategy_category ON strategy(category);

CREATE INDEX idx_chunk_strategy ON knowledge_chunk(strategy_id);
CREATE INDEX idx_chunk_knowledge_base ON knowledge_chunk(knowledge_base_id);
CREATE INDEX idx_chunk_type ON knowledge_chunk(chunk_type);
CREATE INDEX idx_chunk_status ON knowledge_chunk(status);
CREATE INDEX idx_chunk_analysis_status ON knowledge_chunk(analysis_status);
CREATE INDEX idx_chunk_retrieval_status ON knowledge_chunk(retrieval_status);
CREATE INDEX idx_chunk_active_document_index
    ON knowledge_chunk(document_id, chunk_index) WHERE retrieval_status = 'active';
CREATE UNIQUE INDEX idx_chunk_qdrant_point
    ON knowledge_chunk(qdrant_point_id) WHERE qdrant_point_id IS NOT NULL;
CREATE INDEX idx_chunk_metadata_gin ON knowledge_chunk USING GIN(metadata);

CREATE INDEX idx_tag_category ON knowledge_tag(category);
CREATE INDEX idx_chunk_tag_tag_id ON chunk_tag(tag_id);

COMMIT;
