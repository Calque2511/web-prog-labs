# запуск: python scripts/local_postgres.py (печатает DATABASE_URL, остановка по Ctrl+C)
import pathlib
import time

import pgserver
from sqlalchemy import create_engine, text

ROOT = pathlib.Path(__file__).resolve().parent.parent


def main() -> None:
    server = pgserver.get_server(ROOT / "pgdata_local", cleanup_mode="stop")
    url = server.get_uri().replace("postgresql://", "postgresql+psycopg2://", 1)
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE IF NOT EXISTS schema_migrations (name text PRIMARY KEY)"))
        applied = {r[0] for r in conn.execute(text("SELECT name FROM schema_migrations"))}
        for path in sorted((ROOT / "migrations").glob("*.sql")):
            if path.name not in applied:
                conn.exec_driver_sql(path.read_text(encoding="utf-8"))
                conn.execute(text("INSERT INTO schema_migrations VALUES (:n)"), {"n": path.name})
                print("applied", path.name, flush=True)
    print("DATABASE_URL=" + url, flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        server.cleanup()


if __name__ == "__main__":
    main()
