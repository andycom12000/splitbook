"""Repository：所有 SQLite 存取集中於此。寫入時固化分攤、單調 rev 序號。"""
import sqlite3
import threading
from dataclasses import dataclass
from datetime import date

from splitbook.domain import recurrence
from splitbook.domain.ledger import Entry, SettlementLine


@dataclass(frozen=True)
class Snapshot:
    id: int
    group_id: int
    through_rev: int
    created_by: int | None
    created_at: str
    lines: list[SettlementLine]


class Repo:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self._write_lock = threading.Lock()

    def _assert_members(self, group_id: int, member_ids) -> None:
        """驗證 member_ids 全部屬於該帳本（含 inactive）；否則 raise ValueError。"""
        wanted = set(member_ids)
        if not wanted:
            return
        rows = self.conn.execute(
            "SELECT id FROM members WHERE group_id = ?", (group_id,)).fetchall()
        known = {r["id"] for r in rows}
        unknown = wanted - known
        if unknown:
            raise ValueError(f"成員 {sorted(unknown)} 不屬於此帳本")

    # -- groups -------------------------------------------------------
    def create_group(self, name: str) -> int:
        with self._write_lock, self.conn:
            cur = self.conn.execute(
                "INSERT INTO groups (name) VALUES (?)", (name,))
        return cur.lastrowid

    def list_groups(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM groups ORDER BY id").fetchall()

    def get_group(self, group_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM groups WHERE id = ?", (group_id,)).fetchone()

    # -- members ------------------------------------------------------
    def add_member(self, group_id: int, name: str, color: str = "") -> int:
        with self._write_lock, self.conn:
            cur = self.conn.execute(
                "INSERT INTO members (group_id, name, color) VALUES (?, ?, ?)",
                (group_id, name, color))
        return cur.lastrowid

    def set_member_color(self, member_id: int, color: str) -> None:
        with self._write_lock, self.conn:
            self.conn.execute(
                "UPDATE members SET color = ? WHERE id = ?",
                (color, member_id))

    def list_members(self, group_id: int,
                     include_inactive: bool = False) -> list[sqlite3.Row]:
        sql = "SELECT * FROM members WHERE group_id = ?"
        if not include_inactive:
            sql += " AND active = 1"
        return self.conn.execute(sql + " ORDER BY id", (group_id,)).fetchall()

    def get_member(self, member_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM members WHERE id = ?", (member_id,)).fetchone()

    def set_pin_hash(self, member_id: int, pin_hash: str) -> None:
        with self._write_lock, self.conn:
            self.conn.execute(
                "UPDATE members SET pin_hash = ? WHERE id = ?",
                (pin_hash, member_id))

    def set_member_active(self, member_id: int, active: bool) -> None:
        with self._write_lock, self.conn:
            self.conn.execute(
                "UPDATE members SET active = ? WHERE id = ?",
                (1 if active else 0, member_id))

    # -- entries ------------------------------------------------------
    def _next_rev(self, group_id: int) -> int:
        row = self.conn.execute(
            "SELECT COALESCE(MAX(rev), 0) + 1 AS r FROM entries WHERE group_id = ?",
            (group_id,)).fetchone()
        return row["r"]

    def record_expense(self, group_id: int, name: str, amount: int,
                       payer_id: int, allocations: dict[int, int],
                       category: str = "", date: str = "", note: str = "",
                       created_by: int | None = None,
                       template_id: int | None = None) -> int:
        if sum(allocations.values()) != amount:
            raise ValueError(
                f"分攤總和 {sum(allocations.values())} 不等於總金額 {amount}")
        if amount == 0:
            raise ValueError("金額不可為 0")
        self._assert_members(group_id, {payer_id} | set(allocations))
        with self._write_lock, self.conn:
            cur = self.conn.execute(
                """INSERT INTO entries
                   (group_id, rev, kind, name, amount, payer_id, category,
                    date, note, created_by, template_id)
                   VALUES (?, ?, 'expense', ?, ?, ?, ?,
                           COALESCE(?, date('now', 'localtime')), ?, ?, ?)""",
                (group_id, self._next_rev(group_id), name, amount, payer_id,
                 category, date or None, note, created_by, template_id))
            eid = cur.lastrowid
            self.conn.executemany(
                "INSERT INTO allocations (entry_id, member_id, amount) VALUES (?, ?, ?)",
                [(eid, mid, a) for mid, a in allocations.items()])
        return eid

    def record_transfer(self, group_id: int, amount: int, from_id: int,
                        to_id: int, transfer_kind: str, name: str = "轉帳",
                        date: str = "", note: str = "",
                        created_by: int | None = None,
                        snapshot_id: int | None = None) -> int:
        if amount <= 0:
            raise ValueError("轉帳金額必須為正整數")
        if from_id == to_id:
            raise ValueError("轉出方與轉入方不可相同")
        self._assert_members(group_id, {from_id, to_id})
        with self._write_lock, self.conn:
            cur = self.conn.execute(
                """INSERT INTO entries
                   (group_id, rev, kind, name, amount, payer_id, payee_id,
                    transfer_kind, date, note, created_by, snapshot_id)
                   VALUES (?, ?, 'transfer', ?, ?, ?, ?, ?,
                           COALESCE(?, date('now', 'localtime')), ?, ?, ?)""",
                (group_id, self._next_rev(group_id), name, amount, from_id,
                 to_id, transfer_kind, date or None, note, created_by,
                 snapshot_id))
        return cur.lastrowid

    def update_expense(self, entry_id: int, name: str, amount: int,
                       payer_id: int, allocations: dict[int, int],
                       category: str = "", date: str = "",
                       note: str = "", group_id: int | None = None) -> None:
        if sum(allocations.values()) != amount:
            raise ValueError(
                f"分攤總和 {sum(allocations.values())} 不等於總金額 {amount}")
        row = self.conn.execute(
            "SELECT group_id, kind, deleted_at FROM entries WHERE id = ?",
            (entry_id,)).fetchone()
        if (row is None or row["kind"] != "expense" or row["deleted_at"]
                or (group_id is not None and row["group_id"] != group_id)):
            raise ValueError(f"找不到可編輯的支出分錄 {entry_id}")
        self._assert_members(row["group_id"], {payer_id} | set(allocations))
        with self._write_lock, self.conn:
            self.conn.execute(
                """UPDATE entries SET rev = ?, name = ?, amount = ?,
                   payer_id = ?, category = ?, note = ?,
                   date = COALESCE(?, date)
                   WHERE id = ?""",
                (self._next_rev(row["group_id"]), name, amount, payer_id,
                 category, note, date or None, entry_id))
            self.conn.execute(
                "DELETE FROM allocations WHERE entry_id = ?", (entry_id,))
            self.conn.executemany(
                "INSERT INTO allocations (entry_id, member_id, amount) VALUES (?, ?, ?)",
                [(entry_id, mid, a) for mid, a in allocations.items()])

    def soft_delete_entry(self, entry_id: int,
                          group_id: int | None = None) -> None:
        row = self.conn.execute(
            "SELECT group_id, deleted_at FROM entries WHERE id = ?",
            (entry_id,)).fetchone()
        if (row is None or row["deleted_at"]
                or (group_id is not None and row["group_id"] != group_id)):
            raise ValueError(f"找不到分錄 {entry_id}")
        with self._write_lock, self.conn:
            self.conn.execute(
                """UPDATE entries SET rev = ?,
                   deleted_at = datetime('now', 'localtime')
                   WHERE id = ?""",
                (self._next_rev(row["group_id"]), entry_id))

    def _rows_to_entries(self, rows: list[sqlite3.Row]) -> list[Entry]:
        expense_ids = [r["id"] for r in rows if r["kind"] == "expense"]
        alloc_map: dict[int, dict[int, int]] = {eid: {} for eid in expense_ids}
        if expense_ids:
            ph = ",".join("?" * len(expense_ids))
            for a in self.conn.execute(
                    f"SELECT * FROM allocations WHERE entry_id IN ({ph})",
                    expense_ids):
                alloc_map[a["entry_id"]][a["member_id"]] = a["amount"]
        return [Entry(
            id=r["id"], kind=r["kind"], name=r["name"], amount=r["amount"],
            payer_id=r["payer_id"], payee_id=r["payee_id"],
            allocations=alloc_map.get(r["id"], {}),
            transfer_kind=r["transfer_kind"], category=r["category"],
            date=r["date"], note=r["note"], created_by=r["created_by"],
            snapshot_id=r["snapshot_id"]) for r in rows]

    def list_entries(self, group_id: int) -> list[Entry]:
        rows = self.conn.execute(
            "SELECT * FROM entries WHERE group_id = ? AND deleted_at IS NULL "
            "ORDER BY id", (group_id,)).fetchall()
        return self._rows_to_entries(rows)

    def get_entry(self, entry_id: int,
                  group_id: int | None = None) -> Entry | None:
        sql = "SELECT * FROM entries WHERE id = ? AND deleted_at IS NULL"
        params = [entry_id]
        if group_id is not None:
            sql += " AND group_id = ?"
            params.append(group_id)
        row = self.conn.execute(sql, params).fetchone()
        if row is None:
            return None
        return self._rows_to_entries([row])[0]

    # -- snapshots ----------------------------------------------------
    def create_snapshot(self, group_id: int, lines: list[SettlementLine],
                        created_by: int | None = None) -> int:
        with self._write_lock, self.conn:
            row = self.conn.execute(
                "SELECT COALESCE(MAX(rev), 0) AS r FROM entries "
                "WHERE group_id = ?", (group_id,)).fetchone()
            cur = self.conn.execute(
                "INSERT INTO snapshots (group_id, through_rev, created_by) "
                "VALUES (?, ?, ?)",
                (group_id, row["r"], created_by))
            sid = cur.lastrowid
            self.conn.executemany(
                "INSERT INTO snapshot_lines "
                "(snapshot_id, from_member, to_member, amount) "
                "VALUES (?, ?, ?, ?)",
                [(sid, l.from_id, l.to_id, l.amount) for l in lines])
        return sid

    def latest_snapshot(self, group_id: int) -> Snapshot | None:
        row = self.conn.execute(
            "SELECT * FROM snapshots WHERE group_id = ? "
            "ORDER BY id DESC LIMIT 1", (group_id,)).fetchone()
        if row is None:
            return None
        lines = [SettlementLine(r["from_member"], r["to_member"], r["amount"])
                 for r in self.conn.execute(
                     "SELECT * FROM snapshot_lines WHERE snapshot_id = ?",
                     (row["id"],))]
        return Snapshot(id=row["id"], group_id=row["group_id"],
                        through_rev=row["through_rev"],
                        created_by=row["created_by"],
                        created_at=row["created_at"], lines=lines)

    def snapshot_is_stale(self, snapshot: Snapshot) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM entries WHERE group_id = ? AND rev > ? "
            "AND NOT (kind = 'transfer' AND transfer_kind = 'settlement') "
            "LIMIT 1",
            (snapshot.group_id, snapshot.through_rev)).fetchone()
        return row is not None

    def payments_for_snapshot(self, snapshot_id: int) -> list[Entry]:
        rows = self.conn.execute(
            "SELECT * FROM entries WHERE snapshot_id = ? "
            "AND transfer_kind = 'settlement' AND deleted_at IS NULL "
            "ORDER BY id", (snapshot_id,)).fetchall()
        return self._rows_to_entries(rows)

    # -- shopping items -------------------------------------------------
    def add_shopping_item(self, group_id: int, name: str, added_by: int,
                          estimate: int | None = None,
                          note: str = "") -> int:
        self._assert_members(group_id, {added_by})
        if estimate is not None and estimate <= 0:
            raise ValueError("預估金額必須為正整數")
        with self._write_lock, self.conn:
            cur = self.conn.execute(
                """INSERT INTO shopping_items
                   (group_id, name, note, estimate, added_by)
                   VALUES (?, ?, ?, ?, ?)""",
                (group_id, name, note, estimate, added_by))
        return cur.lastrowid

    def list_open_items(self, group_id: int) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM shopping_items WHERE group_id = ? "
            "AND deleted_at IS NULL AND bought_at IS NULL "
            "ORDER BY id", (group_id,)).fetchall()

    def list_bought_items(self, group_id: int,
                          days: int = 7) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM shopping_items WHERE group_id = ? "
            "AND deleted_at IS NULL AND bought_at IS NOT NULL "
            "AND bought_at >= datetime('now', 'localtime', ?) "
            "ORDER BY bought_at DESC, id DESC",
            (group_id, f"-{days} days")).fetchall()

    def get_items(self, group_id: int,
                  item_ids: list[int]) -> list[sqlite3.Row]:
        if not item_ids:
            return []
        ph = ",".join("?" * len(item_ids))
        return self.conn.execute(
            f"SELECT * FROM shopping_items WHERE group_id = ? "
            f"AND deleted_at IS NULL AND bought_at IS NULL "
            f"AND id IN ({ph}) ORDER BY id",
            (group_id, *item_ids)).fetchall()

    def mark_items_bought(self, group_id: int, item_ids: list[int],
                          entry_id: int | None) -> None:
        wanted = set(item_ids)
        if not wanted:
            return
        valid = {r["id"] for r in self.get_items(group_id, list(wanted))}
        invalid = wanted - valid
        if invalid:
            raise ValueError(f"清單項目 {sorted(invalid)} 無法結帳")
        with self._write_lock, self.conn:
            ph = ",".join("?" * len(item_ids))
            self.conn.execute(
                f"""UPDATE shopping_items
                    SET bought_at = datetime('now', 'localtime'),
                        entry_id = ?
                    WHERE id IN ({ph})""",
                (entry_id, *item_ids))

    def delete_shopping_item(self, item_id: int, group_id: int) -> None:
        row = self.conn.execute(
            "SELECT id FROM shopping_items WHERE id = ? AND group_id = ? "
            "AND deleted_at IS NULL", (item_id, group_id)).fetchone()
        if row is None:
            raise ValueError(f"找不到清單項目 {item_id}")
        with self._write_lock, self.conn:
            self.conn.execute(
                "UPDATE shopping_items SET deleted_at = datetime('now', 'localtime') "
                "WHERE id = ?", (item_id,))

    # -- recurring templates ----------------------------------------------
    def add_template(self, group_id: int, name: str, payer_id: int,
                     cycle: str, cycle_day: int, next_due: str,
                     amount: int | None = None, category: str = "",
                     split_kind: str = "equal",
                     split_data: str = "{}") -> int:
        self._assert_members(group_id, {payer_id})
        if amount is not None and amount <= 0:
            raise ValueError("金額必須為正整數")
        with self._write_lock, self.conn:
            cur = self.conn.execute(
                """INSERT INTO recurring_templates
                   (group_id, name, category, amount, payer_id, split_kind,
                    split_data, cycle, cycle_day, next_due)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (group_id, name, category, amount, payer_id, split_kind,
                 split_data, cycle, cycle_day, next_due))
        return cur.lastrowid

    def list_templates(self, group_id: int,
                       include_inactive: bool = False) -> list[sqlite3.Row]:
        sql = "SELECT * FROM recurring_templates WHERE group_id = ?"
        if not include_inactive:
            sql += " AND active = 1"
        return self.conn.execute(
            sql + " ORDER BY next_due, id", (group_id,)).fetchall()

    def get_template(self, template_id: int,
                     group_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM recurring_templates WHERE id = ? AND group_id = ?",
            (template_id, group_id)).fetchone()

    def set_template_active(self, template_id: int, group_id: int,
                            active: bool) -> None:
        row = self.get_template(template_id, group_id)
        if row is None:
            raise ValueError(f"找不到定期項目 {template_id}")
        with self._write_lock, self.conn:
            self.conn.execute(
                "UPDATE recurring_templates SET active = ? WHERE id = ?",
                (1 if active else 0, template_id))

    def due_templates(self, group_id: int, today: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM recurring_templates WHERE group_id = ? "
            "AND active = 1 AND next_due <= ? ORDER BY next_due, id",
            (group_id, today)).fetchall()

    def advance_template(self, template_id: int, group_id: int) -> str:
        row = self.get_template(template_id, group_id)
        if row is None:
            raise ValueError(f"找不到定期項目 {template_id}")
        new_due = recurrence.advance_due(
            date.fromisoformat(row["next_due"]), row["cycle"],
            row["cycle_day"])
        new_due_str = new_due.isoformat()
        with self._write_lock, self.conn:
            self.conn.execute(
                "UPDATE recurring_templates SET next_due = ? WHERE id = ?",
                (new_due_str, template_id))
        return new_due_str
