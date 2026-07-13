"""家庭帳本新 surface 的 web 測試：清單、定期、總覽。"""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from splitbook.web.app import create_app


@pytest.fixture
def c():
    app = create_app(db_path=":memory:", secret="test-secret")
    client = TestClient(app)
    data = {"group_name": "我們家", "member1": "媽媽", "member2": "爸爸",
            "member3": "妹妹"}
    client.post("/setup", data=data, follow_redirects=False)
    client.post("/login", data={"member_id": 1, "pin": "1234"},
                follow_redirects=False)
    return client


# -- 清單 ---------------------------------------------------------------
def test_shopping_add_and_list(c):
    r = c.post("/list/add", data={"name": "牛奶", "estimate": "80"},
               follow_redirects=False)
    assert r.status_code == 303
    page = c.get("/list")
    assert "牛奶" in page.text and "$80" in page.text


def test_shopping_buy_creates_expense_and_moves_item(c):
    c.post("/list/add", data={"name": "牛奶", "estimate": "80"})
    # 打勾 → sheet 預填預估金額
    sheet = c.get("/list?buy=1")
    assert "買到了" in sheet.text and 'value="80"' in sheet.text
    r = c.post("/list/buy", data={
        "item_ids": "1", "amount": 90, "payer_id": 1, "category": "日用"},
        follow_redirects=False)
    assert r.status_code == 303
    page = c.get("/list")
    assert "已入帳" in page.text and "$90" in page.text
    expenses = c.get("/expenses")
    assert "牛奶" in expenses.text


def test_shopping_multi_buy_combines_one_entry(c):
    c.post("/list/add", data={"name": "牛奶"})
    c.post("/list/add", data={"name": "蛋"})
    c.post("/list/buy", data={
        "item_ids": "1,2", "amount": 200, "payer_id": 1, "category": "日用"})
    expenses = c.get("/expenses")
    assert "採買 2 項" in expenses.text
    page = c.get("/list")
    assert page.text.count("已入帳") == 2  # 兩個項目連到同一筆


def test_shopping_buy_rejects_already_bought(c):
    c.post("/list/add", data={"name": "牛奶"})
    c.post("/list/buy", data={
        "item_ids": "1", "amount": 50, "payer_id": 1, "category": "日用"})
    r = c.post("/list/buy", data={
        "item_ids": "1", "amount": 50, "payer_id": 1, "category": "日用"})
    assert r.status_code == 200
    assert "請重新勾選" in r.text


def test_shopping_delete(c):
    c.post("/list/add", data={"name": "洗衣精"})
    c.post("/list/1/delete")
    page = c.get("/list")
    assert "洗衣精" not in page.text


# -- 定期 ---------------------------------------------------------------
def _add_rent(c, next_due, amount="25000"):
    return c.post("/recurring/add", data={
        "name": "房租", "amount": amount, "category": "居住",
        "payer_id": 1, "cycle": "monthly", "next_due": next_due},
        follow_redirects=False)


def test_recurring_due_shows_on_home_and_recurring(c):
    today = date.today().isoformat()
    assert _add_rent(c, today).status_code == 303
    home = c.get("/")
    assert "房租" in home.text and "今天到期" in home.text and "確認入帳" in home.text
    rec = c.get("/recurring")
    assert "$25,000" in rec.text


def test_recurring_not_due_hidden_on_home(c):
    _add_rent(c, "2099-01-01")
    home = c.get("/")
    assert "該繳的" not in home.text
    rec = c.get("/recurring")
    assert "接下來" in rec.text and "房租" in rec.text


def test_recurring_confirm_prefills_and_advances(c):
    today = date.today().isoformat()
    _add_rent(c, today)
    form = c.get("/expenses/new?template=1")
    assert 'value="25000"' in form.text and "房租" in form.text
    r = c.post("/expenses", data={
        "name": "房租", "amount": 25000, "payer_id": 1,
        "template_id": 1, "back": "/"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"
    home = c.get("/")
    assert "確認入帳" not in home.text  # 已推進，不再到期
    expenses = c.get("/expenses")
    assert "房租" in expenses.text


def test_recurring_skip_advances_without_entry(c):
    today = date.today().isoformat()
    _add_rent(c, today)
    r = c.post("/recurring/1/skip", data={"back": "/"},
               follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"
    home = c.get("/")
    assert "確認入帳" not in home.text
    expenses = c.get("/expenses")
    assert "房租" not in expenses.text


def test_recurring_every_period_amount_left_blank(c):
    today = date.today().isoformat()
    c.post("/recurring/add", data={
        "name": "電費", "amount": "", "category": "居住",
        "payer_id": 1, "cycle": "bimonthly", "next_due": today})
    home = c.get("/")
    assert "電費" in home.text and "入帳時填" in home.text
    form = c.get("/expenses/new?template=1")
    assert "這期多少" in form.text


def test_recurring_foreign_template_rejected(c):
    today = date.today().isoformat()
    _add_rent(c, today)
    # 另一個家庭的登入者拿不到這個範本
    c.post("/setup", data={"group_name": "別人家", "member1": "外人"},
           follow_redirects=False)
    c.post("/login", data={"member_id": 4, "pin": "5678"},
           follow_redirects=False)
    r = c.post("/expenses", data={
        "name": "偷入帳", "amount": 100, "payer_id": 4, "template_id": 1})
    assert r.status_code == 200
    assert "找不到定期項目" in r.text


# -- 總覽 ---------------------------------------------------------------
def test_home_month_summary_sentence(c):
    c.post("/expenses", data={"name": "晚餐", "amount": 300, "payer_id": 1,
                              "split_kind": "equal"})
    home = c.get("/")
    assert "這個月全家花了" in home.text and "$300" in home.text
    assert "你目前應收" in home.text


def test_home_empty_month_teaches(c):
    home = c.get("/")
    assert "還沒有帳" in home.text
