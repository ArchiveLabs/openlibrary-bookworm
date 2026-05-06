import json
from datetime import datetime, timezone
from pathlib import Path

import jsonschema
import yaml
from pydantic import BaseModel, field_validator
from sqlalchemy import DateTime, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

_SCHEMATA = Path(__file__).parent.parent / "schemata"

# ---------------------------------------------------------------------------
# Sources — loaded from vendored OL identifiers.yml
# `name` values are the canonical source identifiers (e.g. "better_world_books")
# ---------------------------------------------------------------------------

_RAW_IDENTIFIERS: list[dict] = yaml.safe_load(
    (_SCHEMATA / "identifiers.yml").read_text()
)["identifiers"]

# Flat set of valid source names for fast membership checks
VALID_SOURCE_NAMES: frozenset[str] = frozenset(i["name"] for i in _RAW_IDENTIFIERS)

# Seed rows for the import_source DB table (name + label only)
KNOWN_SOURCES: list[dict] = [
    {"name": i["name"], "label": i["label"]} for i in _RAW_IDENTIFIERS
]

# ---------------------------------------------------------------------------
# Import record validation (vendored OL schema, $refs inlined)
# ---------------------------------------------------------------------------

_SCHEMA = json.loads((_SCHEMATA / "import.schema.json").read_text())
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


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# SQLAlchemy ORM models
# ---------------------------------------------------------------------------


class Base(DeclarativeBase):
    pass


class ImportSource(Base):
    """Reference table of known import sources, seeded from identifiers.yml."""
    __tablename__ = "import_source"

    name: Mapped[str] = mapped_column(Text, primary_key=True)
    label: Mapped[str] = mapped_column(Text, nullable=False)


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
    source: Mapped[str] = mapped_column(Text, nullable=False)  # e.g. "better_world_books"
    value: Mapped[str] = mapped_column(Text, nullable=False)   # source-specific id
    added_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    import_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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
    source: str
    value: str
    data: dict
    submitter: str | None = None
    status: str = "pending"

    @field_validator("source")
    @classmethod
    def check_source(cls, v: str) -> str:
        if v not in VALID_SOURCE_NAMES:
            raise ValueError(
                f"'{v}' is not a recognised OL identifier. "
                f"See app/schemata/identifiers.yml for the full list."
            )
        return v


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
