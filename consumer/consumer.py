"""
Kafka → Postgres consumer for Pulse.

Reads events from the Kafka topic, validates them against the
Pydantic data contract, batches valid rows, and upserts to
raw.events in a transaction. Kafka offsets are only committed
after a successful Postgres commit.

Data contract:
- Defined in contracts/events.py (RawEvent, DLQRecord)
- event_id = user_id:kafka_timestamp_ms (idempotent key)
- ON CONFLICT (event_id) DO NOTHING = duplicates from replay silently dropped

Error handling:
- Validation errors (Pydantic): route to DLQ topic (non-transient)
- Transient Postgres errors: don't commit offset → Kafka replays
- Non-transient Postgres errors: route to DLQ topic → commit offset
"""

import os
import json
import time
import logging
import traceback
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

import psycopg2
from psycopg2.extras import execute_values
from kafka import KafkaConsumer, KafkaProducer
from pydantic import ValidationError

from contracts.events import RawEvent, DLQRecord

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("pulse.consumer")

# ── Config ────────────────────────────────────────────────────────────

KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:29092")
KAFKA_TOPIC = os.getenv("KAFKA_TOPIC", "user_activity")
KAFKA_DLQ_TOPIC = os.getenv("KAFKA_DLQ_TOPIC", "user_activity_dlq")
KAFKA_GROUP = os.getenv("KAFKA_CONSUMER_GROUP", "pulse-postgres-writer")

DB_CONFIG = {
    "dbname": os.getenv("DB_NAME", "pulse"),
    "user": os.getenv("DB_USER", "pulse_user"),
    "password": os.getenv("DB_PASSWORD", "changeme"),
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", "5433")),
}

BATCH_SIZE = int(os.getenv("CONSUMER_BATCH_SIZE", "100"))
FLUSH_INTERVAL_SECONDS = int(os.getenv("CONSUMER_FLUSH_INTERVAL", "5"))

RAW_TABLE = "raw.events"
INSERT_COLUMNS = [
    "event_id",
    "event_type",
    "user_id",
    "event_timestamp",
    "page",
    "product_id",
    "category",
    "price",
    "search_query",
    "funnel_step_index",
    "funnel_complete",
    "kafka_timestamp",
    "kafka_partition",
    "kafka_offset",
]

INSERT_SQL = f"""
    INSERT INTO {RAW_TABLE} ({', '.join(INSERT_COLUMNS)})
    VALUES %s
    ON CONFLICT (event_id) DO NOTHING
"""

INSERT_TEMPLATE = "(" + ", ".join(["%s"] * len(INSERT_COLUMNS)) + ")"


# ── Helpers ───────────────────────────────────────────────────────────

def get_db_connection() -> psycopg2.extensions.connection:
    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = False
    return conn


def get_dlq_producer() -> KafkaProducer:
    return KafkaProducer(
        bootstrap_servers=[KAFKA_BOOTSTRAP],
        value_serializer=lambda v: json.dumps(v, default=str).encode("utf-8"),
        acks="all",
    )


def send_to_dlq(
    dlq_producer: KafkaProducer,
    event: Dict[str, Any],
    error: Exception,
) -> None:
    """Write a failed event to the DLQ topic using the DLQRecord contract."""
    record = DLQRecord(
        original_event=event,
        error_type=type(error).__name__,
        error_message=str(error),
        traceback=traceback.format_exc(),
        consumer_group=KAFKA_GROUP,
    )
    try:
        dlq_producer.send(KAFKA_DLQ_TOPIC, value=record.to_dict())
        dlq_producer.flush()
    except Exception as dlq_err:
        logger.error("Failed to write to DLQ: %s", dlq_err)


def validate_and_convert_batch(
    messages: list,
    dlq_producer: KafkaProducer,
) -> Tuple[List[tuple], int]:
    """
    Validate each Kafka message against the RawEvent contract.
    Valid events → row tuples. Invalid events → DLQ topic.
    """
    valid_rows: List[tuple] = []
    dlq_count = 0

    for msg in messages:
        try:
            # Pydantic validates the event against the contract
            event = RawEvent(**msg.value)
            row = event.to_row(
                kafka_timestamp_ms=msg.timestamp,
                kafka_partition=msg.partition,
                kafka_offset=msg.offset,
            )
            valid_rows.append(row)
        except ValidationError as e:
            logger.warning(
                "Contract violation (routing to DLQ): %s — payload=%s",
                e.error_count(), msg.value.get("user_id", "unknown") if isinstance(msg.value, dict) else "unknown",
            )
            send_to_dlq(dlq_producer, msg.value if isinstance(msg.value, dict) else {}, error=e)
            dlq_count += 1
        except Exception as e:
            logger.warning(
                "Unexpected validation error (routing to DLQ): %s — %s",
                type(e).__name__, e,
            )
            send_to_dlq(dlq_producer, msg.value if isinstance(msg.value, dict) else {}, error=e)
            dlq_count += 1

    return valid_rows, dlq_count


