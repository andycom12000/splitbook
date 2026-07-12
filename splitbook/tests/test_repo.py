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


def test_get_entry_wrong_group_id_returns_none(repo, group):
    g = group
    eid = repo.record_expense(g["gid"], "餐費", 100, g["a"], {g["a"]: 100})
    other_gid = repo.create_group("北海道行")
    assert repo.get_entry(eid, other_gid) is None
    assert repo.get_entry(eid, g["gid"]) is not None


def test_update_expense_wrong_group_id_raises(repo, group):
    g = group
    eid = repo.record_expense(g["gid"], "餐費", 100, g["a"], {g["a"]: 100})
    other_gid = repo.create_group("北海道行")
    with pytest.raises(ValueError):
        repo.update_expense(eid, "改", 100, g["a"], {g["a"]: 100},
                            group_id=other_gid)


def test_soft_delete_entry_wrong_group_id_raises(repo, group):
    g = group
    eid = repo.record_expense(g["gid"], "餐費", 100, g["a"], {g["a"]: 100})
    other_gid = repo.create_group("北海道行")
    with pytest.raises(ValueError):
        repo.soft_delete_entry(eid, group_id=other_gid)


def test_record_expense_rejects_foreign_allocation_member(repo, group):
    g = group
    other_gid = repo.create_group("北海道行")
    foreign = repo.add_member(other_gid, "阿強")
    with pytest.raises(ValueError, match="不屬於此帳本"):
        repo.record_expense(g["gid"], "民宿", 200, g["a"],
                            {g["a"]: 100, foreign: 100})


def test_record_transfer_rejects_foreign_to_id(repo, group):
    g = group
    other_gid = repo.create_group("北海道行")
    foreign = repo.add_member(other_gid, "阿強")
    with pytest.raises(ValueError, match="不屬於此帳本"):
        repo.record_transfer(g["gid"], 100, g["a"], foreign, "prepay")


# -- member color -------------------------------------------------------

def test_add_member_with_color_readable_via_list_members(repo):
    gid = repo.create_group("測試")
    mid = repo.add_member(gid, "小明", color="#ff0000")
    members = repo.list_members(gid)
    assert members[0]["color"] == "#ff0000"


def test_set_member_color(repo, group):
    g = group
    repo.set_member_color(g["a"], "#00ff00")
    m = repo.get_member(g["a"])
    assert m["color"] == "#00ff00"


# -- shopping items -------------------------------------------------------

def test_add_shopping_item_appears_in_open_list(repo, group):
    g = group
    iid = repo.add_shopping_item(g["gid"], "醬油", g["a"], estimate=100)
    open_items = repo.list_open_items(g["gid"])
    assert len(open_items) == 1
    assert open_items[0]["id"] == iid
    assert open_items[0]["name"] == "醬油"
    assert open_items[0]["estimate"] == 100


def test_add_shopping_item_rejects_foreign_added_by(repo, group):
    g = group
    other_gid = repo.create_group("北海道行")
    foreign = repo.add_member(other_gid, "阿強")
    with pytest.raises(ValueError, match="不屬於此帳本"):
        repo.add_shopping_item(g["gid"], "醬油", foreign)


def test_add_shopping_item_rejects_nonpositive_estimate(repo, group):
    g = group
    with pytest.raises(ValueError, match="預估金額必須為正整數"):
        repo.add_shopping_item(g["gid"], "醬油", g["a"], estimate=0)


def test_mark_items_bought_links_entry_and_moves_to_bought(repo, group):
    g = group
    i1 = repo.add_shopping_item(g["gid"], "醬油", g["a"])
    i2 = repo.add_shopping_item(g["gid"], "味噌", g["a"])
    eid = repo.record_expense(g["gid"], "超市", 300, g["a"], {g["a"]: 300})
    repo.mark_items_bought(g["gid"], [i1, i2], eid)

    open_items = repo.list_open_items(g["gid"])
    assert open_items == []

    bought = repo.list_bought_items(g["gid"])
    assert {r["id"] for r in bought} == {i1, i2}
    for r in bought:
        assert r["entry_id"] == eid
        assert r["bought_at"] is not None


def test_mark_items_bought_rejects_item_from_other_group(repo, group):
    g = group
    other_gid = repo.create_group("北海道行")
    other_member = repo.add_member(other_gid, "阿強")
    foreign_item = repo.add_shopping_item(other_gid, "螃蟹", other_member)
    with pytest.raises(ValueError, match="無法結帳"):
        repo.mark_items_bought(g["gid"], [foreign_item], None)


def test_mark_items_bought_rejects_already_bought_item(repo, group):
    g = group
    iid = repo.add_shopping_item(g["gid"], "醬油", g["a"])
    repo.mark_items_bought(g["gid"], [iid], None)
    with pytest.raises(ValueError, match="無法結帳"):
        repo.mark_items_bought(g["gid"], [iid], None)


def test_delete_shopping_item_removes_from_open_list(repo, group):
    g = group
    iid = repo.add_shopping_item(g["gid"], "醬油", g["a"])
    repo.delete_shopping_item(iid, g["gid"])
    assert repo.list_open_items(g["gid"]) == []


def test_delete_shopping_item_not_found_raises(repo, group):
    g = group
    with pytest.raises(ValueError, match="找不到清單項目"):
        repo.delete_shopping_item(99999, g["gid"])


