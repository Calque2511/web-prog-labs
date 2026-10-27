from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response, status

from app.deps import get_auth, get_auth_service, get_current_user, get_user_service
from app.models import User
from app.routers.users import ERRORS, drain_emails
from app.schemas import LoginRequest, RefreshRequest, TokenPair, UserCreate, UserOut
from app.security import TokenClaims
from app.services.auth import AuthService
from app.services.users import UserService

router = APIRouter(prefix="/auth", tags=["auth"])
Auth = Annotated[AuthService, Depends(get_auth_service)]


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED, responses=ERRORS)
def register(
    data: UserCreate,
    request: Request,
    tasks: BackgroundTasks,
    service: UserService = Depends(get_user_service),
) -> UserOut:
    user = service.create_user(data)
    tasks.add_task(drain_emails, request)
    return user


@router.post("/login", response_model=TokenPair, responses=ERRORS)
def login(data: LoginRequest, auth: Auth) -> TokenPair:
    return auth.login(data.email, data.password)


@router.post("/refresh", response_model=TokenPair, responses=ERRORS)
def refresh(data: RefreshRequest, auth: Auth) -> TokenPair:
    return auth.refresh(data.refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, responses=ERRORS)
def logout(
    auth: Auth,
    ctx: tuple[User, TokenClaims] = Depends(get_auth),
    body: RefreshRequest | None = None,
) -> Response:
    auth.logout(ctx[1], body.refresh_token if body else None)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/profile", response_model=UserOut, responses=ERRORS)
def profile(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(user)
