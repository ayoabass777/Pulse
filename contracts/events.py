"""
Pulse — Data Contracts (Pydantic models)

These models define the shape of data at each boundary in the pipeline.
They serve as runtime validation, documentation, and the single source
of truth for what the consumer accepts and what dbt can rely on.

Usage:
    from contracts.events import RawEvent, DLQRecord

    # Validate a Kafka message
    event = RawEvent(**message.value)

    # Convert to Postgres row
    row = event.to_row(kafka_timestamp_ms, kafka_partition, kafka_offset)
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# ── Enums ─────────────────────────────────────────────────────────────

class EventType(str, Enum):
    PAGE_VIEW = "page_view"
    PRODUCT_VIEW = "product_view"
    SEARCH = "search"
    ADD_TO_CART = "add_to_cart"
    REMOVE_FROM_CART = "remove_from_cart"
    CHECKOUT = "checkout"
    PAYMENT = "payment"
    BUTTON_CLICK = "button_click"
    FORM_SUBMIT = "form_submit"
    VIDEO_PLAY = "video_play"


class ProductCategory(str, Enum):
    ELECTRONICS = "electronics"
    BOOKS = "books"
    CLOTHING = "clothing"
    HOME = "home"
    SPORTS = "sports"


# ── Event Metadata ────────────────────────────────────────────────────

class EventMetadata(BaseModel):
    """Optional metadata attached to an event by the producer."""
    product_id: Optional[str] = None
    category: Optional[ProductCategory] = None
    price: Optional[Decimal] = Field(None, ge=0, le=99999.99)
    search_query: Optional[str] = None


# ── Raw Event (Producer → Kafka → Consumer) ──────────────────────────

class RawEvent(BaseModel):
    """
    Contract for events consumed from Kafka.
    Validated before writing to Postgres.

    Required fields: event_type, user_id, timestamp.
    Optional fields: page, metadata, funnel_step_index, funnel_complete.
    """
    event_type: EventType
    user_id: str = Field(..., min_length=1)
    timestamp: datetime
    page: Optional[str] = None
    metadata: Optional[EventMetadata] = None
    funnel_step_index: Optional[int] = Field(None, ge=0, le=4)
    funnel_complete: bool = False

    @field_validator("timestamp", mode="before")
    @classmethod
    def parse_timestamp(cls, v):
        """Accept ISO string or datetime."""
        if isinstance(v, str):
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        return v

    def make_event_id(self, kafka_timestamp_ms: int) -> str:
        """Idempotent key: user_id + kafka broker timestamp."""
        return f"{self.user_id}:{kafka_timestamp_ms}"

    def to_row(
        self,
        kafka_timestamp_ms: int,
        kafka_partition: int,
        kafka_offset: int,
    ) -> tuple:
        """
        Convert to a tuple matching raw.events INSERT_COLUMNS.
        This is the boundary between the contract and Postgres.
        """
        meta = self.metadata or EventMetadata()
        kafka_ts = datetime.fromtimestamp(
            kafka_timestamp_ms / 1000.0, tz=timezone.utc
        )

        return (
            self.make_event_id(kafka_timestamp_ms),
            self.event_type.value,
            self.user_id,
            self.timestamp,
            self.page,
            meta.product_id,
            meta.category.value if meta.category else None,
            float(meta.price) if meta.price is not None else None,
            meta.search_query,
            self.funnel_step_index,
            self.funnel_complete,
            kafka_ts,
            kafka_partition,
            kafka_offset,
        )


# ── DLQ Record ────────────────────────────────────────────────────────

class DLQRecord(BaseModel):
    """
    Contract for events written to the dead letter queue topic.
    Captures the original event and the error context for debugging.
    """
    original_event: dict
    error_type: str
    error_message: str
    traceback: Optional[str] = None
    consumer_group: str
    failed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        """Serialize for Kafka producer."""
        return self.model_dump(mode="json")
