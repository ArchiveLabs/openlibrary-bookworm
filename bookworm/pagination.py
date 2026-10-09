from typing import TypeVar

from fastapi import Query
from fastapi_pagination.cursor import CursorPage
from fastapi_pagination.customization import CustomizedPage, UseParamsFields

T = TypeVar("T")
Page = CustomizedPage[CursorPage[T], UseParamsFields(size=Query(100, ge=1, le=1000))]
