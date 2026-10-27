from decimal import Decimal

import psycopg2
import pytest

from lab07 import indexes
from lab07 import transactions as tx

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def dsn(pg_url):
    d = pg_url.replace("postgresql+psycopg2://", "postgresql://", 1)
    tx.setup_schema(d)
    return d


def _balances(dsn):
    with psycopg2.connect(dsn) as c, c.cursor() as cur:
        cur.execute("SELECT id, balance FROM accounts ORDER BY id")
        return dict(cur.fetchall())


@pytest.fixture
def accounts(dsn):
    with psycopg2.connect(dsn) as c, c.cursor() as cur:
        cur.execute("TRUNCATE accounts RESTART IDENTITY")
        cur.execute("INSERT INTO accounts (name, balance) VALUES ('A', 100), ('B', 50)")
    return dsn


def test_transfer_moves_money_atomically(accounts):
    tx.transfer(accounts, 1, 2, Decimal("30"))
    assert _balances(accounts) == {1: Decimal("70"), 2: Decimal("80")}


def test_transfer_rolls_back_on_insufficient_funds_and_unknown_account(accounts):
    with pytest.raises(tx.InsufficientFunds):
        tx.transfer(accounts, 1, 2, Decimal("500"))
    with pytest.raises(tx.AccountNotFound):
        tx.transfer(accounts, 1, 99, Decimal("1"))
    with pytest.raises(ValueError):
        tx.transfer(accounts, 1, 2, Decimal("-5"))
    assert _balances(accounts) == {1: Decimal("100"), 2: Decimal("50")}


def test_opposite_concurrent_transfers_do_not_deadlock_and_conserve_money(accounts):
    import threading

    threads = [
        threading.Thread(target=tx.transfer, args=(accounts, a, b, Decimal("1")))
        for _ in range(10)
        for a, b in ((1, 2), (2, 1))
    ]
    [t.start() for t in threads]
    [t.join(timeout=20) for t in threads]
    assert not any(t.is_alive() for t in threads)
    assert sum(_balances(accounts).values()) == Decimal("150")


def test_naive_registration_oversells_seat(dsn):
    r = tx.run_concurrently(dsn, tx.register_naive, seats=1, users=2)
    assert r["registered"] == 2 > r["capacity"]  # гонка: оба увидели seats = 1


@pytest.mark.parametrize("fn", [tx.register_for_update, tx.register_atomic])
def test_safe_registration_never_oversells(dsn, fn):
    r = tx.run_concurrently(dsn, fn, seats=3, users=10)
    assert r == {"capacity": 3, "registered": 3, "seats_left": 0, "ok_responses": 3}


def test_unique_constraint_blocks_double_registration(dsn):
    tx.run_concurrently(dsn, tx.register_atomic, seats=5, users=1)
    with pytest.raises(tx.AlreadyRegistered):
        tx.register_unique(dsn, 1, 1)


def test_index_changes_plan_and_lowers_cost(dsn):
    indexes.seed_users(dsn, 20_000)
    q = "SELECT * FROM idx_users WHERE email = 'user777@example.com'"
    before = indexes.explain(dsn, q)
    assert before["node"] == "Seq Scan"
    indexes.create_indexes(dsn, ["CREATE INDEX idx_users_email ON idx_users(email)"])
    after = indexes.explain(dsn, q)
    assert after["index"] == "idx_users_email" and after["cost"] < before["cost"] / 10


def test_composite_index_left_prefix_rule(dsn):
    indexes.seed_users(dsn, 20_000)
    indexes.create_indexes(dsn, ["CREATE INDEX idx_name_age_city ON idx_users(name, age, city)"])

    def uses(where):
        return indexes.explain(dsn, f"SELECT * FROM idx_users WHERE {where}")["index"]

    assert uses("name = 'User5'") == "idx_name_age_city"
    assert uses("name = 'User5' AND age = 30") == "idx_name_age_city"
    assert uses("city = 'Moscow'") is None  # нет левого префикса


def test_n_plus_one_vs_eager_loading_query_counts(pg_url):
    rows = {r["strategy"]: r for r in indexes.compare_strategies(pg_url)}
    assert rows["n_plus_1 (lazy)"]["queries"] == 101
    assert rows["joinedload"]["queries"] == 1
    assert rows["subqueryload"]["queries"] == rows["selectinload"]["queries"] == 2
    assert all(r["orders"] == 500 for r in rows.values())
