"""#604 (2026-10-30): the broadcast crowd never goes silent and never skips, however the engineer delivers it.

Evidence that started this: the broadcast player's log showed 1-7 "ran dry" and 0-4 "skipped ahead" every minute of a
race, and the recordings had crowd holes of 100-440 ms, while the headset (audio_proc.py, with its bed) had none.
"""
import os, socket, sys, threading, time, tracemalloc, types
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engineer import broadcast as B, audio_proc as A, audio_tool
import importlib.util
_spec = importlib.util.spec_from_file_location("bench_broadcast", os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "tools", "bench_broadcast.py"))
bench = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(bench)

RATE = B.RATE


def _player_with_bed(clock):
    p = B.Player(log=lambda m: None)
    bed = (np.random.default_rng(2).standard_normal((RATE * 6, 2)) * 0.1).astype(np.float32)
    p.set_bed(bed); p.cfg["bed_gain"] = 1.0
    return p


def _holes(out):
    return sum(1 for w in range(0, len(out) - 479, 480) if float(np.sqrt(np.mean(out[w:w + 480] ** 2))) < 0.03)


def test_bursty_80_to_120_percent_no_holes_no_skips():
    """Engineer speed wandering 80-120 %, link stalls up to 1.6 s then everything at once, clocks 0.3 % apart."""
    for drift, stall in ((0.997, 0.9), (1.003, 1.6)):
        r = bench.run(B, seconds=180, seed=11, drift=drift, max_stall=stall)
        assert r["holes_10ms"] == 0, r
        assert r["skips"] == 0, r


def test_old_player_had_holes_in_the_same_run():
    """The bench reproduces the race log (sanity check of the bench itself): the old 0.12 s queue ran dry and
    skipped. Reconstructed from its numbers: TARGET 0.12, 30 s memory, silence when dry, skip past 1 s."""
    class Old(B.Player):
        TARGET, WINDOW_S, LOW_S = 0.12, 30.0, 0.0
        def set_bed(self, bed):                  # the old player had no bed
            pass
        def render(self, out):
            if self.queued > RATE:               # old: skipped ahead past 1 s
                self.skips += 1
                self.cr = (self.cr + self.queued - self._target()) % len(self.crowd); self.queued = self._target()
            super().render(out)
    m = types.SimpleNamespace(**{k: getattr(B, k) for k in ("RATE", "time")}); m.Player = Old
    r = bench.run(m, seconds=180, seed=11, drift=1.003, max_stall=1.6)
    assert r["holes_10ms"] > 0


def test_sustained_80_percent_bed_covers_without_flutter():
    clock = [100.0]
    orig = B.time.monotonic
    B.time.monotonic = lambda: clock[0]
    try:
        p = _player_with_bed(clock)
        out = np.zeros((1024, 2), np.float32)
        live = (np.random.default_rng(3).standard_normal((819, 2)) * 0.1).astype(np.float32)
        holes = swaps = 0
        prev = p.crowd_on
        for i in range(47 * 30):                    # 30 s, the engineer at 80 % of real time
            p.add_crowd(live)
            p.render(out)
            clock[0] += 1024 / RATE
            if i > 47 * 2:
                holes += _holes(out)
            if p.crowd_on != prev:
                swaps += 1; prev = p.crowd_on
        assert holes == 0
        assert swaps < 30 * 2                       # at most about one round trip a second, not every block
    finally:
        B.time.monotonic = orig


def test_burst_after_a_pause_is_played_not_skipped():
    p = _player_with_bed(None)
    out = np.zeros((1024, 2), np.float32)
    p.add_crowd(np.full((int(RATE * 2.5), 2), 0.1, np.float32))   # 2.5 s at once
    q0 = p.queued
    for _ in range(47 * 10):
        p.add_crowd(np.full((1024, 2), 0.1, np.float32))
        p.render(out)
    assert p.skips == 0
    assert p.queued < q0                            # catching up (a little faster), nothing thrown away


