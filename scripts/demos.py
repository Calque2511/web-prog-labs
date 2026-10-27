# запуск: python scripts/demos.py > docs/demo_output.md
import asyncio
import hashlib
import pathlib
import sys
import tempfile
import time
import uuid
from decimal import Decimal

import asyncpg
import pgserver
import psycopg2
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool, QueuePool

sys.path.insert(0, ".")
from app.security import hash_password, verify_password
from lab07 import indexes
from lab07 import transactions as tx


def h(title: str) -> None:
    print(f"\n## {title}\n")


def table(rows: list[dict]) -> None:
    print("| " + " | ".join(rows[0]) + " |")
    print("|" + "---|" * len(rows[0]))
    for r in rows:
        print("| " + " | ".join(str(v) for v in r.values()) + " |")
    print()


def sql_injection(dsn: str) -> None:
    h("SQL-инъекция: уязвимый и защищённый поиск")
    with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "DROP TABLE IF EXISTS sqli_users; CREATE TABLE sqli_users (id serial, email text, password text)"
        )
        cur.execute("INSERT INTO sqli_users (email, password) VALUES ('a@x.com','pw-a'), ('b@x.com','pw-b')")

    def vulnerable(email: str) -> list:
        with psycopg2.connect(dsn) as c, c.cursor() as cur:
            cur.execute(
                f"SELECT email FROM sqli_users WHERE email = '{email}'"
            )  # уязвимо специально: демо SQL-инъекции
            # у DROP нет результата, fetchall упал бы
            return cur.fetchall() if cur.description else []

    def safe(email: str) -> list:
        with psycopg2.connect(dsn) as c, c.cursor() as cur:
            cur.execute("SELECT email FROM sqli_users WHERE email = %s", (email,))
            return cur.fetchall()

    payload = "' OR '1'='1"
    print(f"Payload: `{payload}`\n")
    print(f"- уязвимый вариант вернул **{len(vulnerable(payload))}** строк(и): {vulnerable(payload)}")
    print(f"- защищённый вариант вернул **{len(safe(payload))}** строк(и)")
    try:
        vulnerable("x'; DROP TABLE sqli_users; --")
    except psycopg2.Error:
        pass
    with psycopg2.connect(dsn) as c, c.cursor() as cur:
        cur.execute("SELECT to_regclass('sqli_users')")
        print(
            f"- после `'; DROP TABLE` в уязвимом варианте таблица существует: **{cur.fetchone()[0] is not None}**"
        )


def password_hashing() -> None:
    h("Хеширование паролей: время и соль")
    pw = "Secret123"
    t = time.perf_counter()
    for _ in range(1000):
        hashlib.sha256(pw.encode()).hexdigest()
    sha_ms = time.perf_counter() - t
    t = time.perf_counter()
    hashed = hash_password(pw, 12)
    bcrypt_hash_ms = (time.perf_counter() - t) * 1000
    t = time.perf_counter()
    ok = verify_password(pw, hashed)
    bcrypt_verify_ms = (time.perf_counter() - t) * 1000
    print(
        f"- sha256 без соли: {sha_ms:.4f} мс на 1000 хешей — перебирается миллиардами/с, одинаковые пароли дают одинаковый хеш"
    )
    print(
        f"- bcrypt(cost=12): {bcrypt_hash_ms:.0f} мс на хеш, проверка {bcrypt_verify_ms:.0f} мс (верно: {ok})"
    )
    print(
        f"- два хеша одного пароля различаются (соль): {hash_password(pw, 4) != hash_password(pw, 4)}; хеш: `{hashed[:29]}...`"
    )


def pooling(url: str) -> None:
    h("Connection pooling: без пула vs с пулом (500 коротких запросов)")
    rows = []
    for name, kwargs in [
        ("NullPool (без пула)", {"poolclass": NullPool}),
        ("QueuePool(5+10)", {"poolclass": QueuePool, "pool_size": 5, "max_overflow": 10}),
    ]:
        engine = create_engine(url, **kwargs)
        t = time.perf_counter()
        for _ in range(500):
            with engine.connect() as c:
                c.execute(text("SELECT 1"))
        elapsed = time.perf_counter() - t
        rows.append({"режим": name, "время, с": round(elapsed, 2), "запросов/с": round(500 / elapsed)})
        engine.dispose()
    table(rows)