def test_get_items_only_returns_open_items_of_group(repo, group):
    g = group
    i1 = repo.add_shopping_item(g["gid"], "醬油", g["a"])
    other_gid = repo.create_group("北海道行")
    other_member = repo.add_member(other_gid, "阿強")
    i2 = repo.add_shopping_item(other_gid, "螃蟹", other_member)
    result = repo.get_items(g["gid"], [i1, i2])
    assert {r["id"] for r in result} == {i1}


# -- recurring templates ---------------------------------------------------

def test_add_template_and_due_templates_includes_today(repo, group):
    g = group
    tid = repo.add_template(g["gid"], "房租", g["a"], "monthly", 1,
                            next_due="2026-07-12", amount=10000)
    due = repo.due_templates(g["gid"], today="2026-07-12")
    assert [r["id"] for r in due] == [tid]


def test_due_templates_excludes_future(repo, group):
    g = group
    repo.add_template(g["gid"], "房租", g["a"], "monthly", 1,
                      next_due="2026-08-01", amount=10000)
    due = repo.due_templates(g["gid"], today="2026-07-12")
    assert due == []


def test_due_templates_excludes_inactive(repo, group):
    g = group
    tid = repo.add_template(g["gid"], "房租", g["a"], "monthly", 1,
                            next_due="2026-07-12", amount=10000)
    repo.set_template_active(tid, g["gid"], False)
    due = repo.due_templates(g["gid"], today="2026-07-12")
    assert due == []


def test_add_template_with_null_amount(repo, group):
    g = group
    tid = repo.add_template(g["gid"], "電費", g["a"], "monthly", 5,
                            next_due="2026-07-05")
    t = repo.get_template(tid, g["gid"])
    assert t["amount"] is None


def test_add_template_rejects_nonpositive_amount(repo, group):
    g = group
    with pytest.raises(ValueError, match="金額必須為正整數"):
        repo.add_template(g["gid"], "房租", g["a"], "monthly", 1,
                          next_due="2026-07-12", amount=0)


def test_add_template_rejects_foreign_payer(repo, group):
    g = group
    other_gid = repo.create_group("北海道行")
    foreign = repo.add_member(other_gid, "阿強")
    with pytest.raises(ValueError, match="不屬於此帳本"):
        repo.add_template(g["gid"], "房租", foreign, "monthly", 1,
                          next_due="2026-07-12", amount=10000)


def test_advance_template_moves_next_due_forward(repo, group):
    g = group
    tid = repo.add_template(g["gid"], "房租", g["a"], "monthly", 31,
                            next_due="2026-01-31", amount=10000)
    new_due = repo.advance_template(tid, g["gid"])
    assert new_due == "2026-02-28"
    t = repo.get_template(tid, g["gid"])
    assert t["next_due"] == "2026-02-28"


def test_advance_template_not_found_raises(repo, group):
    g = group
    with pytest.raises(ValueError, match="找不到定期項目"):
        repo.advance_template(99999, g["gid"])


def test_set_template_active_not_found_raises(repo, group):
    g = group
    with pytest.raises(ValueError, match="找不到定期項目"):
        repo.set_template_active(99999, g["gid"], False)


def test_get_template_wrong_group_returns_none(repo, group):
    g = group
    tid = repo.add_template(g["gid"], "房租", g["a"], "monthly", 1,
                            next_due="2026-07-12", amount=10000)
    other_gid = repo.create_group("北海道行")
    assert repo.get_template(tid, other_gid) is None


def test_list_templates_ordered_by_next_due(repo, group):
    g = group
    t2 = repo.add_template(g["gid"], "水費", g["a"], "monthly", 1,
                           next_due="2026-08-01", amount=500)
    t1 = repo.add_template(g["gid"], "房租", g["a"], "monthly", 1,
                           next_due="2026-07-12", amount=10000)
    templates = repo.list_templates(g["gid"])
    assert [r["id"] for r in templates] == [t1, t2]


# -- expense/template linkage ----------------------------------------------

def test_record_expense_links_template_id(repo, group):
    g = group
    tid = repo.add_template(g["gid"], "房租", g["a"], "monthly", 1,
                            next_due="2026-07-12", amount=10000)
    eid = repo.record_expense(g["gid"], "房租", 10000, g["a"],
                              {g["a"]: 5000, g["b"]: 5000, g["c"]: 0},
                              template_id=tid)
    row = repo.conn.execute(
        "SELECT template_id FROM entries WHERE id = ?", (eid,)).fetchone()
    assert row["template_id"] == tid


# -- migration --------------------------------------------------------------

def test_migration_adds_new_columns_to_legacy_db():
    import sqlite3
    from splitbook.storage.db import init_db

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE groups (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        );
        CREATE TABLE members (
            id INTEGER PRIMARY KEY,
            group_id INTEGER NOT NULL REFERENCES groups(id),
            name TEXT NOT NULL,
            pin_hash TEXT,
            active INTEGER NOT NULL DEFAULT 1,
            UNIQUE (group_id, name)
        );
        CREATE TABLE entries (
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
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            deleted_at TEXT
        );
        """)
    conn.commit()

    init_db(conn)

    member_cols = {r["name"] for r in
                   conn.execute("PRAGMA table_info(members)").fetchall()}
    entry_cols = {r["name"] for r in
                  conn.execute("PRAGMA table_info(entries)").fetchall()}
    assert "color" in member_cols
    assert "template_id" in entry_cols
    conn.close()
