import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.settlement import compute_settlement, simplify_debts


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


def test_compute_settlement_basic():
    members = [
        {"id": "m1", "name": "Alice", "tags": ["全程"]},
        {"id": "m2", "name": "Bob", "tags": ["全程"]},
        {"id": "m3", "name": "Carol", "tags": ["全程"]},
    ]
    expenses = [
        {"id": "e1", "name": "民宿", "amount": 300, "payer_id": "m1", "tags": ["全程"]},
    ]
    result = compute_settlement(members, expenses)
    assert result["member_totals"]["m1"]["owed"] == 300
    assert result["member_totals"]["m1"]["owes"] == 100
    assert result["member_totals"]["m1"]["net"] == 200
    assert result["member_totals"]["m2"]["net"] == -100
    assert result["member_totals"]["m3"]["net"] == -100


def test_compute_settlement_floor_remainder():
    members = [
        {"id": "m1", "name": "Alice", "tags": ["全程"]},
        {"id": "m2", "name": "Bob", "tags": ["全程"]},
        {"id": "m3", "name": "Carol", "tags": ["全程"]},
    ]
    expenses = [
        {"id": "e1", "name": "餐費", "amount": 100, "payer_id": "m1", "tags": ["全程"]},
    ]
    result = compute_settlement(members, expenses)
    assert result["member_totals"]["m1"]["owes"] == 34
    assert result["member_totals"]["m1"]["owed"] == 100
    assert result["member_totals"]["m1"]["net"] == 66
    assert result["member_totals"]["m2"]["net"] == -33
    assert result["member_totals"]["m3"]["net"] == -33


def test_compute_settlement_multiple_expenses():
    members = [
        {"id": "m1", "name": "Alice", "tags": ["全程", "酒水"]},
        {"id": "m2", "name": "Bob", "tags": ["全程"]},
    ]
    expenses = [
        {"id": "e1", "name": "民宿", "amount": 200, "payer_id": "m1", "tags": ["全程"]},
        {"id": "e2", "name": "酒", "amount": 100, "payer_id": "m2", "tags": ["酒水"]},
    ]
    result = compute_settlement(members, expenses)
    assert result["member_totals"]["m1"]["net"] == 0
    assert result["member_totals"]["m2"]["net"] == 0


def test_compute_settlement_union_tags():
    members = [
        {"id": "m1", "name": "Alice", "tags": ["全程"]},
        {"id": "m2", "name": "Bob", "tags": ["全程", "酒水"]},
        {"id": "m3", "name": "Carol", "tags": ["酒水"]},
    ]
    expenses = [
        {"id": "e1", "name": "酒", "amount": 300, "payer_id": "m2", "tags": ["酒水"]},
    ]
    result = compute_settlement(members, expenses)
    assert result["member_totals"]["m2"]["owes"] == 150
    assert result["member_totals"]["m3"]["owes"] == 150
    assert result["member_totals"]["m1"]["owes"] == 0


def test_compute_settlement_zero_participants_warning():
    members = [
        {"id": "m1", "name": "Alice", "tags": ["全程"]},
    ]
    expenses = [
        {"id": "e1", "name": "VIP", "amount": 500, "payer_id": "m1", "tags": ["VIP"]},
    ]
    result = compute_settlement(members, expenses)
    assert len(result["warnings"]) > 0
    assert "VIP" in result["warnings"][0]
