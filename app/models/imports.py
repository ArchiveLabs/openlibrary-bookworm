import json
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

import jsonschema
from pydantic import BaseModel
from sqlalchemy import DateTime, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

# ---------------------------------------------------------------------------
# Import record validation (vendored OL schema, $refs inlined)
# ---------------------------------------------------------------------------

_SCHEMA = json.loads((Path(__file__).parent.parent / "schemata" / "import.schema.json").read_text())
_VALIDATOR = jsonschema.Draft4Validator(_SCHEMA)

VALID_STATUSES = frozenset(
    {"pending", "staged", "processing", "failed", "found", "created", "modified", "needs_review"}
)


def validate_import_record(data: dict) -> list[str]:
    """Return validation error messages for a candidate import record; empty = valid."""
    return [
        f"{'.'.join(str(p) for p in e.path) or 'root'}: {e.message}"
        for e in _VALIDATOR.iter_errors(data)
    ]


# ---------------------------------------------------------------------------
# Sources  (enum + DB reference table — Python is source of truth)
# ---------------------------------------------------------------------------


class SourceType(str, Enum):
    amazon = "amz"
    bwb = "bwb"
    internet_archive = "ia"
    isbn = "isbn"
    librivox = "librivox"


# Seed data for the import_source table; extend here as new sources are added.
KNOWN_SOURCES: list[dict] = [
    {"name": SourceType.amazon, "label": "Amazon"},
    {"name": SourceType.bwb, "label": "Better World Books"},
    {"name": SourceType.internet_archive, "label": "Internet Archive"},
    {"name": SourceType.isbn, "label": "ISBN"},
    {"name": SourceType.librivox, "label": "LibriVox"},
]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# SQLAlchemy ORM models
# ---------------------------------------------------------------------------


class Base(DeclarativeBase):
    pass


class ImportSource(Base):
    __tablename__ = "import_source"

    name: Mapped[str] = mapped_column(Text, primary_key=True)  # e.g. "bwb"
    label: Mapped[str] = mapped_column(Text, nullable=False)   # e.g. "Better World Books"


class ImportBatch(Base):
    __tablename__ = "import_batch"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str | None] = mapped_column(Text)
    submitter: Mapped[str | None] = mapped_column(Text)
    submit_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    items: Mapped[list["ImportItem"]] = relationship(back_populates="batch")


class ImportItem(Base):
    __tablename__ = "import_item"
    __table_args__ = (
        UniqueConstraint("batch_id", "source", "value", name="uq_import_item_batch_source_value"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(Integer, ForeignKey("import_batch.id"), nullable=False)
    # source references import_source.name; enforced at app level via SourceType, not FK
    # (avoids FK seeding requirement in tests and keeps SQLite-compatible)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)   # source-specific id, e.g. ASIN or ISBN-13
    added_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    import_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # pending | staged | processing | failed | found | created | modified | needs_review
    status: Mapped[str] = mapped_column(Text, default="pending")
    error: Mapped[str | None] = mapped_column(Text)
    data: Mapped[dict | None] = mapped_column(JSON().with_variant(JSONB(), "postgresql"))
    ol_key: Mapped[str | None] = mapped_column(Text)
    submitter: Mapped[str | None] = mapped_column(Text)

    batch: Mapped["ImportBatch"] = relationship(back_populates="items")


# ---------------------------------------------------------------------------
# Pydantic schemas  (request bodies and response shapes)
# ---------------------------------------------------------------------------


class BatchCreate(BaseModel):
    name: str
    submitter: str | None = None


class BatchResponse(BaseModel):
    id: int
    name: str | None
    submitter: str | None
    submit_time: datetime

    model_config = {"from_attributes": True}


class BatchDetail(BatchResponse):
    item_counts: dict[str, int]


class ItemValidationError(BaseModel):
    index: int
    source: str
    value: str
    messages: list[str]


class ItemIn(BaseModel):
    source: SourceType
    value: str
    data: dict
    submitter: str | None = None
    status: str = "pending"


class ItemsResult(BaseModel):
    added: int
    skipped: int
    errors: list[ItemValidationError]


class ItemResponse(BaseModel):
    id: int
    batch_id: int
    source: str
    value: str
    status: str
    ol_key: str | None
    error: str | None
    submitter: str | None
    added_time: datetime
    import_time: datetime | None

    model_config = {"from_attributes": True}


class ItemStatusPatch(BaseModel):
    status: str
    error: str | None = None
    ol_key: str | None = None
