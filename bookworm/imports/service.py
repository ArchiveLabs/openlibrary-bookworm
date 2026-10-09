from typing import Any
from uuid import UUID

from fastapi_pagination.ext.sqlmodel import paginate
from procrastinate.exceptions import JobAborted
from sqlalchemy import bindparam, case, func, literal, or_, update
from sqlmodel import Session, col, select

from bookworm.database import get_engine
from bookworm.exceptions import Conflict, InvalidInput, NotFound
from bookworm.imports.client import ImportResult
from bookworm.imports.constants import NON_RETRYABLE_CODES, error_context
from bookworm.imports.models import QUEUE_JOBS, ImportItem, ItemStatus, Job, SourceReservation
from bookworm.imports.schemas import ImportEnvelope, ItemSelection, JobPage, JobRead
from bookworm.imports.tasks import import_item
from bookworm.pagination import Page
from bookworm.projects.models import Project
from bookworm.utils import utcnow


def create_job(body: ImportEnvelope, session: Session, user_id: str) -> UUID:
    existing_sources: set[str] = set()
    if body.project_id is not None:
        # Hold the project lock until commit so concurrent uploads cannot reserve the same sources.
        project = session.exec(
            select(Project)
            .where(
                Project.id == body.project_id,
                Project.user_id == user_id,
                Project.archived_at.is_(None),
            )
            .with_for_update()
        ).first()
        if project is None:
            raise NotFound("Active project not found")

        incoming_sources = {
            source for record in body.data for source in record["source_records"] if source.strip()
        }
        existing_sources = set(
            session.exec(
                select(SourceReservation.source_record).where(
                    SourceReservation.project_id == body.project_id,
                    SourceReservation.source_record.in_(incoming_sources),
                )
            ).all()
        )

    job = Job(user_id=user_id, project_id=body.project_id)
    items, reservations = prepare_items(job, body.data, existing_sources)

    # Persist the job before its items; commit flushes the remaining rows.
    session.add(job)
    session.flush()
    session.add_all(items)
    session.add_all(reservations)
    return job.id


def prepare_items(
    job: Job, records: list[dict[str, Any]], existing_sources: set[str]
) -> tuple[list[ImportItem], list[SourceReservation]]:
    reserved = existing_sources.copy()
    items = []
    reservations = []

    for position, data in enumerate(records):
        sources = {source for source in data["source_records"] if source.strip()}
        duplicate = job.project_id is not None and bool(sources & reserved)
        item = ImportItem(
            job_id=job.id,
            position=position,
            data=data,
            error_context=error_context(
                "DUPLICATE_SOURCE", "A source identifier is already reserved in this project"
            )
            if duplicate
            else None,
        )
        items.append(item)

        if job.project_id is not None and not duplicate:
            reserved.update(sources)
            reservations.extend(
                SourceReservation(project_id=job.project_id, source_record=source, item_id=item.id)
                for source in sources
            )

    return items, reservations


def accessible_job(
    session: Session, job_id: UUID, user_id: str, *, can_approve: bool = False
) -> Job:
    query = select(Job).where(Job.id == job_id)
    if not can_approve:
        query = query.where(Job.user_id == user_id)
    job = session.exec(query).first()
    if job is None:
        raise NotFound("Job not found")
    return job


def list_jobs(session: Session, user_id: str, *, can_approve: bool = False) -> Page[JobRead]:
    query = select(Job)
    if not can_approve:
        query = query.where(Job.user_id == user_id)
    return paginate(session, query.order_by(Job.created_at.desc(), Job.id.desc()))


def item_status():
    return case(
        (
            ImportItem.procrastinate_job_id.is_(None),
            case(
                (ImportItem.error_context.is_not(None), ItemStatus.failed.value),
                else_=ItemStatus.pending_approval.value,
            ),
        ),
        (QUEUE_JOBS.c.status == "todo", ItemStatus.queued.value),
        (QUEUE_JOBS.c.status == "doing", ItemStatus.processing.value),
        (QUEUE_JOBS.c.status == "succeeded", ItemStatus.completed.value),
        else_=ItemStatus.failed.value,
    )


