"""Central error handling: custom exceptions and FastAPI exception handlers."""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)


class BusinessRuleError(Exception):
    """Business rule violation (HTTP 400)."""

    def __init__(self, message: str, field: str | None = None, details: Any = None):
        """Initialize with error message, optional field name, and details."""
        self.message = message
        self.field = field
        self.details = details
        super().__init__(self.message)


class NotFoundError(Exception):
    """Entity not found (HTTP 404)."""

    def __init__(self, entity: str, entity_id: Any = None):
        """Initialize with entity type name and optional entity ID."""
        self.entity = entity
        self.entity_id = entity_id
        self.message = f"{entity} not found."
        if entity_id:
            self.message = f"{entity} with ID '{entity_id}' not found."
        super().__init__(self.message)


class ConflictError(Exception):
    """Conflict error (HTTP 409). Raised on duplicates or FK-blocked deletions."""

    def __init__(self, message: str):
        """Initialize with a descriptive conflict message."""
        self.message = message
        super().__init__(self.message)


class InputValidationError(Exception):
    """Input validation error (HTTP 422). Raised for invalid data after trimming."""

    def __init__(self, message: str, field: str | None = None):
        """Initialize with error message and optional field name."""
        self.message = message
        self.field = field
        super().__init__(self.message)


class HierarchyValidationError(Exception):
    """Hierarchy validation error (HTTP 422). Raised for invalid parent assignments."""

    def __init__(self, message: str):
        """Initialize with a descriptive hierarchy validation message."""
        self.message = message
        super().__init__(self.message)


class CatchAllExceptionMiddleware(BaseHTTPMiddleware):
    """Middleware that catches unexpected errors and returns HTTP 500."""

    async def dispatch(self, request: Request, call_next):
        """Process the request and catch any unhandled exceptions."""
        try:
            response = await call_next(request)
            return response
        except Exception as exc:
            if not isinstance(
                exc,
                (
                    BusinessRuleError,
                    NotFoundError,
                    ConflictError,
                    InputValidationError,
                    HierarchyValidationError,
                ),
            ):
                logger.exception("Unexpected server error: %s", str(exc))
            return JSONResponse(
                status_code=500,
                content={"detail": "An unexpected server error occurred."},
            )


def register_exception_handlers(app: FastAPI) -> None:
    """Register all custom exception handlers on the FastAPI app."""

    @app.exception_handler(BusinessRuleError)
    async def business_rule_error_handler(
        request: Request, exc: BusinessRuleError
    ) -> JSONResponse:
        content: dict[str, Any] = {"detail": exc.message}
        if exc.field:
            content["field"] = exc.field
        if exc.details:
            content["details"] = exc.details
        return JSONResponse(status_code=400, content=content)

    @app.exception_handler(NotFoundError)
    async def not_found_error_handler(
        request: Request, exc: NotFoundError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"detail": exc.message},
        )

    @app.exception_handler(ConflictError)
    async def conflict_error_handler(
        request: Request, exc: ConflictError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={"detail": exc.message},
        )

    @app.exception_handler(InputValidationError)
    async def input_validation_error_handler(
        request: Request, exc: InputValidationError
    ) -> JSONResponse:
        content: dict[str, Any] = {"detail": exc.message}
        if exc.field:
            content["field"] = exc.field
        return JSONResponse(status_code=422, content=content)

    @app.exception_handler(HierarchyValidationError)
    async def hierarchy_validation_error_handler(
        request: Request, exc: HierarchyValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"detail": exc.message},
        )
