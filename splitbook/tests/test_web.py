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
