"""Benchmark of the engineer's per-tick work (efficiency pass, 2026-10-29).

    python tools/bench_engine.py [--seconds 1500] [--profile out.prof] [--calls calls.txt]

Drives the REAL pyirsdk reader (a fake iRacing memory file, tests/irsdk_fake.py) with a synthetic 40-car multiclass race
and runs, every engine tick (15 a second, like engine.py): Brain.tick() and the app's per-tick work (Api._tick: crowd
frame, strategist, pit crew, memory, iPad feed with one open iPad page). Time is simulated (time.time / monotonic are
the race clock), so a run is deterministic: --calls writes every radio call the engineer made with its race time, and two
builds can be compared line by line (the efficiency pass must not change a single call).

Prints the CPU time per tick (mean / p50 / p99 / max) for each part. Nothing here runs in the app.
"""
import argparse, cProfile, os, pstats, random, sys, tempfile, time

if os.environ.get("PYTHONHASHSEED") != "0":        # string-set order must not differ between runs (call-log compare)
    os.environ["PYTHONHASHSEED"] = "0"
    os.execv(sys.executable, [sys.executable] + sys.argv)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
os.environ["LOCALAPPDATA"] = tempfile.mkdtemp(prefix="ic_bench_")

_real_time, _real_mono, _real_perf = time.time, time.monotonic, time.perf_counter


class Clock:
    t = 1_800_000_000.0

    def __call__(self):
        return self.t


CLOCK = Clock()


def mono():
    return CLOCK.t - 1_700_000_000.0


