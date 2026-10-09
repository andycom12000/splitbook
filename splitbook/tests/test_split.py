import pytest
from splitbook.domain.split import SplitError, split_equal, split_weights, split_exact


def test_equal_exact_division():
    assert split_equal(300, [1, 2, 3]) == {1: 100, 2: 100, 3: 100}


def test_equal_remainder_starts_after_payer():
    # 100 / 3 = 33 餘 1；付款人是 1，餘數從下一位（2）開始分
    assert split_equal(100, [1, 2, 3], payer_id=1) == {1: 33, 2: 34, 3: 33}
    # 付款人是 3（排序後最後一位），餘數繞回第一位
    assert split_equal(100, [1, 2, 3], payer_id=3) == {1: 34, 2: 33, 3: 33}


def test_equal_remainder_two_extra():
    # 200 / 3 = 66 餘 2；付款人 1 → 2 和 3 各 +1
    assert split_equal(200, [1, 2, 3], payer_id=1) == {1: 66, 2: 67, 3: 67}


def test_equal_payer_not_participant():
    # 付款人不參與 → 從名單第一位開始
    assert split_equal(100, [2, 3, 4], payer_id=9) == {2: 34, 3: 33, 4: 33}


def test_equal_negative_amount_refund():
    # 退款：-100 / 3，總和必須仍為 -100
    result = split_equal(-100, [1, 2, 3], payer_id=1)
    assert sum(result.values()) == -100


def test_equal_conservation_property():
    # 守恆性質：任意金額與人數，總和恆等於 amount
    for amount in [1, 7, 99, 100, 101, 12345, -37]:
        for n in range(1, 6):
            ids = list(range(1, n + 1))
            assert sum(split_equal(amount, ids, payer_id=1).values()) == amount


def test_equal_rejects_empty_and_duplicates():
    with pytest.raises(SplitError):
        split_equal(100, [])
    with pytest.raises(SplitError):
        split_equal(100, [1, 1, 2])


def test_weights_basic():
    # 100 依 2:1:1 → 50/25/25
    assert split_weights(100, {1: 2, 2: 1, 3: 1}) == {1: 50, 2: 25, 3: 25}


def test_weights_largest_remainder():
    # 100 依 1:1:1 → 各 33.33...，餘 1 給小數部分最大者；全部同分 → id 最小者
    assert split_weights(100, {1: 1, 2: 1, 3: 1}) == {1: 34, 2: 33, 3: 33}


def test_weights_conservation():
    for amount in [1, 100, 999, 12345]:
        result = split_weights(amount, {1: 3, 2: 2, 3: 5, 4: 1})
        assert sum(result.values()) == amount


def test_weights_rejects_nonpositive():
    with pytest.raises(SplitError):
        split_weights(100, {1: 0, 2: 1})
    with pytest.raises(SplitError):
        split_weights(100, {})


def test_exact_valid():
    assert split_exact(100, {1: 60, 2: 40}) == {1: 60, 2: 40}


def test_exact_sum_mismatch_rejected():
    with pytest.raises(SplitError):
        split_exact(100, {1: 60, 2: 50})
    with pytest.raises(SplitError):
        split_exact(100, {})


def test_exact_mismatch_message_states_gap():
    with pytest.raises(SplitError, match="超出 10 元"):
        split_exact(100, {1: 60, 2: 50})
    with pytest.raises(SplitError, match="還差 10 元"):
        split_exact(100, {1: 60, 2: 30})
