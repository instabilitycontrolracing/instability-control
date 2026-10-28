"""Radio understanding: accuracy on tests/intent_phrases.py, the current engineer/intents.py against an older one.

    python tools/intent_accuracy.py                 # current only
    python tools/intent_accuracy.py --old <rev>     # also the version at git <rev> (e.g. 8df8b66)
"""
import os, subprocess, sys, time, types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "tests")]
from intent_phrases import PHRASES  # noqa: E402


def score(understand, label, show=True):
    ok, bad = 0, []
    t0 = time.perf_counter()
    for text, want, _ in PHRASES:
        got = understand(text)[0]
        if got == want:
            ok += 1
        else:
            bad.append((text, want, got))
    ms = (time.perf_counter() - t0) * 1000 / len(PHRASES)
    print(f"{label}: {ok}/{len(PHRASES)} = {100 * ok / len(PHRASES):.1f}%  ({ms:.2f} ms a phrase)")
    if show:
        for text, want, got in bad:
            print(f"   {text!r:55} want {want:13} got {got}")
    return ok


if __name__ == "__main__":
    if "--old" in sys.argv:
        rev = sys.argv[sys.argv.index("--old") + 1]
        src = subprocess.run(["git", "show", f"{rev}:engineer/intents.py"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
        m = types.ModuleType("intents_old")
        exec(compile(src, "intents_old", "exec"), m.__dict__)
        score(m.understand, f"old ({rev})", show="-v" in sys.argv)
    from engineer.intents import understand
    score(understand, "new")
