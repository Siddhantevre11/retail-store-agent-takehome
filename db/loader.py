import csv
import sqlite3
from pathlib import Path

SCHEMA_PATH = Path(__file__).parent.parent / "schema.sql"

_CSV_TABLES = [
    "products",
    "customers",
    "suppliers",
    "supplier_catalog",
    "inventory",
    "orders",
    "order_lines",
    "returns",
    "promotions",
]

# Columns where a blank CSV cell means NULL (a walk-in order has no customer_id),
# not an empty string.
_NULLABLE_BLANKS = {("orders", "customer_id")}


def bootstrap_db(data_dir, db_path=":memory:"):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA_PATH.read_text())
    _load_csvs(conn, Path(data_dir))
    conn.commit()
    return conn


def _load_csvs(conn, data_dir):
    for table in _CSV_TABLES:
        path = data_dir / f"{table}.csv"
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            columns = reader.fieldnames
            rows = [
                tuple(
                    None if row[c] == "" and (table, c) in _NULLABLE_BLANKS else row[c]
                    for c in columns
                )
                for row in reader
            ]

        col_list = ", ".join(columns)
        placeholders = ", ".join("?" for _ in columns)
        conn.executemany(
            f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})", rows
        )
