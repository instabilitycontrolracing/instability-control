"""Run the race engineer.  python -m engineer.main          (waits for iRacing, then talks)
                           python -m engineer.main --demo   (plays a sample race without iRacing)
"""
import argparse, os, sys, time

from .voice import Voice
from .corners import Corners
from .brain import Brain, Settings

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)  # CrewChiefVoices
VOCAB = os.path.join(ROOT, "Engineer1", "vocab")
PRESET = os.path.join(ROOT, "tools", "radio_preset.json")
LANDMARKS = r"C:\Program Files (x86)\Britton IT Ltd\CrewChiefV4\trackLandmarksData.json"
LOGF = os.path.join(ROOT, "engineer_log.txt")


def log(msg):
    line = time.strftime("%H:%M:%S ") + msg
    print(line, flush=True)
    try:
        with open(LOGF, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


class IRacing:
    """pyirsdk wrapper: src['Var'] and src.info('Section')."""
    def __init__(self):
        import irsdk
        self.ir = irsdk.IRSDK()
        self.ok = False

    def check(self):
        if self.ok and not (self.ir.is_initialized and self.ir.is_connected):
            self.ir.shutdown(); self.ok = False
            log("iRacing closed. Waiting...")
        elif not self.ok and self.ir.startup() and self.ir.is_initialized and self.ir.is_connected:
            self.ok = True
            log("iRacing found.")
        return self.ok

    def freeze(self):
        self.ir.freeze_var_buffer_latest()

    def __getitem__(self, k):
        return self.ir[k]

    def info(self, sec):
        return self.ir[sec]


def typed_questions(get_brain):
    """Until the radio button + voice recognition are in: type a question and press Enter."""
    import threading
    from .intents import understand
    def loop():
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            intent, _ = understand(line)
            b = get_brain()
            log(f"YOU: {line}  -> {intent}")
            if b is None:
                log("(iRacing not running yet)"); continue
            if intent == "meeting":
                b.say("tb_standby", prio=1); continue
            b.answer(intent)
    threading.Thread(target=loop, daemon=True).start()


def run(args):
    v = Voice(VOCAB, PRESET, device=args.device, volume=args.volume, log=log)
    corners = Corners(LANDMARKS, v.blocks.get("corner", {}))
    src = IRacing()
    brain = None
    holder = {"b": None}
    typed_questions(lambda: holder["b"])
    log("Engineer ready. Waiting for iRacing...")
    while True:
        if not src.check():
            brain = holder["b"] = None
            time.sleep(1)
            continue
        if brain is None:
            brain = Brain(src, v, corners, Settings(), log=log)
            holder["b"] = brain
        src.freeze()
        try:
            brain.tick()
        except Exception as e:  # never die mid-race
            log(f"[brain] error: {e!r}")
        time.sleep(1 / 15)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true", help="play a sample race without iRacing")
    ap.add_argument("--record", help="demo only: also save the demo to this wav file")
    ap.add_argument("--device", default=None, help="audio output device name or number")
    ap.add_argument("--volume", type=float, default=1.0)
    ap.add_argument("--list-devices", action="store_true")
    a = ap.parse_args()
    if a.list_devices:
        import sounddevice as sd; print(sd.query_devices()); return
    if a.device and a.device.isdigit():
        a.device = int(a.device)
    if a.demo:
        from .demo import run_demo
        run_demo(VOCAB, PRESET, LANDMARKS, a.record, a.device, a.volume, log)
        return
    run(a)


if __name__ == "__main__":
    main()
