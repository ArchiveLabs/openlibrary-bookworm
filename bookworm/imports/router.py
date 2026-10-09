import logging

from fastapi import APIRouter, HTTPException
from sqlalchemy.exc import SQLAlchemyError

from bookworm.dependencies import ApproverDep, CallerDep, SessionDep
from bookworm.exceptions import error_responses
from bookworm.imports import service
from bookworm.imports.dependencies import ApproverJobDep, JobDep
from bookworm.imports.models import ItemStatus
from bookworm.imports.schemas import (
    ImportAccepted,
    ImportEnvelope,
    ItemSelection,
    JobPage,
    JobRead,
    UpdatedCount,
)
from bookworm.pagination import Page

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/imports", tags=["Imports"])


@router.post(
    "",
    status_code=202,
    summary="Submit records for review",
    responses=error_responses(404, 422, 503),
)
def create_import(body: ImportEnvelope, session: SessionDep, caller: CallerDep) -> ImportAccepted:
    try:
        with session.begin():
            job_id = service.create_job(body, session, caller.user_id)
    except SQLAlchemyError as exc:
        logger.exception("ingestion_failed user_id=%s", caller.user_id)
        raise HTTPException(503, "Ingestion could not be confirmed") from exc
    logger.info("job_accepted job_id=%s user_id=%s", job_id, caller.user_id)
    return ImportAccepted(job_id=job_id)


@router.get("", summary="List accessible import jobs", responses=error_responses(400))
def list_jobs(session: SessionDep, caller: CallerDep) -> Page[JobRead]:
    return service.list_jobs(session, caller.user_id, can_approve=caller.can_approve)


@router.get(
    "/{job_id}", summary="Get job records and status counts", responses=error_responses(400, 404)
)
def get_job(job: JobDep, session: SessionDep, status: ItemStatus | None = None) -> JobPage:
    return service.get_job(job, session, status)


@router.post(
    "/{job_id}/approve",
    summary="Approve selected records or an entire job",
    responses=error_responses(403, 404, 422),
)
def approve(
    job: ApproverJobDep, body: ItemSelection, session: SessionDep, caller: ApproverDep
) -> UpdatedCount:
    return UpdatedCount(updated=service.approve(job, body, session, caller.user_id))


@router.post(
    "/{job_id}/retry",
    summary="Retry eligible failed records",
    responses=error_responses(403, 404, 409, 422),
)
def retry(job: ApproverJobDep, body: ItemSelection, session: SessionDep) -> UpdatedCount:
    return UpdatedCount(updated=service.retry(job, body, session))
