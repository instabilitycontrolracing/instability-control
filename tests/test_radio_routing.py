"""What the radio does with what he said (#453): a question to the strategist never gets just 'copy'."""
import queue
import types

import pytest

app = pytest.importorskip("engineer.app")


class Voice:
    def __init__(self):
        self.said = []

    def say(self, sid, fills=None, prio=None, max_age=None):
        self.said.append(sid)


class Brain:
    def __init__(self, gaps=(None, None, None, None)):
        self.answered = []
        self.x = types.SimpleNamespace(command=lambda t: False)
        self.ask = None
        self.rcft = None
        self.gaps = gaps

    def neighbours(self):
        return self.gaps

    def answer(self, intent):
        self.answered.append(intent)
        return True


class Strat:
    def __init__(self):
        self.spoken, self.plans, self.rec, self.wet_lvl, self.track = [], [], 0, None, None
        self.b = types.SimpleNamespace(is_race=lambda: True)
        self.rp = types.SimpleNamespace(command=lambda t: False)
        self.briefed = 0
        self.dry = True

    def dry_no_rain(self):
        return self.dry

    def speak(self, role, text):
        self.spoken.append((role, text))

    def answer(self, intent):
        self.speak("STRATEGIST", f"answer {intent}")
        return True

    def brief(self):
        self.briefed += 1


def fake(in_car=True, strat=True, gaps=(None, None, None, None)):
    eng = types.SimpleNamespace(voice=Voice(), brain=Brain(gaps))
    me = types.SimpleNamespace(_engine=eng, _team=None, _q=queue.Queue(), _strat=Strat() if strat else None, _pit=None,
                               notes=[], log=[])
    me._log = me.log.append
    me._in_car = lambda: in_car
    me._save_note = me.notes.append
    me._crew_say = lambda role, text: me.log.append(f"{role}: {text}")
    me._strat_line = types.MethodType(app.Api._strat_line, me)
    me._heard = types.MethodType(app.Api._heard, me)
    me._gap_both_ways = types.MethodType(app.Api._gap_both_ways, me)
    return me, eng


@pytest.mark.parametrize("text", ["Strategist.", "Strategist? Strategist?", "Straight just.", "Strategy guy.",
                                  "Strategist, are you there?", "Strategist, what's the plan?",
                                  "Strategist, how's the fuel?", "Strategist, when do we box?",
                                  "Strategist, do we need wets?", "Strategist, what about the purple thing?"])
def test_strategist_never_copy(text):
    me, eng = fake()
    me._heard(text, "radio")
    assert "ack" not in eng.voice.said, (text, eng.voice.said)
    assert not me.notes
    assert me._strat.spoken or me._strat.briefed or eng.brain.answered or eng.voice.said or \
        any(l.startswith(("ENGINEER", "STRATEGIST")) for l in me.log)


def test_strategist_fuel_goes_to_her():
    me, eng = fake()
    me._heard("Strategist, how's the fuel?", "radio")
    assert me._strat.spoken == [("STRATEGIST", "answer fuel")]


def test_unclear_to_her_she_asks_again():
    me, eng = fake()
    me._heard("Strategist, what about the purple thing?", "radio")
    assert me._strat.spoken in ([("STRATEGIST", "Say again for me?")], [("STRATEGIST", "Sorry, say again?")])


def test_unclear_question_engineer_asks_again():
    me, eng = fake()
    me._heard("What's the deal with the banana?", "radio")
    assert eng.voice.said == ["ans_say_again"] and not me.notes


def test_remark_is_still_a_note_with_copy():
    me, eng = fake()
    me._heard("The car is a bit loose in turn three.", "radio")
    assert me.notes and eng.voice.said == ["ack"]


def test_radio_check_to_her_answers_and_briefs():
    me, eng = fake()
    me._heard("Strategist, do you copy?", "radio")
    assert me._strat.spoken[0] == ("STRATEGIST", "Loud and clear. Here's the plan.")
    assert me._strat.briefed == 1


# ---- approved lines wired in (2026-10-28)
H = ("STRATEGIST", "That one's for the engineer.")


def test_name_only_she_says_go_ahead_and_waits():
    me, eng = fake()
    me._heard("Strategist.", "radio")
    assert me._strat.spoken == [("STRATEGIST", "Strategist here, go ahead.")] and not me._strat.briefed
    me._heard("How are the tyres?", "radio")           # no name: the follow-up is still for her
    assert me._strat.spoken[-1] == ("STRATEGIST", "answer tyres") and not eng.brain.answered


