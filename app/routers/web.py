import html
import logging
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Form, Header, Request, Response
from fastapi.responses import HTMLResponse, PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.deps import get_current_user, get_session
from app.errors import PermissionDeniedError
from app.models import User

logger = logging.getLogger("app.web")
router = APIRouter(tags=["web"])
COOKIE_NAME_RE = r"^[A-Za-z0-9_\-]{1,64}$"


@router.get("/health")
def health(request: Request, session=Depends(get_session)) -> dict:
    session.execute(text("SELECT 1"))
    request.app.state.redis.ping()
    return {"status": "ok"}


@router.get("/metrics", include_in_schema=False)
def metrics(request: Request) -> Response:
    return Response(generate_latest(request.app.state.metrics_registry), media_type=CONTENT_TYPE_LATEST)


class CookieIn(BaseModel):
    name: str = Field(pattern=COOKIE_NAME_RE)
    value: str = Field(max_length=200)
    days: int | None = Field(default=None, ge=0, le=365, description="None/0 — сессионная cookie")


@router.post("/set-cookie")
def set_cookie(data: CookieIn, request: Request, response: Response) -> dict:
    response.set_cookie(
        data.name,
        data.value,
        max_age=data.days * 86400 if data.days else None,
        httponly=True,
        secure=request.app.state.settings.cookie_secure,
        samesite="lax",
    )
    logger.info("cookie set", extra={"context": {"name": data.name, "days": data.days}})
    return {"set": data.name}


@router.get("/get-cookie")
def get_cookie(request: Request) -> dict:
    logger.info("cookies read", extra={"context": {"names": list(request.cookies)}})
    return {"cookies": dict(request.cookies)}


@router.post("/delete-cookie")
def delete_cookie(data: CookieIn, response: Response) -> dict:
    response.delete_cookie(data.name)
    logger.info("cookie deleted", extra={"context": {"name": data.name}})
    return {"deleted": data.name}


def _origin_ok(request: Request, origin: str | None) -> bool:
    if not origin:
        return True  # curl и подобные клиенты Origin не шлют
    allowed = {f"{request.url.scheme}://{request.url.netloc}", *request.app.state.settings.cors_origin_list}
    return origin in allowed


@router.get("/form", response_class=HTMLResponse)
def form(request: Request, response: Response) -> HTMLResponse:
    token = request.app.state.csrf.generate()
    page = HTMLResponse(
        '<form action="/submit" method="POST">'
        f'<input type="hidden" name="csrf_token" value="{html.escape(token)}">'
        '<input type="text" name="message"><button>Submit</button></form>'
    )
    page.set_cookie(
        "csrf_token", token, httponly=True, samesite="strict", secure=request.app.state.settings.cookie_secure
    )
    return page


@router.post("/submit", response_class=HTMLResponse)
def submit(
    request: Request,
    message: Annotated[str, Form(max_length=500)],
    csrf_token: Annotated[str, Form()],
    cookie_token: Annotated[str | None, Cookie(alias="csrf_token")] = None,
    origin: Annotated[str | None, Header()] = None,
) -> HTMLResponse:
    csrf = request.app.state.csrf
    if not _origin_ok(request, origin) or not csrf.validate(cookie_token, csrf_token):
        logger.warning("csrf check failed", extra={"context": {"origin": origin}})
        raise PermissionDeniedError("CSRF validation failed")
    return HTMLResponse(f"<p>Received: {html.escape(message)}</p>")


@router.get("/settings")
def settings_get(request: Request, response: Response, user: User = Depends(get_current_user)) -> dict:
    token = request.app.state.csrf.generate()
    response.set_cookie(
        "csrf_token", token, httponly=True, samesite="strict", secure=request.app.state.settings.cookie_secure
    )
    return {"email": user.email, "csrf_token": token}


@router.post("/settings")
def settings_post(
    request: Request,
    payload: dict,
    user: User = Depends(get_current_user),
    x_csrf_token: Annotated[str | None, Header()] = None,
    cookie_token: Annotated[str | None, Cookie(alias="csrf_token")] = None,
) -> dict:
    if not request.app.state.csrf.validate(cookie_token, x_csrf_token):
        logger.warning("csrf check failed", extra={"context": {"user_id": user.id}})
        raise PermissionDeniedError("CSRF validation failed")
    return {"saved": True, "keys": sorted(payload)}


@router.get("/", response_class=PlainTextResponse)
def index() -> str:
    return "Hello from webprog labs! See /docs"
