import logging
import time

import redis

from app.errors import AuthenticationError, TooManyRequestsError
from app.models import User
from app.repositories.users import UserRepository
from app.schemas import TokenPair
from app.security import TokenClaims, TokenService, verify_password

logger = logging.getLogger("app.auth")


class AuthService:
    def __init__(self, repo: UserRepository, tokens: TokenService, store: redis.Redis):
        self.repo = repo
        self.tokens = tokens
        self.store = store

    MAX_FAILED_LOGINS = 5
    LOCKOUT_SECONDS = 900

    def login(self, email: str, password: str) -> TokenPair:
        fail_key = f"loginfail:{email.lower()}"
        if int(self.store.get(fail_key) or 0) >= self.MAX_FAILED_LOGINS:
            logger.warning("login locked", extra={"context": {"email": email}})
            raise TooManyRequestsError("Too many failed login attempts, try again later")
        user = self.repo.get_by_email(email)
        if not verify_password(password, user.password_hash if user else None):
            # ответ один и тот же, чтобы нельзя было узнать, есть ли такой email
            if self.store.incr(fail_key) == 1:
                self.store.expire(fail_key, self.LOCKOUT_SECONDS)
            logger.warning("login failed", extra={"context": {"email": email}})
            raise AuthenticationError("Invalid email or password")
        self.store.delete(fail_key)
        logger.info("login ok", extra={"context": {"user_id": user.id}})
        return self._issue_pair(user)

    def refresh(self, refresh_token: str) -> TokenPair:
        claims = self.tokens.decode(refresh_token, "refresh")
        # refresh одноразовый: если ключа уже нет, токен использован или отозван
        if self.store.delete(f"refresh:{claims.jti}") == 0:
            logger.warning("refresh token reuse", extra={"context": {"user_id": claims.user_id}})
            raise AuthenticationError("Refresh token revoked")
        user = self.repo.get(claims.user_id)
        if user is None:
            raise AuthenticationError("User no longer exists")
        return self._issue_pair(user)

    def logout(self, access: TokenClaims, refresh_token: str | None) -> None:
        self._blacklist(access)
        if refresh_token:
            try:
                refresh = self.tokens.decode(refresh_token, "refresh")
                self.store.delete(f"refresh:{refresh.jti}")
            except AuthenticationError:
                pass  # токен уже недействителен

    def authenticate(self, access_token: str) -> tuple[User, TokenClaims]:
        claims = self.tokens.decode(access_token, "access")
        if self.store.exists(f"blacklist:{claims.jti}"):
            raise AuthenticationError("Token revoked")
        user = self.repo.get(claims.user_id)
        if user is None:
            raise AuthenticationError("User no longer exists")
        return user, claims

    def _blacklist(self, claims: TokenClaims) -> None:
        ttl = max(claims.exp - int(time.time()), 1)
        self.store.set(f"blacklist:{claims.jti}", "1", ex=ttl)

    def _issue_pair(self, user: User) -> TokenPair:
        access, _ = self.tokens.issue(user.id, user.email, user.role, "access")
        refresh, rclaims = self.tokens.issue(user.id, user.email, user.role, "refresh")
        self.store.set(f"refresh:{rclaims.jti}", str(user.id), ex=self.tokens.refresh_ttl_s)
        return TokenPair(access_token=access, refresh_token=refresh, expires_in=self.tokens.access_ttl_s)