def test_follow_up_window_is_one_message():
    me, eng = fake()
    me._heard("Strategist?", "radio")
    me._heard("What's the gap?", "radio")              # for her -> she hands it to the engineer
    assert me._strat.spoken[-1] == H and eng.brain.answered == ["gap_ahead"]
    me._heard("How are the tyres?", "radio")           # window used up: the engineer answers as before
    assert eng.brain.answered[-1] == "tyres"


def test_follow_up_window_times_out(monkeypatch):
    me, eng = fake()
    me._heard("Strategist.", "radio")
    me._strat_wait_t -= app.STRAT_WAIT_S + 1
    me._heard("How are the tyres?", "radio")
    assert eng.brain.answered == ["tyres"]


def test_remark_after_her_name_is_still_a_note():
    me, eng = fake()
    me._heard("Strategist.", "radio")
    me._heard("The car is a bit loose in turn three.", "radio")
    assert me.notes and eng.voice.said == ["ack"]


def test_plan_still_on_request():
    me, eng = fake()
    me._heard("Strategist, what's the plan?", "radio")
    assert me._strat.briefed == 1 and ("STRATEGIST", "Strategist here, go ahead.") not in me._strat.spoken


@pytest.mark.parametrize("text,intent", [("Strategist, what's the gap?", "gap_ahead"), ("Strategist, any damage?", "damage"),
                                         ("Strategist, what was my last lap?", "last_lap")])
def test_not_her_subject_she_hands_over(text, intent):
    me, eng = fake()
    me._heard(text, "radio")
    assert me._strat.spoken == [H] and eng.brain.answered == [intent]


def test_her_subjects_no_handover():
    me, eng = fake()
    me._heard("Strategist, how's the fuel?", "radio")
    me._heard("Strategist, do you copy?", "radio")
    assert H not in me._strat.spoken


def test_tyres_to_her_and_to_him():
    me, eng = fake()
    me._heard("Strategist, how are the tyres?", "radio")
    assert me._strat.spoken == [("STRATEGIST", "answer tyres")] and not eng.brain.answered
    me, eng = fake()
    me._heard("How are the tyres?", "radio")
    assert eng.brain.answered == ["tyres"] and not me._strat.spoken


def test_wets_dry_track_she_answers():
    me, eng = fake()
    me._heard("Strategist, do we need wets?", "radio")
    assert me._strat.spoken == [("STRATEGIST", "No rain expected. We stay on slicks.")]


def test_wets_wet_track_engineer_tips():
    me, eng = fake()
    me._strat.dry = False
    me._heard("Strategist, do we need wets?", "radio")
    assert not me._strat.spoken and any(l.startswith("ENGINEER") for l in me.log)


@pytest.mark.parametrize("text,gaps,want", [
    ("What's the gap?", (1, 0.6, 2, 0.4), "ans_which_gap"),
    ("What's the gap?", (1, 3.0, 2, 0.4), "gap_ahead"),
    ("What's the gap?", (1, 0.6, None, None), "gap_ahead"),
    ("What's the gap to the car ahead?", (1, 0.6, 2, 0.4), "gap_ahead"),
    ("What's the gap behind?", (1, 0.6, 2, 0.4), "gap_behind"),
])
def test_which_gap(text, gaps, want):
    me, eng = fake(gaps=gaps)
    me._heard(text, "radio")
    got = eng.voice.said[-1] if eng.voice.said else eng.brain.answered[-1]
    assert got == want, (eng.voice.said, eng.brain.answered)


def test_which_gap_then_behind():
    me, eng = fake(gaps=(1, 0.6, 2, 0.4))
    me._heard("What's the gap?", "radio")
    me._heard("Behind.", "radio")
    assert eng.voice.said == ["ans_which_gap"] and eng.brain.answered == ["gap_behind"]


def test_engineer_wet_tip_uses_his_clip():
    from engineer import rain as R
    me, eng = fake()
    me._engine = eng
    me._speaker_obj = lambda: (_ for _ in ()).throw(AssertionError("stand-in speaker used"))
    tip = R.TRACK_WET["suzukainternationalracingcourse"][1]
    app.Api._crew_say(me, "ENGINEER", tip)
    assert eng.voice.said == ["wet_suzuka_2"]
