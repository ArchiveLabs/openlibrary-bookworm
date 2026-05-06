from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_api_key
from app.database import get_db
from app.models.imports import ImportItem
from app.routes.batches import VALID_STATUSES

router = APIRouter(tags=["items"])


# ---------- Pydantic schemas ----------


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


# ---------- Routes ----------


@router.get("/items/pending", response_model=list[ItemResponse])
def get_pending_items(
    limit: int = Query(default=1000, le=5000),
    db: Session = Depends(get_db),
    _: str = Depends(require_api_key),
) -> list[ImportItem]:
    """Return up to `limit` pending items ordered by added_time (oldest first).
    Intended for ImportBot to drain the queue."""
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
    _: str = Depends(require_api_key),
) -> ImportItem:
    """Update item status after ImportBot processes it."""
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
