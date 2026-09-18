"""SQLite 持久化层。"""

import os
import sqlite3
from pathlib import Path

DB_PATH = os.environ.get("DATABASE_PATH", "lottery.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS lotteries (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    seat_count  INTEGER NOT NULL,
    candidates  TEXT NOT NULL,          -- JSON: [{"name": ..., "weight": ...}, ...]
    seed        TEXT NOT NULL,          -- 秘密种子，揭示前不得外泄
    commitment  TEXT NOT NULL,          -- SHA-256(seed)
    nonce       TEXT,
    status      TEXT NOT NULL,          -- pending | executed | revealed
    result      TEXT,                   -- JSON: 固定位次的当选名单
    created_at  TEXT NOT NULL,
    executed_at TEXT,
    revealed_at TEXT
);
"""


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    parent = Path(DB_PATH).parent
    if str(parent) not in ("", "."):
        parent.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        conn.executescript(SCHEMA)
