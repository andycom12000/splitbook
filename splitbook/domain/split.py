"""分攤規則：所有函數保證 sum(result.values()) == amount（守恆）。"""


class SplitError(ValueError):
    """分攤規則的輸入無效。"""


def split_equal(
    amount: int, participant_ids: list[int], payer_id: int | None = None
) -> dict[int, int]:
    """均分。餘數每人 +1，從排序後名單中付款人的下一位開始輪流分配。"""
    if not participant_ids:
        raise SplitError("至少需要一位參與者")
    if len(set(participant_ids)) != len(participant_ids):
        raise SplitError("參與者重複")
    ids = sorted(participant_ids)
    n = len(ids)
    base = amount // n  # floor division，負數金額（退款）同樣成立
    remainder = amount - base * n  # 0 <= remainder < n
    start = (ids.index(payer_id) + 1) % n if payer_id in ids else 0
    result = {pid: base for pid in ids}
    for k in range(remainder):
        result[ids[(start + k) % n]] += 1
    return result


def split_weights(amount: int, weights: dict[int, int]) -> dict[int, int]:
    """依權重分攤，整數最大餘數法（不經過 float）。"""
    if not weights:
        raise SplitError("至少需要一位參與者")
    if any(w <= 0 for w in weights.values()):
        raise SplitError("權重必須為正整數")
    total_w = sum(weights.values())
    result = {pid: (amount * w) // total_w for pid, w in weights.items()}
    remainder = amount - sum(result.values())
    order = sorted(weights, key=lambda pid: (-((amount * weights[pid]) % total_w), pid))
    for k in range(remainder):
        result[order[k]] += 1
    return result


def split_exact(amount: int, amounts: dict[int, int]) -> dict[int, int]:
    """指定每人金額，總和必須等於總額。"""
    if not amounts:
        raise SplitError("至少需要一位參與者")
    total = sum(amounts.values())
    if total != amount:
        raise SplitError(f"分攤總和 {total} 不等於總金額 {amount}")
    return dict(amounts)
