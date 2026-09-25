from __future__ import annotations

import argparse
import csv
import os
from collections import Counter
from dataclasses import dataclass

from .db import SIGNAL_COLUMNS, ensure_signal_table, get_database_url, insert_signal_record, is_synthetic_signal_row, row_to_signal_record


@dataclass
class MigrationSummary:
    total: int = 0
    valid: int = 0
    suspicious: int = 0
    migrated: int = 0
    rejected: int = 0
    invalid: int = 0
    duplicates: int = 0
    errors: list[str] | None = None


def _read_csv_rows(path: str):
    with open(path, "r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return list(reader)


def _dry_run_summary(csv_path: str) -> MigrationSummary:
    rows = _read_csv_rows(csv_path)
    summary = MigrationSummary(total=len(rows), errors=[])
    seen = Counter()
    for row in rows:
        ts = str(row.get("timestamp", "")).strip()
        if ts:
            seen[ts] += 1
        if is_synthetic_signal_row(row):
            summary.suspicious += 1
            continue
        summary.valid += 1
    summary.duplicates = sum(count - 1 for count in seen.values() if count > 1)
    summary.migrated = summary.valid - summary.duplicates
    summary.rejected = summary.suspicious + summary.invalid
    return summary


def migrate_csv_to_postgres(csv_path: str = "data/signals.csv", database_url: str | None = None) -> MigrationSummary:
    url = database_url or get_database_url()
    if not url:
        raise RuntimeError("DATABASE_URL is not configured. Set DATABASE_URL before migrating.")

    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("psycopg is required for PostgreSQL migration") from exc

    rows = _read_csv_rows(csv_path)
    summary = MigrationSummary(total=len(rows), errors=[])
    conn = psycopg.connect(url)
    try:
        ensure_signal_table(conn)
        seen = Counter()
        for row in rows:
            ts = str(row.get("timestamp", "")).strip()
            if ts:
                seen[ts] += 1
            if is_synthetic_signal_row(row):
                summary.suspicious += 1
                summary.rejected += 1
                continue
            normalized = {key: row.get(key, "") for key in SIGNAL_COLUMNS if key in row}
            for key in SIGNAL_COLUMNS:
                if key not in normalized:
                    normalized[key] = None
            try:
                record = row_to_signal_record(normalized)
                insert_signal_record(conn, record)
                summary.migrated += 1
            except Exception as exc:  # pragma: no cover
                summary.errors.append(f"Row rejected: {row.get('timestamp', 'unknown')} -> {exc}")
                summary.invalid += 1
                summary.rejected += 1
    finally:
        conn.close()
    summary.duplicates = sum(count - 1 for count in seen.values() if count > 1)
    summary.valid = summary.migrated + summary.rejected - summary.suspicious - summary.invalid
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate the scanner CSV to PostgreSQL")
    parser.add_argument("--dry-run", action="store_true", help="Preview CSV validation and migration counts without connecting to PostgreSQL")
    parser.add_argument("--csv-path", default=os.getenv("SIGNALS_CSV_PATH", "data/signals.csv"), help="CSV file to inspect or migrate")
    args = parser.parse_args()

    csv_path = args.csv_path
    if args.dry_run:
        summary = _dry_run_summary(csv_path)
        print(f"Total rows: {summary.total}")
        print(f"Valid rows: {summary.valid}")
        print(f"Suspicious rows: {summary.suspicious}")
        print(f"Rows to migrate: {summary.migrated}")
        print(f"Invalid rows: {summary.invalid}")
        print(f"Duplicate timestamps: {summary.duplicates}")
        return 0

    try:
        summary = migrate_csv_to_postgres(csv_path)
    except RuntimeError as exc:
        print(f"Migration failed: {exc}")
        return 1

    print(f"Total rows: {summary.total}")
    print(f"Migrated rows: {summary.migrated}")
    print(f"Rejected rows: {summary.rejected}")
    print(f"Suspicious rows: {summary.suspicious}")
    print(f"Invalid rows: {summary.invalid}")
    print(f"Duplicate timestamps: {summary.duplicates}")
    if summary.errors:
        print("Errors:")
        for error in summary.errors[:10]:
            print(f"- {error}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
