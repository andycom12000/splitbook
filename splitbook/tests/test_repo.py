import pytest
from splitbook.domain.ledger import SettlementLine
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


from splitbook.storage.repo import Repo


@pytest.fixture
def repo(conn):
    return Repo(conn)


@pytest.fixture
def group(repo):
    gid = repo.create_group("沖繩行")
    a = repo.add_member(gid, "小明")
    b = repo.add_member(gid, "小華")
    c = repo.add_member(gid, "小美")
    return {"gid": gid, "a": a, "b": b, "c": c}


def test_group_and_members(repo, group):
    assert repo.get_group(group["gid"])["name"] == "沖繩行"
    members = repo.list_members(group["gid"])
    assert [m["name"] for m in members] == ["小明", "小華", "小美"]


def test_record_expense_freezes_allocations(repo, group):
    g = group
    eid = repo.record_expense(
        g["gid"], "民宿", 300, g["a"],
        {g["a"]: 100, g["b"]: 100, g["c"]: 100}, category="住宿")
    entries = repo.list_entries(g["gid"])
    assert len(entries) == 1
    e = entries[0]
    assert e.kind == "expense" and e.amount == 300
    assert e.allocations == {g["a"]: 100, g["b"]: 100, g["c"]: 100}
    assert e.id == eid


def test_record_expense_rejects_bad_allocation_sum(repo, group):
    g = group
    with pytest.raises(ValueError):
        repo.record_expense(g["gid"], "民宿", 300, g["a"],
                            {g["a"]: 100, g["b"]: 100})


def test_update_expense_replaces_allocations(repo, group):
    g = group
    eid = repo.record_expense(g["gid"], "餐費", 300, g["a"],
                              {g["a"]: 150, g["b"]: 150})
    repo.update_expense(eid, "餐費(改)", 200, g["b"],
                        {g["b"]: 100, g["c"]: 100})
    e = repo.get_entry(eid)
    assert e.name == "餐費(改)" and e.amount == 200 and e.payer_id == g["b"]
    assert e.allocations == {g["b"]: 100, g["c"]: 100}


def test_soft_delete_hides_entry(repo, group):
    g = group
    eid = repo.record_expense(g["gid"], "餐費", 100, g["a"], {g["a"]: 100})
    repo.soft_delete_entry(eid)
    assert repo.list_entries(g["gid"]) == []
    # 底層資料仍在（審計軌跡）
    row = repo.conn.execute(
        "SELECT deleted_at FROM entries WHERE id = ?", (eid,)).fetchone()
    assert row["deleted_at"] is not None


def test_rev_increments_on_every_write(repo, group):
    g = group
    e1 = repo.record_expense(g["gid"], "a", 100, g["a"], {g["a"]: 100})
    e2 = repo.record_transfer(g["gid"], 50, g["b"], g["a"], "prepay")
    revs = [r["rev"] for r in repo.conn.execute(
        "SELECT rev FROM entries ORDER BY id").fetchall()]
    assert revs == [1, 2]
    repo.soft_delete_entry(e1)
    row = repo.conn.execute(
        "SELECT rev FROM entries WHERE id = ?", (e1,)).fetchone()
    assert row["rev"] == 3


def test_transfer_roundtrip(repo, group):
    g = group
    repo.record_transfer(g["gid"], 2300, g["b"], g["a"], "prepay", note="先繳")
    e = repo.list_entries(g["gid"])[0]
    assert e.kind == "transfer" and e.payer_id == g["b"] and e.payee_id == g["a"]
    assert e.transfer_kind == "prepay" and e.amount == 2300


def test_snapshot_lifecycle(repo, group):
    g = group
    repo.record_expense(g["gid"], "民宿", 300, g["a"],
                        {g["a"]: 100, g["b"]: 100, g["c"]: 100})
    lines = [SettlementLine(g["b"], g["a"], 100),
             SettlementLine(g["c"], g["a"], 100)]
    sid = repo.create_snapshot(g["gid"], lines, created_by=g["a"])
    snap = repo.latest_snapshot(g["gid"])
    assert snap.id == sid and snap.created_by == g["a"]
    assert set(snap.lines) == set(lines)
    assert repo.snapshot_is_stale(snap) is False


def test_snapshot_stale_after_expense_change(repo, group):
    g = group
    eid = repo.record_expense(g["gid"], "民宿", 300, g["a"],
                              {g["a"]: 100, g["b"]: 100, g["c"]: 100})
    sid = repo.create_snapshot(g["gid"], [SettlementLine(g["b"], g["a"], 100)])
    snap = repo.latest_snapshot(g["gid"])
    repo.soft_delete_entry(eid)  # 快照後修改帳目 → 過期
    assert repo.snapshot_is_stale(snap) is True


def test_settlement_payment_does_not_stale_snapshot(repo, group):
    g = group
    repo.record_expense(g["gid"], "民宿", 200, g["a"],
                        {g["a"]: 100, g["b"]: 100})
    sid = repo.create_snapshot(g["gid"], [SettlementLine(g["b"], g["a"], 100)])
    snap = repo.latest_snapshot(g["gid"])
    repo.record_transfer(g["gid"], 100, g["b"], g["a"], "settlement",
                         snapshot_id=sid)
    assert repo.snapshot_is_stale(snap) is False
    payments = repo.payments_for_snapshot(sid)
    assert len(payments) == 1 and payments[0].amount == 100


def test_latest_snapshot_returns_newest(repo, group):
    g = group
    repo.record_expense(g["gid"], "x", 100, g["a"], {g["a"]: 100})
    s1 = repo.create_snapshot(g["gid"], [])
    s2 = repo.create_snapshot(g["gid"], [])
    assert repo.latest_snapshot(g["gid"]).id == s2


def test_latest_snapshot_none_when_empty(repo, group):
    assert repo.latest_snapshot(group["gid"]) is None
