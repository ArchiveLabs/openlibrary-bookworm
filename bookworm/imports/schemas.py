import json
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

from fastapi_pagination.customization import CustomizedPage, UseAdditionalFields
from jsonschema import Draft4Validator
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator
from referencing import Registry, Resource

from bookworm.imports.models import ItemStatus
from bookworm.pagination import Page

SCHEMA_DIR = Path(__file__).with_name("schemata")
SCHEMAS = {p.name: json.loads(p.read_text()) for p in SCHEMA_DIR.glob("*.json")}
REGISTRY = Registry().with_resources(
    (name, Resource.from_contents(schema)) for name, schema in SCHEMAS.items()
)
VALIDATOR = Draft4Validator(SCHEMAS["import.schema.json"], registry=REGISTRY)


def validate_record(value: Any) -> Any:
    failure = next(VALIDATOR.iter_errors(value), None)
    if failure is not None:
        path = ".".join(map(str, failure.absolute_path)) or "$"
        raise ValueError(f"{path}: {failure.message}"[:2000])
    return value


ImportRecord = Annotated[dict[str, Any], BeforeValidator(validate_record)]


class ImportEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: UUID | None = None
    data: list[ImportRecord] = Field(
        min_length=1,
        description="Records following the vendored Open Library import schema; invalid entries reject the request",
    )

    @model_validator(mode="after")
    def project_sources(self):
        if self.project_id is not None:
            for position, record in enumerate(self.data):
                sources = [s for s in record["source_records"] if s.strip()]
                if not sources or any(len(s.encode("utf-8")) > 1024 for s in sources):
                    raise ValueError(
                        f"data.{position}.source_records: project records need a nonblank source "
                        "identifier; identifiers must be at most 1024 UTF-8 bytes"
                    )
        return self


class ImportAccepted(BaseModel):
    job_id: UUID


class ItemSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    all: bool = False
    item_ids: list[UUID] | None = Field(default=None, min_length=1, max_length=1000)

    @model_validator(mode="after")
    def one_selection(self):
        if self.all == (self.item_ids is not None):
            raise ValueError("Supply either all=true or item_ids")
        if self.item_ids is not None and len(self.item_ids) != len(set(self.item_ids)):
            raise ValueError("item_ids must be unique")
        return self


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: str
    project_id: UUID | None
    created_at: datetime


class ErrorContext(BaseModel):
    error_code: str
    description: str


class ImportItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    job_id: UUID
    position: int
    data: Any
    status: ItemStatus
    error_context: ErrorContext | None
    approved_by: str | None
    approved_at: datetime | None
    created_at: datetime
    updated_at: datetime


class UpdatedCount(BaseModel):
    updated: int


JobPage = CustomizedPage[
    Page[ImportItemRead],
    UseAdditionalFields(job=JobRead, counts=dict[str, int]),
]