class StubVoice:
    """Stands in for engineer.voice.Voice: records every call (no audio)."""
    def __init__(self):
        self.calls = []
        self.blocks = {}
        self.gtp = False
        self.fuel_metric = True
        self.spotter = ""
        self.driver_name = ""
        self.last_said = None
        self.volume = 1.0
        self.player = None

    def has(self, sid):
        return True

    def clip_exists(self, rel):
        return False

    def say(self, sid, fills=None, prio=3, max_age=None):
        self.calls.append((round(CLOCK.t - 1_800_000_000.0, 3), "say", sid, repr(sorted((fills or {}).items())), prio))

    def say_now(self, sid, fills=None, max_age=20.0):
        self.calls.append((round(CLOCK.t - 1_800_000_000.0, 3), "now", sid, repr(sorted((fills or {}).items())), -1))

    def hold(self, flag):
        pass

    def pending(self):
        return 0

    def build(self, sid, fills=None):
        return None, None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=1500.0, help="race length after the green (s)")
    ap.add_argument("--profile", help="write a cProfile of the whole run here")
    ap.add_argument("--calls", help="write the engineer's radio calls (race time, sid, fills, prio) here")
    ap.add_argument("--no-app", action="store_true", help="only Brain.tick (no crowd / strategist / pit / memory / iPad)")
    a = ap.parse_args(argv)

    random.seed(1)
    import numpy as np
    np.random.seed(1)
    time.time = CLOCK
    time.monotonic = mono

    from irsdk_fake import FakeIRFile, SyntheticRace, ir_from_file
    tmp = tempfile.mkdtemp(prefix="ic_bench_ir_")
    fake = FakeIRFile(os.path.join(tmp, "ir.bin"))
    race = SyntheticRace(fake, race_s=a.seconds)
    race.advance(1 / 15)

    from engineer import engine as E
    from engineer.brain import Brain
    from engineer.settings import Settings
    from engineer.corners import Corners

    class Src(E.IRacing):
        def __init__(self, ir):
            self.ir, self.ok, self.log = ir, True, (lambda m: None)

    src = Src(ir_from_file(fake.path))
    s = Settings()
    logs = []
    log = logs.append
    voice = StubVoice()
    corners = Corners(os.path.join(tmp, "none.json"), {}, exists=lambda c: False)
    brain = Brain(src, voice, corners, s, log=log, clock=CLOCK)

    api = None
    if not a.no_app:
        from engineer import app as A
        api = A.Api.__new__(A.Api)
        api._s = s
        api._q = __import__("queue").Queue()
        api._log = log
        from engineer.pit import PitCrew
        from engineer.strat_live import Strategist
        from engineer.memory import Recorder as Mem
        said = []
        crew = lambda role, text: said.append((round(CLOCK.t - 1_800_000_000.0, 3), role, text))
        api._crew_said = said
        api._pit = PitCrew(crew, log=log, emit=api._q.put)
        api._strat = Strategist(crew, log=log, emit=api._q.put)
        api._strat.s = s
        api._strat.idle = lambda: True
        api._pit.strat = api._strat; api._strat.pit = api._pit
        api._mem = Mem(on_done=lambda *x: None, log=log)
        try:
            from engineer.crowd import Crowd, Director, Mixer, SOUND_NAMES, load_sounds
            import crowd_synth
            snd = os.path.join(tmp, "sounds")
            crowd_synth.write_all(snd, SOUND_NAMES)
            clips = load_sounds(snd, os.path.join(tmp, "levels.json"), log=lambda *x: None)
            cr = Crowd.__new__(Crowd)
            cr.s, cr.log, cr.root = s, log, tmp
            cr.mixer = Mixer(max_voices=12, log=log)
            cr.director = Director(cr.mixer, clips, [os.path.join(ROOT, "tests", "fixtures")], s,
                                   rng=random.Random(3), log=log)
            cr.director.pack_root = tmp
            cr.state, cr._last_t, cr._b_prev, cr._drivers, cr._drivers_t = "ready", None, {}, {}, -99
            api._crowd = cr
        except Exception as e:
            print("crowd not in the bench:", repr(e))
            api._crowd = None
        from engineer.remote import Remote
        rem = Remote.__new__(Remote)
        Remote.__init__(rem, api, log=log)
        import queue as _queue
        rem.clients = [_queue.Queue(maxsize=10 ** 6)]               # one open iPad page
        rem._places_busy = True                                     # no Grandstand fetches
        api._remote = rem
        api._engine = type("E", (), {"brain": brain})()
        api._amix = None
        from engineer.audio_tool import AudioMix
        api._amix = AudioMix(log=log)

    parts = {"brain": [], "app": [], "freeze": []}
    prof = cProfile.Profile() if a.profile else None
    n = 0
    end_t = race.FORM_S + a.seconds + 60
    while race.t < end_t:
        race.advance(1 / 15)
        CLOCK.t += 1 / 15
        c0 = _real_perf()
        src.freeze()
        c1 = _real_perf()
        if prof: prof.enable()
        try:
            brain.tick()
        except Exception as e:
            logs.append(f"[brain] error: {e!r}")
        c2 = _real_perf()
        if api is not None:
            try:
                A.Api._tick(api, brain)
            except Exception as e:
                logs.append(f"[engine] extra: {e!r}")
            if n % 15 == 0:
                for q in api._remote.clients:                     # the iPad page reads its queue
                    while not q.empty():
                        q.get_nowait()
        c3 = _real_perf()
        if prof: prof.disable()
        parts["freeze"].append(c1 - c0); parts["brain"].append(c2 - c1); parts["app"].append(c3 - c2)
        n += 1

    def st(xs):
        xs = sorted(xs)
        return (sum(xs) / len(xs) * 1e3, xs[len(xs) // 2] * 1e3, xs[int(len(xs) * 0.99)] * 1e3, xs[-1] * 1e3)
    print(f"{n} ticks ({n / 15:.0f} s of race, {fake.si_update} session-info updates)")
    print(f"{'part':8s} {'mean ms':>9s} {'p50 ms':>9s} {'p99 ms':>9s} {'max ms':>9s}")
    tot = [a_ + b_ + c_ for a_, b_, c_ in zip(parts["freeze"], parts["brain"], parts["app"])]
    for k, xs in list(parts.items()) + [("total", tot)]:
        print(f"{k:8s} " + " ".join(f"{v:9.3f}" for v in st(xs)))
    print(f"engine thread busy: {sum(tot) / (n / 15) * 100:.2f} % of one core (at 15 ticks/s)")
    errs = [l for l in logs if "error" in l.lower() or "Error" in l]
    if errs:
        print(f"{len(errs)} error lines, first: {errs[:3]}")
    if a.calls:
        with open(a.calls, "w", encoding="utf-8") as f:
            for c in voice.calls:
                f.write("\t".join(map(str, c)) + "\n")
            for c in (getattr(api, "_crew_said", None) or []):
                f.write("\t".join(map(str, (c[0], "crew") + c[1:])) + "\n")
        print(f"{len(voice.calls)} engineer calls written to {a.calls}")
    if prof:
        prof.dump_stats(a.profile)
        pstats.Stats(a.profile).sort_stats("cumulative").print_stats(35)
    fake.close()


if __name__ == "__main__":
    main()
