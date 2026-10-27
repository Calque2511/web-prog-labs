import hmac
import secrets
import time
import uuid
from dataclasses import dataclass
from hashlib import sha256

import bcrypt
import jwt

from app.errors import AuthenticationError

# хеш-пустышка для неизвестных email, чтобы время ответа не выдавало, что адреса нет в базе
_DUMMY_HASH = bcrypt.hashpw(b"dummy-password", bcrypt.gensalt(rounds=4)).decode()


def hash_password(password: str, rounds: int = 12) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=rounds)).decode()


def verify_password(password: str, hashed: str | None) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), (hashed or _DUMMY_HASH).encode()) and hashed is not None
    except ValueError:
        return False


@dataclass(frozen=True)
class TokenClaims:
    user_id: int
    email: str
    role: str
    jti: str
    type: str
    exp: int


class TokenService:
    ALGORITHM = "HS256"
    ISSUER = "webprog-labs"

    def __init__(self, secret: str, access_ttl_s: int, refresh_ttl_s: int):
        self.secret = secret
        self.access_ttl_s = access_ttl_s
        self.refresh_ttl_s = refresh_ttl_s

    def issue(self, user_id: int, email: str, role: str, token_type: str) -> tuple[str, TokenClaims]:
        ttl = self.access_ttl_s if token_type == "access" else self.refresh_ttl_s
        now = int(time.time())
        payload = {
            "user_id": user_id,
            "sub": str(user_id),
            "username": email,
            "role": role,
            "jti": uuid.uuid4().hex,
            "type": token_type,
            "iss": self.ISSUER,
            "iat": now,
            "exp": now + ttl,
        }
        token = jwt.encode(payload, self.secret, algorithm=self.ALGORITHM)
        return token, self._claims(payload)

    def decode(self, token: str, expected_type: str) -> TokenClaims:
        try:
            payload = jwt.decode(
                token,
                self.secret,
                algorithms=[self.ALGORITHM],
                issuer=self.ISSUER,
                options={"require": ["exp", "iat", "jti", "iss"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise AuthenticationError("Token expired") from exc
        except jwt.InvalidTokenError as exc:
            raise AuthenticationError("Invalid token") from exc
        if payload.get("type") != expected_type:
            raise AuthenticationError("Wrong token type")
        return self._claims(payload)

    @staticmethod
    def _claims(p: dict) -> TokenClaims:
        return TokenClaims(p["user_id"], p["username"], p["role"], p["jti"], p["type"], p["exp"])


class CsrfProtector:
    def __init__(self, secret: str):
        self._key = secret.encode()

    def generate(self) -> str:
        nonce = secrets.token_urlsafe(24)
        return f"{nonce}.{self._sign(nonce)}"

    def _sign(self, nonce: str) -> str:
        return hmac.new(self._key, nonce.encode(), sha256).hexdigest()

    def validate(self, cookie_token: str | None, submitted: str | None) -> bool:
        if not cookie_token or not submitted:
            return False
        if not hmac.compare_digest(cookie_token, submitted):
            return False
        nonce, _, sig = submitted.partition(".")
        return hmac.compare_digest(sig, self._sign(nonce))
