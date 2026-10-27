import re
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

NAME_RE = re.compile(r"^[^\W\d_]+(?:[ '\-][^\W\d_]+)*$")

Name = Annotated[str, Field(min_length=2, max_length=50, examples=["John Doe"])]
Age = Annotated[int, Field(ge=18, le=120)]
# bcrypt обрезает пароль до 72 байт
Password = Annotated[str, Field(min_length=8, max_length=72)]


def _check_name(value: str) -> str:
    value = value.strip()
    if not NAME_RE.match(value):
        raise ValueError("name must contain only letters, spaces, hyphens and apostrophes")
    return value


def _check_password(value: str) -> str:
    if not (any(c.isalpha() for c in value) and any(c.isdigit() for c in value)):
        raise ValueError("password must contain letters and digits")
    return value


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name
    email: EmailStr
    age: Age
    password: Password

    _name = field_validator("name")(_check_name)
    _password = field_validator("password")(_check_password)


class UserReplace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name
    email: EmailStr
    age: Age

    _name = field_validator("name")(_check_name)


class UserPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name | None = None
    email: EmailStr | None = None
    age: Age | None = None

    @field_validator("name", "email", "age", mode="before")
    @classmethod
    def _reject_null(cls, v):
        if v is None:
            raise ValueError("field cannot be null")
        return v

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        return _check_name(v)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: EmailStr
    age: int
    role: str
    created_at: datetime


class Page(BaseModel):
    items: list[UserOut]
    total: int
    page: int
    size: int


class OrderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product: Annotated[str, Field(min_length=1, max_length=100)]
    total: Annotated[float, Field(gt=0, le=10_000_000)]


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    product: str
    total: float
    created_at: datetime


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=72)


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
