import logging
import re
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from prometheus_client import CollectorRegistry, Counter, Histogram

from app.errors import error_body
from app.logging_setup import request_id_var

logger = logging.getLogger("app.http")
REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9\-_]{8,64}$")

SECURITY_HEADERS = {
    "X-Frame-Options": "SAMEORIGIN",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer-when-downgrade",
    "X-XSS-Protection": "1; mode=block",
}
CSP = "default-src 'self'"
DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")


def install_middleware(app: FastAPI, registry: CollectorRegistry) -> None:
    requests_total = Counter(
        "http_requests_total", "Total requests", ["method", "endpoint", "status"], registry=registry
    )
    duration = Histogram("http_request_duration_seconds", "Request duration", ["endpoint"], registry=registry)
    errors_total = Counter("http_errors_total", "5xx responses", ["endpoint"], registry=registry)

    @app.middleware("http")
    async def observe(request: Request, call_next):
        # id запроса берём из заголовка, только если он безопасный, иначе генерируем свой
        incoming = request.headers.get("X-Request-ID", "")
        rid = incoming if REQUEST_ID_RE.match(incoming) else uuid.uuid4().hex
        token = request_id_var.set(rid)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("unhandled error")
            response = JSONResponse(error_body("internal_error", "Internal server error"), 500)
        finally:
            elapsed = time.perf_counter() - started
        route = request.scope.get("route")
        endpoint = getattr(route, "path", None)
        if endpoint is None:
            # у /docs и /openapi.json шаблона маршрута нет; остальное без шаблона считаем одним лейблом
            endpoint = request.url.path if request.url.path in DOCS_PATHS else "unmatched"
        requests_total.labels(request.method, endpoint, response.status_code).inc()
        duration.labels(endpoint).observe(elapsed)
        if response.status_code >= 500:
            errors_total.labels(endpoint).inc()
        response.headers["X-Request-ID"] = rid
        for key, value in SECURITY_HEADERS.items():
            response.headers[key] = value
        if not request.url.path.startswith(DOCS_PATHS):
            response.headers["Content-Security-Policy"] = CSP
        logger.info(
            f"{request.method} {request.url.path} -> {response.status_code} ({elapsed:.3f}s)",
            extra={
                "context": {
                    "query": str(request.query_params),
                    "ip": request.client.host if request.client else None,
                }
            },
        )
        request_id_var.reset(token)
        return response
