import pytest
from splitbook.domain.ledger import (
    Balance, Entry, LedgerImbalance, SettlementLine,
    compute_balances, simplify_debts,
)


def exp(id, name, amount, payer_id, allocations):
    return Entry(id=id, kind="expense", name=name, amount=amount,
                 payer_id=payer_id, allocations=allocations)


def txf(id, amount, from_id, to_id, transfer_kind="prepay"):
    return Entry(id=id, kind="transfer", name="轉帳", amount=amount,
                 payer_id=from_id, payee_id=to_id, transfer_kind=transfer_kind)


def test_single_expense_balances():
    b = compute_balances({1, 2, 3}, [exp(1, "民宿", 300, 1, {1: 100, 2: 100, 3: 100})])
    assert b[1].advanced == 300 and b[1].share == 100 and b[1].net == 200
    assert b[2].net == -100 and b[3].net == -100
    assert sum(x.net for x in b.values()) == 0


def test_transfer_reduces_debt():
    entries = [
        exp(1, "民宿", 6000, 1, {1: 3000, 2: 3000}),
        txf(2, 2300, from_id=2, to_id=1),
    ]
    b = compute_balances({1, 2}, entries)
    assert b[1].net == 700 and b[2].net == -700


def test_settlement_transfer_also_counts():
    # 結算轉帳就是分錄：付清後 Σnet 歸零、雙方歸零
    entries = [
        exp(1, "餐", 100, 1, {1: 50, 2: 50}),
        txf(2, 50, from_id=2, to_id=1, transfer_kind="settlement"),
    ]
    b = compute_balances({1, 2}, entries)
    assert b[1].net == 0 and b[2].net == 0


def test_unknown_payer_raises():
    with pytest.raises(LedgerImbalance):
        compute_balances({2, 3}, [exp(1, "民宿", 300, 1, {2: 150, 3: 150})])


def test_unknown_allocation_member_raises():
    with pytest.raises(LedgerImbalance):
        compute_balances({1, 2}, [exp(1, "民宿", 300, 1, {1: 150, 9: 150})])


def test_allocation_sum_mismatch_raises():
    with pytest.raises(LedgerImbalance):
        compute_balances({1, 2}, [exp(1, "民宿", 300, 1, {1: 150, 2: 100})])


def test_transfer_unknown_member_raises():
    with pytest.raises(LedgerImbalance):
        compute_balances({1}, [txf(1, 100, from_id=1, to_id=9)])


def test_simplify_debts_basic():
    assert simplify_debts({1: -100, 2: 100}) == [SettlementLine(1, 2, 100)]


def test_simplify_debts_three_people():
    assert simplify_debts({1: -200, 2: 120, 3: 80}) == [
        SettlementLine(1, 2, 120),
        SettlementLine(1, 3, 80),
    ]


def test_simplify_debts_zero_excluded():
    assert simplify_debts({1: -100, 2: 100, 3: 0}) == [SettlementLine(1, 2, 100)]
