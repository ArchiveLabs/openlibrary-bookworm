from uuid import UUID

from fastapi_pagination.ext.sqlmodel import paginate
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from bookworm.exceptions import Conflict, NotFound
from bookworm.pagination import Page
from bookworm.projects.models import Project
from bookworm.projects.schemas import ProjectRead, ProjectWrite
from bookworm.utils import utcnow


def owned_project(
    session: Session, project_id: UUID, user_id: str, *, lock: bool = False
) -> Project:
    query = select(Project).where(Project.id == project_id, Project.user_id == user_id)
    if lock:
        query = query.with_for_update()
    project = session.exec(query).first()
    if project is None:
        raise NotFound("Project not found")
    return project


def save_project(session: Session, project: Project) -> Project:
    session.add(project)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        if getattr(exc.orig, "sqlstate", None) != "23505":
            raise
        raise Conflict("A project with that name already exists") from exc
    session.refresh(project)
    return project


def create_project(body: ProjectWrite, session: Session, user_id: str) -> Project:
    return save_project(session, Project(user_id=user_id, name=body.name))


def list_projects(
    session: Session,
    user_id: str,
    include_archived: bool = False,
) -> Page[ProjectRead]:
    query = select(Project).where(Project.user_id == user_id)
    if not include_archived:
        query = query.where(Project.archived_at.is_(None))
    return paginate(session, query.order_by(Project.created_at.desc(), Project.id.desc()))


def rename_project(project: Project, body: ProjectWrite, session: Session) -> Project:
    if project.archived_at is not None:
        raise Conflict("Archived projects cannot be renamed")
    project.name = body.name
    project.updated_at = utcnow()
    return save_project(session, project)


def archive_project(project: Project, session: Session) -> None:
    if project.archived_at is None:
        project.archived_at = project.updated_at = utcnow()
        session.add(project)
        session.commit()