def test_no_bed_fades_instead_of_cutting():
    p = B.Player(log=lambda m: None)
    out = np.zeros((1024, 2), np.float32)
    p.add_crowd(np.full((RATE, 2), 0.2, np.float32))
    last = []
    for _ in range(60):
        p.render(out); last.append(out.copy())
    x = np.concatenate(last)[:, 0]
    steps = np.abs(np.diff(x))
    assert float(steps.max()) < 0.05                # no hard step down to silence


def test_render_allocates_nothing_much():
    p = _player_with_bed(None)
    out = np.zeros((1024, 2), np.float32)
    p.add_crowd(np.full((RATE * 2, 2), 0.1, np.float32))
    for _ in range(5):
        p.render(out)
    tracemalloc.start()
    for _ in range(50):
        p.render(out)
    cur, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert peak < 16 * 1024, peak                   # was several 1024x2 arrays per block


def test_proc_player_render_allocates_nothing_much():
    ctrl = np.zeros(A.NCTRL, np.int64); ctrl[A.GAIN] = A.SCALE
    ring = np.zeros((RATE * 2, 2), np.float32)
    p = A.Player(ctrl, ring, RATE, "")
    p.loop = (np.random.default_rng(1).standard_normal((RATE * 3, 2)) * 0.1).astype(np.float32)
    ctrl[A.LOOP_GAIN] = A.SCALE
    out = np.zeros((1024, 2), np.float32)
    for _ in range(5):
        p.render(out)
    tracemalloc.start()
    for _ in range(50):
        p.render(out)                               # dry: the bed blends in (ramps on every block)
    cur, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert peak < 16 * 1024, peak


def test_proc_ramp_matches_linspace():
    ctrl = np.zeros(A.NCTRL, np.int64)
    p = A.Player(ctrl, np.zeros((4096, 2), np.float32), RATE, "")
    for g0, g1, n in ((0.0, 1.0, 1024), (0.7, 0.2, 1000), (1.0, 0.0, 4096), (0.3, 0.31, 17)):
        ref = np.linspace(g0, g1, n, endpoint=False, dtype=np.float32)[:, None]
        assert np.allclose(p._ramp(g0, g1, n), ref, atol=2e-6)


def test_proc_loop_swap_mid_play_is_safe():
    """reload_loop can hand over a shorter bed while the bed is mid-way: no error (= no silent block)."""
    ctrl = np.zeros(A.NCTRL, np.int64); ctrl[A.GAIN] = A.SCALE; ctrl[A.LOOP_GAIN] = A.SCALE
    p = A.Player(ctrl, np.zeros((RATE, 2), np.float32), RATE, "")
    p.loop = np.full((RATE * 3, 2), 0.2, np.float32)
    out = np.zeros((1024, 2), np.float32)
    for _ in range(100):
        p.render(out)
    p.loop = np.full((5000, 2), 0.2, np.float32)       # shorter than where the old one was
    p.render(out)
    assert float(np.abs(out).max()) > 0.05


def test_boost_helpers_are_harmless():
    assert isinstance(A.boost_process(), str)
    tb = A.ThreadBoost(); tb.once(); tb.once()
    assert tb.tid == threading.get_ident()


def test_link_sends_bed_and_level(monkeypatch):
    srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(1)
    monkeypatch.setattr(B, "PORT", srv.getsockname()[1])
    monkeypatch.setattr(audio_tool, "EXCLUDE_PID", None)
    s = types.SimpleNamespace(bcast_on=True, bcast_crowd=True)
    link = B.Link(s, log=lambda m: None)
    bed = np.full((RATE, 2), 0.25, np.float32)
    link.watch(types.SimpleNamespace(bed=bed, bed_gain=0.5))
    c, _ = srv.accept(); c.settimeout(3)
    p = B.Player(log=lambda m: None)
    threading.Thread(target=lambda: p._client(c), daemon=True).start()
    for _ in range(200):
        if p.bed is not None and p.cfg.get("bed_gain") == 0.5:
            break
        time.sleep(0.02)
    link.stop()
    assert p.bed is not None and np.array_equal(p.bed, bed)
    assert p.cfg["bed_gain"] == 0.5
