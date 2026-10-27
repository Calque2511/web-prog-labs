from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request, Response, status

from app.deps import ensure_owner_or_admin, get_current_user, get_user_service
from app.infra import EmailQueue, EmailWorker
from app.models import User
from app.schemas import OrderCreate, OrderOut, Page, UserCreate, UserOut, UserPatch, UserReplace
from app.services.users import UserService

router = APIRouter(tags=["users"])

ERRORS = {
    400: {"description": "Validation error"},
    401: {"description": "Authentication required"},
    403: {"description": "Forbidden"},
    404: {"description": "Not found"},
    409: {"description": "Conflict"},
    422: {"description": "Business rule violation"},
}
Service = Annotated[UserService, Depends(get_user_service)]
Current = Annotated[User, Depends(get_current_user)]


def drain_emails(request: Request) -> None:
    state = request.app.state
    EmailWorker(EmailQueue(state.redis), state.email_sender).drain()


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED, responses=ERRORS)
def create_user(
    data: UserCreate, request: Request, response: Response, tasks: BackgroundTasks, service: Service
) -> UserOut:
    user = service.create_user(data)
    response.headers["Location"] = f"/users/{user.id}"
    tasks.add_task(drain_emails, request)
    return user


@router.get("/users", response_model=Page, responses=ERRORS)
def list_users(
    _: Current,
    service: Service,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
    q: Annotated[str | None, Query(max_length=100, description="Поиск по имени/email")] = None,
    min_age: Annotated[int | None, Query(ge=0)] = None,
    max_age: Annotated[int | None, Query(le=150)] = None,
    sort: Literal["id", "-id", "name", "-name", "age", "-age", "created_at", "-created_at"] = "id",
) -> Page:
    return service.list_users(page, size, q=q, min_age=min_age, max_age=max_age, sort=sort)


@router.get("/users/{user_id}", response_model=UserOut, responses=ERRORS)
def get_user(user_id: int, _: Current, service: Service) -> UserOut:
    return service.get_user(user_id)


@router.put("/users/{user_id}", response_model=UserOut, responses=ERRORS)
def replace_user(user_id: int, data: UserReplace, current: Current, service: Service) -> UserOut:
    ensure_owner_or_admin(current, user_id)
    return service.replace_user(user_id, data)


@router.patch("/users/{user_id}", response_model=UserOut, responses=ERRORS)
def patch_user(user_id: int, data: UserPatch, current: Current, service: Service) -> UserOut:
    ensure_owner_or_admin(current, user_id)
    return service.patch_user(user_id, data)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT, responses=ERRORS)
def delete_user(user_id: int, current: Current, service: Service) -> Response:
    ensure_owner_or_admin(current, user_id)
    service.delete_user(user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/users/{user_id}/orders", response_model=list[OrderOut], responses=ERRORS)
def list_orders(user_id: int, current: Current, service: Service) -> list[OrderOut]:
    ensure_owner_or_admin(current, user_id)
    return service.list_orders(user_id)


@router.post(
    "/users/{user_id}/orders", response_model=OrderOut, status_code=status.HTTP_201_CREATED, responses=ERRORS
)
def create_order(user_id: int, data: OrderCreate, current: Current, service: Service) -> OrderOut:
    ensure_owner_or_admin(current, user_id)
    return service.create_order(user_id, data)
