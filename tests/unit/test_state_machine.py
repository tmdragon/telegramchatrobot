from src.models.status import StatusCode, is_legal, legal_next_states


def test_legal_transitions_from_ordered():
    assert is_legal(StatusCode.ORDERED, StatusCode.MAKING)
    assert not is_legal(StatusCode.ORDERED, StatusCode.PUBLISHED)


def test_legal_rework_returns_to_review():
    assert is_legal(StatusCode.REWORK, StatusCode.CLIENT_REVIEW)


def test_first_review_rejected_returns_to_submitting():
    assert is_legal(StatusCode.FIRST_REVIEW_REJECTED, StatusCode.SUBMITTING)
    assert not is_legal(StatusCode.FIRST_REVIEW_REJECTED, StatusCode.MAKING)


def test_remaking_goes_to_making():
    assert is_legal(StatusCode.REMAKING, StatusCode.MAKING)
    assert not is_legal(StatusCode.REMAKING, StatusCode.CLIENT_REVIEW)


def test_paid_unpaid_bidirectional():
    assert is_legal(StatusCode.PAID, StatusCode.UNPAID)
    assert is_legal(StatusCode.UNPAID, StatusCode.PAID)


def test_legal_next_states():
    assert legal_next_states(StatusCode.ORDERED) == {StatusCode.MAKING}
    assert StatusCode.SECOND_REVIEW not in legal_next_states(StatusCode.SECOND_REVIEW)
    assert {StatusCode.PUBLISHED, StatusCode.REMAKING} == legal_next_states(StatusCode.SECOND_REVIEW)


def test_off_shelf_reachable_from_published():
    assert is_legal(StatusCode.PUBLISHED, StatusCode.OFF_SHELF)
    assert not is_legal(StatusCode.MAKING, StatusCode.OFF_SHELF)
    assert not is_legal(StatusCode.PAID, StatusCode.OFF_SHELF)


def test_off_shelf_is_terminal():
    assert legal_next_states(StatusCode.OFF_SHELF) == set()
    for code in StatusCode:
        assert not is_legal(StatusCode.OFF_SHELF, code), (
            f"OFF_SHELF must be terminal but legal to {code}"
        )


def test_published_has_off_shelf_as_next():
    assert StatusCode.OFF_SHELF in legal_next_states(StatusCode.PUBLISHED)
    assert {StatusCode.PAID, StatusCode.UNPAID, StatusCode.OFF_SHELF} == legal_next_states(
        StatusCode.PUBLISHED
    )