async def async_crud(dsn: str) -> None:
    h("Асинхронный доступ (asyncpg)")
    conn = await asyncpg.connect(dsn)
    await conn.execute(
        "DROP TABLE IF EXISTS async_users; CREATE TABLE async_users (id serial PRIMARY KEY, email text UNIQUE)"
    )
    uid = await conn.fetchval("INSERT INTO async_users (email) VALUES ($1) RETURNING id", "a@x.com")
    print(
        f"- INSERT -> id={uid}; SELECT -> {dict(await conn.fetchrow('SELECT * FROM async_users WHERE id=$1', uid))}"
    )
    try:
        await conn.execute("INSERT INTO async_users (email) VALUES ($1)", "a@x.com")
    except asyncpg.UniqueViolationError as exc:
        print(f"- дубликат обработан: `{type(exc).__name__}`")
    await conn.execute("UPDATE async_users SET email=$1 WHERE id=$2", "b@x.com", uid)
    print(
        f"- UPDATE -> {await conn.fetchval('SELECT email FROM async_users WHERE id=$1', uid)}; DELETE -> {await conn.execute('DELETE FROM async_users WHERE id=$1', uid)}"
    )
    await conn.close()

    async def one(i: int) -> int:
        c = await asyncpg.connect(dsn)
        try:
            await c.execute("SELECT pg_sleep(0.1)")
            return i
        finally:
            await c.close()

    t = time.perf_counter()
    await asyncio.gather(*(one(i) for i in range(20)))
    print(
        f"- 20 запросов по 0.1 с выполнены конкурентно за **{time.perf_counter() - t:.2f} с** (последовательно было бы 2 с)"
    )


def transactions(dsn: str) -> None:
    h("Лаба 7: транзакции и гонки")
    tx.setup_schema(dsn)
    with psycopg2.connect(dsn) as c, c.cursor() as cur:
        cur.execute("INSERT INTO accounts (name, balance) VALUES ('A', 100), ('B', 50)")
    tx.transfer(dsn, 1, 2, Decimal("30"))
    print("- перевод 30: A=70, B=80 (атомарно)")
    try:
        tx.transfer(dsn, 1, 2, Decimal("999"))
    except tx.InsufficientFunds as exc:
        print(f"- перевод 999 отклонён и откатан: {exc}")
    print()
    rows = []
    for name, fn, seats, users in [
        ("наивный check-then-act", tx.register_naive, 1, 2),
        ("SELECT ... FOR UPDATE", tx.register_for_update, 3, 10),
        ("атомарный UPDATE ... WHERE seats > 0", tx.register_atomic, 3, 10),
    ]:
        r = tx.run_concurrently(dsn, fn, seats, users)
        rows.append(
            {
                "способ": name,
                "мест": r["capacity"],
                "потоков": users,
                "записано": r["registered"],
                "seats в БД": r["seats_left"],
                "результат": "ПЕРЕПРОДАЖА" if r["registered"] > r["capacity"] else "ок",
            }
        )
    table(rows)


def index_report(dsn: str) -> None:
    h("Лаба 7: индексы и EXPLAIN (50 000 строк)")
    indexes.seed_users(dsn, 50_000)
    queries = {
        "email = ...": "SELECT * FROM idx_users WHERE email = 'user777@example.com'",
        "name AND age": "SELECT * FROM idx_users WHERE name = 'User5' AND age = 30",
        "age = 30": "SELECT * FROM idx_users WHERE age = 30",
        "active AND city": "SELECT * FROM idx_users WHERE active = true AND city = 'Moscow'",
        "city (без префикса)": "SELECT * FROM idx_users WHERE city = 'Moscow' AND age = 30",
    }
    before = {k: indexes.explain(dsn, q) for k, q in queries.items()}
    indexes.create_indexes(
        dsn,
        [
            "CREATE INDEX idx_users_email ON idx_users(email)",
            "CREATE INDEX idx_users_name_age ON idx_users(name, age)",
            "CREATE INDEX idx_users_age ON idx_users(age)",
            "CREATE INDEX idx_users_active_city ON idx_users(active, city)",
        ],
    )
    after = {k: indexes.explain(dsn, q) for k, q in queries.items()}
    table(
        [
            {
                "запрос": k,
                "до: узел": before[k]["node"],
                "до: cost": before[k]["cost"],
                "после: узел": after[k]["node"],
                "индекс": after[k]["index"],
                "после: cost": after[k]["cost"],
            }
            for k in queries
        ]
    )

    h("Лаба 7: N+1 и eager loading (100 пользователей × 5 заказов)")
    table(indexes.compare_strategies(dsn.replace("postgresql://", "postgresql+psycopg2://", 1)))


def main() -> None:
    pgdata = pathlib.Path(tempfile.gettempdir()) / f"pgdata_demo_{uuid.uuid4().hex[:8]}"
    pgdata.mkdir()  # не mkdtemp, см. tests/conftest.py
    server = pgserver.get_server(pgdata, cleanup_mode="stop")
    dsn = server.get_uri()
    print("# Результаты демонстраций\n\nСгенерировано `python scripts/demos.py` на встроенном PostgreSQL 16.")
    try:
        sql_injection(dsn)
        password_hashing()
        pooling(dsn.replace("postgresql://", "postgresql+psycopg2://", 1))
        asyncio.run(async_crud(dsn))
        transactions(dsn)
        index_report(dsn)
    finally:
        server.cleanup()


if __name__ == "__main__":
    main()
