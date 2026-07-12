import pytest
from splitbook.storage.db import connect, init_db


@pytest.fixture
def conn():
    c = connect(":memory:")
    init_db(c)
    yield c
    c.close()


def test_schema_tables_exist(conn):
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    names = {r["name"] for r in rows}
    assert {"groups", "members", "entries", "allocations",
            "snapshots", "snapshot_lines"} <= names


def test_foreign_keys_enforced(conn):
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO members (group_id, name) VALUES (999, 'x')")


def test_init_db_idempotent(conn):
    init_db(conn)  # 不應 raise
