from fastapi import APIRouter, Response

from bookworm.dependencies import CallerDep, SessionDep
from bookworm.exceptions import error_responses
from bookworm.pagination import Page
from bookworm.projects import service
from bookworm.projects.dependencies import LockedProjectDep, OwnedProjectDep
from bookworm.projects.schemas import ProjectRead, ProjectWrite

router = APIRouter(prefix="/projects", tags=["Projects"])


@router.post("", status_code=201, summary="Create a project", responses=error_responses(409))
def create_project(body: ProjectWrite, session: SessionDep, caller: CallerDep) -> ProjectRead:
    return ProjectRead.model_validate(service.create_project(body, session, caller.user_id))


@router.get("", summary="List your projects", responses=error_responses(400))
def list_projects(
    session: SessionDep, caller: CallerDep, include_archived: bool = False
) -> Page[ProjectRead]:
    return service.list_projects(session, caller.user_id, include_archived)


@router.get("/{project_id}", summary="Get a project", responses=error_responses(404))
def get_project(project: OwnedProjectDep) -> ProjectRead:
    return ProjectRead.model_validate(project)


@router.patch("/{project_id}", summary="Rename a project", responses=error_responses(404, 409))
def rename_project(
    project: LockedProjectDep, body: ProjectWrite, session: SessionDep
) -> ProjectRead:
    return ProjectRead.model_validate(service.rename_project(project, body, session))


@router.delete(
    "/{project_id}", status_code=204, summary="Archive a project", responses=error_responses(404)
)
def archive_project(project: LockedProjectDep, session: SessionDep) -> Response:
    service.archive_project(project, session)
    return Response(status_code=204)
