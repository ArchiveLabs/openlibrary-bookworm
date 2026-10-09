from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from procrastinate.jobs import Status
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    MetaData,
    Table,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlmodel import Field, SQLModel

from bookworm.utils import utcnow

# Procrastinate owns this table; keep it outside Bookworm's migration metadata.
QUEUE_JOBS = Table(
    "procrastinate_jobs",
    MetaData(),
    Column("id", BigInteger, primary_key=True),
    Column(
        "status",
        ENUM(
            Status,
            name="procrastinate_job_status",
            schema="procrastinate",
            create_type=False,
            values_callable=lambda statuses: [status.value for status in statuses],
        ),
    ),
    schema="procrastinate",
)


class ItemStatus(StrEnum):
    pending_approval = "pending_approval"
    queued = "queued"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class Job(SQLModel, table=True):
    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_created_id", "created_at", "id"),)

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: str = Field(index=True, max_length=255)
    project_id: UUID | None = Field(default=None, foreign_key="projects.id", index=True)
    created_at: datetime = Field(default_factory=utcnow, sa_type=DateTime(timezone=True))


class ImportItem(SQLModel, table=True):
    __tablename__ = "import_items"
    __table_args__ = (
        UniqueConstraint("job_id", "position", name="uq_item_job_position"),
        CheckConstraint("position >= 0", name="ck_item_position"),
        Index("ix_items_job_position", "job_id", "position"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    job_id: UUID = Field(foreign_key="jobs.id")
    position: int
    data: dict[str, Any] = Field(sa_column=Column(JSONB, nullable=False))
    procrastinate_job_id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger, ForeignKey(QUEUE_JOBS.c.id), index=True),
    )
    error_context: dict[str, str] | None = Field(
        default=None, sa_column=Column(JSONB(none_as_null=True))
    )
    approved_by: str | None = Field(default=None, max_length=255)
    approved_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    created_at: datetime = Field(default_factory=utcnow, sa_type=DateTime(timezone=True))
    updated_at: datetime = Field(default_factory=utcnow, sa_type=DateTime(timezone=True))


class SourceReservation(SQLModel, table=True):
    __tablename__ = "source_reservations"

    project_id: UUID = Field(foreign_key="projects.id", primary_key=True)
    source_record: str = Field(primary_key=True)
    item_id: UUID = Field(foreign_key="import_items.id", index=True)
