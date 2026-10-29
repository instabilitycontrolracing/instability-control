"""#542: a shared copy - the player's typed name is shown as written and SAID the way they typed it sounds."""
import types
import numpy as np
from engineer import voice as V


def _fake_voice():
    v = V.Voice.__new__(V.Voice)
    v.new, v.gtp, v.fuel_metric, v.sr, v.volume = {}, True, True, 24000, 1.0
    v.fx = lambda a, **k: a
    return v


def test_standin_says_sounds_like_but_shows_name(monkeypatch):
    said = []
    import engineer.standin as S
    monkeypatch.setattr(S, "synth", lambda text, sr: (said.append(text), np.ones(100, np.float32))[1])
    v = _fake_voice()
    audio, text = v._standin("x", {}, texts=["Good job Siobhan, P3."], say=("Siobhan", "Shiv-AWN"))
    assert text == "Good job Siobhan, P3."
    assert said == ["Good job Shiv-AWN, P3."]
    assert audio is not None


def test_standin_without_sounds_like_says_name_as_written(monkeypatch):
    said = []
    import engineer.standin as S
    monkeypatch.setattr(S, "synth", lambda text, sr: (said.append(text), np.ones(100, np.float32))[1])
    v = _fake_voice()
    v._standin("x", {}, texts=["Box this lap, Angelo."], say=("Angelo", ""))
    assert said == ["Box this lap, Angelo."]


def test_settings_has_sounds_like():
    from engineer.settings import Settings
    assert Settings().driver_name_say == ""
