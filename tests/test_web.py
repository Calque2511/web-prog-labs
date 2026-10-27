import re

import pytest

pytestmark = pytest.mark.unit


def test_health_and_index(client):
    assert client.get("/health").json() == {"status": "ok"}
    assert "Hello" in client.get("/").text


def test_request_id_generated_propagated_and_sanitised(client):
    assert re.fullmatch(r"[0-9a-f]{32}", client.get("/health").headers["X-Request-ID"])
    assert (
        client.get("/health", headers={"X-Request-ID": "trace-12345678"}).headers["X-Request-ID"]
        == "trace-12345678"
    )
    evil = client.get("/health", headers={"X-Request-ID": "bad id\r\n"}).headers["X-Request-ID"]
    assert re.fullmatch(r"[0-9a-f]{32}", evil)


def test_error_body_contains_same_request_id_as_header(client):
    r = client.get("/nope", headers={"X-Request-ID": "trace-abcdefgh"})
    assert r.json()["error"]["request_id"] == r.headers["X-Request-ID"] == "trace-abcdefgh"


def test_security_headers_present_and_docs_not_blocked_by_csp(client):
    h = client.get("/health").headers
    assert h["X-Content-Type-Options"] == "nosniff" and h["X-Frame-Options"] == "SAMEORIGIN"
    assert h["Content-Security-Policy"] == "default-src 'self'"
    assert "Content-Security-Policy" not in client.get("/docs").headers


def test_cors_allows_configured_origin_only(client):
    ok = client.options(
        "/users", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST"}
    )
    assert ok.headers["access-control-allow-origin"] == "http://localhost:3000"
    bad = client.options(
        "/users", headers={"Origin": "https://evil.com", "Access-Control-Request-Method": "POST"}
    )
    assert "access-control-allow-origin" not in bad.headers


def test_metrics_count_requests_by_route_template(client):
    client.get("/health")
    client.get("/users/1")
    text = client.get("/metrics").text
    assert 'http_requests_total{endpoint="/health",method="GET",status="200"}' in text
    assert 'endpoint="/users/{user_id}"' in text
    assert "http_request_duration_seconds_bucket" in text


def test_unhandled_exception_returns_500_without_leaking_details(app):
    from fastapi.testclient import TestClient

    @app.get("/boom")
    def boom():
        raise RuntimeError("secret internal detail")

    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get("/boom")
    assert r.status_code == 500
    assert "secret" not in r.text and r.json()["error"]["code"] == "internal_error"
    assert 'status="500"' in c.get("/metrics").text and "http_errors_total" in c.get("/metrics").text


def test_cookie_lifecycle_with_security_attributes(client):
    r = client.post("/set-cookie", json={"name": "user_id", "value": "123", "days": 30})
    sc = r.headers["set-cookie"]
    assert "HttpOnly" in sc and "SameSite=lax" in sc and "Max-Age=2592000" in sc
    assert client.get("/get-cookie").json() == {"cookies": {"user_id": "123"}}
    client.post("/delete-cookie", json={"name": "user_id", "value": ""})
    assert client.get("/get-cookie").json() == {"cookies": {}}


def test_session_cookie_has_no_max_age_and_name_is_validated(client):
    sc = client.post("/set-cookie", json={"name": "s", "value": "1"}).headers["set-cookie"]
    assert "Max-Age" not in sc
    assert client.post("/set-cookie", json={"name": "bad name;", "value": "1"}).status_code == 400


def _form_token(client) -> str:
    html = client.get("/form").text
    return re.search(r'value="([^"]+)"', html).group(1)


def test_form_submit_with_valid_csrf_and_xss_escaped(client):
    token = _form_token(client)
    r = client.post("/submit", data={"message": "<script>alert(1)</script>", "csrf_token": token})
    assert r.status_code == 200
    assert "<script>" not in r.text and "&lt;script&gt;" in r.text


def test_form_submit_rejects_missing_wrong_and_foreign_origin(client):
    token = _form_token(client)
    assert client.post("/submit", data={"message": "x", "csrf_token": "wrong"}).status_code == 403
    assert (
        client.post(
            "/submit", data={"message": "x", "csrf_token": token}, headers={"Origin": "https://evil.com"}
        ).status_code
        == 403
    )
    client.cookies.clear()
    assert client.post("/submit", data={"message": "x", "csrf_token": token}).status_code == 403
    assert "SameSite=strict" in client.get("/form").headers["set-cookie"]


def test_settings_requires_auth_and_csrf_header(client, headers):
    assert client.get("/settings").status_code == 401
    token = client.get("/settings", headers=headers).json()["csrf_token"]
    assert client.post("/settings", headers=headers, json={"theme": "dark"}).status_code == 403
    r = client.post("/settings", headers={**headers, "X-CSRF-Token": token}, json={"theme": "dark"})
    assert r.status_code == 200 and r.json() == {"saved": True, "keys": ["theme"]}


def test_openapi_declares_bearer_auth_for_protected_endpoints(client):
    spec = client.get("/openapi.json").json()
    assert spec["components"]["securitySchemes"]["HTTPBearer"]["scheme"] == "bearer"
    assert spec["paths"]["/auth/profile"]["get"]["security"] == [{"HTTPBearer": []}]
    assert spec["paths"]["/users"]["get"]["security"] == [{"HTTPBearer": []}]
    assert "security" not in spec["paths"]["/auth/login"]["post"]


def test_docs_requests_are_not_counted_as_unmatched(client):
    client.get("/openapi.json")
    client.get("/nope")
    text = client.get("/metrics").text
    assert 'endpoint="/openapi.json"' in text
    assert 'endpoint="unmatched",method="GET",status="200"' not in text
    assert 'endpoint="unmatched",method="GET",status="404"' in text
