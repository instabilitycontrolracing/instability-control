"""Radio understanding (#453, 2026-10-28): natural questions, recogniser mistakes, who it was for."""
import time

import pytest

from engineer.intents import analyse, understand
from intent_phrases import NOT_QUESTIONS, PHRASES, UNCLEAR


@pytest.mark.parametrize("text,want,to", PHRASES)
def test_phrase(text, want, to):
    a = analyse(text)
    assert a["intent"] == want, f"{text!r}: {a}"
    assert understand(text)[0] == want
    if to is not None:
        assert a["to"] == to, f"{text!r}: {a}"


def test_table_is_big_enough():
    assert len(PHRASES) >= 80


def test_shape_unchanged():
    i, s = understand("how many laps left")
    assert isinstance(i, str) and isinstance(s, int) and s > 0
    assert understand("") == (None, 0)
    assert understand(None) == (None, 0)
    assert understand("the purple banana") == (None, 0)


@pytest.mark.parametrize("text", [p[0] for p in PHRASES if p[2] == "strategist"] + [u for u in UNCLEAR if "trategist" in u])
def test_strategist_never_just_copy(text):
    """10-27: 'I am asking for strategist multiple times, I just hear copy'. Anything said to her is either understood
    or marked unclear (the app then asks again with an approved line) - it never falls through to the note + 'copy'."""
    a = analyse(text)
    assert a["to"] == "strategist"
    assert a["intent"] or a["unclear"]


@pytest.mark.parametrize("text", UNCLEAR)
def test_unclear_questions_ask_again(text):
    a = analyse(text)
    assert a["intent"] is None and a["unclear"]


@pytest.mark.parametrize("text", NOT_QUESTIONS)
def test_remarks_stay_notes(text):
    a = analyse(text)
    assert a["intent"] is None and not a["unclear"]


def test_engineer_name_is_not_the_engine():
    assert understand("Engineer, what's the gap?")[0] == "gap_ahead"
    assert understand("engine temps?")[0] == "engine"


def test_fast():
    t0 = time.perf_counter()
    for text, _, _ in PHRASES:
        understand(text)
    per = (time.perf_counter() - t0) / len(PHRASES)
    assert per < 0.020                        # well under 20 ms a phrase (about 0.3 ms here)
    t0 = time.perf_counter()
    understand("quixotic zephyr marmalade kaleidoscope juxtaposition unfathomable")   # all words new: spell-fix path
    assert time.perf_counter() - t0 < 0.020
