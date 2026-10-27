from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "ponto.db"
UPLOAD_DIR = DATA_DIR / "uploads"


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS employees (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                cpf TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS imports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id INTEGER NOT NULL REFERENCES employees(id),
                original_name TEXT NOT NULL,
                stored_name TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                reference_year INTEGER NOT NULL,
                reference_month INTEGER NOT NULL,
                mode TEXT NOT NULL,
                inserted_days INTEGER NOT NULL DEFAULT 0,
                updated_days INTEGER NOT NULL DEFAULT 0,
                unchanged_days INTEGER NOT NULL DEFAULT 0,
                imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(employee_id, sha256)
            );

            CREATE TABLE IF NOT EXISTS attendance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id INTEGER NOT NULL REFERENCES employees(id),
                work_date TEXT NOT NULL,
                weekday_label TEXT NOT NULL,
                punches_json TEXT NOT NULL,
                source_import_id INTEGER NOT NULL REFERENCES imports(id),
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(employee_id, work_date)
            );

            CREATE TABLE IF NOT EXISTS attendance_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                attendance_id INTEGER NOT NULL REFERENCES attendance(id),
                import_id INTEGER NOT NULL REFERENCES imports(id),
                punches_json TEXT NOT NULL,
                saved_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS schedule (
                weekday INTEGER PRIMARY KEY,
                expected_minutes INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS holidays (
                holiday_date TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        for weekday in range(7):
            conn.execute(
                "INSERT OR IGNORE INTO schedule(weekday, expected_minutes) VALUES (?, 0)",
                (weekday,),
            )
        defaults = {
            "cycle_anchor_month": "1",
            "opening_balance_minutes": "0",
        }
        for key, value in defaults.items():
            conn.execute(
                "INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)",
                (key, value),
            )


def get_setting(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def punches_from_row(row: sqlite3.Row) -> list[str]:
    return json.loads(row["punches_json"])

