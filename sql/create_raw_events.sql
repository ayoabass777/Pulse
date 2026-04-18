-- ═══════════════════════════════════════════════════════════════════════
-- Pulse — Raw Events Schema
-- ═══════════════════════════════════════════════════════════════════════
-- Data contract: the consumer guarantees every row has:
--   - event_id (Kafka-derived: user_id + kafka_timestamp_ms, unique)
--   - event_type, user_id, event_timestamp (NOT NULL)
--   - kafka_timestamp (broker ingestion time, NOT NULL)
--   - kafka_partition, kafka_offset (provenance tracking)
--
-- Downstream (dbt) can rely on:
--   - event_id is unique (idempotent writes via ON CONFLICT)
--   - kafka_timestamp for watermark-based aggregation
--   - event_timestamp for business-time analytics
-- ═══════════════════════════════════════════════════════════════════════

CREATE SCHEMA IF NOT EXISTS raw;

-- ── Raw events ───────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS raw.events (
    -- Idempotent key: user_id + kafka_timestamp_ms
    -- Duplicates from at-least-once delivery are rejected via ON CONFLICT
    event_id            TEXT PRIMARY KEY,

    -- Event payload (from producer)
    event_type          TEXT NOT NULL,
    user_id             TEXT NOT NULL,
    event_timestamp     TIMESTAMPTZ NOT NULL,  -- business time (when event "happened")
    page                TEXT,
    product_id          TEXT,
    category            TEXT,
    price               NUMERIC(10, 2),
    search_query        TEXT,
    funnel_step_index   INT,
    funnel_complete     BOOLEAN DEFAULT FALSE,

    -- Kafka provenance (from consumer)
    kafka_timestamp     TIMESTAMPTZ NOT NULL,  -- broker ingestion time (watermark source)
    kafka_partition     INT,
    kafka_offset        BIGINT,

    -- Consumer metadata
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_events_user_id ON raw.events (user_id);
CREATE INDEX IF NOT EXISTS idx_events_event_ts ON raw.events (event_timestamp);
CREATE INDEX IF NOT EXISTS idx_events_kafka_ts ON raw.events (kafka_timestamp);
CREATE INDEX IF NOT EXISTS idx_events_type ON raw.events (event_type);

-- ── Consumer offset tracking ─────────────────────────────────────────
-- Stores Kafka offsets in the same transaction as event writes.
-- Enables exactly-once delivery: consumer reads last committed offset
-- from this table on startup instead of relying on Kafka consumer groups.

CREATE TABLE IF NOT EXISTS raw.consumer_offsets (
    topic            TEXT NOT NULL,
    partition_id     INT NOT NULL,
    committed_offset BIGINT NOT NULL,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (topic, partition_id)
);
