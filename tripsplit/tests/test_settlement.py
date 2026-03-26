import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.settlement import compute_settlement, simplify_debts, build_settlement_instructions


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
    """No exclusion tags = everyone participates"""
    members = [
        {"id": "m1", "name": "Alice", "tags": [], "prepaid": 0},
        {"id": "m2", "name": "Bob", "tags": [], "prepaid": 0},
        {"id": "m3", "name": "Carol", "tags": [], "prepaid": 0},
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
    """Expense with exclusion tag excludes members who have that tag"""
    members = [
        {"id": "m1", "name": "Alice", "tags": [], "prepaid": 0},
        {"id": "m2", "name": "Bob", "tags": ["不喝酒"], "prepaid": 0},
        {"id": "m3", "name": "Carol", "tags": [], "prepaid": 0},
    ]
    expenses = [
        {"id": "e1", "name": "酒水", "amount": 200, "payer_id": "m1", "tags": ["不喝酒"]},
    ]
    result = compute_settlement(members, expenses)
    # Bob is excluded (has 不喝酒 tag), only Alice and Carol participate
    assert result["member_totals"]["m1"]["owes"] == 100
    assert result["member_totals"]["m3"]["owes"] == 100
    assert result["member_totals"]["m2"]["owes"] == 0  # excluded


def test_compute_settlement_floor_remainder():
    """floor(100/3)=33, remainder 1 absorbed by payer"""
    members = [
        {"id": "m1", "name": "Alice", "tags": [], "prepaid": 0},
        {"id": "m2", "name": "Bob", "tags": [], "prepaid": 0},
        {"id": "m3", "name": "Carol", "tags": [], "prepaid": 0},
    ]
    expenses = [
        {"id": "e1", "name": "餐費", "amount": 100, "payer_id": "m1", "tags": []},
    ]
    result = compute_settlement(members, expenses)
    assert result["member_totals"]["m1"]["owes"] == 34  # 33 + 1 remainder
    assert result["member_totals"]["m1"]["owed"] == 100
    assert result["member_totals"]["m1"]["net"] == 66
    assert result["member_totals"]["m2"]["net"] == -33
    assert result["member_totals"]["m3"]["net"] == -33


def test_compute_settlement_multiple_expenses():
    """Multiple expenses accumulate correctly"""
    members = [
        {"id": "m1", "name": "Alice", "tags": [], "prepaid": 0},
        {"id": "m2", "name": "Bob", "tags": ["不喝酒"], "prepaid": 0},
    ]
    expenses = [
        {"id": "e1", "name": "民宿", "amount": 200, "payer_id": "m1", "tags": []},
        {"id": "e2", "name": "酒", "amount": 100, "payer_id": "m2", "tags": ["不喝酒"]},
    ]
    result = compute_settlement(members, expenses)
    # 民宿: no exclusion, 200/2=100 each. Alice paid 200.
    # 酒: exclude 不喝酒 (Bob), only Alice. 100/1=100. Bob paid 100.
    # Alice: owed 200, owes 100+100=200, net=0
    # Bob: owed 100, owes 100, net=0
    assert result["member_totals"]["m1"]["net"] == 0
    assert result["member_totals"]["m2"]["net"] == 0


def test_compute_settlement_all_excluded_warning():
    """If all members are excluded, skip with warning"""
    members = [
        {"id": "m1", "name": "Alice", "tags": ["不參加"], "prepaid": 0},
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
    """Payer is excluded from participants — still gets credited"""
    members = [
        {"id": "m1", "name": "Alice", "tags": ["不喝酒"], "prepaid": 0},
        {"id": "m2", "name": "Bob", "tags": [], "prepaid": 0},
    ]
    expenses = [
        {"id": "e1", "name": "酒", "amount": 100, "payer_id": "m1", "tags": ["不喝酒"]},
    ]
    result = compute_settlement(members, expenses)
    # Alice excluded but paid -> owed 100, owes 0, net +100
    # Bob participates -> owes 100, net -100
    assert result["member_totals"]["m1"]["owed"] == 100
    assert result["member_totals"]["m1"]["owes"] == 0
    assert result["member_totals"]["m1"]["net"] == 100
    assert result["member_totals"]["m2"]["owes"] == 100
    assert result["member_totals"]["m2"]["net"] == -100


def test_compute_settlement_prepaid_reduces_balance():
    """Prepaid amount reduces what a member still owes"""
    members = [
        {"id": "m1", "name": "Alice", "tags": [], "prepaid": 0},
        {"id": "m2", "name": "Bob", "tags": [], "prepaid": 2300},
    ]
    expenses = [
        {"id": "e1", "name": "民宿", "amount": 6000, "payer_id": "m1", "tags": []},
    ]
    result = compute_settlement(members, expenses)
    # 6000/2 = 3000 each. Alice paid 6000, owes 3000, net = +3000
    # Bob owes 3000, prepaid 2300, net = 0 + 2300 - 3000 = -700
    assert result["member_totals"]["m1"]["net"] == 3000
    assert result["member_totals"]["m2"]["net"] == -700
    # Transaction: Bob pays Alice $700 (not $3000)
    assert len(result["transactions"]) == 1
    assert result["transactions"][0]["amount"] == 700
