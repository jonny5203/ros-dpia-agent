"""RFC 9457 (`application/problem+json`) error responses.

Every error the API returns is a problem document with a stable `type` URN so
the SPA can branch on it. The generic handler logs the real traceback server-
side but never leaks internals to the client.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

PROBLEM_MEDIA_TYPE = "application/problem+json"

_TITLES: dict[int, str] = {
    400: "Bad Request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    409: "Conflict",
    422: "Validation Failed",
    500: "Internal Server Error",
    502: "Bad Gateway",
    503: "Service Unavailable",
}


def _title_for(status: int) -> str:
    return _TITLES.get(status, "Error")


def problem(
    status: int,
    detail: str,
    *,
    title: str | None = None,
    type_: str = "about:blank",
    **extra: Any,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "type": type_,
        "title": title or _title_for(status),
        "status": status,
        "detail": detail,
    }
    body.update(extra)
    return body


def _problem_response(status: int, payload: dict[str, Any]) -> JSONResponse:
    return JSONResponse(status_code=status, content=payload, media_type=PROBLEM_MEDIA_TYPE)


def _safe_errors(errors: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop the non-JSON-serializable `ctx` field pydantic attaches to some errors."""
    return [{k: v for k, v in err.items() if k != "ctx"} for err in errors]


def register_exception_handlers(app: FastAPI) -> None:
    # Register on Starlette's base HTTPException so missing-route 404s (raised by
    # Starlette) AND FastAPI-raised HTTPExceptions (a subclass) both map to
    # problem+json via MRO resolution.
    @app.exception_handler(StarletteHTTPException)
    async def _http_exc_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return _problem_response(exc.status_code, problem(exc.status_code, str(exc.detail)))

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        return _problem_response(
            422,
            problem(
                422,
                "One or more request parameters failed validation.",
                type_="urn:dpia:error:validation",
                errors=_safe_errors(exc.errors()),
            ),
        )

    @app.exception_handler(Exception)
    async def _unhandled_handler(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error: %s", exc)
        return _problem_response(500, problem(500, "An unexpected error occurred."))
