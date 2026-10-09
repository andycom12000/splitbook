import pytest
from fastapi.testclient import TestClient
from splitbook.web.app import create_app


@pytest.fixture
def client():
    app = create_app(db_path=":memory:", secret="test-secret")
    return TestClient(app)


def _setup_group(client, members=("小明", "小華", "小美")):
    data = {"group_name": "沖繩行"}
    for i, name in enumerate(members, 1):
        data[f"member{i}"] = name
    return client.post("/setup", data=data, follow_redirects=False)


def _login(client, member_id=1, pin="1234"):
    return client.post("/login", data={"member_id": member_id, "pin": pin},
                       follow_redirects=False)


def test_root_redirects_to_setup_when_no_groups(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/setup"


def test_setup_creates_group_and_members(client):
    r = _setup_group(client)
    assert r.status_code == 303 and r.headers["location"] == "/login"
    page = client.get("/login")
    assert "沖繩行" in page.text and "小明" in page.text


def test_first_login_sets_pin_then_requires_it(client):
    _setup_group(client)
    r = _login(client, member_id=1, pin="1234")
    assert r.status_code == 303 and r.headers["location"] == "/"
    assert "session" in r.cookies
    # 登出後用錯 PIN 再登入 → 失敗留在 login 頁
    client.post("/logout")
    r2 = client.post("/login", data={"member_id": 1, "pin": "9999"})
    assert "PIN 錯誤" in r2.text


def test_short_pin_rejected_on_first_login(client):
    _setup_group(client)
    r = client.post("/login", data={"member_id": 1, "pin": "12"})
    assert "至少 4 碼" in r.text


def test_home_requires_login(client):
    _setup_group(client)
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"


def test_home_shows_members_and_balances(client):
    _setup_group(client)
    _login(client)
    r = client.get("/")
    assert r.status_code == 200
    for name in ("小明", "小華", "小美"):
        assert name in r.text


def _logged_in_client():
    app = create_app(db_path=":memory:", secret="test-secret")
    c = TestClient(app)
    _setup_group(c)
    _login(c, member_id=1, pin="1234")
    return c


def test_create_equal_expense_defaults_to_all(client=None):
    c = _logged_in_client()
    r = c.post("/expenses", data={
        "name": "民宿", "category": "住宿", "amount": 300, "payer_id": 1,
        "split_kind": "equal"}, follow_redirects=False)
    assert r.status_code == 303
    page = c.get("/expenses")
    assert "民宿" in page.text
    home = c.get("/")
    assert "$200" in home.text  # 小明 net = 300 - 100


def test_create_weighted_expense():
    c = _logged_in_client()
    c.post("/expenses", data={
        "name": "包車", "category": "交通", "amount": 100, "payer_id": 1,
        "split_kind": "weights", "w_1": 2, "w_2": 1, "w_3": 1})
    page = c.get("/expenses")
    assert "包車" in page.text


def test_exact_split_mismatch_shows_error():
    c = _logged_in_client()
    r = c.post("/expenses", data={
        "name": "門票", "category": "票券", "amount": 100, "payer_id": 1,
        "split_kind": "exact", "x_1": 60, "x_2": 50})
    assert "不等於總金額" in r.text


def test_exact_split_blank_total_uses_sum_of_amounts():
    c = _logged_in_client()
    r = c.post("/expenses", data={
        "name": "門票", "category": "票券", "amount": "", "payer_id": 1,
        "split_kind": "exact", "x_1": 60, "x_2": 50}, follow_redirects=False)
    assert r.status_code == 303
    page = c.get("/expenses")
    assert "門票" in page.text and "$110" in page.text


def test_exact_split_typed_total_still_validated():
    c = _logged_in_client()
    r = c.post("/expenses", data={
        "name": "門票", "category": "票券", "amount": 100, "payer_id": 1,
        "split_kind": "exact", "x_1": 60, "x_2": 30})
    assert "還差 10 元" in r.text
    assert "門票" not in c.get("/expenses").text


def test_blank_total_rejected_outside_exact_mode():
    c = _logged_in_client()
    r = c.post("/expenses", data={
        "name": "晚餐", "category": "餐食", "amount": "", "payer_id": 1,
        "split_kind": "equal"})
    assert r.status_code == 200
    assert "請輸入金額" in r.text


def test_expense_form_offers_all_split_kinds_with_equal_default():
    c = _logged_in_client()
    page = c.get("/expenses/new").text
    assert "data-split-form" in page
    assert 'value="equal" checked' in page
    assert 'value="weights"' in page and 'value="exact"' in page
    assert page.count('name="p_') == 3 and 'name="p_1" checked' in page


def test_saved_expense_redirects_to_list_with_banner_and_highlight():
    c = _logged_in_client()
    r = c.post("/expenses", data={
        "name": "門票", "category": "娛樂", "amount": "", "payer_id": 1,
        "date": "2026-10-09", "split_kind": "exact",
        "x_1": 60, "x_2": 50, "x_3": 40}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/expenses?month=2026-10&saved=1"
    page = c.get(r.headers["location"]).text
    assert "已記下 門票 $150" in page
    assert "小明 $60、小華 $50、小美 $40" in page
    assert "is-new" in page


def test_saved_param_ignores_foreign_or_invalid_ids():
    c = _logged_in_client()
    for q in ("abc", "999"):
        page = c.get(f"/expenses?saved={q}")
        assert page.status_code == 200
        assert "已記下" not in page.text


def test_back_target_still_wins_over_saved_banner():
    c = _logged_in_client()
    r = c.post("/expenses", data={
        "name": "晚餐", "category": "餐食", "amount": 90, "payer_id": 1,
        "split_kind": "equal", "back": "/"}, follow_redirects=False)
    assert r.headers["location"] == "/"


def test_update_and_delete_expense():
    c = _logged_in_client()
    c.post("/expenses", data={
        "name": "餐費", "category": "餐費", "amount": 300, "payer_id": 1,
        "split_kind": "equal"})
    c.post("/expenses/1/update", data={
        "name": "晚餐", "category": "餐費", "amount": 600, "payer_id": 2,
        "split_kind": "equal"})
    page = c.get("/expenses")
    assert "晚餐" in page.text and "餐費(舊)" not in page.text
    c.post("/expenses/1/delete")
    page = c.get("/expenses")
    assert "晚餐" not in page.text


def test_expense_requires_login():
    app = create_app(db_path=":memory:", secret="test-secret")
    c = TestClient(app)
    _setup_group(c)
    r = c.get("/expenses", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"


def test_expenses_edit_with_invalid_id_does_not_500():
    c = _logged_in_client()
    r = c.get("/expenses?edit=abc")
    assert r.status_code == 200


def test_expenses_edit_prefill_shows_exact_split():
    c = _logged_in_client()
    c.post("/expenses", data={
        "name": "門票", "category": "票券", "amount": 100, "payer_id": 1,
        "split_kind": "exact", "x_1": 60, "x_2": 40})
    page = c.get("/expenses?edit=1")
    assert page.status_code == 200
    assert 'value="60"' in page.text
    assert 'value="40"' in page.text
    assert 'value="exact" checked' in page.text


def test_cross_group_update_and_delete_blocked_and_no_leak():
    c = _logged_in_client()
    c.post("/expenses", data={
        "name": "民宿", "category": "住宿", "amount": 300, "payer_id": 1,
        "split_kind": "equal"})
    # 建立第二個帳本（不同 group），成員 id 會是 4
    c.post("/setup", data={"group_name": "北海道行", "member1": "阿強"},
          follow_redirects=False)
    _login(c, member_id=4, pin="5678")

    r1 = c.post("/expenses/1/update", data={
        "name": "偷改", "amount": 999, "payer_id": 4, "split_kind": "equal"})
    assert r1.status_code == 200
    assert "偷改" not in r1.text

    r2 = c.post("/expenses/1/delete")
    assert r2.status_code == 200

    edit_page = c.get("/expenses?edit=1")
    assert edit_page.status_code == 200
    assert "民宿" not in edit_page.text

    # 換回原帳本成員，確認帳目完好無缺
    _login(c, member_id=1, pin="1234")
    page = c.get("/expenses")
    assert "民宿" in page.text


def test_record_prepay_transfer_affects_balances():
    c = _logged_in_client()
    c.post("/expenses", data={
        "name": "民宿", "category": "住宿", "amount": 3000, "payer_id": 1,
        "split_kind": "equal"})
    r = c.post("/transfers", data={
        "from_id": 2, "to_id": 1, "amount": 500, "note": "先繳"},
        follow_redirects=False)
    assert r.status_code == 303
    page = c.get("/transfers")
    assert "先繳" in page.text
    # 小華 net：-1000 + 500 = -500
    home = c.get("/")
    assert "$-500" in home.text or "-500" in home.text


def test_self_transfer_rejected():
    c = _logged_in_client()
    r = c.post("/transfers", data={"from_id": 1, "to_id": 1, "amount": 100})
    assert "不可相同" in r.text


def test_delete_transfer():
    c = _logged_in_client()
    c.post("/transfers", data={"from_id": 2, "to_id": 1, "amount": 500})
    c.post("/transfers/1/delete")
    page = c.get("/transfers")
    assert "尚未有轉帳" in page.text


def test_settlement_flow_with_partial_payment_and_stale():
    c = _logged_in_client()
    c.post("/expenses", data={
        "name": "民宿", "category": "住宿", "amount": 300, "payer_id": 1,
        "split_kind": "equal"})
    # 即時方案：小華→小明 $100、小美→小明 $100
    page = c.get("/settlement")
    assert "小華" in page.text and "$100" in page.text

    # 建立快照
    r = c.post("/settlement/snapshot", follow_redirects=False)
    assert r.status_code == 303
    page = c.get("/settlement")
    assert "付款進度" in page.text

    # 部分付款 60/100 → partial
    c.post("/settlement/pay", data={
        "from_id": 2, "to_id": 1, "amount": 60, "snapshot_id": 1})
    page = c.get("/settlement")
    assert "已付 $60" in page.text

    # 快照後修改帳目 → 過期警告
    c.post("/expenses", data={
        "name": "追加", "category": "雜支", "amount": 90, "payer_id": 2,
        "split_kind": "equal"})
    page = c.get("/settlement")
    assert "已過期" in page.text


def test_undo_payment():
    c = _logged_in_client()
    c.post("/expenses", data={
        "name": "餐", "category": "餐費", "amount": 300, "payer_id": 1,
        "split_kind": "equal"})
    c.post("/settlement/snapshot")
    c.post("/settlement/pay", data={
        "from_id": 2, "to_id": 1, "amount": 100, "snapshot_id": 1})
    # 找出付款分錄 id（expense=1 之後的下一筆 transfer）
    page = c.get("/settlement")
    assert "已付 $100" in page.text
    c.post("/payments/2/undo")
    page = c.get("/settlement")
    assert "已付 $100" not in page.text


def test_snapshot_requires_login():
    app = create_app(db_path=":memory:", secret="test-secret")
    c = TestClient(app)
    _setup_group(c)
    r = c.post("/settlement/snapshot", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"


def _two_group_client():
    """group-1 成員 1~3（登入 id=1），group-2 成員 id=4。"""
    c = _logged_in_client()
    c.post("/expenses", data={
        "name": "民宿", "category": "住宿", "amount": 300, "payer_id": 1,
        "split_kind": "equal"})
    c.post("/setup", data={"group_name": "北海道行", "member1": "阿強"},
           follow_redirects=False)
    return c


def test_foreign_payer_on_post_expense_shows_error_no_leak():
    c = _two_group_client()
    # group-1 成員（登入 id=1）用 group-2 成員 id=4 當付款人
    r = c.post("/expenses", data={
        "name": "偷渡", "category": "雜支", "amount": 300, "payer_id": 4,
        "split_kind": "equal"})
    assert r.status_code == 200
    assert "不屬於此帳本" in r.text
    assert "偷渡" not in r.text
    # 帳目乾淨：home 仍 200 且無錯誤橫幅（守恆不變量未被污染）
    home = c.get("/")
    assert home.status_code == 200
    assert "alert" not in home.text


def test_foreign_from_id_on_post_transfer_shows_error_no_500():
    c = _two_group_client()
    r = c.post("/transfers", data={
        "from_id": 4, "to_id": 1, "amount": 100})
    assert r.status_code == 200
    assert "不屬於此帳本" in r.text


def test_settlement_pay_foreign_from_id_redirects_no_payment():
    c = _two_group_client()
    r = c.post("/settlement/snapshot", follow_redirects=False)
    assert r.status_code == 303
    before = c.get("/settlement").text
    r2 = c.post("/settlement/pay", data={
        "from_id": 4, "to_id": 1, "amount": 100, "snapshot_id": 1},
        follow_redirects=False)
    assert r2.status_code == 303 and r2.headers["location"] == "/settlement"
    after = c.get("/settlement").text
    assert "已記錄的付款" not in after
    assert before == after


def test_zero_amount_expense_shows_error_no_500():
    c = _logged_in_client()
    r = c.post("/expenses", data={
        "name": "免費", "category": "雜支", "amount": 0, "payer_id": 1,
        "split_kind": "equal"})
    assert r.status_code == 200
    assert "金額不可為 0" in r.text
