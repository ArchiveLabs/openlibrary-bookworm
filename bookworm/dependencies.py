from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlmodel import Session

from bookworm.database import get_session
from bookworm.exceptions import InvalidInput

SessionDep = Annotated[Session, Depends(get_session)]


@dataclass(frozen=True)
class Caller:
    user_id: str
    can_approve: bool


async def get_caller(
    user_id: Annotated[str, Header(alias="X-User-Id", min_length=1, max_length=255)],
    can_approve: Annotated[bool, Header(alias="X-Can-Approve")] = False,
) -> Caller:
    if not user_id.strip():
        raise InvalidInput("X-User-Id must not be blank")
    return Caller(user_id, can_approve)


CallerDep = Annotated[Caller, Depends(get_caller)]


async def require_approver(caller: CallerDep) -> Caller:
    if not caller.can_approve:
        raise HTTPException(403, "Approval permission required")
    return caller


ApproverDep = Annotated[Caller, Depends(require_approver)]
