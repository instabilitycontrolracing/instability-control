"""Runs the engineer in the background (used by the window and by the console launcher)."""
import os, threading, time

from .voice import Voice, PRIO_URGENT
from .corners import Corners
from .brain import Brain
from .intents import understand

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
VOCAB = os.path.join(ROOT, "Engineer1", "vocab")
PRESET = os.path.join(ROOT, "tools", "radio_preset.json")
LANDMARKS = r"C:\Program Files (x86)\Britton IT Ltd\CrewChiefV4\trackLandmarksData.json"


class IRacing:
    """pyirsdk wrapper: src['Var'] and src.info('Section').

    Efficiency (2026-10-29): one engine tick reads the same frozen snapshot hundreds of times (the brain, racecraft,
    timing, crowd, iPad... ~460 reads a tick, the CarIdx arrays of 64 values over and over). Each pyirsdk read unpacks
    the variable's header and data again. Telemetry values read since the last freeze() are kept in a small memo, so a
    value is unpacked once per tick. The snapshot is frozen, so the values are exactly what pyirsdk would return.
    The memo is a fresh dict on every freeze (a reader on another thread can never put an old value into the new tick).
    """
    def __init__(self, log):
        import irsdk
        self.ir, self.ok, self.log = irsdk.IRSDK(), False, log
        self._memo = {}

    def check(self):
        if self.ok and not (self.ir.is_initialized and self.ir.is_connected):
            self.ir.shutdown(); self.ok = False
            self._memo = {}
            self.log("iRacing closed. Waiting for iRacing...")
        elif not self.ok and self.ir.startup() and self.ir.is_initialized and self.ir.is_connected:
            self.ok = True
            self._memo = {}
            self.log("iRacing found.")
        return self.ok

    def freeze(self):
        self._memo = {}
        self.ir.freeze_var_buffer_latest()

    replay_test = False     # Settings: treat a replay of your own race as if you were driving it (for testing)

    def _var(self, k):
        m = getattr(self, "_memo", None)
        if m is None:
            m = self._memo = {}
        try:
            return m[k]
        except KeyError:
            pass
        ir = self.ir
        v = ir[k]
        try:
            if k in ir._var_headers_dict:          # telemetry only (session-info sections are cached by pyirsdk)
                m[k] = v
        except Exception:
            pass
        return v

    def __getitem__(self, k):
        if self.replay_test and k in ("IsOnTrack", "IsOnTrackCar"):
            try:
                if self._var("IsReplayPlaying"):
                    return True
            except Exception:
                pass
        return self._var(k)

    def info(self, sec):
        # ~70 calls a tick; pyirsdk re-checks the session-info counter on each. Kept for the rest of the tick too.
        m = getattr(self, "_memo", None)
        if m is None:
            m = self._memo = {}
        key = ("\x00info", sec)
        try:
            return m[key]
        except KeyError:
            pass
        v = self.ir[sec]
        m[key] = v
        return v

    def close(self):
        try:
            self.ir.shutdown()
        except Exception:
            pass


