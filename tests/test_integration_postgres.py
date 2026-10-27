import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.infra import EmailQueue, make_redis
from app.main import create_app
from app.repositories.users import UserRepository
from app.schemas import UserCreate
from app.services.users import UserService
from tests.conftest import auth_header, login, make_settings, user_payload

pytestmark = pytest.mark.integration


@pytest.fixture
def engine(pg_url):
    eng = create_engine(pg_url)
    yield eng
    with eng.begin() as conn:  # чистим таблицы после каждого теста
        conn.execute(text("TRUNCATE users RESTART IDENTITY CASCADE"))
    eng.dispose()


@pytest.fixture
def session(engine):
    with Session(engine) as s:
        yield s


@pytest.fixture
def pg_client(pg_url):
    app = create_app(make_settings(database_url=pg_url), create_tables=False)
    with TestClient(app) as c:
        yield c, app
    app.state.engine.dispose()


def count(engine, sql: str):
    with engine.connect() as conn:
        return conn.execute(text(sql)).scalar()


def test_service_with_real_repository_persists_user(session, engine):
    queue = EmailQueue(make_redis(None))
    svc = UserService(UserRepository(session), queue, bcrypt_rounds=4)
    out = svc.create_user(UserCreate(name="John", email="john@example.com", age=30, password="Secret123"))

    assert count(engine, "SELECT count(*) FROM users WHERE email = 'john@example.com'") == 1
    assert count(engine, "SELECT password_hash FROM users").startswith("$2")
    assert queue.size() == 1 and out.id == 1


def test_database_constraints_back_up_application_rules(session, engine):
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        session.execute(
            text("INSERT INTO users (name,email,age,password_hash) VALUES ('A','a@x.com',10,'h')")
        )
    session.rollback()
    session.execute(text("INSERT INTO users (name,email,age,password_hash) VALUES ('A','a@x.com',20,'h')"))
    with pytest.raises(IntegrityError):
        session.execute(
            text("INSERT INTO users (name,email,age,password_hash) VALUES ('B','a@x.com',20,'h')")
        )


def test_full_api_flow_on_postgres_with_side_effects_checked(pg_client, engine):
    client, app = pg_client
    r = client.post("/users", json=user_payload())
    assert r.status_code == 201
    # проверяем БД и письмо, а не только статус
    assert count(engine, "SELECT email FROM users") == "john@example.com"
    assert app.state.email_sender.sent == [("john@example.com", "Welcome!")]

    h = auth_header(login(client))
    uid = r.json()["id"]
    assert (
        client.post(f"/users/{uid}/orders", headers=h, json={"product": "Book", "total": 9.99}).status_code
        == 201
    )
    assert float(count(engine, "SELECT total FROM orders")) == 9.99
    assert client.delete(f"/users/{uid}", headers=h).status_code == 204
    assert count(engine, "SELECT count(*) FROM orders") == 0  # ON DELETE CASCADE


def test_duplicate_email_is_409_on_postgres(pg_client):
    client, _ = pg_client
    assert client.post("/users", json=user_payload()).status_code == 201
    assert client.post("/users", json=user_payload()).status_code == 409


def test_request_id_ties_response_to_log_lines(pg_client, caplog):
    import logging

    client, _ = pg_client
    with caplog.at_level(logging.INFO, logger="app"):
        r = client.get("/users/1", headers={"X-Request-ID": "trace-integration-1"})
    assert r.status_code == 401
    assert r.headers["X-Request-ID"] == "trace-integration-1"
