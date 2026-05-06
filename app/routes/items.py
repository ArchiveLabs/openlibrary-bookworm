from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ImportItem, ItemResponse, ItemStatusPatch, VALID_STATUSES

router = APIRouter(tags=["items"])


@router.get("/items/pending", response_model=list[ItemResponse])
def get_pending_items(
    limit: int = Query(default=1000, le=5000),
    db: Session = Depends(get_db),
) -> list[ImportItem]:
    """Oldest-first pending items — called by ImportBot to drain the queue."""
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
    """Called by ImportBot to report the outcome of processing an item."""
    item = db.get(ImportItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    if body.status not in VALID_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid status '{body.status}'. Must be one of {sorted(VALID_STATUSES)}",
        )

    item.status = body.status
    item.error = body.error
    item.ol_key = body.ol_key
    if body.status in {"created", "modified", "found", "failed"}:
        item.import_time = datetime.now(timezone.utc)

    db.commit()
    db.refresh(item)
    return item
