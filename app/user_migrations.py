from __future__ import annotations

import argparse
import os
from pathlib import Path

from werkzeug.security import generate_password_hash

from .auth_utils import normalize_login
from .db import get_database_url, seed_master_user


MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def _connect():
    database_url = get_database_url()
    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured")
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("psycopg is required to apply user migrations") from exc
    return psycopg.connect(database_url)


def apply_migrations() -> list[str]:
    applied: list[str] = []
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version TEXT PRIMARY KEY,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            conn.commit()

            for migration_path in sorted(MIGRATIONS_DIR.glob("[0-9]*.sql")):
                version = migration_path.name
                cur.execute(
                    "SELECT 1 FROM schema_migrations WHERE version = %s",
                    (version,),
                )
                if cur.fetchone():
                    continue

                statements = migration_path.read_text(encoding="utf-8").split(";")
                for statement in statements:
                    if statement.strip():
                        cur.execute(statement)
                cur.execute(
                    "INSERT INTO schema_migrations (version) VALUES (%s)",
                    (version,),
                )
                conn.commit()
                applied.append(version)
    return applied


def create_master_from_environment() -> dict[str, object]:
    login_value = os.getenv("MASTER_LOGIN", "izicode")
    name = os.getenv("MASTER_NAME", "izicode").strip()
    password = os.getenv("MASTER_PASSWORD")
    try:
        login = normalize_login(login_value)
    except ValueError as exc:
        raise RuntimeError(f"Invalid MASTER_LOGIN: {exc}") from exc
    if not name:
        raise RuntimeError("MASTER_NAME must not be empty")
    if not password or len(password) < 12:
        raise RuntimeError("MASTER_PASSWORD must be set and contain at least 12 characters")

    password_hash = generate_password_hash(password, method="scrypt")
    return seed_master_user(login=login, name=name, password_hash=password_hash)


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply user-schema migrations and seed the master account")
    parser.add_argument("command", choices=("migrate", "seed-master", "setup"))
    args = parser.parse_args()

    try:
        if args.command in {"migrate", "setup"}:
            applied = apply_migrations()
            print(f"Applied migrations: {', '.join(applied) if applied else 'none'}")
        if args.command in {"seed-master", "setup"}:
            if args.command == "seed-master":
                apply_migrations()
            master = create_master_from_environment()
            print(f"Master account ready: {master['login']} (id={master['id']}, role={master['role']})")
    except RuntimeError as exc:
        print(f"User setup failed: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
