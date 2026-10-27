import pytest

from tests.conftest import user_payload

pytestmark = pytest.mark.unit


def test_create_user_returns_201_location_and_no_password(client):
    r = client.post("/users", json=user_payload())
    assert r.status_code == 201
    body = r.json()
    assert r.headers["Location"] == f"/users/{body['id']}"
    assert body["email"] == "john@example.com"
    assert "password" not in body and "password_hash" not in body


def test_create_user_invalid_data_returns_400_with_all_field_errors(client):
    r = client.post("/users", json={"name": "J", "email": "invalid-email", "age": 15, "password": "123"})
    assert r.status_code == 400
    err = r.json()["error"]
    assert err["code"] == "validation_error"
    assert {d["field"] for d in err["details"]} == {"name", "email", "age", "password"}
    assert err["request_id"] != "-"


@pytest.mark.parametrize(
    "field,value",
    [
        ("name", "A"),
        ("name", "A" * 51),
        ("name", "John3"),
        ("age", 17),
        ("age", 121),
        ("age", "abc"),
        ("password", "short1"),
        ("password", "onlyletters"),
        ("password", "12345678"),
        ("email", "no-at.example.com"),
        ("email", None),
    ],
)
def test_create_user_rejects_bad_field(client, field, value):
    r = client.post("/users", json=user_payload(**{field: value}))
    assert r.status_code == 400


@pytest.mark.parametrize("age", [18, 120])
def test_create_user_age_boundaries_accepted(client, age):
    assert client.post("/users", json=user_payload(age=age)).status_code == 201


def test_create_user_missing_field_and_extra_field(client):
    assert client.post("/users", json={"name": "John"}).status_code == 400
    assert client.post("/users", json=user_payload(role="admin")).status_code == 400


def test_create_user_malformed_json_returns_400(client):
    r = client.post("/users", content="{bad", headers={"Content-Type": "application/json"})
    assert r.status_code == 400


def test_duplicate_email_returns_409_case_insensitive(client, registered):
    r = client.post("/users", json=user_payload(email="JOHN@example.com"))
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "conflict"


def test_business_rules_return_422(client):
    assert client.post("/users", json=user_payload(name="Admin Root")).status_code == 422
    r = client.post("/users", json=user_payload(email="secret1x@example.com", password="secret1x"))
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "business_rule_violation"


def test_welcome_email_is_sent_in_background(client, app):
    client.post("/users", json=user_payload())
    assert app.state.email_sender.sent == [("john@example.com", "Welcome!")]


def test_endpoints_require_authentication(client, registered):
    for method, url in [("get", "/users"), ("get", "/users/1"), ("delete", "/users/1")]:
        r = getattr(client, method)(url)
        assert r.status_code == 401, url
        assert r.headers["WWW-Authenticate"] == "Bearer"


def test_get_user_and_not_found(client, headers, registered):
    assert client.get(f"/users/{registered['id']}", headers=headers).json()["name"] == "John Doe"
    r = client.get("/users/999", headers=headers)
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    assert client.get("/users/abc", headers=headers).status_code == 400


def test_list_pagination_filter_sort(client, headers):
    for i, (n, age) in enumerate([("Alice", 20), ("Bob", 35), ("Carol", 50)]):
        client.post("/users", json=user_payload(name=n, email=f"u{i}@example.com", age=age))
    r = client.get("/users", headers=headers, params={"size": 2, "page": 1, "sort": "-age"})
    body = r.json()
    assert body["total"] == 4 and [u["name"] for u in body["items"]] == ["Carol", "Bob"]
    r = client.get("/users", headers=headers, params={"min_age": 30, "max_age": 40})
    assert [u["name"] for u in r.json()["items"]] == ["John Doe", "Bob"]
    r = client.get("/users", headers=headers, params={"q": "alic"})
    assert r.json()["total"] == 1
    assert client.get("/users", headers=headers, params={"size": 1000}).status_code == 400
    assert client.get("/users", headers=headers, params={"sort": "password_hash"}).status_code == 400


def test_put_replaces_and_patch_updates_partially(client, headers, registered):
    uid = registered["id"]
    r = client.put(
        f"/users/{uid}", headers=headers, json={"name": "Johnny", "email": "j@example.com", "age": 31}
    )
    assert r.status_code == 200 and r.json()["email"] == "j@example.com"
    assert client.put(f"/users/{uid}", headers=headers, json={"name": "Johnny"}).status_code == 400
    r = client.patch(f"/users/{uid}", headers=headers, json={"age": 40})
    assert r.json()["age"] == 40 and r.json()["name"] == "Johnny"


def test_patch_to_taken_email_returns_409(client, headers, registered):
    client.post("/users", json=user_payload(email="other@example.com"))
    r = client.patch(f"/users/{registered['id']}", headers=headers, json={"email": "other@example.com"})
    assert r.status_code == 409


def test_delete_returns_204_then_404(client, admin_headers, registered):
    uid = registered["id"]
    assert client.delete(f"/users/{uid}", headers=admin_headers).status_code == 204
    assert client.get(f"/users/{uid}", headers=admin_headers).status_code == 404
    assert client.delete(f"/users/{uid}", headers=admin_headers).status_code == 404


def test_user_cannot_modify_another_user_but_admin_can(client, headers, admin_headers):
    other = client.post("/users", json=user_payload(email="other@example.com")).json()
    assert client.delete(f"/users/{other['id']}", headers=headers).status_code == 403
    assert client.patch(f"/users/{other['id']}", headers=headers, json={"age": 50}).status_code == 403
    assert client.patch(f"/users/{other['id']}", headers=admin_headers, json={"age": 50}).status_code == 200


def test_orders_create_list_and_cascade(client, headers, admin_headers, registered):
    uid = registered["id"]
    r = client.post(f"/users/{uid}/orders", headers=headers, json={"product": "Book", "total": 12.5})
    assert r.status_code == 201
    assert (
        client.post(f"/users/{uid}/orders", headers=headers, json={"product": "x", "total": -1}).status_code
        == 400
    )
    orders = client.get(f"/users/{uid}/orders", headers=headers).json()
    assert orders[0]["product"] == "Book" and orders[0]["total"] == 12.5
    assert client.get("/users/999/orders", headers=admin_headers).status_code == 404
    client.delete(f"/users/{uid}", headers=headers)
    assert client.get("/users", headers=admin_headers).json()["total"] == 1  # остался только admin


def test_unknown_route_and_method_use_error_format(client):
    r = client.get("/nope")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    assert client.put("/health").status_code == 405


def test_openapi_documents_users_endpoints(client):
    spec = client.get("/openapi.json").json()
    assert {"get", "post"} <= set(spec["paths"]["/users"])
    assert {"get", "put", "patch", "delete"} <= set(spec["paths"]["/users/{user_id}"])


@pytest.mark.parametrize("field", ["name", "email", "age"])
def test_patch_rejects_explicit_null(client, headers, registered, field):
    r = client.patch(f"/users/{registered['id']}", headers=headers, json={field: None})
    assert r.status_code == 400
    assert r.json()["error"]["details"][0]["field"] == field
