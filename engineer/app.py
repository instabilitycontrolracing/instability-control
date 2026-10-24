"""Race Engineer window (ApexHUD style).   pythonw -m engineer.app

The window is a web page (engineer/ui) shown by pywebview / Edge WebView2.
The page calls the Api methods below through window.pywebview.api.
"""
import ctypes, os, sys, threading, time, queue
from ctypes import wintypes

from .settings import Settings
from . import buttons as B

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LOGF = os.path.join(ROOT, "engineer_log.txt")
VERSION = "0.62 beta"
try:        # beta (2026-10-24): the release number lives in the VERSION file next to engineer/ (when there is one)
    VERSION = open(os.path.join(ROOT, "VERSION"), encoding="utf-8").read().strip() or VERSION
except OSError:
    pass
REPORT_FORM = "https://github.com/instabilitycontrol/instability-control/issues/new?template=beta_report.yml"
UI = os.path.join(HERE, "ui", "index.html")


def output_devices():
    try:
        import sounddevice as sd
        apis = sd.query_hostapis()
        out, seen = [], set()
        for d in sd.query_devices():
            if d["max_output_channels"] > 0 and apis[d["hostapi"]]["name"] in ("MME", "Windows WASAPI"):
                n = d["name"]
                if n not in seen and "Sound Mapper" not in n:
                    seen.add(n); out.append(n)
        return out
    except Exception:
        return []


def input_devices():
    try:
        import sounddevice as sd
        apis = sd.query_hostapis()
        out, seen = [], set()
        for d in sd.query_devices():
            if d["max_input_channels"] > 0 and apis[d["hostapi"]]["name"] in ("MME", "Windows WASAPI"):
                n = d["name"]
                if n not in seen and "Sound Mapper" not in n:
                    seen.add(n); out.append(n)
        return out
    except Exception:
        return []


# wheel buttons that ask the engineer something without talking (Settings > Buttons)
BIND_ACTIONS = {
    "say_again": ("intent", "say_again"), "gap_ahead": ("intent", "gap_ahead"), "gap_behind": ("intent", "gap_behind"),
    "position": ("intent", "position"), "fuel": ("intent", "fuel"), "laps_left": ("intent", "laps_left"),
    "pit_plan": ("pit", None), "pit_out": ("intent", "pit_out"), "damage": ("intent", "damage"),
    "tyres": ("intent", "tyres"), "irating": ("intent", "irating"), "weather": ("intent", "weather"),
    "mark_behind": ("cmd", "mark the car behind"), "mark_ahead": ("cmd", "mark the car ahead"),
    "quiet": ("intent", "quiet"), "talk": ("intent", "talk"),
}


def S_num(x):
    """'2700.0000 sec' -> 2700.0, 'unlimited' -> None (memory, 2026-10-24)."""
    try:
        return float(str(x).split()[0])
    except (ValueError, IndexError, TypeError):
        return None