def get_job(job: Job, session: Session, status: ItemStatus | None = None) -> JobPage:
    state = item_status()
    query = (
        select(ImportItem, state.label("status"))
        .outerjoin(QUEUE_JOBS, ImportItem.procrastinate_job_id == QUEUE_JOBS.c.id)
        .where(ImportItem.job_id == job.id)
    )
    counts = {s.value: 0 for s in ItemStatus}
    for value, count in session.exec(
        select(state, func.count())
        .select_from(ImportItem)
        .outerjoin(QUEUE_JOBS, ImportItem.procrastinate_job_id == QUEUE_JOBS.c.id)
        .where(ImportItem.job_id == job.id)
        .group_by(state)
    ):
        counts[value] = count
    if status is not None:
        query = query.where(state == status.value)
    return paginate(
        session,
        query.order_by(ImportItem.position),
        transformer=lambda rows: [{**item.model_dump(), "status": value} for item, value in rows],
        count_query=select(literal(sum(counts.values()))),
        additional_data={"job": JobRead.model_validate(job), "counts": counts},
    )


def selected_items(session: Session, job_id: UUID, selection: ItemSelection):
    query = select(ImportItem.id).where(ImportItem.job_id == job_id)
    if selection.item_ids is not None:
        query = query.where(ImportItem.id.in_(selection.item_ids))
        if len(session.exec(query).all()) != len(selection.item_ids):
            raise InvalidInput("All selected items must belong to this job")
    return query


def enqueue_items(session: Session, ids: list[UUID]) -> None:
    if not ids:
        return

    # Link tasks in the approval/retry transaction so workers only see committed items.
    connection = session.connection().connection.driver_connection
    queue_ids = import_item.configure(connection=connection).batch_defer(
        *({"item_id": str(item_id)} for item_id in ids)
    )

    session.connection().execute(
        ImportItem.__table__.update()
        .where(ImportItem.id == bindparam("item_id"))
        .values(procrastinate_job_id=bindparam("queue_id")),
        [
            {"item_id": item_id, "queue_id": queue_id}
            for item_id, queue_id in zip(ids, queue_ids, strict=True)
        ],
    )


def approve(job: Job, body: ItemSelection, session: Session, user_id: str) -> int:
    selected = selected_items(session, job.id, body)
    now = utcnow()
    result = session.exec(
        update(ImportItem)
        .where(
            ImportItem.id.in_(selected),
            ImportItem.approved_at.is_(None),
            ImportItem.error_context.is_(None),
            ImportItem.procrastinate_job_id.is_(None),
        )
        .values(
            approved_by=user_id,
            approved_at=now,
            updated_at=now,
        )
        .returning(ImportItem.id)
    )
    ids = list(result.scalars())
    enqueue_items(session, ids)
    session.commit()
    return len(ids)


def retry(job: Job, body: ItemSelection, session: Session) -> int:
    selected = selected_items(session, job.id, body)
    rows = session.exec(
        select(ImportItem)
        .where(ImportItem.id.in_(selected))
        .order_by(ImportItem.id)
        .with_for_update()
    ).all()
    code = ImportItem.error_context["error_code"].astext
    ids = session.exec(
        select(ImportItem.id)
        .join(QUEUE_JOBS, ImportItem.procrastinate_job_id == QUEUE_JOBS.c.id)
        .where(
            ImportItem.id.in_([row.id for row in rows]),
            QUEUE_JOBS.c.status.in_(["failed", "aborted"]),
            ImportItem.approved_at.is_not(None),
            or_(code.is_(None), code.not_in(NON_RETRYABLE_CODES)),
        )
    ).all()
    if body.item_ids is not None and len(ids) != len(rows):
        raise Conflict("Some selected items cannot be retried")
    enqueue_items(session, ids)
    if ids:
        session.exec(update(ImportItem).where(ImportItem.id.in_(ids)).values(updated_at=utcnow()))
    session.commit()
    return len(ids)


def get_import_data(item_id: UUID, queue_job_id: int) -> dict[str, Any] | None:
    with Session(get_engine()) as session:
        return session.exec(
            select(col(ImportItem.data)).where(
                ImportItem.id == item_id,
                ImportItem.procrastinate_job_id == queue_job_id,
                ImportItem.approved_at.is_not(None),
            )
        ).first()


def finish_import(item_id: UUID, queue_job_id: int, result: ImportResult):
    success = result.success and not result.unknown
    context = (
        None
        if success
        else error_context(
            "OUTCOME_UNKNOWN" if result.unknown else (result.error_code or "IMPORT_FAILED"),
            result.description or "Import failed",
        )
    )
    with Session(get_engine()) as session, session.begin():
        session.exec(
            update(ImportItem)
            .where(ImportItem.id == item_id, ImportItem.procrastinate_job_id == queue_job_id)
            .values(error_context=context, updated_at=utcnow())
        )
    if not success:
        if result.retryable and not result.unknown:
            raise RuntimeError(result.description or "Import failed")
        raise JobAborted(result.description or "Import failed")
