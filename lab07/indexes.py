import random
import time

import psycopg2
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, joinedload, selectinload, subqueryload

from app.models import Base, Order, User

CITIES = ["Moscow", "Kazan", "Perm", "Omsk", "Tomsk", "Sochi", "Ufa", "Tula"]


def seed_users(dsn: str, n: int = 50_000) -> None:
    rnd = random.Random(42)
    with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("""
            DROP TABLE IF EXISTS idx_users;
            CREATE TABLE idx_users (id SERIAL PRIMARY KEY, name VARCHAR(50), email VARCHAR(100),
                                    age INTEGER, city VARCHAR(50), active BOOLEAN);""")
        rows = [
            (
                f"User{rnd.randrange(2000)}",
                f"user{i}@example.com",
                rnd.randint(18, 80),
                rnd.choice(CITIES),
                rnd.random() < 0.5,
            )
            for i in range(n)
        ]
        cur.executemany(
            "INSERT INTO idx_users (name, email, age, city, active) VALUES (%s,%s,%s,%s,%s)", rows
        )
        cur.execute("ANALYZE idx_users")


def explain(dsn: str, sql: str) -> dict:
    import json

    with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("EXPLAIN (FORMAT JSON) " + sql)
        raw = cur.fetchone()[0]
        plan = (raw if isinstance(raw, list) else json.loads(raw))[0]["Plan"]

    def find_index(node: dict) -> str | None:
        if "Index Name" in node:
            return node["Index Name"]
        return next((i for c in node.get("Plans", []) if (i := find_index(c))), None)

    node = plan
    while "Plans" in node and "Relation Name" not in node:
        node = node["Plans"][0]
    return {"node": node["Node Type"], "index": find_index(plan), "cost": plan["Total Cost"]}


def run(dsn: str, sql: str) -> None:
    with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(sql)


def create_indexes(dsn: str, statements: list[str]) -> None:
    with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
        for stmt in statements:
            cur.execute(stmt)
        cur.execute("ANALYZE idx_users")


def drop_indexes(dsn: str) -> None:
    with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("""DO $$ DECLARE r record; BEGIN
            FOR r IN SELECT indexname FROM pg_indexes
                     WHERE tablename = 'idx_users' AND indexname NOT LIKE '%pkey' LOOP
                EXECUTE 'DROP INDEX ' || quote_ident(r.indexname);
            END LOOP; END $$;""")


class QueryCounter:
    def __init__(self, engine):
        self.count = 0
        event.listen(engine, "before_cursor_execute", self._inc)
        self.engine = engine

    def _inc(self, *_args) -> None:
        self.count += 1

    def close(self) -> None:
        event.remove(self.engine, "before_cursor_execute", self._inc)


def seed_orders(engine, users: int = 100, orders_per_user: int = 5) -> None:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        for i in range(users):
            u = User(name=f"User {i}", email=f"u{i}@example.com", age=30, password_hash="x")
            u.orders = [Order(product=f"p{j}", total=10 + j) for j in range(orders_per_user)]
            s.add(u)
        s.commit()


def _consume(users) -> int:
    return sum(len(u.orders) for u in users)


STRATEGIES = {
    "n_plus_1 (lazy)": lambda s: list(s.scalars(select(User))),
    "joinedload": lambda s: list(s.scalars(select(User).options(joinedload(User.orders))).unique()),
    "subqueryload": lambda s: list(s.scalars(select(User).options(subqueryload(User.orders)))),
    "selectinload": lambda s: list(s.scalars(select(User).options(selectinload(User.orders)))),
}


def compare_strategies(url: str) -> list[dict]:
    engine = create_engine(url)
    seed_orders(engine)
    out = []
    for name, loader in STRATEGIES.items():
        counter = QueryCounter(engine)
        started = time.perf_counter()
        with Session(engine) as s:
            total = _consume(loader(s))
        out.append(
            {
                "strategy": name,
                "queries": counter.count,
                "orders": total,
                "ms": round((time.perf_counter() - started) * 1000, 1),
            }
        )
        counter.close()
    engine.dispose()
    return out
