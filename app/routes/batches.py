from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    BatchCreate,
    BatchDetail,
    BatchResponse,
    ImportBatch,
    ImportItem,
    ItemIn,
    ItemValidationError,
    ItemsResult,
    VALID_STATUSES,
    validate_import_record,
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

    invalid_statuses = {i.status for i in items} - VALID_STATUSES
    if invalid_statuses:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid status values: {sorted(invalid_statuses)}",
        )

    added = skipped = 0
    errors: list[ItemValidationError] = []

    for idx, item in enumerate(items):
        messages = validate_import_record(item.data)
        if messages:
            errors.append(ItemValidationError(
                index=idx,
                source=item.source,
                value=item.value,
                messages=messages,
            ))
            continue

        # Use a savepoint per item so a duplicate-key violation only rolls back
        # that one insert, not the whole batch. This also handles concurrent
        # requests inserting the same (batch_id, source, value) without a 500.
        sp = db.begin_nested()
        try:
            db.add(ImportItem(
                batch_id=batch_id,
                source=item.source,
                value=item.value,
                data=item.data,
                submitter=item.submitter,
                status=item.status,
            ))
            sp.commit()
            added += 1
        except IntegrityError:
            sp.rollback()
            skipped += 1

    db.commit()
    return ItemsResult(added=added, skipped=skipped, errors=errors)
