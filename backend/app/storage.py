"""SQLite history of finished cooking sessions."""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    burner_id TEXT NOT NULL,
    burner_name TEXT NOT NULL,
    dish_id TEXT,
    dish TEXT,
    confidence REAL,
    overridden INTEGER NOT NULL DEFAULT 0,
    started_at REAL NOT NULL,
    ended_at REAL NOT NULL,
    cook_seconds REAL NOT NULL,
    target_seconds REAL,
    stirs INTEGER NOT NULL DEFAULT 0,
    alerts TEXT,
    ingredients TEXT,
    profile TEXT,
    rating TEXT
);
CREATE INDEX IF NOT EXISTS sessions_started ON sessions(started_at);
"""


class Storage:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)
        cols = {r[1] for r in self._db.execute("PRAGMA table_info(sessions)")}
        for col in ("ingredients", "profile", "rating"):  # migrate databases from before ingredient tracking
            if col not in cols:
                self._db.execute(f"ALTER TABLE sessions ADD COLUMN {col} TEXT")
        self._db.commit()

    def save(self, row: dict) -> None:
        cols = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        with self._lock:
            self._db.execute(f"INSERT INTO sessions ({cols}) VALUES ({marks})", tuple(row.values()))
            self._db.commit()

    def save_rating(self, sid: int, profile_id: str, ratings: dict) -> None:
        import json
        with self._lock:
            self._db.execute("UPDATE sessions SET rating = ? WHERE id = ?",
                             (json.dumps({"profile": profile_id, **ratings}), sid))
            self._db.commit()

    def history(self, limit: int = 50) -> list[dict]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM sessions ORDER BY started_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def stats(self) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT COALESCE(dish, 'Unknown') AS dish, COUNT(*) AS sessions, "
                "SUM(cook_seconds) AS total_seconds, AVG(cook_seconds) AS avg_seconds "
                "FROM sessions GROUP BY COALESCE(dish, 'Unknown') ORDER BY total_seconds DESC"
            ).fetchall()
        return [dict(r) for r in rows]
