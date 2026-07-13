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
    color TEXT NOT NULL DEFAULT '',
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
    deleted_at TEXT,
    template_id INTEGER REFERENCES recurring_templates(id)
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

CREATE TABLE IF NOT EXISTS shopping_items (
    id INTEGER PRIMARY KEY,
    group_id INTEGER NOT NULL REFERENCES groups(id),
    name TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    estimate INTEGER,                 -- 預估金額，NULL = 未填
    added_by INTEGER NOT NULL REFERENCES members(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    bought_at TEXT,                   -- NULL = 還沒買
    entry_id INTEGER REFERENCES entries(id),
    deleted_at TEXT
);

CREATE TABLE IF NOT EXISTS recurring_templates (
    id INTEGER PRIMARY KEY,
    group_id INTEGER NOT NULL REFERENCES groups(id),
    name TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT '',
    amount INTEGER,                   -- NULL = 每期填金額
    payer_id INTEGER NOT NULL REFERENCES members(id),
    split_kind TEXT NOT NULL DEFAULT 'equal' CHECK (split_kind IN ('equal','weights','exact')),
    split_data TEXT NOT NULL DEFAULT '{}',   -- JSON 序列化的權重/指定金額
    cycle TEXT NOT NULL CHECK (cycle IN ('monthly','bimonthly','yearly')),
    cycle_day INTEGER NOT NULL CHECK (cycle_day BETWEEN 1 AND 31),
    next_due TEXT NOT NULL,           -- ISO 日期字串 YYYY-MM-DD
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
"""


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _ensure_column(conn: sqlite3.Connection, table: str, column: str,
                    ddl: str) -> None:
    """對已存在的舊表補欄位：不存在才 ALTER TABLE ADD COLUMN。"""
    cols = {row["name"] for row in
            conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    _ensure_column(conn, "members", "color", "color TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "entries", "template_id",
                   "template_id INTEGER REFERENCES recurring_templates(id)")
    conn.commit()
