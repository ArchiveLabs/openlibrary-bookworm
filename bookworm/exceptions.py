"""Application failures, translated to HTTP responses by the app."""

from typing import Any

from pydantic import BaseModel


class ApplicationError(Exception):
    status_code: int

    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)


class NotFound(ApplicationError):
    status_code = 404


class Conflict(ApplicationError):
    status_code = 409


class InvalidInput(ApplicationError):
    status_code = 422


class ErrorResponse(BaseModel):
    detail: str | list[dict[str, Any]]


def error_responses(*codes: int) -> dict:
    return {code: {"model": ErrorResponse} for code in codes}
