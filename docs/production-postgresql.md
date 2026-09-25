# PostgreSQL production setup for trading_context_scanner

## 1. Prerequisites

- PostgreSQL server running on the VPS.
- A database and application user dedicated to this project.
- Python environment with the project dependencies installed.
- A `.env` file in the project root, not committed to Git.

## 2. Create the database

```bash
sudo -u postgres psql
CREATE DATABASE trading_context_scanner;
\q
```

## 3. Create the application user

Use a dedicated non-admin user instead of `postgres`:

```bash
sudo -u postgres psql
CREATE USER trading_context_scanner WITH PASSWORD 'CHANGE_ME';
GRANT ALL PRIVILEGES ON DATABASE trading_context_scanner TO trading_context_scanner;
ALTER DATABASE trading_context_scanner OWNER TO trading_context_scanner;
\q
```

Do not grant SUPERUSER privileges.

## 4. Configure DATABASE_URL

Create a local `.env` file in the project root with the value:

```env
DATABASE_URL=postgresql://trading_context_scanner:CHANGE_ME@127.0.0.1:5432/trading_context_scanner
WEB_BASE_URL=http://127.0.0.1:5000
SIGNALS_CSV_PATH=data/signals.csv
AUTH_SECRET_KEY=REPLACE_WITH_A_RANDOM_SECRET
APP_ENV=production
```

Do not commit `.env` to the repository.
Generate `AUTH_SECRET_KEY` on the VPS with `python -c "import secrets; print(secrets.token_urlsafe(48))"` and store it only in `.env`.

## 5. Schema initialization and idempotence

The project already has the schema initializer in `app/db.py`:

- `signals_table_sql()` builds the `signals` table definition.
- `ensure_signal_table(conn)` runs `CREATE TABLE IF NOT EXISTS signals (...)`.
- it also creates the timestamp and score indexes with `IF NOT EXISTS`.

This is the required initialization pattern:

```bash
. .venv/bin/activate
python -c "import os; import psycopg; from app.db import ensure_signal_table; conn = psycopg.connect(os.environ['DATABASE_URL']); ensure_signal_table(conn); conn.close()"
```

This is safe because it:

- creates the table only if it does not exist;
- keeps existing rows intact;
- does not drop or rename the table;
- does not perform destructive schema changes.

## 6. Test the connection

```bash
. .venv/bin/activate
python -c "import os, psycopg; conn = psycopg.connect(os.environ['DATABASE_URL']); print(conn.info.dbname); conn.close()"
```

## 7. Check current records

```bash
. .venv/bin/activate
python -c "import os, psycopg; conn = psycopg.connect(os.environ['DATABASE_URL']); cur = conn.cursor(); cur.execute('SELECT COUNT(*) FROM signals'); print(cur.fetchone()[0]); conn.close()"
```

Optional query:

```bash
python -c "import os, psycopg; conn = psycopg.connect(os.environ['DATABASE_URL']); cur = conn.cursor(); cur.execute('SELECT timestamp, side, score, price FROM signals ORDER BY timestamp DESC LIMIT 10'); print(cur.fetchall()); conn.close()"
```

## 8. Notes

- The legacy CSV remains a fallback only when `DATABASE_URL` is unset.
- No historical CSV migration is required for production startup.
- The application must not use the `postgres` user directly for runtime access.

## User authentication foundation

The versioned user migration creates `users`, `user_coins`, and `strategies`; it does not modify the global `signals` table.

After setting `DATABASE_URL` and `AUTH_SECRET_KEY` in `.env`, apply the migration:

```bash
cd /opt/trading_context_scanner
set -a
. ./.env
set +a
. .venv/bin/activate
python -m app.user_migrations migrate
```

Seed the first MASTER account without putting the password in a file or command history:

```bash
read -rsp "Master password: " MASTER_PASSWORD
export MASTER_PASSWORD
echo
python -m app.user_migrations seed-master
unset MASTER_PASSWORD
```

The seed defaults to login/name `izicode`, requires at least 12 password characters, and stores only a Werkzeug `scrypt` password hash. Re-running the seed updates the same account's hash and MASTER role; it never prints the password or hash.

Authentication uses a signed Flask session cookie (`HttpOnly`, `SameSite=Lax`, eight-hour lifetime). In production, `AUTH_SECRET_KEY` must be at least 32 characters and the `Secure` cookie flag is always enabled. The analysis endpoints require a valid session but return the same global signals to every authenticated user; no analysis query is scoped by user.
