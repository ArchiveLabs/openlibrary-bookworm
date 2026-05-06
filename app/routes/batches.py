from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import require_api_key
from app.database import get_db
from app.models.imports import ImportBatch, ImportItem

router = APIRouter(tags=["batches"])

VALID_STATUSES = frozenset(
    {"pending", "staged", "processing", "failed", "found", "created", "modified", "needs_review"}
)


# ---------- Pydantic schemas ----------


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
    # callers with admin keys may set status directly; defaults to "pending"
    status: str = "pending"


class ItemsResponse(BaseModel):
    added: int
    skipped: int  # duplicates ignored due to UNIQUE constraint


# ---------- Routes ----------


@router.post("/batches", response_model=BatchResponse, status_code=status.HTTP_201_CREATED)
def create_batch(
    body: BatchCreate,
    db: Session = Depends(get_db),
    _: str = Depends(require_api_key),
) -> ImportBatch:
    batch = ImportBatch(name=body.name, submitter=body.submitter)
    db.add(batch)
    db.commit()
    db.refresh(batch)
    return batch


@router.get("/batches/{batch_id}", response_model=BatchDetail)
def get_batch(batch_id: int, db: Session = Depends(get_db)) -> BatchDetail:
    batch = db.get(ImportBatch, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Batch not found")

    counts_rows = (
        db.execute(
            select(ImportItem.status, func.count().label("n"))
            .where(ImportItem.batch_id == batch_id)
            .group_by(ImportItem.status)
        )
        .all()
    )
    counts = {row.status: row.n for row in counts_rows}

    return BatchDetail(
        id=batch.id,
        name=batch.name,
        submitter=batch.submitter,
        submit_time=batch.submit_time,
        item_counts=counts,
    )


@router.post(
    "/batches/{batch_id}/items",
    response_model=ItemsResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_items(
    batch_id: int,
    items: list[ItemIn],
    db: Session = Depends(get_db),
    _: str = Depends(require_api_key),
) -> ItemsResponse:
    if db.get(ImportBatch, batch_id) is None:
        raise HTTPException(status_code=404, detail="Batch not found")

    # Fetch source_ids already in this batch to detect duplicates without relying on
    # catching IntegrityError (simpler and DB-agnostic).
    existing = set(
        db.scalars(
            select(ImportItem.source_id).where(ImportItem.batch_id == batch_id)
        ).all()
    )

    added = 0
    skipped = 0
    for item in items:
        if item.source_id in existing:
            skipped += 1
            continue
        if item.status not in VALID_STATUSES:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid status '{item.status}'. Must be one of {sorted(VALID_STATUSES)}",
            )
        db.add(
            ImportItem(
                batch_id=batch_id,
                source_id=item.source_id,
                data=item.data,
                submitter=item.submitter,
                status=item.status,
            )
        )
        existing.add(item.source_id)
        added += 1

    db.commit()
    return ItemsResponse(added=added, skipped=skipped)
