"""Pydantic request and response schemas for the API."""

from pydantic import BaseModel, ConfigDict


class ResponseModel(BaseModel):
    """Describe serialized defaults as present, while retaining nullable values.

    FastAPI includes response defaults. Marking them optional in OpenAPI makes
    generated clients handle omissions that the server does not produce. Input
    schemas keep their separate validation/default semantics.
    """

    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )
