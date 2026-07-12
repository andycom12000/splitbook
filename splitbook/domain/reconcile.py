# splitbook/domain/reconcile.py
"""對帳：快照方案 vs 實際結算轉帳。全系統唯一一份比對語意。"""
from dataclasses import dataclass, field

from splitbook.domain.ledger import Entry, SettlementLine


@dataclass
class LineProgress:
    from_id: int
    to_id: int
    planned: int
    paid: int

    @property
    def remaining(self) -> int:
        return max(0, self.planned - self.paid)

    @property
    def status(self) -> str:
        if self.paid == 0:
            return "unpaid"
        if self.paid < self.planned:
            return "partial"
        if self.paid == self.planned:
            return "paid"
        return "overpaid"


@dataclass
class CollectorProgress:
    to_id: int
    expected: int = 0
    received: int = 0
    lines: list[LineProgress] = field(default_factory=list)


def reconcile(lines: list[SettlementLine],
              payments: list[Entry]) -> tuple[list[LineProgress], list[Entry]]:
    paid_map: dict[tuple[int, int], int] = {}
    for p in payments:
        key = (p.payer_id, p.payee_id)
        paid_map[key] = paid_map.get(key, 0) + p.amount
    line_keys = {(l.from_id, l.to_id) for l in lines}
    progress = [
        LineProgress(l.from_id, l.to_id, l.amount,
                     paid_map.get((l.from_id, l.to_id), 0))
        for l in lines
    ]
    unplanned = [p for p in payments
                 if (p.payer_id, p.payee_id) not in line_keys]
    return progress, unplanned


def by_collector(progress: list[LineProgress]) -> list[CollectorProgress]:
    collectors: dict[int, CollectorProgress] = {}
    for lp in progress:
        c = collectors.setdefault(lp.to_id, CollectorProgress(to_id=lp.to_id))
        c.expected += lp.planned
        c.received += min(lp.paid, lp.planned)
        c.lines.append(lp)
    return sorted(collectors.values(), key=lambda c: -c.expected)
