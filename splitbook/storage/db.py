"""SQLite 連線工廠與 schema。"""
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS groups (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS members (
    id INTEGER PRIMARY KEY,
    group_id INTEGER NOT NULL REFERENCES groups(id),
    name TEXT NOT NULL,
    pin_hash TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    UNIQUE (group_id, name)
);

CREATE TABLE IF NOT EXISTS entries (
    id INTEGER PRIMARY KEY,
    group_id INTEGER NOT NULL REFERENCES groups(id),
    rev INTEGER NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('expense', 'transfer')),
    name TEXT NOT NULL,
    amount INTEGER NOT NULL CHECK (amount != 0),
    payer_id INTEGER NOT NULL REFERENCES members(id),
    payee_id INTEGER REFERENCES members(id),
    transfer_kind TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT '',
    date TEXT NOT NULL DEFAULT (date('now', 'localtime')),
    note TEXT NOT NULL DEFAULT '',
    created_by INTEGER REFERENCES members(id),
    snapshot_id INTEGER REFERENCES snapshots(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    deleted_at TEXT
);

CREATE TABLE IF NOT EXISTS allocations (
    entry_id INTEGER NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
    member_id INTEGER NOT NULL REFERENCES members(id),
    amount INTEGER NOT NULL,
    PRIMARY KEY (entry_id, member_id)
);

CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY,
    group_id INTEGER NOT NULL REFERENCES groups(id),
    through_rev INTEGER NOT NULL,
    created_by INTEGER REFERENCES members(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS snapshot_lines (
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    from_member INTEGER NOT NULL REFERENCES members(id),
    to_member INTEGER NOT NULL REFERENCES members(id),
    amount INTEGER NOT NULL CHECK (amount > 0),
    PRIMARY KEY (snapshot_id, from_member, to_member)
);
"""


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()
