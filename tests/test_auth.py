import time

import jwt
import pytest

from app.security import CsrfProtector, TokenService, hash_password, verify_password
from tests.conftest import PASSWORD, auth_header, login, user_payload

pytestmark = pytest.mark.unit


def test_register_login_profile_flow(client):
    assert client.post("/auth/register", json=user_payload()).status_code == 201
    tokens = login(client)
    assert tokens["token_type"] == "bearer" and tokens["expires_in"] == 900
    r = client.get("/auth/profile", headers=auth_header(tokens))
    assert r.status_code == 200 and r.json()["email"] == "john@example.com"


@pytest.mark.parametrize(
    "email,password", [("john@example.com", "Wrong12345"), ("nobody@example.com", PASSWORD)]
)
def test_login_failure_is_uniform_401(client, registered, email, password):
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 401
    assert r.json()["error"]["message"] == "Invalid email or password"


def test_protected_endpoint_rejects_missing_malformed_and_garbage_tokens(client):
    assert client.get("/auth/profile").status_code == 401
    assert client.get("/auth/profile", headers={"Authorization": "Basic abc"}).status_code == 401
    assert client.get("/auth/profile", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_expired_and_wrong_type_and_forged_tokens_rejected(client, app, registered, tokens):
    expired = TokenService(app.state.settings.secret_key, -10, 10).issue(
        registered["id"], "j@e.com", "user", "access"
    )[0]
    assert (
        client.get("/auth/profile", headers={"Authorization": f"Bearer {expired}"}).json()["error"]["message"]
        == "Token expired"
    )
    refresh_as_access = {"Authorization": f"Bearer {tokens['refresh_token']}"}
    assert client.get("/auth/profile", headers=refresh_as_access).status_code == 401
    forged = jwt.encode(
        {"user_id": 1, "type": "access"}, "other-secret-other-secret-other-1234", algorithm="HS256"
    )
    assert client.get("/auth/profile", headers={"Authorization": f"Bearer {forged}"}).status_code == 401
    none_alg = jwt.encode({"user_id": 1, "type": "access"}, key=None, algorithm="none")
    assert client.get("/auth/profile", headers={"Authorization": f"Bearer {none_alg}"}).status_code == 401


def test_refresh_rotates_and_old_refresh_token_is_rejected(client, tokens):
    r = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 200
    new = r.json()
    assert new["refresh_token"] != tokens["refresh_token"]
    assert client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]}).status_code == 401
    assert client.get("/auth/profile", headers=auth_header(new)).status_code == 200


def test_access_token_cannot_be_used_as_refresh(client, tokens):
    assert client.post("/auth/refresh", json={"refresh_token": tokens["access_token"]}).status_code == 401


def test_logout_blacklists_access_and_revokes_refresh(client, tokens):
    h = auth_header(tokens)
    r = client.post("/auth/logout", headers=h, json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 204
    assert client.get("/auth/profile", headers=h).json()["error"]["message"] == "Token revoked"
    assert client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]}).status_code == 401


def test_logout_without_body_still_blacklists_access(client, tokens):
    h = auth_header(tokens)
    assert client.post("/auth/logout", headers=h).status_code == 204
    assert client.get("/auth/profile", headers=h).status_code == 401


def test_token_for_deleted_user_is_rejected(client, tokens, registered, admin_headers):
    client.delete(f"/users/{registered['id']}", headers=admin_headers)
    assert client.get("/auth/profile", headers=auth_header(tokens)).status_code == 401


def test_password_hashing_is_salted_and_verifiable():
    h1, h2 = hash_password("Secret123", 4), hash_password("Secret123", 4)
    assert h1 != h2 and h1 != "Secret123"
    assert verify_password("Secret123", h1) and not verify_password("nope", h1)
    assert not verify_password("anything", None)
    assert not verify_password("x", "not-a-hash")


def test_csrf_token_validation_rules():
    csrf = CsrfProtector("k" * 32)
    t = csrf.generate()
    assert csrf.validate(t, t)
    assert not csrf.validate(t, csrf.generate())
    assert not csrf.validate(None, t) and not csrf.validate(t, None)
    forged = "abc.deadbeef"
    assert not csrf.validate(forged, forged)


def test_rbac_admin_only_dependency():
    from app.deps import require_role
    from app.errors import PermissionDeniedError
    from app.models import User

    checker = require_role("admin")
    with pytest.raises(PermissionDeniedError):
        checker(User(id=1, role="user"))
    assert checker(User(id=2, role="admin")).id == 2


def test_token_ttl_matches_spec(app):
    tokens = app.state.tokens
    _, access = tokens.issue(1, "a@b.c", "user", "access")
    _, refresh = tokens.issue(1, "a@b.c", "user", "refresh")
    now = time.time()
    assert 14 * 60 < access.exp - now <= 15 * 60
    assert 6.9 * 86400 < refresh.exp - now <= 7 * 86400


def test_login_is_locked_after_five_failures_and_reset_on_success(client, registered):
    bad = {"email": "john@example.com", "password": "Wrong12345"}
    for _ in range(4):
        assert client.post("/auth/login", json=bad).status_code == 401
    assert login(client)  # успешный вход сбрасывает счётчик
    for _ in range(5):
        assert client.post("/auth/login", json=bad).status_code == 401
    r = client.post("/auth/login", json=bad)
    assert r.status_code == 429 and r.json()["error"]["code"] == "too_many_requests"
    # даже верный пароль заблокирован, пока действует блокировка
    assert client.post("/auth/login", json={**bad, "password": PASSWORD}).status_code == 429


def test_lockout_applies_to_unknown_emails_too(client):
    for _ in range(5):
        client.post("/auth/login", json={"email": "ghost@example.com", "password": "Whatever123"})
    assert (
        client.post("/auth/login", json={"email": "ghost@example.com", "password": "Whatever123"}).status_code
        == 429
    )
