"""#537: checkpoints write only the new part; the finished recording replaces them; a crash's pieces are joined."""
import os, time, glob
from array import array
import numpy as np
import pytest

from engineer import recorder as R


def _rec(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "recordings_dir", lambda: str(tmp_path))
    monkeypatch.setattr(R, "fallback_dir", lambda: str(tmp_path / "fb"))
    monkeypatch.setattr(R, "TELEMETRY_DIR", str(tmp_path / "none"))
    r = R.Recorder.__new__(R.Recorder)
    r.log = lambda *a: None; r.alive = False; r.status = "idle"; r._map = {}
    return r


def _cur(tmp_path, n):
    cols = {"SessionTime": array("d", np.arange(n) / 60.0), "Speed": array("f", np.ones(n, np.float32) * 50),
            "LapDist": array("f", np.arange(n, dtype=np.float32))}
    return {"src": "live", "sess": 0, "t0": time.time(), "si": "WeekendInfo: {}", "track": "t", "car": "c",
            "path": str(tmp_path / ("c_t x" + R.EXT)), "done": [False], "cols": cols, "n": n, "wall0": time.localtime()}


def _wait(pattern, count):
    for _ in range(100):
        if len(glob.glob(pattern)) >= count:
            return
        time.sleep(0.05)


def test_pieces_only_new_part_and_final_cleans(tmp_path, monkeypatch):
    r = _rec(tmp_path, monkeypatch)
    cur = _cur(tmp_path, 7200)
    r._checkpoint(cur)
    _wait(cur["path"] + ".ck*", 1)
    for v in cur["cols"].values():
        v.extend(v[:7200])                       # 2 more minutes
    cur["n"] = 14400
    r._checkpoint(cur)
    _wait(cur["path"] + ".ck*", 2)
    pieces = sorted(glob.glob(cur["path"] + ".ck*"))
    assert len(pieces) == 2
    assert len(np.load(pieces[1])["Speed"]) == 7200          # only the new part
    r._save(cur)
    assert os.path.exists(cur["path"]) and not glob.glob(cur["path"] + ".ck*")


def test_crash_pieces_are_joined(tmp_path, monkeypatch):
    r = _rec(tmp_path, monkeypatch)
    cur = _cur(tmp_path, 7200)
    r._checkpoint(cur)
    for v in cur["cols"].values():
        v.extend(v[:7200])
    cur["n"] = 14400
    r._checkpoint(cur)
    _wait(cur["path"] + ".ck*", 2)
    time.sleep(0.2)
    r._recover()                                  # as if the engineer started again after a crash
    assert os.path.exists(cur["path"]) and not glob.glob(cur["path"] + ".ck*")
    data, si, tick = R.read_renpz(cur["path"])
    assert len(data["Speed"]) == 14400 and "WeekendInfo" in si
