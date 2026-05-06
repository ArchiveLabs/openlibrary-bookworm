from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ImportItem, ItemResponse, ItemStatusPatch, VALID_STATUSES

router = APIRouter(tags=["items"])


@router.get("/items/pending", response_model=list[ItemResponse])
def get_pending_items(
    limit: int = Query(default=1000, ge=1, le=5000),
    db: Session = Depends(get_db),
) -> list[ImportItem]:
    """Return up to `limit` pending items, oldest first.

    NOTE: This endpoint does not claim/lock items. It assumes a single ImportBot
    worker. If multiple workers are added in the future, add a status transition
    to 'processing' here to prevent double-processing.
    """
    return list(
        db.scalars(
            select(ImportItem)
            .where(ImportItem.status == "pending")
            .order_by(ImportItem.added_time)
            .limit(limit)
        ).all()
    )


@router.patch("/items/{item_id}", response_model=ItemResponse)
def update_item_status(
    item_id: int,
    body: ItemStatusPatch,
    db: Session = Depends(get_db),
) -> ImportItem:
    """Called by ImportBot to report the outcome of processing an item.

    Only fields explicitly included in the request body are updated;
    omitting 'error' or 'ol_key' leaves their existing values unchanged.
    """
    item = db.get(ImportItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")

    update = body.model_dump(exclude_unset=True)
    new_status = update.get("status", item.status)
    if new_status not in VALID_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid status '{new_status}'. Must be one of {sorted(VALID_STATUSES)}",
        )

    for field, val in update.items():
        setattr(item, field, val)

    if item.status in {"created", "modified", "found", "failed"}:
        item.import_time = datetime.now(timezone.utc)

    db.commit()
    db.refresh(item)
    return item
