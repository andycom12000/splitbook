"""定期項目的日期推算：純函式，不依賴 sqlite。"""
import calendar
from datetime import date

CYCLES = ("monthly", "bimonthly", "yearly")

_MONTHS_TO_ADD = {"monthly": 1, "bimonthly": 2, "yearly": 12}


def advance_due(current: date, cycle: str, cycle_day: int) -> date:
    """回傳下一個到期日。

    monthly +1 月、bimonthly +2 月、yearly +12 月。日期以 cycle_day 為準
    （不是 current.day），超過該月天數時 clamp 到月底，因此 1/31 → 2/28 →
    3/31 不會漂移。cycle 不合法或 cycle_day 不在 1..31 raise ValueError。
    """
    if cycle not in _MONTHS_TO_ADD:
        raise ValueError(f"未知的週期 {cycle!r}")
    if not (1 <= cycle_day <= 31):
        raise ValueError(f"cycle_day 必須在 1..31 之間，得到 {cycle_day}")

    months_to_add = _MONTHS_TO_ADD[cycle]
    total_months = (current.year * 12 + (current.month - 1)) + months_to_add
    year, month0 = divmod(total_months, 12)
    month = month0 + 1

    last_day = calendar.monthrange(year, month)[1]
    day = min(cycle_day, last_day)
    return date(year, month, day)
