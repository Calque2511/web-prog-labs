import logging

from sqlalchemy.exc import IntegrityError

from app.errors import BusinessRuleError, ConflictError, NotFoundError
from app.infra import EmailQueue, UserCache
from app.models import Order, User
from app.repositories.users import UserRepository
from app.schemas import OrderCreate, OrderOut, Page, UserCreate, UserOut, UserPatch, UserReplace
from app.security import hash_password

logger = logging.getLogger("app.users")

FORBIDDEN_NAME_PARTS = ("admin", "root", "moderator")


class UserService:
    def __init__(
        self,
        repo: UserRepository,
        email_queue: EmailQueue,
        cache: UserCache | None = None,
        bcrypt_rounds: int = 12,
    ):
        self.repo = repo
        self.email_queue = email_queue
        self.cache = cache
        self.bcrypt_rounds = bcrypt_rounds

    @staticmethod
    def _check_name_allowed(name: str) -> None:
        lowered = name.lower()
        if any(part in lowered for part in FORBIDDEN_NAME_PARTS):
            raise BusinessRuleError(
                "Name is not allowed", [{"field": "name", "message": "reserved word in name"}]
            )

    @staticmethod
    def _check_password_not_login(email: str, password: str) -> None:
        local = email.split("@")[0].lower()
        if password.lower() in (email.lower(), local):
            raise BusinessRuleError(
                "Password is too weak", [{"field": "password", "message": "password must differ from login"}]
            )

    def _require(self, user_id: int) -> User:
        user = self.repo.get(user_id)
        if user is None:
            raise NotFoundError(f"User {user_id} not found")
        return user

    def _commit_unique(self, email: str) -> None:
        # между проверкой email_exists и commit может вклиниться другой запрос
        try:
            self.repo.commit()
        except IntegrityError as exc:
            self.repo.rollback()
            raise ConflictError(
                "Email already registered", [{"field": "email", "message": f"{email} is taken"}]
            ) from exc

    def create_user(self, data: UserCreate, role: str = "user") -> UserOut:
        self._check_name_allowed(data.name)
        self._check_password_not_login(data.email, data.password)
        if self.repo.email_exists(data.email):
            raise ConflictError("Email already registered", [{"field": "email", "message": "already exists"}])
        user = User(
            name=data.name,
            email=data.email.lower(),
            age=data.age,
            password_hash=hash_password(data.password, self.bcrypt_rounds),
            role=role,
        )
        self.repo.add(user)
        self._commit_unique(data.email)
        self.email_queue.enqueue(user.email, "Welcome!")
        logger.info("user created", extra={"context": {"user_id": user.id}})
        return UserOut.model_validate(user)

    def get_user(self, user_id: int) -> UserOut:
        if self.cache and (cached := self.cache.get(user_id)):
            return cached
        out = UserOut.model_validate(self._require(user_id))
        if self.cache:
            self.cache.set(out)
        return out

    def list_users(self, page: int, size: int, **filters) -> Page:
        users, total = self.repo.search(page, size, **filters)
        return Page(items=[UserOut.model_validate(u) for u in users], total=total, page=page, size=size)

    def replace_user(self, user_id: int, data: UserReplace) -> UserOut:
        user = self._require(user_id)
        self._check_name_allowed(data.name)
        return self._apply(user, data.model_dump())

    def patch_user(self, user_id: int, data: UserPatch) -> UserOut:
        user = self._require(user_id)
        changes = data.model_dump(exclude_unset=True)
        if "name" in changes:
            self._check_name_allowed(changes["name"])
        return self._apply(user, changes)

    def _apply(self, user: User, changes: dict) -> UserOut:
        new_email = changes.get("email")
        if new_email and self.repo.email_exists(new_email, exclude_id=user.id):
            raise ConflictError("Email already registered", [{"field": "email", "message": "already exists"}])
        for key, value in changes.items():
            setattr(user, key, value.lower() if key == "email" else value)
        self._commit_unique(user.email)
        if self.cache:
            self.cache.invalidate(user.id)
        return UserOut.model_validate(user)

    def delete_user(self, user_id: int) -> None:
        user = self._require(user_id)
        self.repo.delete(user)
        self.repo.commit()
        if self.cache:
            self.cache.invalidate(user_id)
        logger.info("user deleted", extra={"context": {"user_id": user_id}})

    def list_orders(self, user_id: int) -> list[OrderOut]:
        self._require(user_id)
        return [OrderOut.model_validate(o) for o in self.repo.list_orders(user_id)]

    def create_order(self, user_id: int, data: OrderCreate) -> OrderOut:
        self._require(user_id)
        order = self.repo.add_order(Order(user_id=user_id, product=data.product, total=data.total))
        self.repo.commit()
        return OrderOut.model_validate(order)
