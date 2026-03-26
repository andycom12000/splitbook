import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.notion import parse_member, parse_expense, build_member_update


def test_parse_member():
    page = {
        "id": "page-id-1",
        "properties": {
            "姓名": {"title": [{"plain_text": "王小明"}]},
            "出席狀態": {"status": {"name": "已付款"}},
            "房間": {"select": {"name": "A01"}},
            "參與標籤": {"multi_select": [{"name": "不喝酒"}]},
            "已付款項": {"number": 2300},
        },
    }
    result = parse_member(page)
    assert result["id"] == "page-id-1"
    assert result["name"] == "王小明"
    assert result["payment_status"] == "已付款"
    assert result["room"] == "A01"
    assert result["tags"] == ["不喝酒"]
    assert result["prepaid"] == 2300


def test_parse_expense():
    page = {
        "id": "exp-id-1",
        "properties": {
            "項目名稱": {"title": [{"plain_text": "民宿費"}]},
            "類別": {"select": {"name": "民宿"}},
            "總金額": {"number": 40000},
            "付款人": {"relation": [{"id": "page-id-1"}]},
            "排除標籤": {"multi_select": [{"name": "不喝酒"}]},
            "日期": {"date": {"start": "2026-04-15"}},
            "備註": {"rich_text": [{"plain_text": "兩棟民宿"}]},
        },
    }
    result = parse_expense(page)
    assert result["id"] == "exp-id-1"
    assert result["name"] == "民宿費"
    assert result["category"] == "民宿"
    assert result["amount"] == 40000
    assert result["payer_id"] == "page-id-1"
    assert result["tags"] == ["不喝酒"]
    assert result["date"] == "2026-04-15"
    assert result["note"] == "兩棟民宿"


def test_build_member_update():
    update = build_member_update(
        total_owes=4660,
        total_paid=40000,
        net=35340,
        settlement_instruction="收回 $35,340",
        details=["民宿費：$1,000（40人均分）", "餐費：$500（40人均分）"],
    )
    assert update["應付總額"]["number"] == 4660
    assert update["已付/代墊金額"]["number"] == 40000
    assert update["淨餘額"]["number"] == 35340


def test_parse_member_missing_fields():
    """Missing optional fields should return defaults"""
    page = {
        "id": "page-id-2",
        "properties": {
            "姓名": {"title": [{"plain_text": "測試"}]},
        },
    }
    result = parse_member(page)
    assert result["name"] == "測試"
    assert result["payment_status"] == ""
    assert result["room"] == ""
    assert result["tags"] == []
    assert result["prepaid"] == 0