def flush_batch(
    conn: psycopg2.extensions.connection,
    rows: List[tuple],
) -> int:
    """
    Upsert a batch of event rows to Postgres in a single transaction.
    ON CONFLICT (event_id) DO NOTHING handles duplicates from replay.
    """
    if not rows:
        return 0
    cur = conn.cursor()
    try:
        execute_values(cur, INSERT_SQL, rows, template=INSERT_TEMPLATE, page_size=BATCH_SIZE)
        conn.commit()
        return len(rows)
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


def is_transient_error(error: Exception) -> bool:
    transient_types = (
        psycopg2.OperationalError,
        psycopg2.InterfaceError,
    )
    if hasattr(psycopg2, "errors"):
        transient_types += (
            psycopg2.errors.SerializationFailure,
            psycopg2.errors.DeadlockDetected,
        )
    return isinstance(error, transient_types)


# ── Main loop ─────────────────────────────────────────────────────────

def run():
    logger.info(
        "Starting Pulse consumer: topic=%s, group=%s, batch=%d, flush=%ds",
        KAFKA_TOPIC, KAFKA_GROUP, BATCH_SIZE, FLUSH_INTERVAL_SECONDS,
    )

    consumer = KafkaConsumer(
        KAFKA_TOPIC,
        bootstrap_servers=[KAFKA_BOOTSTRAP],
        auto_offset_reset="earliest",
        enable_auto_commit=False,
        group_id=KAFKA_GROUP,
        key_deserializer=lambda k: k.decode("utf-8") if k else None,
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
        consumer_timeout_ms=1000,
    )

    conn = get_db_connection()
    dlq_producer = get_dlq_producer()
    msg_batch: list = []
    last_flush = time.time()
    total_flushed = 0
    total_dlq = 0

    logger.info("Connected. Consuming from %s...", KAFKA_TOPIC)

    try:
        while True:
            for message in consumer:
                msg_batch.append(message)

                if len(msg_batch) >= BATCH_SIZE:
                    flushed, dlq_count = _process_batch(
                        conn, dlq_producer, consumer, msg_batch
                    )
                    total_flushed += flushed
                    total_dlq += dlq_count
                    logger.info(
                        "Batch flush: %d written, %d to DLQ (total: %d written, %d DLQ)",
                        flushed, dlq_count, total_flushed, total_dlq,
                    )
                    msg_batch.clear()
                    last_flush = time.time()

            if msg_batch and (time.time() - last_flush) >= FLUSH_INTERVAL_SECONDS:
                flushed, dlq_count = _process_batch(
                    conn, dlq_producer, consumer, msg_batch
                )
                total_flushed += flushed
                total_dlq += dlq_count
                logger.info(
                    "Time flush: %d written, %d to DLQ (total: %d written, %d DLQ)",
                    flushed, dlq_count, total_flushed, total_dlq,
                )
                msg_batch.clear()
                last_flush = time.time()

    except KeyboardInterrupt:
        logger.info("Shutting down. Flushing remaining %d events...", len(msg_batch))
        if msg_batch:
            flushed, dlq_count = _process_batch(
                conn, dlq_producer, consumer, msg_batch
            )
            total_flushed += flushed
            total_dlq += dlq_count
    except Exception as e:
        logger.error("Consumer fatal error: %s", e, exc_info=True)
    finally:
        consumer.close()
        dlq_producer.close()
        conn.close()
        logger.info(
            "Consumer stopped. Total: %d written, %d to DLQ.",
            total_flushed, total_dlq,
        )


def _process_batch(
    conn: psycopg2.extensions.connection,
    dlq_producer: KafkaProducer,
    consumer: KafkaConsumer,
    msg_batch: list,
) -> Tuple[int, int]:
    """
    Validate (Pydantic) → upsert (Postgres) → commit (Kafka).
    """
    valid_rows, dlq_count = validate_and_convert_batch(msg_batch, dlq_producer)

    flushed = 0
    try:
        flushed = flush_batch(conn, valid_rows)
        consumer.commit()
    except Exception as e:
        logger.error(
            "Flush failed (type=%s): %s", type(e).__name__, e, exc_info=True,
        )
        if is_transient_error(e):
            logger.warning("Transient error, will retry from Kafka: %s", e)
            raise
        else:
            logger.error(
                "Non-transient batch error (type=%s), routing %d events to DLQ",
                type(e).__name__, len(valid_rows),
            )
            for msg in msg_batch:
                event = msg.value if isinstance(msg.value, dict) else {}
                send_to_dlq(dlq_producer, event, error=e)
            consumer.commit()
            dlq_count = len(msg_batch)
            flushed = 0

    return flushed, dlq_count


if __name__ == "__main__":
    run()
