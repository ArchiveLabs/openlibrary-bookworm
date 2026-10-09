from typing import Annotated
from uuid import UUID

from fastapi import Depends

from bookworm.dependencies import ApproverDep, CallerDep, SessionDep
from bookworm.imports import service
from bookworm.imports.models import Job


def accessible_job(job_id: UUID, session: SessionDep, caller: CallerDep) -> Job:
    return service.accessible_job(session, job_id, caller.user_id, can_approve=caller.can_approve)


def approver_job(job_id: UUID, session: SessionDep, caller: ApproverDep) -> Job:
    return service.accessible_job(session, job_id, caller.user_id, can_approve=True)


JobDep = Annotated[Job, Depends(accessible_job)]
ApproverJobDep = Annotated[Job, Depends(approver_job)]
