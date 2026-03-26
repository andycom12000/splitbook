from math import floor


def simplify_debts(balances: dict[str, int]) -> list[dict]:
    """Minimize transactions to settle all debts. All amounts are integer TWD."""
    debtors = []
    creditors = []

    for person, balance in balances.items():
        if balance < 0:
            debtors.append([person, -balance])
        elif balance > 0:
            creditors.append([person, balance])

    debtors.sort(key=lambda x: -x[1])
    creditors.sort(key=lambda x: -x[1])

    transactions = []
    i, j = 0, 0
    while i < len(debtors) and j < len(creditors):
        amount = min(debtors[i][1], creditors[j][1])
        transactions.append({
            "from": debtors[i][0],
            "to": creditors[j][0],
            "amount": amount,
        })
        debtors[i][1] -= amount
        creditors[j][1] -= amount
        if debtors[i][1] == 0:
            i += 1
        if creditors[j][1] == 0:
            j += 1

    return transactions


def build_settlement_instructions(member_id: str, transactions: list[dict]) -> str:
    """Build human-readable settlement instruction for a specific member."""
    instructions = []
    for tx in transactions:
        if tx["from"] == member_id:
            instructions.append(f"轉 ${tx['amount']:,} 給 {tx['to_name']}")
        elif tx["to"] == member_id:
            instructions.append(f"收 ${tx['amount']:,} 從 {tx['from_name']}")
    return "\n".join(instructions) if instructions else "已結清"


def compute_settlement(
    members: list[dict], expenses: list[dict]
) -> dict:
    warnings = []
    totals: dict[str, dict] = {}
    for m in members:
        totals[m["id"]] = {"name": m["name"], "owed": 0, "owes": 0, "net": 0, "details": []}

    tag_index: dict[str, set[str]] = {}
    for m in members:
        for tag in m["tags"]:
            tag_index.setdefault(tag, set()).add(m["id"])

    for exp in expenses:
        participant_ids: set[str] = set()
        for tag in exp["tags"]:
            participant_ids |= tag_index.get(tag, set())

        if not participant_ids:
            warnings.append(f"帳目「{exp['name']}」的標籤匹配不到任何人，已跳過")
            continue

        n = len(participant_ids)
        per_person = floor(exp["amount"] / n)
        remainder = exp["amount"] - per_person * n

        payer_id = exp["payer_id"]
        if payer_id in totals:
            totals[payer_id]["owed"] += exp["amount"]

        for pid in participant_ids:
            share = per_person + (remainder if pid == payer_id else 0)
            if pid in totals:
                totals[pid]["owes"] += share
                totals[pid]["details"].append(
                    f"{exp['name']}：${share}（{n}人均分）"
                )

    balances = {}
    for mid, t in totals.items():
        t["net"] = t["owed"] - t["owes"]
        if t["net"] != 0 or t["owed"] > 0 or t["owes"] > 0:
            balances[mid] = t["net"]

    transactions = simplify_debts(balances)

    for tx in transactions:
        tx["from_name"] = totals[tx["from"]]["name"]
        tx["to_name"] = totals[tx["to"]]["name"]

    return {
        "member_totals": totals,
        "transactions": transactions,
        "warnings": warnings,
    }
