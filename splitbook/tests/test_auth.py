from splitbook.web.auth import hash_pin, verify_pin, make_token, parse_token


def test_pin_roundtrip():
    stored = hash_pin("1234")
    assert verify_pin("1234", stored) is True
    assert verify_pin("9999", stored) is False


def test_pin_hashes_are_salted():
    assert hash_pin("1234") != hash_pin("1234")


def test_verify_pin_bad_format_returns_false():
    assert verify_pin("1234", "garbage") is False


def test_token_roundtrip():
    t = make_token(3, 7, "secret", now=1000)
    assert parse_token(t, "secret", now=1000) == (3, 7)


def test_token_rejects_tamper_and_wrong_secret():
    t = make_token(3, 7, "secret", now=1000)
    assert parse_token(t + "x", "secret", now=1000) is None
    assert parse_token(t, "other", now=1000) is None
    assert parse_token("a.b.c", "secret") is None


def test_token_expires():
    t = make_token(3, 7, "secret", now=1000, ttl=60)
    assert parse_token(t, "secret", now=1061) is None
