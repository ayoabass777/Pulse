# Pulse — Data Contracts

## raw.events

The consumer guarantees every row written to `raw.events` satisfies:

### Fields

| Column | Type | Nullable | Source | Description |
|---|---|---|---|---|
| event_id | TEXT (PK) | NO | Consumer | Idempotent key: `{user_id}:{kafka_timestamp_ms}`. Duplicates rejected via `ON CONFLICT DO NOTHING`. |
| event_type | TEXT | NO | Producer | One of: `page_view`, `product_view`, `search`, `add_to_cart`, `remove_from_cart`, `checkout`, `payment`, `button_click`, `form_submit`, `video_play` |
| user_id | TEXT | NO | Producer | UUID identifying the user |
| event_timestamp | TIMESTAMPTZ | NO | Producer | Business time — when the event "happened" in the simulation |
| page | TEXT | YES | Producer | URI path of the page |
| product_id | TEXT | YES | Producer | UUID of the product (null for non-product events) |
| category | TEXT | YES | Producer | Product category: `electronics`, `books`, `clothing`, `home`, `sports` |
| price | NUMERIC(10,2) | YES | Producer | Product price (null for non-product events) |
| search_query | TEXT | YES | Producer | Search query text (null for non-search events) |
| funnel_step_index | INT | YES | Producer | 0-4 mapping to funnel sequence position |
| funnel_complete | BOOLEAN | NO | Producer | `true` only when event_type = `payment` |
| kafka_timestamp | TIMESTAMPTZ | NO | Consumer | Broker ingestion time — when Kafka received the message. Watermark source for dbt. |
| kafka_partition | INT | YES | Consumer | Kafka partition the message was read from |
| kafka_offset | BIGINT | YES | Consumer | Kafka offset within the partition |
| created_at | TIMESTAMPTZ | NO | Postgres | Row insertion time (DEFAULT NOW()) |

### Invariants

1. **event_id is unique** — enforced by PK. Consumer generates it from `user_id + kafka_timestamp_ms`. Replayed events produce the same event_id → `ON CONFLICT DO NOTHING`.
2. **Two timestamps, two purposes:**
   - `event_timestamp` = business time (analytics: "when did the user click?") — **used for session reconstruction ordering**
   - `kafka_timestamp` = ingestion time (operations: "when did we receive this?") — **used for dbt freshness checks and watermarks**
3. **kafka_partition + kafka_offset** = exact provenance back to Kafka. You can trace any row to the exact message in the topic.
4. **Funnel ordering:** `funnel_step_index` maps to: 0=page_view, 1=product_view, 2=add_to_cart, 3=checkout, 4=payment. Not enforced in Postgres — validated in dbt.

### Delivery Guarantee

| Layer | Guarantee | Mechanism |
|---|---|---|
| Producer → Kafka | Exactly-once | `enable.idempotence=True` (broker dedup on retry) |
| Kafka → Consumer | At-least-once | Manual offset commit after Postgres commit |
| Consumer → Postgres | Idempotent | `ON CONFLICT (event_id) DO NOTHING` (replay-safe) |

**End-to-end: effectively exactly-once.** Idempotent producer prevents Kafka duplicates. At-least-once consumer may replay on crash, but `ON CONFLICT` silently drops the duplicate row in Postgres.

#### Two Layers of Idempotency (Not the Same Thing)

| Concept | Layer | Purpose |
|---------|-------|--------|
| `enable.idempotence=True` | Producer → Kafka | Prevents duplicate messages *in Kafka* when producer retries due to network timeout |
| Idempotent key (`event_id`) | Consumer → Postgres | Prevents duplicate rows *in Postgres* when consumer replays after crash |

**Why both are needed:**
- Producer retries on timeout → Kafka broker rejects duplicate (idempotent producer handles this)
- Consumer crashes after Postgres write but before offset commit → Kafka replays → Postgres rejects duplicate (idempotent key handles this)

Together = effectively exactly-once end-to-end.

### Error Routing

| Error type | Example | Action |
|---|---|---|
| Transient | Connection timeout, deadlock | Don't commit offset → Kafka replays automatically |
| Non-transient (event) | Missing `user_id`, bad data type | Route individual event to `user_activity_dlq` topic |
| Non-transient (batch) | Schema mismatch, table dropped | Route entire batch to DLQ → commit offset |

---

## raw.consumer_offsets

Tracks the last successfully committed Kafka offset per topic-partition in the same Postgres transaction as the event writes.

| Column | Type | Description |
|---|---|---|
| topic | TEXT (PK) | Kafka topic name |
| partition_id | INT (PK) | Kafka partition number |
| committed_offset | BIGINT | Last offset successfully written to Postgres |
| updated_at | TIMESTAMPTZ | When the offset was last updated |

### Purpose

Enables recovery without relying on Kafka consumer group offsets. On startup, the consumer can read the last committed offset from this table and seek to it — no data loss, no duplicates.

---

## dbt Downstream Expectations

dbt models can rely on:

- `event_id` is unique (safe to use as grain)
- `kafka_timestamp` is always populated (use for watermark-based incremental processing)
- `event_timestamp` is always populated (use for business-time analytics)
- `event_type` is always one of the defined enum values
- `user_id` is always populated
- `funnel_step_index` of 0-4 when present, null otherwise
- Rows may arrive out of order — `kafka_timestamp` ordering may differ from `event_timestamp` ordering
