import tempfile

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models import User
from app.security import hash_password

PASSWORD = "Secret123"


def make_settings(**overrides) -> Settings:
    base = dict(
        database_url="sqlite://",
        secret_key="test-secret-key-test-secret-key-0123",
        bcrypt_rounds=4,
        log_level="CRITICAL",
    )
    base.update(overrides)
    return Settings(_env_file=None, **base)


@pytest.fixture
def app():
    application = create_app(make_settings())
    application.state.redis.flushdb()  # на случай реального Redis
    return application


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


def user_payload(**over) -> dict:
    data = {"name": "John Doe", "email": "john@example.com", "age": 30, "password": PASSWORD}
    data.update(over)
    return data


def login(client, email="john@example.com", password=PASSWORD) -> dict:
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


def auth_header(tokens: dict) -> dict:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


@pytest.fixture
def registered(client):
    r = client.post("/users", json=user_payload())
    assert r.status_code == 201
    return r.json()


@pytest.fixture
def tokens(client, registered):
    return login(client)


@pytest.fixture
def headers(tokens):
    return auth_header(tokens)


@pytest.fixture
def admin_headers(client, app):
    with app.state.session_factory() as s:
        s.add(
            User(
                name="Boss",
                email="boss@example.com",
                age=40,
                role="admin",
                password_hash=hash_password(PASSWORD, 4),
            )
        )
        s.commit()
    return auth_header(login(client, "boss@example.com"))


@pytest.fixture(scope="session")
def pg_url():
    import os
    import pathlib
    import uuid

    url = os.getenv("TEST_DATABASE_URL")
    server = None
    if not url:
        pgserver = pytest.importorskip("pgserver")
        # через mkdtemp на Windows initdb падает с "Invalid argument", поэтому обычный mkdir
        pgdata = pathlib.Path(tempfile.gettempdir()) / f"pgdata_{uuid.uuid4().hex[:8]}"
        pgdata.mkdir()
        try:
            server = pgserver.get_server(pgdata, cleanup_mode="stop")
        except Exception as exc:
            pytest.skip(
                f"встроенный PostgreSQL не запустился ({type(exc).__name__}); "
                "поднимите БД через docker-compose.test.yml и задайте TEST_DATABASE_URL"
            )
        url = server.get_uri().replace("postgresql://", "postgresql+psycopg2://", 1)
    from sqlalchemy import create_engine, text

    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
        for path in sorted(pathlib.Path("migrations").glob("*.sql")):
            conn.exec_driver_sql(path.read_text(encoding="utf-8"))
    engine.dispose()
    yield url
    if server:
        server.cleanup()
