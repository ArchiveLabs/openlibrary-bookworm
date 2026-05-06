from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    BatchCreate,
    BatchDetail,
    BatchResponse,
    ImportBatch,
    ImportItem,
    ItemIn,
    ItemsResult,
    VALID_STATUSES,
)

router = APIRouter(tags=["batches"])


@router.post("/batches", response_model=BatchResponse, status_code=status.HTTP_201_CREATED)
def create_batch(body: BatchCreate, db: Session = Depends(get_db)) -> ImportBatch:
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

    counts = {
        row.status: row.n
        for row in db.execute(
            select(ImportItem.status, func.count().label("n"))
            .where(ImportItem.batch_id == batch_id)
            .group_by(ImportItem.status)
        ).all()
    }

    return BatchDetail(
        id=batch.id,
        name=batch.name,
        submitter=batch.submitter,
        submit_time=batch.submit_time,
        item_counts=counts,
    )


@router.post(
    "/batches/{batch_id}/items",
    response_model=ItemsResult,
    status_code=status.HTTP_201_CREATED,
)
def add_items(
    batch_id: int,
    items: list[ItemIn],
    db: Session = Depends(get_db),
) -> ItemsResult:
    if db.get(ImportBatch, batch_id) is None:
        raise HTTPException(status_code=404, detail="Batch not found")

    invalid = {i.status for i in items} - VALID_STATUSES
    if invalid:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid status values: {sorted(invalid)}. Must be one of {sorted(VALID_STATUSES)}",
        )

    existing = set(
        db.scalars(
            select(ImportItem.source_id).where(ImportItem.batch_id == batch_id)
        ).all()
    )

    added = skipped = 0
    for item in items:
        if item.source_id in existing:
            skipped += 1
            continue
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
    return ItemsResult(added=added, skipped=skipped)
