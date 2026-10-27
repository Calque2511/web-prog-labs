import threading
import time
from decimal import Decimal

import psycopg2
from psycopg2 import errors

SCHEMA = """
DROP TABLE IF EXISTS registrations, courses, accounts CASCADE;
CREATE TABLE accounts (
    id SERIAL PRIMARY KEY, name VARCHAR(50) NOT NULL,
    balance DECIMAL(10, 2) NOT NULL CHECK (balance >= 0));
CREATE TABLE courses (
    id SERIAL PRIMARY KEY, name VARCHAR(100) NOT NULL,
    seats INTEGER NOT NULL CHECK (seats >= 0));
CREATE TABLE registrations (
    id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL, course_id INTEGER NOT NULL,
    UNIQUE (user_id, course_id));
"""


class InsufficientFunds(Exception):
    pass


class AccountNotFound(Exception):
    pass


class AlreadyRegistered(Exception):
    pass


def setup_schema(dsn: str) -> None:
    with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(SCHEMA)


def transfer(dsn: str, from_id: int, to_id: int, amount: Decimal) -> None:
    if amount <= 0:
        raise ValueError("amount must be positive")
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            # блокируем строки в порядке id, чтобы встречные переводы не повисли друг на друге
            cur.execute(
                "SELECT id, balance FROM accounts WHERE id IN (%s, %s) ORDER BY id FOR UPDATE",
                (from_id, to_id),
            )
            balances = dict(cur.fetchall())
            if from_id not in balances or to_id not in balances:
                raise AccountNotFound("account not found")
            if balances[from_id] < amount:
                raise InsufficientFunds(f"balance {balances[from_id]} < {amount}")
            cur.execute("UPDATE accounts SET balance = balance - %s WHERE id = %s", (amount, from_id))
            cur.execute("UPDATE accounts SET balance = balance + %s WHERE id = %s", (amount, to_id))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _fresh_course(dsn: str, seats: int) -> int:
    with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("TRUNCATE registrations, courses RESTART IDENTITY")
        cur.execute("INSERT INTO courses (name, seats) VALUES ('Web', %s) RETURNING id", (seats,))
        return cur.fetchone()[0]


def register_naive(dsn: str, course_id: int, user_id: int, barrier: threading.Barrier | None = None) -> bool:
    # так делать нельзя: проверка и запись разнесены, seats считается в Python
    with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("SELECT seats FROM courses WHERE id = %s", (course_id,))
        seats = cur.fetchone()[0]
        if barrier:
            barrier.wait(timeout=5)  # ждём, пока оба потока прочитают seats
        time.sleep(0.01)
        if seats <= 0:
            return False
        cur.execute("UPDATE courses SET seats = %s WHERE id = %s", (seats - 1, course_id))
        cur.execute("INSERT INTO registrations (user_id, course_id) VALUES (%s, %s)", (user_id, course_id))
        return True


def register_for_update(
    dsn: str, course_id: int, user_id: int, barrier: threading.Barrier | None = None
) -> bool:
    with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("SELECT seats FROM courses WHERE id = %s FOR UPDATE", (course_id,))
        seats = cur.fetchone()[0]
        time.sleep(0.01)
        if seats <= 0:
            return False
        cur.execute("UPDATE courses SET seats = seats - 1 WHERE id = %s", (course_id,))
        cur.execute("INSERT INTO registrations (user_id, course_id) VALUES (%s, %s)", (user_id, course_id))
        return True


def register_atomic(dsn: str, course_id: int, user_id: int, barrier: threading.Barrier | None = None) -> bool:
    with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("UPDATE courses SET seats = seats - 1 WHERE id = %s AND seats > 0", (course_id,))
        if cur.rowcount == 0:
            return False
        cur.execute("INSERT INTO registrations (user_id, course_id) VALUES (%s, %s)", (user_id, course_id))
        return True


def register_unique(dsn: str, course_id: int, user_id: int) -> None:
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO registrations (user_id, course_id) VALUES (%s, %s)", (user_id, course_id)
            )
        conn.commit()
    except errors.UniqueViolation as exc:
        conn.rollback()
        raise AlreadyRegistered(f"user {user_id} is already registered on course {course_id}") from exc
    finally:
        conn.close()


def run_concurrently(dsn: str, register, seats: int, users: int) -> dict:
    course_id = _fresh_course(dsn, seats)
    barrier = threading.Barrier(users)
    results: list[bool] = []

    def worker(uid: int) -> None:
        try:
            results.append(register(dsn, course_id, uid, barrier))
        except Exception:  # ошибка БД тоже считается неудачной регистрацией
            results.append(False)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(1, users + 1)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("SELECT seats FROM courses WHERE id = %s", (course_id,))
        left = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM registrations WHERE course_id = %s", (course_id,))
        registered = cur.fetchone()[0]
    return {"capacity": seats, "registered": registered, "seats_left": left, "ok_responses": sum(results)}
