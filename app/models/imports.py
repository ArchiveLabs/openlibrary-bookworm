from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


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
