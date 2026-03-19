from __future__ import annotations

from src.monitor.voter import PriceVoter


def test_unanimous_vote() -> None:
    voter = PriceVoter()
    assert (
        voter.vote({"jsonld": 29.99, "css": 29.99, "regex": 29.99, "llm": 29.99})
        == 29.99
    )


def test_majority_vote() -> None:
    voter = PriceVoter()
    assert (
        voter.vote({"jsonld": 29.99, "css": 29.99, "regex": 35.00, "llm": 29.99})
        == 29.99
    )


def test_no_consensus() -> None:
    voter = PriceVoter()
    assert (
        voter.vote({"jsonld": 29.99, "css": 35.00, "regex": 42.00, "llm": None}) is None
    )


def test_tolerance_vote() -> None:
    voter = PriceVoter()
    assert (
        voter.vote({"jsonld": 29.99, "css": 30.00, "regex": 29.98, "llm": None})
        == 29.99
    )


def test_single_result() -> None:
    voter = PriceVoter()
    assert (
        voter.vote({"jsonld": None, "css": 25.00, "regex": None, "llm": None}) == 25.00
    )
