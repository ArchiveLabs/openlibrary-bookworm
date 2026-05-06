from datetime import datetime, timezone
from pathlib import Path

import yaml
from pydantic import BaseModel, field_validator
from sqlalchemy import DateTime, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

_SCHEMATA = Path(__file__).parent.parent / "schemata"

# ---------------------------------------------------------------------------
# Sources — loaded from vendored OL identifiers.yml
# ---------------------------------------------------------------------------

_RAW_IDENTIFIERS: list[dict] = yaml.safe_load(
    (_SCHEMATA / "identifiers.yml").read_text()
)["identifiers"]

VALID_SOURCE_NAMES: frozenset[str] = frozenset(i["name"] for i in _RAW_IDENTIFIERS)

KNOWN_SOURCES: list[dict] = [
    {"name": i["name"], "label": i["label"]} for i in _RAW_IDENTIFIERS
]

VALID_STATUSES = frozenset(
    {"pending", "staged", "processing", "failed", "found", "created", "modified", "needs_review"}
)


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
        # Uniqueness is per-batch: the same (source, value) can appear in
        # multiple batches (different submitters, different runs) without
        # conflict. Only within one batch is a duplicate rejected.
        UniqueConstraint("batch_id", "source", "value", name="uq_import_item_batch_source_value"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(Integer, ForeignKey("import_batch.id"), nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)  # e.g. "bwb"
    value: Mapped[str] = mapped_column(Text, nullable=False)   # e.g. "9780451524935"
    added_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    import_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, default="pending")
    error: Mapped[str | None] = mapped_column(Text)
    data: Mapped[dict | None] = mapped_column(JSON().with_variant(JSONB(), "postgresql"))
    ol_key: Mapped[str | None] = mapped_column(Text)
    submitter: Mapped[str | None] = mapped_column(Text)

    batch: Mapped["ImportBatch"] = relationship(back_populates="items")


# ---------------------------------------------------------------------------
# Pydantic schemas
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
                "See app/schemata/identifiers.yml for the full list."
            )
        return v


class ItemsResult(BaseModel):
    added: int
    skipped: int


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
