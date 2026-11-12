"""SQLite: отдельное соединение на операцию, транзакции для записи."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import config


@contextmanager
def connection():
    Path(config.DB_PATH).resolve().parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(config.DB_PATH, timeout=30)
    db.row_factory = sqlite3.Row
    try:
        db.execute("""CREATE TABLE IF NOT EXISTS entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner TEXT NOT NULL, created TEXT NOT NULL, text TEXT NOT NULL,
            results TEXT NOT NULL DEFAULT '{}')""")
        db.execute("CREATE INDEX IF NOT EXISTS entries_owner ON entries(owner, id)")
        with db:
            yield db
    finally:
        db.close()


def add(owner, text):
    with connection() as db:
        cursor = db.execute(
            "INSERT INTO entries (owner, created, text) VALUES (?, ?, ?)",
            (owner, datetime.now(timezone.utc).isoformat(timespec="seconds"), text))
        db.execute("""DELETE FROM entries WHERE owner = ? AND id NOT IN
                      (SELECT id FROM entries WHERE owner = ?
                       ORDER BY id DESC LIMIT ?)""", (owner, owner, config.HISTORY_LIMIT))
        return cursor.lastrowid


def get(owner, entry_id):
    with connection() as db:
        row = db.execute("SELECT * FROM entries WHERE owner = ? AND id = ?",
                         (owner, entry_id)).fetchone()
    if row is None:
        return None
    return {"id": row["id"], "created": row["created"], "text": row["text"],
            "results": json.loads(row["results"])}


def listing(owner):
    with connection() as db:
        rows = db.execute("SELECT id, created, substr(text, 1, 80) AS preview, results "
                          "FROM entries WHERE owner = ? ORDER BY id DESC", (owner,)).fetchall()
    return [{"id": r["id"], "created": r["created"], "preview": r["preview"],
             "checks": list(json.loads(r["results"]))} for r in rows]


def save_results(owner, entry_id, results):
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT results FROM entries WHERE owner = ? AND id = ?",
                         (owner, entry_id)).fetchone()
        if row:
            merged = {**json.loads(row["results"]), **results}
            db.execute("UPDATE entries SET results = ? WHERE owner = ? AND id = ?",
                       (json.dumps(merged, ensure_ascii=False), owner, entry_id))


def delete(owner, entry_id):
    with connection() as db:
        db.execute("DELETE FROM entries WHERE owner = ? AND id = ?", (owner, entry_id))


def clear(owner):
    with connection() as db:
        db.execute("DELETE FROM entries WHERE owner = ?", (owner,))
