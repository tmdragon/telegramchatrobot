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
    assert StatusCode.SECOND_REVIEW in legal_next_states(StatusCode.SECOND_REVIEW) is False
    assert {StatusCode.PUBLISHED, StatusCode.REMAKING} == legal_next_states(StatusCode.SECOND_REVIEW)