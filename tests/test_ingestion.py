import pytest

from knowledge.ingestion import locate_passage, locate_quote


def test_quote_restores_whitespace_but_not_wording():
    assert locate_quote("A result\nwas  observed.", "A result was observed.") == (
        "A result\nwas  observed."
    )
    with pytest.raises(ValueError):
        locate_quote("A result was not observed.", "A result was observed.")
    with pytest.raises(ValueError):
        locate_quote("A  result; A\nresult", "A result")
    assert locate_quote("A ﬂawed ﬁlter", "A flawed filter") == "A ﬂawed ﬁlter"
    assert locate_passage(["cover", "different", "An exact result"], 2, "An exact result") == (
        3,
        "An exact result",
    )
