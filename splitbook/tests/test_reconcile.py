# splitbook/tests/test_reconcile.py
from splitbook.domain.ledger import Entry, SettlementLine
from splitbook.domain.reconcile import reconcile, by_collector


def pay(id, amount, from_id, to_id):
    return Entry(id=id, kind="transfer", name="結算轉帳", amount=amount,
                 payer_id=from_id, payee_id=to_id, transfer_kind="settlement")


def test_exact_payment_marks_paid():
    lines = [SettlementLine(2, 1, 500)]
    progress, unplanned = reconcile(lines, [pay(1, 500, 2, 1)])
    assert progress[0].status == "paid" and progress[0].remaining == 0
    assert unplanned == []


def test_partial_and_split_payments_accumulate():
    # 分兩筆付 300 + 100，計 400/500 → partial（tripsplit 的精確比對做不到）
    lines = [SettlementLine(2, 1, 500)]
    progress, _ = reconcile(lines, [pay(1, 300, 2, 1), pay(2, 100, 2, 1)])
    assert progress[0].paid == 400
    assert progress[0].status == "partial" and progress[0].remaining == 100


def test_overpayment_flagged():
    lines = [SettlementLine(2, 1, 500)]
    progress, _ = reconcile(lines, [pay(1, 600, 2, 1)])
    assert progress[0].status == "overpaid" and progress[0].remaining == 0


def test_unplanned_payment_reported():
    lines = [SettlementLine(2, 1, 500)]
    p = pay(1, 100, 3, 1)  # 方案中沒有 3→1 這條線
    progress, unplanned = reconcile(lines, [p])
    assert unplanned == [p]
    assert progress[0].status == "unpaid"


def test_by_collector_aggregates():
    lines = [SettlementLine(2, 1, 500), SettlementLine(3, 1, 300),
             SettlementLine(3, 4, 50)]
    progress, _ = reconcile(lines, [pay(1, 500, 2, 1)])
    collectors = by_collector(progress)
    assert collectors[0].to_id == 1
    assert collectors[0].expected == 800 and collectors[0].received == 500
    assert collectors[1].to_id == 4 and collectors[1].expected == 50