class Engine:
    def __init__(self, settings, log=print, on_say=None, on_status=None):
        self.s, self.log = settings, log
        self.on_status = on_status or (lambda st: None)
        self.voice = Voice(VOCAB, PRESET, device=settings.device or None, volume=settings.volume,
                           log=log, strength=settings.radio_strength)
        self.voice.on_say = on_say
        try:
            from .voice import sound_gaps_logger
            sound_gaps_logger(log)
        except Exception:
            pass
        self.voice.spotter = getattr(settings, "spotter_voice", "") or ""
        self.voice.driver_name = getattr(settings, "driver_name", "") or ""   # beta (2026-10-24): no name fallback
        self.voice.driver_name_say = getattr(settings, "driver_name_say", "") or ""   # #542: how to say it
        self.corners = Corners(LANDMARKS, self.voice.blocks.get("corner", {}), exists=self.voice.clip_exists)
        self.brain = None
        self.on_tick = None          # extra work every tick (pit crew, iPad feed)
        self.running = False
        self._t = None
        self.status = {"state": "stopped"}

    # settings that change live
    def apply(self):
        self.voice.volume = self.s.volume
        self.voice.fx.set_strength(self.s.radio_strength)
        self.voice.spotter = getattr(self.s, "spotter_voice", "") or ""
        self.voice.driver_name = getattr(self.s, "driver_name", "") or ""     # beta (2026-10-24): no name fallback
        self.voice.driver_name_say = getattr(self.s, "driver_name_say", "") or ""
        if self.brain:
            self.brain.s = self.s

    def set_device(self, dev):
        self.voice.set_device(dev or None)

    def start(self):
        if self.running:
            return
        self.running = True
        self._t = threading.Thread(target=self._loop, daemon=True)
        self._t.start()

    def stop(self):
        self.running = False
        self._set_status({"state": "stopped"})

    def close(self):
        self.stop()
        self.voice.close()

    def ask(self, text):
        """A question from the driver (typed now; voice recognition later)."""
        intent, _ = understand(text)
        self.log(f"YOU: {text}")
        if self.brain is None:
            self.voice.say("tb_no_data", prio=PRIO_URGENT)
            return intent
        if self.brain.x.command(text):
            return "command"
        if intent == "meeting":
            self.brain.say("tb_standby", prio=PRIO_URGENT)
        else:
            self.brain.answer(intent)
        return intent

    def _set_status(self, st):
        st = dict(st, running=self.running)
        self.status = st
        try:
            self.on_status(st)
        except Exception:
            pass

    def _loop(self):
        try:
            src = IRacing(self.log)
        except Exception as e:
            self.log(f"Can't load the iRacing reader: {e}")
            self.running = False
            self._set_status({"state": "error"})
            return
        self._set_status({"state": "waiting"})
        self.log("Engineer on. Waiting for iRacing...")
        try:   # 2026-10-28 (#499): Xbox-style controller as a replay remote (never while driving)
            from . import replay_remote
            self._remote = replay_remote.start(src.ir, log=self.log)
        except Exception as e:
            self.log(f"[replay remote] {e!r}")
        last_status = 0
        while self.running:
            try:
                connected = src.check()
            except Exception as e:
                self.log(f"[engine] iRacing check failed: {e!r}")
                connected = False
            if not connected:
                if self.brain is not None:
                    self.brain = None
                    if self.on_tick:
                        try: self.on_tick(None)
                        except Exception: pass
                    self._set_status({"state": "waiting"})
                time.sleep(1)
                continue
            if self.brain is None:
                self.brain = Brain(src, self.voice, self.corners, self.s, log=self.log)
            src.replay_test = bool(getattr(self.s, "replay_test", False))
            src.freeze()
            try:
                self.brain.tick()
            except Exception as e:  # never die mid-race
                self.log(f"[brain] error: {e!r}")
            if self.on_tick:
                try:
                    self.on_tick(self.brain)
                except Exception as e:
                    self.log(f"[engine] extra: {e!r}")
            now = time.time()
            if now - last_status > 1:
                last_status = now
                self._set_status(self._status_from(self.brain))
            time.sleep(1 / 15)
        src.close()
        self.brain = None

    def _status_from(self, b):
        try:
            d = b.drivers().get(b.me(), {})
            wk = b.info("WeekendInfo", {})
            st = {"state": "connected",
                  "track": wk.get("TrackDisplayShortName") or wk.get("TrackDisplayName") or wk.get("TrackName", ""),
                  "track_full": wk.get("TrackDisplayName") or wk.get("TrackName", ""),
                  "car": d.get("CarScreenName", ""), "session": b.sess_type,
                  "pos": b.class_pos(b.me()) or None, "gtp": b.v.gtp}
            try:                                     # 2026-10-26: the track logo + its plate colour for the top strip
                from .track_theme import theme
                st["theme"] = theme(wk.get("TrackDisplayName", ""), wk.get("TrackName", ""))
            except Exception:
                pass
            # session progress for the gold strip
            lr = b.g("SessionLapsRemainEx", 32767)
            if lr is not None and 0 <= lr < 32000:
                done = max(0, b.g("LapCompleted", 0) or 0)
                st["progress"] = done / max(1, done + lr)
            else:
                left = b.g("SessionTimeRemain", -1) or -1
                total = str(b.session().get("SessionTime", ""))
                try:
                    tot = float(total.split()[0])
                    if left >= 0 and tot > 0:
                        st["progress"] = 1 - left / tot
                except (ValueError, IndexError):
                    pass
            f = b.g("SessionFlags", 0) or 0
            st["flag"] = ("checkered" if f & 0x1 else "red" if f & 0x10 else "yellow" if f & (0x8 | 0x100 | 0x4000 | 0x8000)
                          else "white" if f & 0x2 else "blue" if f & 0x20 else "green" if f & 0x4 else None)
            return st
        except Exception:
            return {"state": "connected"}
