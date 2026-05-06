from datetime import datetime, timezone

from pydantic import BaseModel
from sqlalchemy import DateTime, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

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


class ImportBatch(Base):
    __tablename__ = "import_batch"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str | None] = mapped_column(Text)
    submitter: Mapped[str | None] = mapped_column(Text)
    submit_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    items: Mapped[list["ImportItem"]] = relationship(back_populates="batch")


class ImportItem(Base):
    __tablename__ = "import_item"
    __table_args__ = (UniqueConstraint("batch_id", "source_id", name="uq_import_item_batch_source"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(Integer, ForeignKey("import_batch.id"), nullable=False)
    added_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    import_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # pending | staged | processing | failed | found | created | modified | needs_review
    status: Mapped[str] = mapped_column(Text, default="pending")
    error: Mapped[str | None] = mapped_column(Text)
    source_id: Mapped[str | None] = mapped_column(Text)  # e.g. "bwb:9780123456789"
    data: Mapped[dict | None] = mapped_column(JSON().with_variant(JSONB(), "postgresql"))
    ol_key: Mapped[str | None] = mapped_column(Text)  # /books/OL... after import
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


class ItemIn(BaseModel):
    source_id: str
    data: dict
    submitter: str | None = None
    status: str = "pending"


class ItemsResult(BaseModel):
    added: int
    skipped: int


class ItemResponse(BaseModel):
    id: int
    batch_id: int
    source_id: str | None
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
