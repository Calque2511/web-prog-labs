from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import Order, User

SORTABLE = {"id": User.id, "name": User.name, "age": User.age, "created_at": User.created_at}


class UserRepository:
    def __init__(self, session: Session):
        self.session = session

    def add(self, user: User) -> User:
        self.session.add(user)
        self.session.flush()
        return user

    def get(self, user_id: int) -> User | None:
        return self.session.get(User, user_id)

    def get_by_email(self, email: str) -> User | None:
        return self.session.scalar(select(User).where(func.lower(User.email) == email.lower()))

    def email_exists(self, email: str, exclude_id: int | None = None) -> bool:
        stmt = select(User.id).where(func.lower(User.email) == email.lower())
        if exclude_id is not None:
            stmt = stmt.where(User.id != exclude_id)
        return self.session.scalar(stmt) is not None

    def search(
        self,
        page: int,
        size: int,
        q: str | None = None,
        min_age: int | None = None,
        max_age: int | None = None,
        sort: str = "id",
    ) -> tuple[list[User], int]:
        stmt = select(User)
        if q:
            like = f"%{q.lower()}%"
            stmt = stmt.where(or_(func.lower(User.name).like(like), func.lower(User.email).like(like)))
        if min_age is not None:
            stmt = stmt.where(User.age >= min_age)
        if max_age is not None:
            stmt = stmt.where(User.age <= max_age)
        total = self.session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        desc = sort.startswith("-")
        column = SORTABLE[sort.lstrip("-")]
        stmt = stmt.order_by(column.desc() if desc else column.asc(), User.id)
        stmt = stmt.offset((page - 1) * size).limit(size)
        return list(self.session.scalars(stmt)), total

    def delete(self, user: User) -> None:
        self.session.delete(user)
        self.session.flush()

    def list_orders(self, user_id: int) -> list[Order]:
        return list(self.session.scalars(select(Order).where(Order.user_id == user_id).order_by(Order.id)))

    def add_order(self, order: Order) -> Order:
        self.session.add(order)
        self.session.flush()
        return order

    def commit(self) -> None:
        self.session.commit()

    def rollback(self) -> None:
        self.session.rollback()
