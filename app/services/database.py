import sqlite3
import os
from datetime import datetime, timedelta

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
    _conn.execute("""
        CREATE TABLE IF NOT EXISTS user_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            track_title TEXT,
            created_at TEXT NOT NULL
        )
    """)
    _conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_user_events_guild_user
        ON user_events (guild_id, user_id, created_at DESC)
    """)
    _conn.commit()


def log_play(guild_id, user_id, track_title, track_url=None):
    conn = _get_conn()
    conn.execute(
        "INSERT INTO play_history (guild_id, user_id, track_title, track_url, played_at) VALUES (?, ?, ?, ?, ?)",
        (guild_id, user_id, track_title, track_url, datetime.utcnow().isoformat())
    )
    conn.commit()


def log_event(guild_id, user_id, event_type, track_title=None):
    conn = _get_conn()
    conn.execute(
        "INSERT INTO user_events (guild_id, user_id, event_type, track_title, created_at) VALUES (?, ?, ?, ?, ?)",
        (guild_id, user_id, event_type, track_title, datetime.utcnow().isoformat())
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


def get_user_status(guild_id, user_id):
    conn = _get_conn()
    since = (datetime.utcnow() - timedelta(days=30)).isoformat()

    total_plays = conn.execute(
        "SELECT COUNT(*) as c FROM play_history WHERE guild_id = ? AND user_id = ? AND played_at >= ?",
        (guild_id, user_id, since)
    ).fetchone()['c']

    if total_plays == 0:
        return None

    total_skips = conn.execute(
        "SELECT COUNT(*) as c FROM user_events WHERE guild_id = ? AND user_id = ? AND event_type = 'skip' AND created_at >= ?",
        (guild_id, user_id, since)
    ).fetchone()['c']

    total_likes = conn.execute(
        "SELECT COUNT(*) as c FROM user_events WHERE guild_id = ? AND user_id = ? AND event_type = 'like' AND created_at >= ?",
        (guild_id, user_id, since)
    ).fetchone()['c']

    top_tracks = conn.execute(
        "SELECT track_title, COUNT(*) as plays FROM play_history WHERE guild_id = ? AND user_id = ? AND played_at >= ? GROUP BY track_title ORDER BY plays DESC LIMIT 5",
        (guild_id, user_id, since)
    ).fetchall()

    top_artists = conn.execute("""
        SELECT
            CASE WHEN INSTR(track_title, ' - ') > 0
                THEN SUBSTR(track_title, 1, INSTR(track_title, ' - ') - 1)
                ELSE track_title
            END as artist,
            COUNT(*) as plays
        FROM play_history
        WHERE guild_id = ? AND user_id = ? AND played_at >= ?
        GROUP BY artist ORDER BY plays DESC LIMIT 5
    """, (guild_id, user_id, since)).fetchall()

    hours = conn.execute(
        "SELECT CAST(SUBSTR(played_at, 12, 2) AS INTEGER) as hour FROM play_history WHERE guild_id = ? AND user_id = ? AND played_at >= ?",
        (guild_id, user_id, since)
    ).fetchall()

    blocks = [0, 0, 0, 0]
    for row in hours:
        h = row['hour']
        if h < 6:
            blocks[0] += 1
        elif h < 12:
            blocks[1] += 1
        elif h < 18:
            blocks[2] += 1
        else:
            blocks[3] += 1

    unique_tracks = conn.execute(
        "SELECT COUNT(DISTINCT track_title) as c FROM play_history WHERE guild_id = ? AND user_id = ? AND played_at >= ?",
        (guild_id, user_id, since)
    ).fetchone()['c']

    repeat_rate = 0.0
    if total_plays > 0 and unique_tracks > 0:
        repeat_rate = ((total_plays - unique_tracks) / total_plays) * 100

    return {
        'total_plays': total_plays,
        'total_skips': total_skips,
        'total_likes': total_likes,
        'skip_rate': (total_skips / total_plays * 100) if total_plays > 0 else 0,
        'like_rate': (total_likes / total_plays * 100) if total_plays > 0 else 0,
        'top_tracks': top_tracks,
        'top_artists': top_artists,
        'hour_blocks': blocks,
        'repeat_rate': repeat_rate,
    }
