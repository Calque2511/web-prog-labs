import pytest

from app.examples import calculate_discount, divide, validate_email

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "email,expected",
    [
        ("a@b.com", True),
        ("no-at.com", False),
        ("a@@b.com", False),
        ("@b.com", False),
        ("a@", False),
        ("a@nodot", False),
        ("", False),
    ],
)
def test_validate_email(email, expected):
    assert validate_email(email) is expected


def test_discount_regression_returns_price_after_discount_not_the_discount():
    # раньше функция возвращала 10 вместо 90
    assert calculate_discount(100, 10) == 90


@pytest.mark.parametrize("price,pct,expected", [(100, 0, 100), (100, 100, 0), (59.9, 50, 29.95)])
def test_discount_boundaries(price, pct, expected):
    assert calculate_discount(price, pct) == pytest.approx(expected)


@pytest.mark.parametrize("price,pct", [(-1, 10), (100, -1), (100, 101)])
def test_discount_rejects_invalid_input(price, pct):
    with pytest.raises(ValueError):
        calculate_discount(price, pct)


def test_divide_ok_and_by_zero():
    assert divide(10, 2) == 5
    with pytest.raises(ValueError, match="Division by zero"):
        divide(1, 0)


def test_email_uniqueness_is_case_insensitive_regression(client, registered):
    r = client.post(
        "/users", json={"name": "Jane", "email": "JOHN@EXAMPLE.COM", "age": 30, "password": "Secret123"}
    )
    assert r.status_code == 409


def test_500_keeps_request_id_header_regression(app):
    from fastapi.testclient import TestClient

    @app.get("/boom")
    def boom():
        raise RuntimeError("x")

    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get("/boom", headers={"X-Request-ID": "trace-regress-1"})
    assert r.status_code == 500 and r.headers["X-Request-ID"] == "trace-regress-1"
    assert r.json()["error"]["request_id"] == "trace-regress-1"
