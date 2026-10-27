import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.logging_setup import request_id_var

logger = logging.getLogger("app.errors")


class AppError(Exception):
    status_code = 500
    code = "internal_error"

    def __init__(self, message: str, details: list[dict] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or []


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class BusinessRuleError(AppError):
    status_code = 422
    code = "business_rule_violation"


class AuthenticationError(AppError):
    status_code = 401
    code = "unauthorized"


class TooManyRequestsError(AppError):
    status_code = 429
    code = "too_many_requests"


class PermissionDeniedError(AppError):
    status_code = 403
    code = "forbidden"


def error_body(code: str, message: str, details: list[dict] | None = None) -> dict:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or [],
            "request_id": request_id_var.get(),
        }
    }


def _field_name(loc: tuple) -> str:
    parts = [str(p) for p in loc if p not in ("body", "query", "path")]
    return ".".join(parts) or "body"


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
        return JSONResponse(error_body(exc.code, exc.message, exc.details), exc.status_code, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def handle_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"field": _field_name(e["loc"]), "message": e["msg"], "type": e["type"]} for e in exc.errors()
        ]
        logger.warning("validation failed", extra={"context": {"errors": details}})
        return JSONResponse(error_body("validation_error", "Invalid request data", details), 400)

    @app.exception_handler(StarletteHTTPException)
    async def handle_http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
        return JSONResponse(error_body(code, str(exc.detail)), exc.status_code)

    @app.exception_handler(Exception)
    async def handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        # детали только в лог, клиенту отдаём общее сообщение
        logger.exception("unhandled error", exc_info=exc)
        return JSONResponse(error_body("internal_error", "Internal server error"), 500)
