from typing import Annotated
from uuid import UUID

from fastapi import Depends

from bookworm.dependencies import CallerDep, SessionDep
from bookworm.projects import service
from bookworm.projects.models import Project


def owned_project(project_id: UUID, session: SessionDep, caller: CallerDep) -> Project:
    return service.owned_project(session, project_id, caller.user_id)


def locked_owned_project(project_id: UUID, session: SessionDep, caller: CallerDep) -> Project:
    return service.owned_project(session, project_id, caller.user_id, lock=True)


OwnedProjectDep = Annotated[Project, Depends(owned_project)]
LockedProjectDep = Annotated[Project, Depends(locked_owned_project)]