class Api:
    def __init__(self):
        self._win = None
        self._page_ready = False
        self._s = Settings.load()
        self._q = queue.Queue()
        self._engine = None
        self._progress = (0.0, "Starting up")
        self._buttons = None
        self._last_ctrl = None
        threading.Thread(target=self._load, daemon=True).start()

    # ---------- plumbing ----------
    # ---------- team radio captions on the Grandstand overlay (2026-10-24) ----------
    _SPOT = ("car left", "car right", "clear", "clear left", "clear right", "clear sides", "clear all round",
             "still there", "three wide", "three wide, you are middle", "three wide, you're in the middle",
             "car left, car left", "car right, car right", "still there, still there")

    def _radio_out(self, msg):
        if not getattr(self._s, "overlay_radio", True):
            return
        who, text = None, ""
        if msg.startswith("ENGINEER:"):
            text = msg.split(":", 1)[1].strip()
            if text.lower().rstrip(".") in self._SPOT:
                return                                   # spotter calls are too quick for a caption
            who = "ENGINEER"
            if text.lower().startswith("race control:"):
                who, text = "RACE CONTROL", text.split(":", 1)[1].strip()
                try:      # send the timed version so the card captions the race director as he speaks
                    from .voice import RC_TEXT, RC_CUES
                    for k, full in RC_TEXT.items():
                        if full.split(":", 1)[1].strip().lower() == text.lower() and k in RC_CUES:
                            text = RC_CUES[k]; break
                except Exception:
                    pass
        elif msg.startswith("STRATEGIST:"):
            who, text = "STRATEGIST", msg.split(":", 1)[1].strip()
        if not who or not text:
            return
        import re as _re
        text = _re.sub(r"\s*\{GTP:[^}]*\}", "", text).strip()
        q = getattr(self, "_radio_q", None)
        if q is None:
            import queue as _queue
            q = self._radio_q = _queue.Queue(maxsize=20)
            threading.Thread(target=self._radio_sender, daemon=True).start()
        try:
            q.put_nowait((who, text))
        except Exception:
            pass

    def _radio_sender(self):
        import json as _json, urllib.request as _ur
        while True:
            who, text = self._radio_q.get()
            try:
                req = _ur.Request("http://127.0.0.1:8790/api/radio", data=_json.dumps({"who": who, "text": text}).encode(),
                                  headers={"Content-Type": "application/json", "X-Grandstand": "1"}, method="POST")
                _ur.urlopen(req, timeout=0.5).read()
            except Exception:
                pass                                     # Grandstand not running: nothing to do

    def _log(self, msg):
        try:
            self._radio_out(msg)
        except Exception:
            pass
        kind = "eng" if msg.startswith("ENGINEER:") else ("you" if msg.startswith("YOU:") else "sys")
        text = msg.split(": ", 1)[1] if kind != "sys" else msg
        self._q.put({"t": "log", "kind": kind, "text": text})
        rem = getattr(self, "_remote", None)
        if rem and not (kind == "sys" and text.startswith("[")):
            rem.push_log(kind, text)
        try:
            with open(LOGF, "a", encoding="utf-8") as f:
                f.write(time.strftime("%H:%M:%S ") + msg + "\n")
        except OSError:
            pass

    def _load(self):
        try:
            self._progress = (0.15, "Loading the voice")
            from .engine import Engine
            self._engine = Engine(self._s, log=self._log, on_status=lambda st: self._q.put({"t": "status", "st": st}))
            self._progress = (0.55, "Reading the track maps")
            # warm the most common clips so the first calls are instant
            for sid in ("radio_check", "car_left", "car_right", "clear", "three_wide", "still_there"):
                try:
                    self._engine.voice.build(sid, {})
                except Exception:
                    pass
            self._progress = (0.8, "Warming up the radio")
            from .pit import PitCrew
            self._pit = PitCrew(self._crew_say, log=self._log, emit=self._pit_emit)
            from .strat_live import Strategist
            self._strat = Strategist(self._crew_say, log=self._log, emit=self._pit_emit)
            self._strat.s = self._s
            self._strat.idle = lambda: self._speaker_obj().idle()
            self._pit.strat = self._strat
            self._strat.pit = self._pit
            from .memory import Recorder                       # memory (2026-10-24): one summary per session, written in a thread
            self._mem = Recorder(on_done=self._mem_done, log=self._log)
            threading.Thread(target=self._strategy_backfill, daemon=True).start()
            self._engine.on_tick = self._tick
            try:                                               # crowd (2026-10-24): own stream, never the radio
                from .crowd import Crowd
                self._crowd = Crowd(self._s, log=self._log, device=self._s.device or None)
            except Exception as e:
                self._crowd = None
                self._log(f"[crowd] {e!r}")
            self._buttons = B.Buttons(self._on_button, log=self._log)
            try:
                self._remote_start()
            except Exception as e:
                self._log(f"[ipad] {e!r}")
            try:
                from .ptt import Listener
                self._ptt = Listener(log=self._log, device=self._s.mic_device or None)
            except Exception as e:
                self._ptt = None
                self._log(f"[voice] {e!r}")
            time.sleep(0.4)
            self._progress = (1.0, "Ready")
            self._log("Race Engineer ready.")
            if self._s.autostart_engine:
                self._engine.start()
        except Exception as e:
            self._progress = (1.0, "Problem starting")
            self._log(f"Couldn't start the engineer: {e!r}")

    def _on_button(self, name, btn, down):
        if not self._engine:
            return
        if down:
            for action, binding in (self._s.binds or {}).items():
                if B.matches(binding, name, btn):
                    threading.Thread(target=self._bind_action, args=(action,), daemon=True).start()
                    return
        ch = "radio" if B.matches(self._s.radio_button, name, btn) else "team" if B.matches(self._s.team_button, name, btn) else None
        if not ch:
            return
        ptt = getattr(self, "_ptt", None)
        st = getattr(self, "_strat", None)
        if down and ch == "radio" and st and st.radio_ack():    # answering the strategist's radio check
            self._rc_ack_t = time.time()
        if not ptt or not ptt.ready:
            if down and ch == "radio" and time.time() - getattr(self, "_rc_ack_t", 0) > 2:
                self._engine.voice.test_tone()     # no speech recognition yet: radio check
            return
        self._ptt_down = bool(down)
        if down and getattr(self, "_speaker", None):
            self._speaker.stop()                  # talking over the team interrupts them
        if down:                                  # ...and the engineer / strategist (not the spotter) - 2026-10-24
            try:
                from .voice import RADIO, PRIO_SPOTTER
                o = RADIO.owner
                if o and o[1] > PRIO_SPOTTER:
                    o[0].stop()
            except Exception:
                pass
        if down:
            ptt.start()
            self._q.put({"t": "ptt", "on": True, "ch": ch})
        else:
            self._q.put({"t": "ptt", "on": False, "ch": ch})
            threading.Thread(target=lambda: self._heard(ptt.stop(), ch), daemon=True).start()

    def _in_car(self):
        b = self._engine.brain if self._engine else None
        return bool(b and (b.g("IsOnTrack", False) or b.g("IsOnTrackCar", False)))

    def _heard(self, text, ch):
        """What to do with something the driver said on the radio."""
        if not text:
            return
        from .intents import understand
        from .voice import PRIO_URGENT
        self._log(f"YOU: {text}")
        eng = self._engine
        team = getattr(self, "_team", None)
        if ch == "team":
            if self._in_car() and team and team.driving:
                eng.voice.say("tb_standby", prio=PRIO_URGENT)
                self._q.put({"t": "toast", "text": "Not while driving"})
                return
            self._q.put({"t": "goto", "tab": "team"})
            self._team_obj().start()
            self._q.put({"t": "team_heard", "text": text})
            return
        if time.time() - getattr(self, "_rc_ack_t", 0) < 10 and len(text.split()) <= 6:
            return                                  # "loud and clear" to the strategist: nothing else to do
        st = getattr(self, "_strat", None)
        if st and st.rp.command(text):              # practice run plan: skip / one more lap / what's the plan
            return
        pit = getattr(self, "_pit", None)
        if pit and pit.wants(text) and pit.answer(text):
            return
        if eng.brain is not None and getattr(eng.brain, "ask", None):          # Batch E questions (2026-10-24)
            eng.brain.strat = st
            try:
                if eng.brain.ask.command(text):
                    return
            except Exception as e:
                self._log(f"[ask] {e!r}")
        if eng.brain is not None and getattr(eng.brain, "rcft", None) and eng.brain.rcft.command(text):   # 2026-10-24 questions
            fb = getattr(eng.brain, "feedback_note", None)
            if fb:
                eng.brain.feedback_note = None
                self._save_note(fb)                       # remembered for the debrief + the pit plan
            return
        if eng.brain is not None and eng.brain.x.command(text):    # requests with a value: car numbers, litres, timers, chat
            return
        intent, _ = understand(text)
        if intent == "pit_plan" and pit:
            pit.propose(); return
        if intent == "rain":
            from .rain import tips, WET_NAME
            st = getattr(self, "_strat", None)
            lvl = st.wet_lvl if st else None
            head = f"Track is {WET_NAME.get(lvl, 'dry')}. " if lvl else ""
            for i, tip in enumerate(tips(2, seed=int(time.time()), track_key=st.track if st else None)):
                self._crew_say("ENGINEER", (head if i == 0 else "") + tip)
            return
        if intent == "strategy" and getattr(self, "_strat", None):
            st = self._strat
            if st.b is None:
                self._crew_say("ENGINEER", "No session yet.")
            elif st.plans and st.b.is_race():
                st.say_plan(st.rec, intro="Current plan")
            else:
                st.brief()
            return
        if intent == "meeting":
            if self._in_car():
                eng.voice.say("tb_standby", prio=PRIO_URGENT); return
            self._q.put({"t": "goto", "tab": "team"}); self._team_obj().start()
            # memory (2026-10-24): "debrief" opens the debrief, any other meeting request the pre-race meeting
            self._q.put({"t": "team_meeting", "kind": "debrief" if "debrief" in text.lower() else "prerace"}); return
        if intent in ("fuel", "fuel_per_lap", "next_stop") and st is not None:
            try:
                if st.answer(intent):
                    return
            except Exception as e:
                self._log(f"[strategy] answer: {e!r}")
        if intent == "next_stop":
            intent = "strategy" if st is None else None   # no plan yet: the engineer says what he has
            if intent is None:
                eng.voice.say("tb_no_data", prio=PRIO_URGENT); return
        if intent and eng.brain:
            eng.brain.answer(intent); return
        if self._in_car():
            self._save_note(text)
            eng.voice.say("ack", {"_variant": 1}, prio=PRIO_URGENT)
            return
        if team and team.state == "ready":
            self._q.put({"t": "goto", "tab": "team"}); self._q.put({"t": "team_heard", "text": text}); return
        eng.voice.say("ans_didnt_catch", prio=PRIO_URGENT)

    def _save_note(self, text):
        from . import notes
        b = self._engine.brain
        try:
            wk = b.info("WeekendInfo", {})
            d = b.drivers().get(b.me(), {})
            dist = float(b.g("LapDist", 0) or 0)
            key = (b.c.at(dist) or b.c.nearest_behind(dist)) if b.c else None
            corner = key.replace("_", " ").title().replace("Nascar", "NASCAR") if key else None
            lap = int(b.g("LapCompleted", 0) or 0) + 1
            notes.add(text, track=wk.get("TrackName", ""), car=d.get("CarPath", ""), session=b.sess_type,
                      lap=lap, lap_dist=dist, corner=corner)
            if getattr(self, "_pit", None) and self._pit.note(text, lap, corner):
                self._log(f"[pit] remembered for the stop: {text}")
            self._log(f"NOTE: lap {lap}{', ' + corner if corner else ''}: {text}")
        except Exception as e:
            notes.add(text)
            self._log(f"NOTE: {text}")

    # ---------- called from the page ----------
    def load_progress(self):
        p, t = self._progress
        return {"p": p, "text": t}

    def get_state(self):
        from dataclasses import asdict
        from .voice import cc_spotters, builtin_spotters
        return {"settings": asdict(self._s), "spotters": cc_spotters(), "spotters_builtin": builtin_spotters(), "devices": ["Windows default"] + output_devices(),
                "mics": ["Windows default"] + input_devices(),
                "controllers": self._buttons.names if self._buttons else []}

    def poll(self):
        out = []
        try:
            while len(out) < 60:
                out.append(self._q.get_nowait())
        except queue.Empty:
            pass
        if self._buttons:
            names = list(self._buttons.names)
            if names != self._last_ctrl:
                self._last_ctrl = names
                out.append({"t": "controllers", "names": names})
        return out

    def toggle(self):
        if not self._engine:
            return False
        if self._engine.running:
            self._engine.stop()
        else:
            self._engine.start()
        self._q.put({"t": "status", "st": dict(self._engine.status, running=self._engine.running)})
        return self._engine.running

    def set(self, key, value):
        if not hasattr(self._s, key):
            return False
        if key in ("volume", "radio_strength", "crowd_volume"):
            value = round(float(value), 2)
        elif key == "crowd_max_db":                            # crowd (2026-10-24): never above -6 dBFS
            value = max(-48.0, min(-6.0, float(value)))
        elif key == "gaps_every":
            value = int(value)
        setattr(self._s, key, value)
        self._s.save()
        if key == "start_with_windows":
            self._startup(bool(value))
        if key == "mic_device" and getattr(self, "_ptt", None):
            self._ptt.set_device(value or None)
        cr = getattr(self, "_crowd", None)                    # crowd (2026-10-24)
        if cr:
            if key == "device":
                cr.set_device(value)
            elif key.startswith("crowd_"):
                cr.apply()
        if self._engine:
            if key == "device":
                self._engine.set_device(value)
            else:
                self._engine.apply()
        return True

    def ask(self, text):
        if self._engine:
            return self._engine.ask(text)
        return None

    def radio_check(self):
        if self._engine:
            self._engine.voice.test_tone()

    def demo(self):
        try:
            from .demo import run_demo
            from .engine import VOCAB, PRESET, LANDMARKS
            run_demo(VOCAB, PRESET, LANDMARKS, None, self._s.device or None, self._s.volume, self.log)
        except Exception as e:
            self._log(f"Demo problem: {e!r}")
        return True

    def _bind_action(self, action):
        """A command button on the wheel: same as asking on the radio."""
        kind, what = BIND_ACTIONS.get(action, (None, None))
        eng = self._engine
        b = eng.brain if eng else None
        self._log(f"[button] {action}")
        if kind == "pit" and getattr(self, "_pit", None):
            self._pit.propose()
        elif b is None:
            from .voice import PRIO_URGENT
            eng.voice.say("tb_no_data", prio=PRIO_URGENT)
        elif kind == "intent":
            b.answer(what)
        elif kind == "cmd":
            b.x.command(what)

    def marks_list(self):
        from .extras import marks
        out = []
        for uid, m in sorted(marks().items(), key=lambda kv: -(kv[1].get("at") or 0)):
            when = time.strftime("%b %d", time.localtime(m["at"])) if m.get("at") else ""
            out.append({"id": uid, "name": m.get("name", ""), "car": m.get("car"), "when": when})
        return out

    def unmark_id(self, uid):
        from .extras import marks, save_marks
        marks().pop(str(uid), None)
        save_marks()
        return True

    def capture_bind(self, action):
        if not self._buttons or action not in BIND_ACTIONS:
            return False
        def got(name, btn):
            bnd = {"device": name, "button": btn}
            binds = dict(self._s.binds or {})
            binds[action] = bnd
            self._s.binds = binds; self._s.save()
            self._q.put({"t": "bind", "attr": "bind-" + action, "binding": bnd})
        self._buttons.capture = got
        return True

    def clear_bind(self, action):
        binds = dict(self._s.binds or {})
        binds.pop(action, None)
        self._s.binds = binds; self._s.save()
        if self._buttons:
            self._buttons.capture = None
        return True

    def capture(self, attr):
        if not self._buttons:
            return False
        def got(name, btn):
            b = {"device": name, "button": btn}
            setattr(self._s, attr, b); self._s.save()
            self._q.put({"t": "bind", "attr": attr, "binding": b})
        self._buttons.capture = got
        return True

    def clear_binding(self, attr):
        setattr(self._s, attr, None); self._s.save()
        if self._buttons:
            self._buttons.capture = None
        return True

    # ---------------- lap analysis ----------------
    def _an_index(self):
        """Background: best lap of every session (cached), for the session list and the all-time reference."""
        if getattr(self, "_an_indexing", False):
            return
        self._an_indexing = True
        def run():
            try:
                from .analysis import lap_index
                self._an_idx = lap_index(progress=lambda i, n: setattr(self, "_an_idx_prog", (i, n)))
            except Exception as e:
                self._log(f"[analysis] index: {e!r}")
            self._an_indexing = False
        threading.Thread(target=run, daemon=True).start()

    # ---------------- series prep ----------------
    def _idx(self):
        idx = getattr(self, "_an_idx", None)
        if idx is None:
            import json
            from .telemetry import CACHE_DIR
            try:
                idx = json.load(open(os.path.join(CACHE_DIR, "laps_index.json"), encoding="utf-8"))
            except Exception:
                idx = {}
            self._an_idx = idx
        return idx

    def prep_state(self):
        from .series import series_list, week_now, SERIES
        idx = self._idx()
        cars, tracks = {}, {}
        for v in idx.values():
            if v.get("error") or not v.get("car_path") or not v.get("track"):
                continue
            cars.setdefault(v["car_path"], v.get("car") or v["car_path"])
            t = tracks.setdefault(v["car_path"], {})
            e = t.setdefault(v["track"], {"display": v.get("track_display") or v["track"], "sessions": 0})
            e["sessions"] += 1
        sched = sorted({t for S in SERIES for t in S["weeks"].values()})
        return {"series": series_list(), "week": week_now(), "cars": cars, "tracks": tracks, "sched_tracks": sched,
                "pick": {"series": self._s.prep_series, "car": self._s.prep_car, "track": self._s.prep_track}}

    def prep_info(self, series_id, car_path, track_key):
        from .series import (series_by_id, track_info, MULTICLASS_GTP, MULTICLASS_GT3, CAR_NOTES, week_now,
                             SCHEDULE_PDF, your_numbers, race_plan)
        from .track_theme import theme, norm
        S = series_by_id(series_id)
        self._s.prep_series, self._s.prep_car, self._s.prep_track = series_id, car_path, track_key
        self._s.save()
        idx = self._idx()
        rows = sorted([(k, v) for k, v in idx.items() if not v.get("error") and v.get("car_path") == car_path
                       and v.get("track") == track_key], key=lambda kv: kv[1].get("date", ""))
        display = rows[0][1].get("track_display") if rows else track_key
        cp = car_path.lower()
        klass = ("GTP" if any(x in cp for x in ("lmdh", "gtp", "963", "499p", "vseriesr", "arx06", "valkyrie")) else
                 "LMP2" if "p217" in cp or "dallarap" in cp else "GT3" if "gt3" in cp else "")
        ti = track_info(display, track_key)
        watch = list(ti["watch"]) if ti else []
        multi = (MULTICLASS_GTP if klass in ("GTP", "LMP2") else MULTICLASS_GT3 if klass == "GT3" else []) if len(S["classes"]) > 1 else []
        wk = week_now()
        nd = norm(display)
        here_weeks = [w for w, t in S["weeks"].items() if norm(t) == nd or norm(t) in nd or nd in norm(t)]
        best = min((v["best"]["time"] for _, v in rows if v.get("best")), default=None)
        laps = sum(sum(1 for L in v.get("laps", []) if L.get("complete")) for _, v in rows)
        this_week = S["weeks"].get(wk)
        sched, next_here = None, None
        try:                                   # the official schedule (your iRacing account data, or the season PDF)
            from . import schedule as SC
            sc = SC.series(S.get("rid"), S.get("pdf"))
            if sc:
                sched = SC.summary(sc, car_path)
                cur = SC.week_now(sc)
                if cur:
                    wk, this_week = cur["wk"], cur["track"]
                here_weeks = [w["wk"] for w in SC.weeks_at(sc, display)]
                nx = SC.next_at(sc, display)
                if nx:
                    next_here = next((w for w in sched["weeks"] if w["wk"] == nx["wk"]), None)
        except Exception as e:
            self._log(f"[prep] schedule: {e!r}")
        out = {"series": {k: S[k] for k in ("name", "tag", "license", "classes", "minutes", "setup", "notes")},
               "week": wk, "this_week": this_week, "here_weeks": here_weeks, "known_weeks": S["weeks"],
               "schedule": sched, "next_here": next_here,
               "schedule_url": SCHEDULE_PDF, "klass": klass, "track": display, "car": rows[0][1].get("car") if rows else car_path,
               "theme": theme(display, track_key), "watch": watch, "multi": multi, "car_notes": CAR_NOTES.get(car_path, []),
               "quick": {"sessions": len(rows), "laps": laps, "best": best}}
        self._prep_req = getattr(self, "_prep_req", 0) + 1
        req = self._prep_req
        if rows:
            def run():
                try:
                    from .analysis import build_theory, load_theory, save_theory, theory_cache_key, theory_sources
                    from .telemetry import Session
                    base = None
                    for sid, v in reversed(rows):
                        if any(L.get("valid") for L in v.get("laps", [])):
                            base, base_sid = Session(v["path"]), sid
                            break
                    th = None
                    if base:
                        srcs = theory_sources(idx, base, base_sid)
                        key = theory_cache_key(base, srcs)
                        th = load_theory(key)
                        if th is None:
                            th = build_theory(base, srcs)
                            if th:
                                save_theory(key, th)
                    nums = your_numbers(idx, car_path, track_key, landmarks=base.landmarks if base else None,
                                        progress=lambda i, n: self._q.put({"t": "prep_prog", "req": req, "i": i, "n": n}) if req == self._prep_req else None)
                    if req != self._prep_req:
                        return
                    plan = race_plan(S["minutes"], nums.get("typical"), nums.get("fuel_lap"), nums.get("tank"))
                    focus = sorted(th.segs, key=lambda g: -g.get("typical_loss", 0))[:3] if th else []
                    strat = None
                    try:
                        from . import strategy as SG
                        sm = SG.model(car_path, track_key)
                        tank = nums.get("tank")
                        ev = SG.last_race(car_path, track_key)
                        race_s = (ev or {}).get("race_s") or (S.get("minutes") or 0) * 60
                        temp = ev.get("track_temp") if ev else None
                        src = "your last race here" if ev else "series default"
                        if next_here:                  # the scheduled race here wins: its length, BoP fuel, forecast
                            if next_here.get("min"):
                                race_s, src = next_here["min"] * 60, f"week {next_here['wk']} schedule"
                            if next_here.get("fuel") and nums.get("tank_max"):
                                tank = nums["tank_max"] * next_here["fuel"] / 100
                            if next_here.get("temp"):
                                temp = max(next_here["temp"]) + 6      # forecast air -> track (about +6 °C)
                        if sm.get("fuel_lap") and tank and race_s:
                            pl = SG.best_plans(sm, race_s, tank, tank, 0, 0.0, temp, 0)
                            last_pace = nums.get("last_pace")
                            cond = SG.conditions(sm, temp if next_here else nums.get("last_temp"), nums.get("last_wet"), last_pace)
                            rainx = None
                            try:
                                from . import rain as R
                                mine, nwet = R.wet_pace(car_path, track_key)
                                chance = (next_here or {}).get("rain") or 0
                                rainx = {"chance": chance, "plan": R.rain_plan(sm, pl[0]["res"] if pl else None, race_s, chance, mine),
                                         "tips": R.tips(5, seed=int(time.time() // 86400), track_key=display), "wet_laps": nwet,
                                         "mine": {str(k): round(v, 1) for k, v in mine.items()}}
                            except Exception as e:
                                self._log(f"[prep] rain: {e!r}")
                            strat = {"plans": [SG.describe(o, True, "ABC"[i]) for i, o in enumerate(pl)], "cond": cond, "event": ev, "rain": rainx,
                                     "race_min": round(race_s / 60), "source": src, "tank": tank, "next": next_here,
                                     "learned": sm.get("learned", []), "n": sm.get("n", 0), "sims": sm.get("race_sims", 0),
                                     "fuel_effect": sm["fuel_effect"], "tyre_deg": sm["tyre_deg"], "lane_loss": sm["lane_loss"]}
                    except Exception as e:
                        self._log(f"[prep] strategy: {e!r}")
                    self._q.put({"t": "prep_stats", "req": req, "nums": {k: v for k, v in nums.items() if k != "sig"},
                                 "theory": th.time if th else None, "plan": plan, "strategy": strat,
                                 "focus": [{"name": g["name"], "loss": g.get("typical_loss", 0)} for g in focus if g.get("typical_loss", 0) > 0.02]})
                except Exception as e:
                    self._log(f"[prep] {e!r}")
                    self._q.put({"t": "prep_stats", "req": req, "error": True})
            threading.Thread(target=run, daemon=True).start()
        out["req"] = req
        return out

    def an_sessions(self):
        from .telemetry import list_sessions, car_name
        import json
        from .telemetry import CACHE_DIR
        idx = getattr(self, "_an_idx", None)
        if idx is None:
            try:
                idx = json.load(open(os.path.join(CACHE_DIR, "laps_index.json"), encoding="utf-8"))
            except Exception:
                idx = {}
            self._an_idx = idx
        self._an_index()
        out = []
        for s in list_sessions():
            v = idx.get(s["id"], {})
            if v and v.get("laps") is not None and not any(L.get("complete") for L in v.get("laps", [])) and "error" not in v:
                continue   # indexed and has no full lap: hide
            track = v.get("track_display") or s["track"].title()
            car = v.get("car") or car_name(s["car"])
            date = s["date"][:10] + " " + s["date"][11:16].replace("-", ":")
            best = v.get("best")
            label = f"{track}  ·  {car}  ·  {date}" + (f"  ·  best {best['time'] // 60:.0f}:{best['time'] % 60:06.3f}" if best else "")
            out.append({"id": s["id"], "label": label})
        self._an_paths = {s["id"]: s["path"] for s in list_sessions()}
        return out

    def an_open(self, sid):
        from .analysis import open_session, all_time_best
        try:
            path = self._an_paths[sid]
            se = open_session(path)
            self._an = {"sess": se, "sid": sid}
            fmt = lambda t: f"{int(t // 60)}:{t % 60:06.3f}"
            refs = []
            if se.best:
                refs.append({"key": "best", "label": f"Best lap  ·  {fmt(se.best['time'])}"})
            idx = getattr(self, "_an_idx", {}) or {}
            ab = all_time_best(idx, se.car_path, se.track_name)
            if ab and ab[0] != sid and (not se.best or ab[1]["best"]["time"] < se.best["time"] - 0.001):
                refs.insert(0, {"key": "alltime", "label": f"All-time best  ·  {fmt(ab[1]['best']['time'])}"})
                self._an["alltime"] = ab
            if not se.best:
                return {"error": "No complete lap in this session."}
            theory = None
            try:
                from .analysis import build_theory
                th = build_theory(se)
                if th and th.gain > 0.0005:
                    self._an["theory"] = th
                    theory = th.summary()
                    at = next((i + 1 for i, r in enumerate(refs) if r["key"] == "best"), 0)
                    refs.insert(at, {"key": "theory", "label": f"Theoretical best  ·  {fmt(th.time)}"})
            except Exception as e:
                self._log(f"[analysis] theory: {e!r}")
            for L in se.laps:
                if L["complete"]:
                    refs.append({"key": f"lap:{L['n']}", "label": f"Lap {L['n']}  ·  {fmt(L['time'])}"})
            cr = getattr(self, "_coach_ref", None)                                 # coach (2026-10-24)
            if cr is not None and abs(cr.track_len - se.track_len) < 0.03 * se.track_len:
                refs.insert(0, {"key": "coach", "label": f"Coach ref  ·  {cr.label}  ·  {fmt(cr.time)}"})
            self._an_theory_all(se, sid)
            try:
                from . import notes
                from datetime import datetime
                import re as _re
                m = _re.search(r"(\d{4}-\d\d-\d\d \d\d-\d\d-\d\d)", os.path.basename(path))
                t0 = datetime.strptime(m.group(1), "%Y-%m-%d %H-%M-%S").timestamp() if m else 0
                se.notes = notes.for_session(se.track_name, t0, os.path.getmtime(path))
            except Exception:
                se.notes = []
            try:
                from .track_theme import theme
                tt = theme(se.track_display, se.track_name)
            except Exception:
                tt = None
            return {"sid": sid, "theme": tt, "theory": theory, "notes": se.notes, "car": se.car, "track": se.track_display, "laps": se.laps, "best_n": se.best["n"],
                    "map": se.track_map(), "corners": se.find_corners(), "refs": refs, "track_len": se.track_len}
        except Exception as e:
            self._log(f"[analysis] open: {e!r}")
            return {"error": f"Can't read session ({e.__class__.__name__})"}

    def _an_theory_all(self, se, sid):
        """Theoretical best from ALL your sessions in this car at this track (background; cached)."""
        from .analysis import build_theory, theory_sources, theory_cache_key, load_theory, save_theory
        srcs = theory_sources(getattr(self, "_an_idx", {}) or {}, se, sid)
        if not srcs:
            return
        fmt = lambda t: f"{int(t // 60)}:{t % 60:06.3f}"

        def run():
            try:
                key = theory_cache_key(se, srcs)
                th = load_theory(key)
                if th is None:
                    th = build_theory(se, srcs)
                    if th:
                        save_theory(key, th)
                an = getattr(self, "_an", {}) or {}
                if not th or an.get("sid") != sid:
                    return
                own = an.get("theory")
                if own and th.time >= own.time - 0.0005:
                    return                              # nothing better in the other sessions
                an["theory_all"] = th
                self._q.put({"t": "an_ref", "sid": sid, "key": "theory_all",
                             "label": f"All-time theoretical  ·  {fmt(th.time)}", "theory": th.summary()})
            except Exception as e:
                self._log(f"[analysis] theory all: {e!r}")
        threading.Thread(target=run, daemon=True).start()

    def _an_ref(self, key):
        from .analysis import open_session
        se = self._an["sess"]
        if key in ("theory", "theory_all") and self._an.get(key):
            return self._an[key], 0
        if key == "alltime" and self._an.get("alltime"):
            sid, v = self._an["alltime"]
            from .telemetry import Session
            rs = self._an.get("ref_sess")
            if not rs or rs.path != v["path"]:
                rs = Session(v["path"])
                self._an["ref_sess"] = rs
            return rs, v["best"]["n"]
        if key == "coach" and getattr(self, "_coach_ref", None) is not None:   # coach (2026-10-24)
            return self._coach_ref, 0
        if key.startswith("lap:"):
            return se, int(key[4:])
        return se, se.best["n"]

    def an_compare(self, lap_n, ref_key):
        from .analysis import compare
        try:
            se = self._an["sess"]
            rs, rn = self._an_ref(ref_key)
            self._an.update(lap=int(lap_n), ref=(rs, rn))
            self._an_last_section = None
            out = compare(se, int(lap_n), rs, rn)
            try:
                from .mechanic import car_summary
                out["mech_summary"] = car_summary(se)
            except Exception as e:
                self._log(f"[mechanic] {e!r}")
            return out
        except Exception as e:
            self._log(f"[analysis] compare: {e!r}")
            return {"error": f"Can't compare ({e.__class__.__name__})"}

    def an_section(self, d0, d1):
        from .analysis import section
        try:
            se = self._an["sess"]; rs, rn = self._an["ref"]
            out = section(se, self._an["lap"], rs, rn, float(d0), float(d1))
            self._an_last_section = out
            try:
                from .mechanic import advise_section
                advise_section(se, self._an["lap"], out)
            except ImportError:
                pass
            return out
        except Exception as e:
            self._log(f"[analysis] section: {e!r}")
            return {"error": repr(e), "corners": [], "notes": [], "lost": 0, "from": d0, "to": d1}

    # ---------------- driving coach vs a fast reference lap: coach (2026-10-24) ----------------
    # The Garage 61 token lives only in %LOCALAPPDATA%\RaceEngineer\garage61_token.txt (see garage61.py):
    # never in the settings JSON, never logged, never sent back to the page.
    def coach_state(self):
        from . import garage61
        cr = getattr(self, "_coach_ref", None)
        return {"token": garage61.has_token(), "ref": cr.info() if cr is not None else None}

    def g61_save_token(self, token):
        from . import garage61
        try:
            garage61.save_token(str(token or ""))
            return {"ok": True, "token": garage61.has_token()}
        except OSError as e:
            self._log(f"[coach] couldn't save the Garage 61 token ({e.__class__.__name__})")
            return {"ok": False, "token": garage61.has_token()}

    def g61_clear_token(self):
        from . import garage61
        garage61.clear_token()
        return {"ok": True, "token": False}

    def g61_test(self):
        from . import garage61
        return garage61.test_token()

    def coach_g61_laps(self):
        """Fastest Garage 61 laps the token can see for the open session's car + track."""
        from . import garage61
        try:
            se = self._an["sess"]
            c = garage61.Client()
            me = c.me()
            di = se.info.get("DriverInfo", {}) or {}
            drv = next((x for x in di.get("Drivers", []) or [] if x.get("CarIdx") == di.get("DriverCarIdx")), {})
            wk = se.info.get("WeekendInfo", {}) or {}
            car_id, track_id = garage61.match_ids(c, drv.get("CarID"), wk.get("TrackID"), se.car, se.track_display)
            if not car_id or not track_id:
                return {"ok": False, "error": "Couldn't match this car or track on Garage 61."}
            res = garage61.fastest_laps(c, car_id, track_id, me_id=me.get("id"))
            return dict(res, ok=True)
        except garage61.G61Error as e:
            return e.as_dict()
        except Exception as e:
            self._log(f"[coach] g61 laps: {e.__class__.__name__}")
            return {"ok": False, "error": "Couldn't list Garage 61 laps."}

    def _pick_file(self, kind):
        try:
            import webview
            ft = ("Lap CSV (*.csv)",) if kind == "csv" else ("iRacing telemetry (*.ibt)",)
            mode = getattr(getattr(webview, "FileDialog", None), "OPEN", None) or webview.OPEN_DIALOG
            r = self._win.create_file_dialog(mode, allow_multiple=False, file_types=ft) if self._win else None
            return (r[0] if isinstance(r, (list, tuple)) else r) if r else None
        except Exception as e:
            self._log(f"[coach] file dialog: {e!r}")
            return None

    def coach_load(self, kind, arg=None):
        """kind = 'g61' (arg = lap id), 'csv' or 'ibt' (arg = path, or None to pick a file)."""
        from . import coach, garage61
        try:
            se = self._an["sess"]
            if kind == "g61":
                ref = coach.ref_from_garage61(garage61.Client(), arg, se.track_len)
            else:
                path = arg or self._pick_file(kind)
                if not path:
                    return {"ok": False, "cancel": True}
                if kind == "csv":
                    ref = coach.ref_from_csv(path, track_len=se.track_len)
                else:
                    ref, rs = coach.ref_from_ibt(path, landmarks=se.landmarks)
                    if rs.track_name != se.track_name:
                        return {"ok": False, "error": f"That lap is from {rs.track_display}, this session is {se.track_display}."}
            if abs(ref.track_len - se.track_len) > 0.03 * se.track_len:
                return {"ok": False, "error": f"That lap is {ref.track_len:.0f} m long; this track is {se.track_len:.0f} m. Wrong track or layout?"}
            self._coach_ref = ref
            fmt = lambda t: f"{int(t // 60)}:{t % 60:06.3f}"
            return {"ok": True, "key": "coach", "label": f"Coach ref  ·  {ref.label}  ·  {fmt(ref.time)}", "ref": ref.info()}
        except garage61.G61Error as e:
            return e.as_dict()
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:
            self._log(f"[coach] load: {e!r}")
            return {"ok": False, "error": f"Couldn't read that lap ({e.__class__.__name__})."}

    def coach_run(self, lap_n, ref_key):
        """Corner-by-corner coaching for this lap vs the reference picked in the Analysis tab."""
        from . import coach
        try:
            se = self._an["sess"]
            rs, rn = self._an_ref(ref_key)
            info = rs.info() if isinstance(rs, coach.RefLap) else {"label": {"best": "Your best lap", "alltime": "Your all-time best",
                   "theory": "Theoretical best", "theory_all": "All-time theoretical"}.get(ref_key, f"Lap {rn}"), "source": "session"}
            return coach.coach_session(se, int(lap_n), rs, rn, ref_info=info)
        except Exception as e:
            self._log(f"[coach] run: {e!r}")
            return {"error": f"Can't coach this lap ({e.__class__.__name__})"}

    def coach_last(self):
        """The last coaching summary (plain dict), e.g. for the team meeting room."""
        from . import coach
        return coach.last_summary()

    # ---------------- the team (local AI) ----------------
    def _team_obj(self):
        if getattr(self, "_team", None) is None:
            from .team import Team
            self._team = Team(self._s, log=self._log, emit=self._q.put)
            self._team_hist = []
        return self._team

    def team_open(self):
        t = self._team_obj(); t.start()
        return {"state": t.state, "reason": t.reason}

    def team_close(self):
        self.meet_live(False, save=False)
        if getattr(self, "_team", None):
            self._team.stop()
        return True

    # ---------------- every engine tick ----------------
    def _tick(self, brain):
        cr = getattr(self, "_crowd", None)                    # crowd (2026-10-24): a tiny state update per tick
        if cr:
            cr.tick(brain)
        if getattr(self, "_strat", None):
            self._strat.tick(brain)
        if getattr(self, "_pit", None):
            self._pit.tick(brain)
        if getattr(self, "_mem", None):                       # memory (2026-10-24): cheap per tick, writes on session end
            try:
                self._mem.tick(brain, getattr(self, "_strat", None))
            except Exception as e:
                if not getattr(self, "_mem_err", None):
                    self._mem_err = True; self._log(f"[memory] {e!r}")
        rem = getattr(self, "_remote", None)
        if rem:
            rem.feed(brain, self._pit)

    # ---------------- pit crew (window + iPad) ----------------
    def _crew_say(self, role, text):
        self._log(f"{role}: {text}" if role in ("ENGINEER", "STRATEGIST") else f"[pit] {role}: {text}")
        self._speaker_obj().say(role, text)

    def rc_test(self):
        """Settings > Race Control: hear the race director (green flag call)."""
        if self._engine:
            v = self._engine.voice
            v.rc_volume = float(getattr(self._s, "race_control_volume", 0.8) or 0)
            from .voice import PRIO_URGENT
            v.say("rc:green", prio=PRIO_URGENT, max_age=10)
        return True

    # crowd (2026-10-24): Settings > Race Control > Trackside crowd
    def crowd_state(self):
        cr = getattr(self, "_crowd", None)
        return cr.info() if cr else {"state": "off", "sounds": 0, "tracks": 0, "status": "", "playing": 0}

    def crowd_test(self):
        cr = getattr(self, "_crowd", None)
        return cr.test() if cr else {"ok": False, "msg": "Crowd not running"}

    def crowd_copy(self):
        cr = getattr(self, "_crowd", None)
        if cr:
            return cr.copy_from_simhub()
        from .crowd import copy_from_simhub
        return copy_from_simhub(log=self._log)

    def beep_test(self):
        """Settings > Race Control: hear the shift beep with the current settings."""
        from .extras import play_beep
        play_beep(self._s)
        return True

    def spot_test(self):
        """Settings > Sound: hear the spotter."""
        from .voice import PRIO_URGENT
        if self._engine:
            v = self._engine.voice
            for sid in ("car_left", "still_there", "clear_left"):
                v.say(sid, prio=PRIO_URGENT, max_age=10)
        return True

    def strat_test(self):
        """Settings > Sound: hear the strategist."""
        from .strat_lines import Lines, f_laps, f_litres
        L = Lines(seed=int(time.time()))
        for t in (L.say("rc")["text"], L.say("fuel_start", flaps=f_laps(8), fuel=f_litres(58))["text"]):
            for sent in __import__("re").split(r"(?<=[.!?])\s+", t):
                self._speaker_obj().say("STRATEGIST", sent)
        return True

    def _pit_emit(self, e):
        self._q.put(e)
        rem = getattr(self, "_remote", None)
        if rem and e.get("t") == "pit_state":
            rem.push("pit", e["s"])
        if rem and e.get("t") == "strat":
            rem.push("strat", e["s"])

    def _strategy_backfill(self):
        """Store every saved telemetry file in the strategy database (only new ones; first time takes a minute)."""
        try:
            time.sleep(8)
            from .strategy import backfill
            from .telemetry import list_sessions
            n = backfill(list_sessions(), log=self._log)
            if n:
                self._log(f"[strategy] stored {n} sessions")
        except Exception as e:
            self._log(f"[strategy] {e!r}")

    def strat_state(self):
        s = getattr(self, "_strat", None)
        return s.state() if s else {"plans": []}

    def pit_state(self):
        p = getattr(self, "_pit", None)
        return p.state() if p else {"live": False}

    def pit_propose(self):
        p = getattr(self, "_pit", None)
        return bool(p and p.propose())

    def pit_apply(self, plan):
        p = getattr(self, "_pit", None)
        if not p or not p.b:
            return False
        base = p.plan or p.make_plan()
        base.update({k: v for k, v in (plan or {}).items() if k in ("fuel", "tyres", "pressure", "ws", "fr", "compound")})
        ok = p.apply(base)
        if ok:
            self._speaker_obj().say("ENGINEER", "Copy, pit menu updated.")
        return ok

    def pit_clear(self):
        p = getattr(self, "_pit", None)
        if p and p.b:
            p.plan = None; p.send_clear(); p.emit({"t": "pit_state", "s": p.state()})
        return True

    # ---------------- iPad (live telemetry + pit, on your home Wi-Fi) ----------------
    def _remote_start(self):
        if not getattr(self._s, "remote_on", True):
            return
        from .remote import Remote
        if not self._s.remote_token:
            import secrets
            self._s.remote_token = secrets.token_urlsafe(9); self._s.save()
        self._remote = Remote(self, port=self._s.remote_port, token=self._s.remote_token, log=self._log)
        self._remote.start()

    def remote_info(self):
        rem = getattr(self, "_remote", None)
        if not rem:
            return {"on": False}
        return {"on": True, "url": rem.url(), "qr": rem.qr_data_uri()}

    # ---------------- team meeting by voice ----------------
    def _speaker_obj(self):
        if getattr(self, "_speaker", None) is None:
            from .meeting import Speaker
            self._speaker = Speaker(self._s, log=self._log, emit=self._q.put)
        return self._speaker

    def meet_state(self):
        hf = getattr(self, "_hf", None)
        return {"voice": bool(self._s.meet_voice), "live": bool(hf and hf.on), "want_live": bool(self._s.meet_live)}

    def meet_voice(self, on):
        self._s.meet_voice = bool(on); self._s.save()
        if not on and getattr(self, "_speaker", None):
            self._speaker.stop()
        return True

    def meet_stop(self):
        """Interrupt: the team stops talking."""
        if getattr(self, "_speaker", None):
            self._speaker.stop()
        return True

    def meet_live(self, on, save=True):
        if save:
            self._s.meet_live = bool(on); self._s.save()
        hf = getattr(self, "_hf", None)
        if not on:
            if hf:
                hf.stop()
            self._q.put({"t": "meet_state", "state": "off"})
            return False
        if hf is None:
            from .meeting import HandsFree
            hf = self._hf = HandsFree(self._meet_heard, self._meet_can_listen, device=self._s.mic_device or None,
                                      log=self._log, emit=self._q.put)
        hf.device = self._s.mic_device or None
        hf.start()
        self._q.put({"t": "meet_state", "state": "listening" if hf.on else "off"})
        return hf.on

    def _meet_can_listen(self):
        t = getattr(self, "_team", None)
        sp = getattr(self, "_speaker", None)
        ptt = getattr(self, "_ptt_down", False)
        busy = getattr(self, "_team_busy", False) and time.time() - getattr(self, "_team_busy_t", 0) < 90
        return bool(t and t.state == "ready" and not busy and not ptt and (sp is None or sp.idle()))

    def _meet_heard(self, audio):
        ptt = getattr(self, "_ptt", None)
        if not ptt or not ptt.ready:
            self._q.put({"t": "toast", "text": "Speech recognition not ready"}); return
        self._q.put({"t": "meet_state", "state": "thinking"})
        text = ptt.transcribe(audio)
        if not text or len(text) < 2:
            self._q.put({"t": "meet_state", "state": "listening"}); return
        self._log(f"YOU: {text}")
        self._team_busy, self._team_busy_t = True, time.time()     # mic stays muted until the answer is done
        self._q.put({"t": "team_heard", "text": text})

    def team_reset(self):
        self._team_hist = []
        self._meet = None                                   # memory (2026-10-24): leaves the meeting / debrief
        return True

    def team_ask(self, text):
        t = self._team_obj()
        if getattr(self, "_meet", None):                    # memory (2026-10-24): in a meeting the facts pack is the DATA
            from . import briefing as BR
            mt = self._meet
            wi = BR.what_if(text, mt.get("ctx") or {}) if mt.get("kind") == "prerace" else None
            return self._team_run(t, text, BR.model_context(mt, wi))
        an = getattr(self, "_an", None)
        if not an or "lap" not in an:
            # no lap picked yet: use the newest session with a full lap vs its best
            try:
                sess = self.an_sessions()
                for x in sess:
                    r = self.an_open(x["id"])
                    if not r.get("error"):
                        laps = [L for L in r["laps"] if L["complete"]]
                        self.an_compare(laps[-1]["n"], "best")
                        break
            except Exception as e:
                self._log(f"[team] no data: {e!r}")
        an = getattr(self, "_an", {}) or {}
        from .team import build_context
        from .analysis import compare
        try:
            se = an["sess"]; rs, rn = an["ref"]
            cmp = compare(se, an["lap"], rs, rn)
            try:
                from .mechanic import car_summary
                ms = car_summary(se)
            except Exception:
                ms = None
            from .analysis import Theory
            if isinstance(rs, Theory):
                ref_label = f"theoretical best {rs.time // 60:.0f}:{rs.time % 60:06.3f} (your best piece of every part of the track, stitched together)"
            else:
                ref_label = f"best lap {rn}" + (" of another session (all-time best)" if rs is not se else " of this session")
            ctx = build_context(se, cmp, an["lap"], ref_label, getattr(self, "_an_last_section", None), ms)
            nts = getattr(se, "notes", None) or []
            if nts:
                ctx += "\nWhat the driver said on the radio this session: " + " | ".join(
                    f"lap {n.get('lap')}{' at ' + n['corner'] if n.get('corner') else ''}: \"{n['text']}\"" for n in nts[-12:])
        except Exception as e:
            self._team_busy = False
            self._q.put({"t": "team_done", "err": "Open a lap in Analysis first"}); return False
        try:
            from .series import series_by_id
            S = series_by_id(self._s.prep_series)
            if S.get("classes"):
                ctx += f"\nPractising for: {S['name']} ({S['tag']}), {S['minutes']} min races, classes {', '.join(S['classes'])}."
        except Exception:
            pass
        return self._team_run(t, text, ctx)

    def _team_run(self, t, text, ctx):
        """Stream the team's answer to text with this DATA (split out of team_ask for the meeting, 2026-10-24)."""
        hist = self._team_hist
        speak = bool(self._s.meet_voice)
        q = text
        if speak:
            q += "\n(Spoken in a meeting: 2 to 4 short spoken sentences, no lists, no symbols.)"
            from .meeting import Splitter
            sp = self._speaker_obj()
            sp.stop()
            split = Splitter(sp.say)
        self._team_busy, self._team_busy_t = True, time.time()
        self._q.put({"t": "meet_state", "state": "thinking"})

        def on_text(d):
            self._q.put({"t": "team_tok", "text": d})
            if speak:
                split.feed(d)

        def on_done(err, full=""):
            if full:
                hist.extend([{"role": "user", "content": text}, {"role": "assistant", "content": full}])
                del hist[:-12]
            if speak:
                split.flush()
            self._team_busy = False
            self._q.put({"t": "team_done", "err": err})
            hf = getattr(self, "_hf", None)
            self._q.put({"t": "meet_state", "state": "listening" if hf and hf.on else "off"})
        threading.Thread(target=t.ask, args=(q, ctx, list(hist), on_text, on_done), daemon=True).start()
        return True

    # ---------------- race memory, pre-race meeting, debrief (memory, 2026-10-24) ----------------
    def _mem_where(self):
        """Car + track for the memory: the live session, else the last stored session, else Series prep."""
        from . import memory as M
        b = self._engine.brain if self._engine else None
        if b is not None:
            try:
                d = b.drivers().get(b.me(), {}) or {}
                wk = b.info("WeekendInfo", {}) or {}
                if d.get("CarPath") and wk.get("TrackName"):
                    return {"car": d["CarPath"], "track": wk["TrackName"], "car_name": d.get("CarScreenName"),
                            "track_name": wk.get("TrackDisplayName"), "cls": M.car_class(d["CarPath"], d.get("CarClassShortName")), "b": b}
            except Exception:
                pass
        car, track = M.last_combo()
        if not car:
            car, track = self._s.prep_car, self._s.prep_track
        return {"car": car, "track": track, "cls": M.car_class(car), "b": None}

    def mem_state(self):
        from . import memory as M
        w = self._mem_where()
        r = M.recall(w["car"], w["track"], w.get("cls"))
        ag = dict(r["aggregates"]); ag.pop("notes", None)
        return {"car": w.get("car_name") or r.get("car_name") or w["car"], "track": w.get("track_name") or r.get("track_name") or w["track"],
                "live": w["b"] is not None, "source": r["source"], "from_cars": r["from_cars"], "ag": ag,
                "notes": (r["aggregates"].get("notes") or [])[:3],
                "sessions": [{k: x.get(k) for k in ("date", "session", "laps", "best", "spins", "offs", "incidents")}
                             | {"pos": (x.get("race") or {}).get("pos"), "car": x.get("car_name")} for x in r["sessions"][:5]]}

    def _mech_recs(self, car, track):
        """The mechanic's recommendations from the session open in Analysis, when it's this car + track."""
        an = getattr(self, "_an", None) or {}
        se = an.get("sess")
        if not se or getattr(se, "car_path", None) != car or getattr(se, "track_name", None) != track:
            return [], None
        recs, ms = [], None
        try:
            from .mechanic import corner_advice, car_summary
            for c in se.find_corners():
                for n in corner_advice(se, c["key"]):
                    if "Try:" in n or "technique" in n or "bottoming" in n or "close to the ground" in n:
                        recs.append(f"{c['name']}: {n}")
            ms = car_summary(se)
        except Exception as e:
            self._log(f"[memory] mechanic: {e!r}")
        return recs, ms

    def team_meeting(self, kind="prerace"):
        """Build the pre-race meeting or the debrief (fixed code), start the team AI if it's allowed.
        -> {"pack", "text", "team", "reason"}; the page shows the facts and asks the AI to talk them through."""
        from . import briefing as BR, memory as M
        w = self._mem_where()
        b = w["b"]
        metric = b.metric() if b is not None else True
        recs, ms = self._mech_recs(w["car"], w["track"])
        try:
            if kind == "debrief":
                last = getattr(getattr(self, "_mem", None), "last", None)
                if not (last and last.get("car") == w["car"] and last.get("track") == w["track"]):
                    ss = M.recall(w["car"], w["track"], w.get("cls"))
                    last = ss["sessions"][0] if ss["source"] == M.THIS_CAR and ss["sessions"] else last
                pack = BR.debrief_pack(last, metric, recs)
            else:
                race_s = race_laps = tank = fuel_now = temp = None
                label = None
                st = getattr(self, "_strat", None)
                if b is not None:
                    try:
                        tank = st.tank() if st is not None and st.b is b else None
                        for x in (b.info("SessionInfo", {}) or {}).get("Sessions", []) or []:
                            if "race" in str(x.get("SessionType", "")).lower():
                                race_s = S_num(x.get("SessionTime"))
                                race_laps = x.get("SessionLaps") if isinstance(x.get("SessionLaps"), int) else None
                                label = "this event"
                        if not race_s and st is not None and st.b is b:
                            nx = st._forecast() or {}
                            if nx.get("min"):
                                race_s, label = nx["min"] * 60, "this week's race in the schedule"
                        f = b.g("FuelLevel", 0) or 0
                        fuel_now = f if f > 1 else None
                        temp = b.g("TrackTempCrew")
                    except Exception as e:
                        self._log(f"[memory] race facts: {e!r}")
                if race_laps and not race_s:
                    race_s, label = None, None                 # lap race: briefing works the time out from the pace
                pack = BR.prerace_pack(w["car"], w["track"], w.get("car_name"), w.get("track_name"), w.get("cls"), race_s, label,
                                       tank, fuel_now, temp, metric, recs, ms, race_laps=race_laps)
        except Exception as e:
            self._log(f"[memory] meeting: {e!r}")
            return {"error": repr(e)}
        self._meet, self._team_hist = pack, []
        t = self._team_obj(); t.start()                     # the driving guard decides whether the AI may load
        return {"pack": BR.public(pack), "text": BR.pack_text(pack), "team": t.state, "reason": t.reason}

    def team_whatif(self, text):
        """'What if...' in the meeting, worked out by the strategy code (no AI). -> {"lines": [...] or None}"""
        from . import briefing as BR
        mt = getattr(self, "_meet", None)
        if not mt or mt.get("kind") != "prerace":
            return {"lines": None}
        wi = BR.what_if(text, mt.get("ctx") or {})
        return {"lines": wi["lines"] if wi else None, "kind": wi["kind"] if wi else None}

    def _mem_done(self, summary, debrief):
        """A session was stored: the automatic data review, the memory card, and after a race the debrief."""
        from .memory import review_line
        try:
            line = review_line(summary)
            self._log(f"REVIEW: {line}")
            self._q.put({"t": "mem_review", "text": line})
            self._q.put({"t": "mem", "s": self.mem_state()})
        except Exception as e:
            self._log(f"[memory] review: {e!r}")
        if debrief and getattr(self._s, "team_debrief_auto", True):
            self._q.put({"t": "goto", "tab": "team"})
            self._q.put({"t": "team_meeting", "kind": "debrief"})

    # ---------------- setup helper (no AI) ----------------
    def setup_bank(self, kind=None):
        from .setup_bank import bank_for, current_values, detected
        from .mechanic import car_kind
        se = (getattr(self, "_an", None) or {}).get("sess")
        if se is None:
            try:
                from .analysis import open_session
                from .telemetry import list_sessions
                for x in list_sessions()[:6]:
                    try:
                        cand = open_session(x["path"])
                        if cand.best:
                            se = cand; break
                    except Exception:
                        continue
            except Exception:
                se = None
        auto = car_kind(se) if se else "gt3"
        k = kind or auto
        out = {"kind": k, "auto": auto, "bank": bank_for(k)}
        if se is not None:
            out.update(car=se.car, track=se.track_display, values=current_values(se) if k == auto else {},
                       detected=detected(se) if k == auto else [])
        return out

    def toggle_max(self):
        if not self._win:
            return
        if getattr(self, "_maxed", False):
            self._win.restore(); self._maxed = False
        else:
            self._win.maximize(); self._maxed = True

    def page_ready(self):
        self._page_ready = True
        return True

    def js_error(self, msg):
        """The window's script errors land in the engineer log (2026-10-24)."""
        self._log(f"[ui] {str(msg)[:600]}")
        return True

    def minimize(self):
        if self._win:
            self._win.minimize()

    def win_pos(self):
        """Window position for dragging from the top bar."""
        try:
            return [self._win.x, self._win.y] if self._win else [0, 0]
        except Exception:
            return [0, 0]

    def win_move(self, x, y):
        """Move the window (dragging from the top bar; 2026-10-24: the built-in drag region didn't move it)."""
        try:
            if self._win:
                self._win.move(int(x), int(y))
        except Exception:
            pass
        return True

    def close(self):
        if self._win:
            self._win.destroy()

    def app_info(self):
        return {"version": VERSION}

    def open_url(self, url):
        """Only our own pages (GitHub, Ko-fi, PayPal donate) open from the window."""
        from .series import SCHEDULE_PDF
        ok = ("https://github.com/instabilitycontrol/", "https://ko-fi.com/instabilitycontrol", "https://www.paypal.com/donate/",
              SCHEDULE_PDF)
        if isinstance(url, str) and url.startswith(ok):
            import webbrowser
            webbrowser.open(url)
            return True
        return False

    def report_problem(self):
        """Report a problem: zip the log, the last radio calls, settings (no device names) and the session
        to the Desktop, open the folder and the GitHub problem form. Nothing is uploaded by itself."""
        import zipfile, json, webbrowser
        from dataclasses import asdict
        try:
            stamp = time.strftime("%Y-%m-%d %H-%M")
            desk = None
            try:        # the real Desktop (OneDrive often moves it to ~/OneDrive/Desktop)
                import ctypes
                buf = ctypes.create_unicode_buffer(260)
                if ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf) == 0:
                    desk = buf.value
            except Exception:
                pass
            if not desk or not os.path.isdir(desk):
                desk = os.path.join(os.path.expanduser("~"), "Desktop")
            if not os.path.isdir(desk):
                desk = ROOT
            path = os.path.join(desk, f"Instability Control report {stamp}.zip")
            lines = []
            try:
                with open(LOGF, encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()[-1500:]
            except OSError:
                pass
            calls = [l for l in lines if " ENGINEER:" in l or " YOU:" in l][-60:]
            st = dict(self._engine.status) if self._engine else {}
            s = asdict(self._s)
            for k in ("device", "mic_device", "remote_token", "radio_button", "team_button", "binds", "driver_name"):
                s.pop(k, None)                                   # nothing personal in the report
            info = {"version": VERSION, "time": stamp, "session": st, "settings": s}
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
                z.writestr("log_last_1500_lines.txt", "".join(lines))
                z.writestr("last_radio_calls.txt", "".join(calls))
                z.writestr("session_and_settings.json", json.dumps(info, indent=1, default=str))
            self._log(f"Problem report saved: {path}")
            try:
                os.startfile(desk)
            except Exception:
                pass
            webbrowser.open(REPORT_FORM)
            return {"ok": True, "path": path}
        except Exception as e:
            self._log(f"[report] {e!r}")
            return {"ok": False}

    def open_log(self):
        try:
            os.startfile(LOGF)
        except Exception:
            pass

    def _startup(self, on):
        try:
            folder = os.path.join(os.environ["APPDATA"], r"Microsoft\Windows\Start Menu\Programs\Startup")
            path = os.path.join(folder, "Race Engineer.bat")
            if on:
                pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")   # beta (2026-10-24): the Python running us
                if not os.path.exists(pyw):                                          # (was always ROOT\venv_eng)
                    pyw = os.path.join(ROOT, "venv_eng", "Scripts", "pythonw.exe")
                open(path, "w").write(f'@echo off\r\ncd /d "{ROOT}"\r\nstart "" "{pyw}" -m engineer.app\r\n')
            elif os.path.exists(path):
                os.remove(path)
        except Exception as e:
            self._log(f"Couldn't change Windows startup: {e}")

    def _shutdown(self):
        if getattr(self, "_team", None):
            self._team.stop()
        if getattr(self, "_crowd", None):                     # crowd (2026-10-24)
            self._crowd.close()
        if self._engine:
            self._engine.close()


# ---------------- Windows niceties ----------------
def _win_setup_process():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass
    try:  # own taskbar button + our icon instead of Python's
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("AngeloRacing.RaceEngineer")
    except Exception:
        pass


def ensure_icon():
    ico = os.path.join(HERE, "ui", "assets", "race_engineer.ico")
    if not os.path.exists(ico):
        try:
            from PIL import Image
            from .watch_skia import render_icon_png
            png = render_icon_png(os.path.join(HERE, "ui", "assets", "race_engineer.png"), 256)
            Image.open(png).save(ico, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
        except Exception as e:
            print("icon:", e)
    return ico


def _find_hwnd(title, timeout=10):
    u = ctypes.windll.user32
    u.FindWindowW.restype = wintypes.HWND
    t0 = time.time()
    while time.time() - t0 < timeout:
        h = u.FindWindowW(None, title)
        if h:
            return h
        time.sleep(0.02)
    return None


def _style_window(hwnd, ico):
    u, d = ctypes.windll.user32, ctypes.windll.dwmapi
    d.DwmSetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    try:
        val = ctypes.c_int(2)    # DWMWCP_ROUND: Windows 11 rounded corners
        d.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(val), 4)
        val = ctypes.c_int(1)    # no Windows open/close zoom: our intro is the animation
        d.DwmSetWindowAttribute(hwnd, 3, ctypes.byref(val), 4)
        col = ctypes.c_int(0x00241A12)   # border colour (BGR) - deep navy
        d.DwmSetWindowAttribute(hwnd, 34, ctypes.byref(col), 4)
    except Exception:
        pass
    try:
        LR_LOADFROMFILE, IMAGE_ICON = 0x10, 1
        u.LoadImageW.restype = ctypes.c_void_p
        u.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, ctypes.c_void_p]
        big = u.LoadImageW(None, ico, IMAGE_ICON, 256, 256, LR_LOADFROMFILE)
        small = u.LoadImageW(None, ico, IMAGE_ICON, 32, 32, LR_LOADFROMFILE)
        u.SendMessageW(hwnd, 0x80, 1, big)    # WM_SETICON big
        u.SendMessageW(hwnd, 0x80, 0, small)  # WM_SETICON small
    except Exception:
        pass


def _target_rect(w_css, h_css):
    u = ctypes.windll.user32
    k = u.GetDpiForSystem() / 96.0 if hasattr(u, "GetDpiForSystem") else 1.0
    wa = wintypes.RECT()
    u.SystemParametersInfoW(0x30, 0, ctypes.byref(wa), 0)   # SPI_GETWORKAREA
    w, h = int(w_css * k), int(h_css * k)
    x = wa.left + (wa.right - wa.left - w) // 2
    y = wa.top + (wa.bottom - wa.top - h) // 2
    return (x, y, w, h), k


def _place(hwnd, rect):
    x, y, w, h = rect
    u = ctypes.windll.user32
    u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
    u.SetWindowPos(hwnd, None, x, y, w, h, 0x0010 | 0x0004)   # NOACTIVATE | NOZORDER


W_CSS, H_CSS = 1120, 780


def _orchestrate(win, api, rect, k, ico):
    hwnd = _find_hwnd("Race Engineer")
    if hwnd:
        _style_window(hwnd, ico)
        _place(hwnd, rect)

    def show():
        win.show()
        h = hwnd or _find_hwnd("Race Engineer", 2)
        if h:
            _place(h, rect)
            _style_window(h, ico)
            ctypes.windll.user32.SetForegroundWindow.argtypes = [wintypes.HWND]
            ctypes.windll.user32.SetForegroundWindow(h)

    if api._s.splash:
        try:
            from .intro import play
            play(rect, k, show, lambda: api._page_ready, log=api._log)
        except Exception as e:
            api._log(f"[intro] skipped: {e!r}")
            show()
    else:
        show()
    api._q.put({"t": "reveal"})


def main():
    import webview
    _win_setup_process()
    ico = ensure_icon()
    rect, k = _target_rect(W_CSS, H_CSS)
    api = Api()
    win = webview.create_window("Race Engineer", UI, js_api=api, width=W_CSS, height=H_CSS,
                                x=int(rect[0] / k), y=int(rect[1] / k), frameless=True, easy_drag=False,
                                hidden=True, background_color="#05070C")
    api._win = win
    win.events.closed += api._shutdown
    webview.start(_orchestrate, (win, api, rect, k, ico), http_server=True, debug=False)


if __name__ == "__main__":
    main()
