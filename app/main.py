from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CollectorRegistry

from app.config import Settings, get_settings
from app.db import make_engine, make_session_factory
from app.errors import install_error_handlers
from app.infra import LogEmailSender, make_redis
from app.logging_setup import setup_logging
from app.middleware import install_middleware
from app.models import Base
from app.routers import auth, users, web
from app.security import CsrfProtector, TokenService


def create_app(settings: Settings | None = None, create_tables: bool = True) -> FastAPI:
    settings = settings or get_settings()
    setup_logging(settings.log_level)

    app = FastAPI(
        title="Webprog Labs API",
        version="1.0.0",
        description="Учебный REST API: пользователи, заказы, аутентификация (JWT).",
    )
    engine = make_engine(settings.database_url)
    if create_tables:
        Base.metadata.create_all(engine)

    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)
    app.state.redis = make_redis(settings.redis_url)
    app.state.email_sender = LogEmailSender()
    app.state.tokens = TokenService(
        settings.secret_key, settings.access_ttl_minutes * 60, settings.refresh_ttl_days * 86400
    )
    app.state.csrf = CsrfProtector(settings.secret_key)
    app.state.metrics_registry = CollectorRegistry()

    install_error_handlers(app)
    install_middleware(app, app.state.metrics_registry)
    # CORS добавляем последним: так он срабатывает первым и сам отвечает на preflight
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "Authorization", "X-CSRF-Token", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
    )

    app.include_router(web.router)
    app.include_router(auth.router)
    app.include_router(users.router)
    return app


def app_factory() -> FastAPI:
    return create_app()
