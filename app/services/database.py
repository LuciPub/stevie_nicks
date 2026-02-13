import sqlite3
import os
from datetime import datetime

DB_PATH = os.getenv("DB_PATH", "/app/data/history.db")

_conn = None


def _get_conn():
    global _conn
    if _conn is None:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _init_tables()
    return _conn


def _init_tables():
    _conn.execute("""
        CREATE TABLE IF NOT EXISTS play_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            track_title TEXT NOT NULL,
            track_url TEXT,
            played_at TEXT NOT NULL
        )
    """)
    _conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_play_history_guild
        ON play_history (guild_id, played_at DESC)
    """)
    _conn.commit()


def log_play(guild_id, user_id, track_title, track_url=None):
    conn = _get_conn()
    conn.execute(
        "INSERT INTO play_history (guild_id, user_id, track_title, track_url, played_at) VALUES (?, ?, ?, ?, ?)",
        (guild_id, user_id, track_title, track_url, datetime.utcnow().isoformat())
    )
    conn.commit()


def get_recent(guild_id, limit=15):
    conn = _get_conn()
    return conn.execute(
        "SELECT track_title, user_id, played_at FROM play_history WHERE guild_id = ? ORDER BY played_at DESC LIMIT ?",
        (guild_id, limit)
    ).fetchall()


def get_top_tracks(guild_id, limit=10):
    conn = _get_conn()
    return conn.execute(
        "SELECT track_title, COUNT(*) as plays FROM play_history WHERE guild_id = ? GROUP BY track_title ORDER BY plays DESC LIMIT ?",
        (guild_id, limit)
    ).fetchall()


def get_most_active(guild_id, limit=10):
    conn = _get_conn()
    return conn.execute(
        "SELECT user_id, COUNT(*) as plays FROM play_history WHERE guild_id = ? GROUP BY user_id ORDER BY plays DESC LIMIT ?",
        (guild_id, limit)
    ).fetchall()
