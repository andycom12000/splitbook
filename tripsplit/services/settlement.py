
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


def build_settlement_instructions(
    member_id: str, transactions: list[dict], paid_map: dict[tuple, int] | None = None,
) -> str:
    """Build human-readable settlement instruction for a specific member.

    paid_map: dict mapping (from_id, to_id) to total paid amount from 結算轉帳.
    """
    if paid_map is None:
        paid_map = {}
    instructions = []
    for tx in transactions:
        paid_amount = paid_map.get((tx["from"], tx["to"]), 0)
        if paid_amount >= tx["amount"]:
            mark = " ✅ 已付"
        elif paid_amount > 0:
            diff = tx["amount"] - paid_amount
            mark = f" ⏳ 已付${paid_amount:,}，差${diff:,}"
        else:
            mark = ""
        if tx["from"] == member_id:
            instructions.append(f"轉 ${tx['amount']:,} 給 {tx['to_name']}{mark}")
        elif tx["to"] == member_id:
            instructions.append(f"收 ${tx['amount']:,} 從 {tx['from_name']}{mark}")
    return "\n".join(instructions) if instructions else "已結清"


def compute_settlement(
    members: list[dict], expenses: list[dict], transactions: list[dict] | None = None
) -> dict:
    """
    Compute settlement with double-entry transaction support.

    Money flows:
    - Expenses: payer advances money for the group (owed)
    - Transactions: member-to-member transfers (prepaid to organizer, etc.)

    Formula per member:
        net = owed + paid_out - received_in - owes
    where:
        owed        = total expenses this member paid for
        paid_out    = sum of transactions FROM this member
        received_in = sum of transactions TO this member
        owes        = this member's share of all expenses
    """
    if transactions is None:
        transactions = []

    # Only use prepaid/代墊 transactions for settlement; exclude 結算轉帳 (actual payments)
    transactions = [t for t in transactions if t.get("type") != "結算轉帳"]

    warnings = []
    totals: dict[str, dict] = {}
    for m in members:
        totals[m["id"]] = {
            "name": m["name"],
            "owed": 0,
            "owes": 0,
            "paid_out": 0,
            "received_in": 0,
            "net": 0,
            "details": [],
        }

    all_member_ids = set(m["id"] for m in members)

    # --- Process transactions (prepaid, etc.) ---
    for txn in transactions:
        from_id = txn["from_id"]
        to_id = txn["to_id"]
        amount = txn["amount"]
        if from_id in totals:
            totals[from_id]["paid_out"] += amount
            totals[from_id]["details"].append(f"已預繳：-${amount:,}")
        if to_id in totals:
            totals[to_id]["received_in"] += amount

    # --- Process expenses (same as before) ---
    tag_index: dict[str, set[str]] = {}
    for m in members:
        for tag in m["tags"]:
            tag_index.setdefault(tag, set()).add(m["id"])

    for exp in expenses:
        if exp["tags"]:
            excluded_ids: set[str] = set()
            for tag in exp["tags"]:
                excluded_ids |= tag_index.get(tag, set())
            participant_ids = all_member_ids - excluded_ids
        else:
            participant_ids = all_member_ids

        if not participant_ids:
            warnings.append(f"帳目「{exp['name']}」排除後無人參與，已跳過")
            continue

        n = len(participant_ids)
        per_person = exp["amount"] // n
        remainder = exp["amount"] - per_person * n

        payer_id = exp["payer_id"]
        if payer_id in totals:
            totals[payer_id]["owed"] += exp["amount"]

        remainder_target = payer_id if payer_id in participant_ids else sorted(participant_ids)[0]
        for pid in participant_ids:
            share = per_person + (remainder if pid == remainder_target else 0)
            if pid in totals:
                totals[pid]["owes"] += share
                totals[pid]["details"].append(
                    f"{exp['name']}：${share:,}（{n}人均分）"
                )

    # --- Compute net balances ---
    balances = {}
    for mid, t in totals.items():
        t["net"] = t["owed"] + t["paid_out"] - t["received_in"] - t["owes"]
        # For display: total contribution = owed (expenses paid) + paid_out (prepaid sent)
        t["total_contributed"] = t["owed"] + t["paid_out"]
        if t["received_in"] > 0:
            t["details"].append(f"收到預付款：+${t['received_in']:,}")
        if t["net"] != 0 or t["total_contributed"] > 0 or t["owes"] > 0:
            balances[mid] = t["net"]

    settle_transactions = simplify_debts(balances)

    for tx in settle_transactions:
        tx["from_name"] = totals[tx["from"]]["name"]
        tx["to_name"] = totals[tx["to"]]["name"]

    return {
        "member_totals": totals,
        "transactions": settle_transactions,
        "warnings": warnings,
    }


def compute_payment_progress(
    settlement_txns: list[dict],
    payment_records: list[dict],
    members_by_id: dict,
) -> dict:
    """Compute payment progress per collector by matching settlement transactions
    against actual payment records (結算轉帳 type)."""
    # Build a set of paid (from_id, to_id, amount) with their transaction IDs
    paid_set: dict[tuple, str] = {}
    for pr in payment_records:
        if pr["type"] == "結算轉帳":
            key = (pr["from_id"], pr["to_id"], pr["amount"])
            paid_set[key] = pr["id"]

    # Group settlement transactions by collector (to)
    collector_map: dict[str, dict] = {}
    for tx in settlement_txns:
        to_id = tx["to"]
        if to_id not in collector_map:
            to_member = members_by_id.get(to_id, {})
            collector_map[to_id] = {
                "id": to_id,
                "name": to_member.get("name", to_id),
                "expected": 0,
                "received": 0,
                "payments": [],
            }
        c = collector_map[to_id]
        c["expected"] += tx["amount"]

        key = (tx["from"], tx["to"], tx["amount"])
        is_paid = key in paid_set
        txn_id = paid_set.get(key, "")

        from_member = members_by_id.get(tx["from"], {})
        c["payments"].append({
            "from_id": tx["from"],
            "from_name": from_member.get("name", tx.get("from_name", "")),
            "to_id": tx["to"],
            "amount": tx["amount"],
            "paid": is_paid,
            "txn_id": txn_id,
        })
        if is_paid:
            c["received"] += tx["amount"]

    # Sort collectors by expected amount descending
    collectors = sorted(collector_map.values(), key=lambda x: -x["expected"])
    for c in collectors:
        c["pct"] = round(c["received"] / c["expected"] * 100, 1) if c["expected"] > 0 else 0

    total_expected = sum(c["expected"] for c in collectors)
    total_received = sum(c["received"] for c in collectors)

    return {
        "collectors": collectors,
        "total_expected": total_expected,
        "total_received": total_received,
        "total_pct": round(total_received / total_expected * 100, 1) if total_expected > 0 else 0,
    }
