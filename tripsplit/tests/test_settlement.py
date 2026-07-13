import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.settlement import compute_settlement, simplify_debts, build_settlement_instructions, compute_payment_progress


def test_simplify_debts_basic():
    balances = {"A": -100, "B": 100}
    result = simplify_debts(balances)
    assert result == [{"from": "A", "to": "B", "amount": 100}]


def test_simplify_debts_three_people():
    balances = {"A": -200, "B": 120, "C": 80}
    result = simplify_debts(balances)
    assert result == [
        {"from": "A", "to": "B", "amount": 120},
        {"from": "A", "to": "C", "amount": 80},
    ]


def test_simplify_debts_zero_balance_excluded():
    balances = {"A": -100, "B": 100, "C": 0}
    result = simplify_debts(balances)
    assert len(result) == 1
    assert result[0] == {"from": "A", "to": "B", "amount": 100}


def test_compute_settlement_no_tags_all_participate():
    members = [
        {"id": "m1", "name": "Alice", "tags": []},
        {"id": "m2", "name": "Bob", "tags": []},
        {"id": "m3", "name": "Carol", "tags": []},
    ]
    expenses = [
        {"id": "e1", "name": "民宿", "amount": 300, "payer_id": "m1", "tags": []},
    ]
    result = compute_settlement(members, expenses)
    assert result["member_totals"]["m1"]["owed"] == 300
    assert result["member_totals"]["m1"]["owes"] == 100
    assert result["member_totals"]["m1"]["net"] == 200
    assert result["member_totals"]["m2"]["net"] == -100
    assert result["member_totals"]["m3"]["net"] == -100


def test_compute_settlement_blacklist_excludes_tagged():
    members = [
        {"id": "m1", "name": "Alice", "tags": []},
        {"id": "m2", "name": "Bob", "tags": ["不喝酒"]},
        {"id": "m3", "name": "Carol", "tags": []},
    ]
    expenses = [
        {"id": "e1", "name": "酒水", "amount": 200, "payer_id": "m1", "tags": ["不喝酒"]},
    ]
    result = compute_settlement(members, expenses)
    assert result["member_totals"]["m1"]["owes"] == 100
    assert result["member_totals"]["m3"]["owes"] == 100
    assert result["member_totals"]["m2"]["owes"] == 0


def test_compute_settlement_floor_remainder():
    members = [
        {"id": "m1", "name": "Alice", "tags": []},
        {"id": "m2", "name": "Bob", "tags": []},
        {"id": "m3", "name": "Carol", "tags": []},
    ]
    expenses = [
        {"id": "e1", "name": "餐費", "amount": 100, "payer_id": "m1", "tags": []},
    ]
    result = compute_settlement(members, expenses)
    assert result["member_totals"]["m1"]["owes"] == 34
    assert result["member_totals"]["m1"]["owed"] == 100
    assert result["member_totals"]["m1"]["net"] == 66
    assert result["member_totals"]["m2"]["net"] == -33
    assert result["member_totals"]["m3"]["net"] == -33


def test_compute_settlement_multiple_expenses():
    members = [
        {"id": "m1", "name": "Alice", "tags": []},
        {"id": "m2", "name": "Bob", "tags": ["不喝酒"]},
    ]
    expenses = [
        {"id": "e1", "name": "民宿", "amount": 200, "payer_id": "m1", "tags": []},
        {"id": "e2", "name": "酒", "amount": 100, "payer_id": "m2", "tags": ["不喝酒"]},
    ]
    result = compute_settlement(members, expenses)
    assert result["member_totals"]["m1"]["net"] == 0
    assert result["member_totals"]["m2"]["net"] == 0


def test_compute_settlement_all_excluded_warning():
    members = [
        {"id": "m1", "name": "Alice", "tags": ["不參加"]},
    ]
    expenses = [
        {"id": "e1", "name": "活動", "amount": 500, "payer_id": "m1", "tags": ["不參加"]},
    ]
    result = compute_settlement(members, expenses)
    assert len(result["warnings"]) > 0


def test_build_settlement_instructions():
    transactions = [
        {"from": "m1", "to": "m2", "amount": 100, "from_name": "Alice", "to_name": "Bob"},
        {"from": "m3", "to": "m2", "amount": 50, "from_name": "Carol", "to_name": "Bob"},
    ]
    result = build_settlement_instructions("m1", transactions)
    assert "轉 $100 給 Bob" in result

    result = build_settlement_instructions("m2", transactions)
    assert "收 $100 從 Alice" in result
    assert "收 $50 從 Carol" in result

    result = build_settlement_instructions("m4", transactions)
    assert result == "已結清"


def test_compute_settlement_payer_excluded():
    members = [
        {"id": "m1", "name": "Alice", "tags": ["不喝酒"]},
        {"id": "m2", "name": "Bob", "tags": []},
    ]
    expenses = [
        {"id": "e1", "name": "酒", "amount": 100, "payer_id": "m1", "tags": ["不喝酒"]},
    ]
    result = compute_settlement(members, expenses)
    assert result["member_totals"]["m1"]["owed"] == 100
    assert result["member_totals"]["m1"]["owes"] == 0
    assert result["member_totals"]["m1"]["net"] == 100
    assert result["member_totals"]["m2"]["owes"] == 100
    assert result["member_totals"]["m2"]["net"] == -100


def test_compute_settlement_with_transactions():
    """Transactions (prepaid) reduce what a member still owes."""
    members = [
        {"id": "m1", "name": "Alice", "tags": []},
        {"id": "m2", "name": "Bob", "tags": []},
    ]
    expenses = [
        {"id": "e1", "name": "民宿", "amount": 6000, "payer_id": "m1", "tags": []},
    ]
    transactions = [
        {"id": "t1", "from_id": "m2", "to_id": "m1", "amount": 2300, "type": "預付款", "note": "", "date": ""},
    ]
    result = compute_settlement(members, expenses, transactions)
    # Alice: owed=6000, received_in=2300, owes=3000 → net = 6000+0-2300-3000 = 700
    # Bob: paid_out=2300, owes=3000 → net = 0+2300-0-3000 = -700
    assert result["member_totals"]["m1"]["net"] == 700
    assert result["member_totals"]["m2"]["net"] == -700
    assert len(result["transactions"]) == 1
    assert result["transactions"][0]["amount"] == 700


def test_compute_payment_progress():
    settlement_txns = [
        {"from": "m1", "to": "m3", "amount": 500, "from_name": "Alice", "to_name": "Carol"},
        {"from": "m2", "to": "m3", "amount": 300, "from_name": "Bob", "to_name": "Carol"},
    ]
    payment_records = [
        {"id": "p1", "from_id": "m1", "to_id": "m3", "amount": 500, "type": "結算轉帳", "note": "", "date": ""},
    ]
    members_by_id = {
        "m1": {"name": "Alice"},
        "m2": {"name": "Bob"},
        "m3": {"name": "Carol"},
    }
    progress = compute_payment_progress(settlement_txns, payment_records, members_by_id)
    assert len(progress["collectors"]) == 1
    assert progress["collectors"][0]["name"] == "Carol"
    assert progress["collectors"][0]["expected"] == 800
    assert progress["collectors"][0]["received"] == 500
    assert progress["total_expected"] == 800
    assert progress["total_received"] == 500
    # Check individual payment status
    payments = progress["collectors"][0]["payments"]
    alice_payment = next(p for p in payments if p["from_name"] == "Alice")
    assert alice_payment["paid"] is True
    assert alice_payment["txn_id"] == "p1"
    bob_payment = next(p for p in payments if p["from_name"] == "Bob")
    assert bob_payment["paid"] is False
