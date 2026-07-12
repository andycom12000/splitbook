"""帳本核心：餘額計算與轉帳最小化。守恆不變量在此強制執行。"""
from dataclasses import dataclass, field


class LedgerImbalance(Exception):
    """帳本不平衡：分攤總和錯誤、成員不明、或 Σnet != 0。"""


@dataclass(frozen=True)
class Entry:
    id: int
    kind: str                 # 'expense' | 'transfer'
    name: str
    amount: int
    payer_id: int             # expense=付款人；transfer=轉出方
    allocations: dict[int, int] = field(default_factory=dict)  # expense 專用
    payee_id: int | None = None       # transfer 專用
    transfer_kind: str = ""           # 'prepay' | 'settlement'
    category: str = ""
    date: str = ""
    note: str = ""
    created_by: int | None = None
    snapshot_id: int | None = None    # settlement 轉帳對準的快照


@dataclass
class Balance:
    advanced: int = 0    # 代墊（支出付款總額）
    share: int = 0       # 應分攤總額
    sent: int = 0        # 轉出總額
    received: int = 0    # 轉入總額

    @property
    def net(self) -> int:
        return self.advanced + self.sent - self.received - self.share


@dataclass(frozen=True)
class SettlementLine:
    from_id: int
    to_id: int
    amount: int


def compute_balances(member_ids: set[int], entries: list[Entry]) -> dict[int, Balance]:
    balances = {mid: Balance() for mid in member_ids}
    for e in entries:
        if e.kind == "expense":
            if e.payer_id not in balances:
                raise LedgerImbalance(f"分錄「{e.name}」的付款人 {e.payer_id} 不在成員名單中")
            unknown = set(e.allocations) - member_ids
            if unknown:
                raise LedgerImbalance(f"分錄「{e.name}」的分攤對象 {unknown} 不在成員名單中")
            alloc_sum = sum(e.allocations.values())
            if alloc_sum != e.amount:
                raise LedgerImbalance(
                    f"分錄「{e.name}」分攤總和 {alloc_sum} != 總金額 {e.amount}")
            balances[e.payer_id].advanced += e.amount
            for mid, a in e.allocations.items():
                balances[mid].share += a
        elif e.kind == "transfer":
            if e.payer_id not in balances or e.payee_id not in balances:
                raise LedgerImbalance(f"轉帳分錄 {e.id} 的成員不在名單中")
            balances[e.payer_id].sent += e.amount
            balances[e.payee_id].received += e.amount
        else:
            raise LedgerImbalance(f"未知的分錄類型 {e.kind!r}")
    total = sum(b.net for b in balances.values())
    if total != 0:
        raise LedgerImbalance(f"帳本不平衡：Σnet = {total}")
    return balances


def simplify_debts(nets: dict[int, int]) -> list[SettlementLine]:
    """Greedy 最小化轉帳次數。輸入為每人淨額（正=應收回，負=應付）。"""
    debtors = sorted(
        ([mid, -n] for mid, n in nets.items() if n < 0), key=lambda x: -x[1])
    creditors = sorted(
        ([mid, n] for mid, n in nets.items() if n > 0), key=lambda x: -x[1])
    lines: list[SettlementLine] = []
    i = j = 0
    while i < len(debtors) and j < len(creditors):
        amount = min(debtors[i][1], creditors[j][1])
        lines.append(SettlementLine(debtors[i][0], creditors[j][0], amount))
        debtors[i][1] -= amount
        creditors[j][1] -= amount
        if debtors[i][1] == 0:
            i += 1
        if creditors[j][1] == 0:
            j += 1
    return lines
