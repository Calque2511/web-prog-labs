import logging
from collections.abc import Callable, Iterator

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.errors import AuthenticationError, PermissionDeniedError
from app.infra import EmailQueue, UserCache
from app.models import User
from app.repositories.users import UserRepository
from app.security import TokenClaims
from app.services.auth import AuthService
from app.services.users import UserService

logger = logging.getLogger("app.security")


def get_session(request: Request) -> Iterator[Session]:
    session = request.app.state.session_factory()
    try:
        yield session
    finally:
        session.close()


def get_repo(session: Session = Depends(get_session)) -> UserRepository:
    return UserRepository(session)


def get_user_service(request: Request, repo: UserRepository = Depends(get_repo)) -> UserService:
    state = request.app.state
    return UserService(
        repo,
        EmailQueue(state.redis),
        UserCache(state.redis, state.settings.user_cache_ttl_seconds),
        state.settings.bcrypt_rounds,
    )


def get_auth_service(request: Request, repo: UserRepository = Depends(get_repo)) -> AuthService:
    return AuthService(repo, request.app.state.tokens, request.app.state.redis)


bearer_scheme = HTTPBearer(auto_error=False, description="access_token из POST /auth/login")


def get_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    auth: AuthService = Depends(get_auth_service),
) -> tuple[User, TokenClaims]:
    if credentials is None:
        raise AuthenticationError("Authentication required")
    return auth.authenticate(credentials.credentials)


def get_current_user(ctx: tuple[User, TokenClaims] = Depends(get_auth)) -> User:
    return ctx[0]


def require_role(*roles: str) -> Callable[[User], User]:
    def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            logger.warning("role check failed", extra={"context": {"user_id": user.id, "need": roles}})
            raise PermissionDeniedError("Insufficient permissions")
        return user

    return checker


def ensure_owner_or_admin(current: User, owner_id: int) -> None:
    if current.id != owner_id and current.role != "admin":
        logger.warning(
            "unauthorized access attempt",
            extra={"context": {"user_id": current.id, "target_user_id": owner_id}},
        )
        raise PermissionDeniedError("Access denied")
