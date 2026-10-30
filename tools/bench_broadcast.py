"""Bench: the broadcast player's crowd under a realistic, bursty delivery (2026-10-30, #604).

Simulates 10 minutes of a race: the engineer makes the crowd on the headset card's clock (0.3 % off the broadcast
card), at a speed that wanders 80-120 % of real time, bounded like the real crowd feed (never more than 0.6 s ahead of
the headset), and its link thread stalls now and then (0.1-0.9 s, or up to 1.6 s) and then hands over everything at once. Counts what
reaches the recording: holes (10 ms windows where the crowd is gone), "ran low/dry" events and skips.

    python tools/bench_broadcast.py                  # the current engineer/broadcast.py
    python tools/bench_broadcast.py --old FILE       # another version of broadcast.py (e.g. from git), for before/after
"""
import importlib.util, os, random, sys, time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def load(path=None):
    if not path:
        from engineer import broadcast
        return broadcast
    import engineer
    spec = importlib.util.spec_from_file_location("engineer._bench_bcast", path, submodule_search_locations=None)
    m = importlib.util.module_from_spec(spec); m.__package__ = "engineer"
    spec.loader.exec_module(m)
    return m


def run(B, seconds=600, seed=7, drift=1.003, stalls_per_min=6, max_stall=0.9):
    rng = random.Random(seed)
    nrng = np.random.default_rng(seed)
    clock = [1000.0]
    real = B.time.monotonic
    B.time.monotonic = lambda: clock[0]
    try:
        p = B.Player(log=lambda m: None)
        RATE = B.RATE
        bed = (nrng.standard_normal((RATE * 10, 2)) * 0.1).astype(np.float32)
        if hasattr(p, "set_bed"):
            p.set_bed(bed); p.cfg["bed_gain"] = 1.0
        noise = (nrng.standard_normal((RATE * 4, 2)) * 0.1).astype(np.float32)
        out = np.zeros((1024, 2), np.float32)
        dt_tick = 0.01                                # the engineer's feed loop
        made = 0.0                                    # frames the engineer made (headset clock)
        head_played = 0.0                             # frames the headset has played
        pending = []                                  # blocks made but still in the link queue
        stall_until = 0.0
        speed, speed_until = 1.0, 0.0
        dev_t = 0.0
        t = 0.0
        holes = windows = 0
        rms_log = []
        src = 0
        cb_time = []
        while t < seconds:
            # engineer side
            if t >= speed_until:
                speed = rng.uniform(0.8, 1.2); speed_until = t + rng.uniform(1.0, 4.0)
            head_played += dt_tick * RATE * drift
            budget = dt_tick * RATE * drift * speed
            while budget >= 1024 or (made < head_played and budget > 0):
                if made - head_played > 0.6 * RATE:
                    break
                k = src % (len(noise) - 1024)
                pending.append(noise[k:k + 1024].copy()); src += 1024
                made += 1024; budget -= 1024
            if made < head_played - 0.6 * RATE:       # the headset bed covered; its feed waits (does not race ahead)
                head_played = made + 0.6 * RATE
            if t >= stall_until and rng.random() < stalls_per_min / 60 * dt_tick:
                stall_until = t + rng.uniform(0.1, max_stall)
            if t >= stall_until and pending:
                for b in pending:
                    p.add_crowd(b)
                pending.clear()
            # broadcast card
            while dev_t <= t:
                t0 = time.perf_counter()
                p.render(out)
                cb_time.append(time.perf_counter() - t0)
                dev_t += 1024 / RATE
                if t > 10:
                    for w in range(0, 1024 - 479, 480):
                        r = float(np.sqrt(np.mean(out[w:w + 480] ** 2)))
                        windows += 1
                        if r < 0.03:
                            holes += 1
            t += dt_tick; clock[0] += dt_tick
        return {"holes_10ms": holes, "hole_pct": 100.0 * holes / max(1, windows), "ran_low_or_dry": p.underruns,
                "skips": p.skips, "cb_ms_mean": 1000 * float(np.mean(cb_time)), "cb_ms_p99": 1000 * float(np.percentile(cb_time, 99))}
    finally:
        B.time.monotonic = real


if __name__ == "__main__":
    path = sys.argv[sys.argv.index("--old") + 1] if "--old" in sys.argv else None
    B = load(path)
    for d, ms in ((0.997, 0.9), (1.003, 0.9), (1.003, 1.6)):
        r = run(B, drift=d, max_stall=ms)
        print(f"{'old' if path else 'current'} drift {d}, stalls up to {ms} s: " + ", ".join(f"{k} {v:.3f}" if isinstance(v, float) else f"{k} {v}" for k, v in r.items()))
