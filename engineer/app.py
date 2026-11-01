"""Race Engineer window (ApexHUD style).   pythonw -m engineer.app

The window is a web page (engineer/ui) shown by pywebview / Edge WebView2.
The page calls the Api methods below through window.pywebview.api.
"""
import ctypes, os, random, re, sys, threading, time, queue
from ctypes import wintypes

from .settings import Settings
from . import buttons as B

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LOGF = os.path.join(ROOT, "engineer_log.txt")
VERSION = "0.62 beta"
# radio routing (#453, approved lines 2026-10-28)
STRAT_WAIT_S = 15          # after her "go ahead", the next thing he says (without a name) is for her
FIGHT_GAP_S = 1.0          # "what's the gap?" with a car this close ahead AND behind -> "Ahead or behind?"
# what the strategist answers herself; any other question said to her gets "That one's for the engineer." first
HER_SUBJECTS = {"fuel", "fuel_per_lap", "fuel_target", "next_stop", "strategy", "rain", "weather", "pit_out", "pit_loss",
                "tyres", "radio_check", "say_again", "meeting", "pit_plan", "spotter_off", "spotter_on", "quiet", "talk"}
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
        elif msg.startswith("YOU:"):                     # 2026-10-25 (driver request): what the driver says goes on the card too
            who, text = "DRIVER", msg.split(":", 1)[1].strip()
            if text:
                text = text[0].upper() + text[1:]
                if text[-1] not in ".?!":
                    text += "."
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
            try:                                               # 2026-10-27: Settings > Telemetry vault > PC folder
                from . import telemetry as _T
                _T.ARCHIVE_DIR_OVERRIDE = (self._s.vault_dir or "").strip()
            except Exception:
                pass
            threading.Thread(target=self._archive_loop, daemon=True).start()     # 2026-10-26/27: every recording kept (vault.py)
            threading.Thread(target=self._sound_guard_loop, daemon=True).start()  # 2026-10-26: headphones stay on Voicemeeter
            threading.Thread(target=self._launch_loop, daemon=True).start()      # 2026-10-26: start chosen programs with iRacing
            if getattr(self._s, "vibrance_keep", False):                          # #308: NVIDIA vibrance kept
                threading.Thread(target=self._vibrance_keep, args=(5,), daemon=True).start()
            threading.Thread(target=self._fx_loop, daemon=True).start()          # forensics (2026-10-27): tonight's incidents, ready for the meeting
            try:                                               # 2026-10-26: the engineer's own telemetry recorder (drives + replays)
                from .recorder import Recorder
                self._rec = Recorder(log=self._log)
            except Exception as e:
                self._log(f"[recorder] {e!r}")
            self._engine.on_tick = self._tick
            # ic172 (#685): in iRacing's menus (sim not running) keep the crowd ticking so its pit-lane loop plays
            self._engine.on_idle = lambda: (getattr(self, "_crowd", None) and self._crowd.tick(None))
            try:                                               # crowd (2026-10-24): own stream, never the radio
                from .crowd import Crowd
                self._crowd = Crowd(self._s, log=self._log, device=self._s.device or None)
            except Exception as e:
                self._crowd = None
                self._log(f"[crowd] {e!r}")
            try:                                               # broadcast radio (2026-10-29, #515): TV + stream only
                from .broadcast import Link
                from . import voice as _V, crowd as _C
                self._bcast = Link(self._s, log=self._log, on_change=lambda: self._audio_mix().write_stream())
                _V.TAPS.append(self._bcast.clip)
                _C.TAPS.append(self._bcast.crowd)
                if getattr(self, "_crowd", None) is not None:   # #604: the bed covers a late crowd on the broadcast too
                    self._bcast.watch(self._crowd.mixer)
                import atexit
                atexit.register(self._bcast.stop)
            except Exception as e:
                self._bcast = None
                self._log(f"[broadcast] {e!r}")
            try:                                               # bass shaker (2026-10-26, #211): off until a device is picked
                from .shaker import Shaker
                self._shaker = Shaker(self._s, log=self._log)
                self._pedal = Shaker(self._s, log=self._log, prefix="pedal_")   # D11 (#249): pedals / cushion
            except Exception as e:
                self._shaker = None
                self._log(f"[shaker] {e!r}")
            try:                                               # cockpit layer (2026-10-26, D1-D3): only from your recordings
                from .cockpit import Cockpit
                self._cockpit = Cockpit(self._s, lambda: getattr(getattr(getattr(self, "_crowd", None), "director", None), "clips", None),
                                        device=self._s.device or None, log=self._log)
            except Exception as e:
                self._cockpit = None
                self._log(f"[cockpit] {e!r}")
            try:                                               # flag lights (2026-10-26, #236): off until set up
                from .lights import Lights
                self._lights = Lights(self._s, log=self._log)
                from .hue_rig import HueRig                    # #239-#240: the Hue lamps + desk strip
                self._hue = HueRig(self._s, log=self._log)
                import atexit
                atexit.register(self._hue.close)
                from .radio_log import RadioLog                # W3 (#253): your engineer's radio, played back in replays
                from .voice import TAPS as _TAPS
                self._radiolog = RadioLog(self._s, log=self._log)
                _TAPS.append(self._radiolog.tap)
                from .fan import Fan                           # D12 / H4 (#250, #287): the speed fan
                self._fan = Fan(self._s, lambda: self._hue.base, log=self._log)
            except Exception as e:
                self._lights = None
                self._log(f"[lights] {e!r}")
            try:                                               # sound mix (2026-10-25): write the APO files
                self._audio_mix()
            except Exception as e:
                self._log(f"[sound] {e!r}")
            self._buttons = B.Buttons(self._on_button, log=self._log, on_devices=self._check_binds)
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

    def _check_binds(self, names):
        """#322: say in the log when a bound wheel / box isn't plugged in (so a dead radio button has a reason)."""
        for label, b in (("radio button", self._s.radio_button), ("team button", self._s.team_button)):
            if b and not B.connected(b, names):
                self._log(f"[buttons] {label} is set to {b.get('device')} (button {int(b.get('button', 0)) + 1}), "
                          f"which isn't connected right now")

    def _on_button(self, name, btn, down):
        if not self._engine:
            return
        names = list(self._buttons.names) if self._buttons else None
        if down:
            for action, binding in (self._s.binds or {}).items():
                if B.matches(binding, name, btn, names):
                    threading.Thread(target=self._bind_action, args=(action,), daemon=True).start()
                    return
        ch = ("radio" if B.matches(self._s.radio_button, name, btn, names)
              else "team" if B.matches(self._s.team_button, name, btn, names) else None)
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
        try:
            from .extras import play_radio_click
            play_radio_click(self._s, down=bool(down))
        except Exception:
            pass
        if down:
            ptt.start()
            self._q.put({"t": "ptt", "on": True, "ch": ch})
        else:
            self._q.put({"t": "ptt", "on": False, "ch": ch})
            threading.Thread(target=lambda: self._heard(ptt.stop(), ch), daemon=True).start()

    def _sim_running(self):
        """True while iRacing's sim is open (garage, menus, replays included). Cheap: checked every couple of minutes."""
        try:
            from .procs import is_running                # 2026-10-29: asks Windows directly (no tasklist process)
            return is_running("iRacingSim64DX11.exe")
        except Exception:
            return False

    def _in_car(self):
        b = self._engine.brain if self._engine else None
        return bool(b and (b.g("IsOnTrack", False) or b.g("IsOnTrackCar", False)))

    def _heard(self, text, ch):
        """What to do with something the driver said on the radio."""
        if not text:
            return
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
        from .intents import analyse
        heard = analyse(text)                       # #453: who it was for, was it a question, what it was about
        if heard["to"] is None and time.time() - getattr(self, "_strat_wait_t", 0) < STRAT_WAIT_S:
            # she said "go ahead" after her name (2026-10-28): the follow-up question is for her
            h2 = analyse("Strategist, " + text)
            h2["unclear"] = heard["unclear"]        # a remark after her name is still a note, not "say again"
            heard = h2
        self._strat_wait_t = 0
        if time.time() - getattr(self, "_rc_ack_t", 0) < 10 and len(text.split()) <= 6 and not heard["intent"]:
            return                                  # "loud and clear" to the strategist: nothing else to do
        st = getattr(self, "_strat", None)
        if st and st.rp.command(text):              # practice run plan: skip / one more lap / what's the plan
            return
        pit = getattr(self, "_pit", None)
        if pit and pit.wants(text) and pit.answer(text):
            return
        # #591: the rain brain's questions (will it rain any more / drying or wetter / when do we switch tyres) go before
        # the older weather questions, which only know this week's forecast
        if Api._rain_q(self, heard, st):           # (called on the class: the radio test doubles stay valid)
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
        intent = heard["intent"]
        if heard["to"] or heard["alt"][0]:
            self._log(f"[radio] for {heard['to'] or 'anyone'}: {intent} {heard['score']}"
                      f"{' (or ' + heard['alt'][0] + ')' if heard['alt'][0] else ''}")
        if intent == "radio_check" and heard["to"] == "strategist" and st is not None and st.b is not None:
            # "strategist, are you there?" - she answers herself (approved lines) and gives the plan, never "copy"
            self._strat_line("rc_ok", 0)
            if st.plans and st.b.is_race():
                st.say_plan(st.rec, intro="Current plan")
            else:
                st.brief()
            return
        if intent == "pit_plan" and pit:
            pit.propose(); return
        if intent == "rain" and heard["to"] == "strategist" and st is not None and st.dry_no_rain():
            self._strat_line("sa_rain_none", 0)       # "No rain expected. We stay on slicks."
            return
        if intent == "rain":
            from .rain import tips, WET_NAME
            st = getattr(self, "_strat", None)
            lvl = st.wet_lvl if st else None
            if lvl:
                self._crew_say("ENGINEER", f"Track is {WET_NAME.get(lvl, 'dry')}.")
            for tip in tips(2, seed=int(time.time()), track_key=st.track if st else None):
                self._crew_say("ENGINEER", tip)        # one line each: a track tip has its own clip
            return
        if intent == "strategy" and heard["score"] <= 8 and st is not None and st.b is not None:
            # her name on its own (2026-10-28, the owner's pick): "Strategist here, go ahead." and she waits for the
            # question (the plan is one "what's the plan?" away)
            self._strat_line("sa_go_ahead", 0)
            self._strat_wait_t = time.time()
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
            low = text.lower()
            kind = "review" if ("review" in low or "tonight" in low or "night" in low) else "debrief" if "debrief" in low else "prerace"
            self._q.put({"t": "team_meeting", "kind": kind}); return       # forensics (2026-10-27): "night review"
        if (intent in ("fuel", "fuel_per_lap", "next_stop") or (intent == "tyres" and heard["to"] == "strategist")) \
                and st is not None:
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
            if intent == "gap_ahead" and self._gap_both_ways(heard):
                eng.voice.say("ans_which_gap", prio=PRIO_URGENT)        # "Ahead or behind?"
                return
            if heard["to"] == "strategist" and st is not None and intent not in HER_SUBJECTS:
                self._strat_line("sa_handoff", 0)    # "That one's for the engineer." - then he answers
            eng.brain.answer(intent); return
        if heard["unclear"]:
            # #453: a question (or something said to the strategist / engineer by name) we didn't understand: ask him
            # again with an approved line - never "copy", and it isn't saved as a note
            if heard["to"] == "strategist" and st is not None:
                self._strat_line("sa_say_again", random.randrange(2))   # "Say again for me?" / "Sorry, say again?"
            else:
                eng.voice.say("ans_say_again", prio=PRIO_URGENT)        # "Say again?" / "Didn't get that, say again."
            return
        if self._in_car():
            self._save_note(text)
            eng.voice.say("ack", {"_variant": 1}, prio=PRIO_URGENT)
            return
        if team and team.state == "ready":
            self._q.put({"t": "goto", "tab": "team"}); self._q.put({"t": "team_heard", "text": text}); return
        eng.voice.say("ans_didnt_catch", prio=PRIO_URGENT)

    def _rain_q(self, heard, st):
        """#591: "will it rain any more?", "is it drying?", "when do we go to slicks?" -> the rain brain answers (its own
        clip once rendered, an existing clip that fits, or the answer as text). True if it answered. Without a session
        the question falls back to the old rain answer (track wetness + tips)."""
        from .intents import RAIN_INTENTS
        kind = RAIN_INTENTS.get(heard["intent"])
        cs = set(heard.get("concepts") or ())
        rb = getattr(st, "rb", None) if st is not None else None
        if kind is None and heard["intent"] == "rain" and heard["question"] and rb is not None \
                and cs & {"DRYCOMP", "WETCOMP"}:
            # "do we need wets?" / "slicks yet?" on a wet track: the crossover answers it (a dry track keeps the old answer)
            try:
                ts = rb.trend.state()
                if (ts.get("level") or 0) >= 2 or ts.get("raining"):
                    kind = "switch"
            except Exception:
                pass
        if kind is None:
            return False
        if rb is None or getattr(st, "b", None) is None:
            heard["intent"] = "rain"                 # no session yet: the old rain answer
            return False
        try:
            a = st.rain_answer(kind, cs)
        except Exception as e:
            self._log(f"[rain] answer: {e!r}")
            a = None
        if not a:
            heard["intent"] = "rain"
            return False
        if a.get("route"):                           # "should we change tyres?" on a dry track = tyre wear
            heard["intent"] = a["route"]
            return False
        how = rb.deliver(a, "ENGINEER", answer=True)
        self._log(f"[radio] rain {kind}: {a['sid']} ({how})")
        return True

    def _gap_both_ways(self, heard):
        """'What's the gap?' (no ahead / behind said) while he's fighting a car in front AND a car behind."""
        if set(heard.get("concepts") or ()) & {"AHEAD", "BEHIND", "CATCH_HIM", "CATCH_ME", "LEADER"}:
            return False
        try:
            _, ga, _, gb = self._engine.brain.neighbours()
        except Exception:
            return False
        return ga is not None and gb is not None and ga < FIGHT_GAP_S and gb < FIGHT_GAP_S

    def _strat_line(self, lid, variant):
        """One of the strategist's approved lines, a set wording (so the rendered clip is used)."""
        st = getattr(self, "_strat", None)
        try:
            from .strat_lines import LINES, _register
            t = LINES[lid][variant]
            _register(lid, variant, t, {})
            if st is not None:
                st.speak("STRATEGIST", t)
            else:
                self._crew_say("STRATEGIST", t)
        except Exception as e:
            self._log(f"[radio] strategist line: {e!r}")

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
        elif key in ("spotter_volume", "strategist_volume", "crew_volume", "race_control_volume"):   # ic165
            value = max(0.0, min(5.0, round(float(value), 2)))
        elif key == "crowd_max_db":                            # crowd (2026-10-24): never above -6 dBFS
            value = max(-48.0, min(-6.0, float(value)))
        elif key == "gaps_every":
            value = int(value)
        elif key == "vibrance_level":                          # #308: NVIDIA control panel percent
            value = max(0, min(100, int(value)))
        elif key in ("spot_call_ms", "spot_clear_ms", "spot_min_kmh"):    # spotter timing (2026-10-26)
            value = max(0, min(2000, int(value)))
        elif key == "spot_still_s":
            value = max(1.0, min(30.0, float(value)))
        elif key in ("snd_engine", "snd_detail"):              # sound mix (2026-10-25)
            value = max(0, min(100, int(value)))
            car = getattr(self, "_car_now", None)               # 2026-10-26 (#209): kept for the car you're in
            if car and getattr(self._s, "snd_per_car", True):
                prof = dict((self._s.snd_car_profiles or {}).get(car) or {"engine": self._s.snd_engine, "detail": self._s.snd_detail})
                prof["engine" if key == "snd_engine" else "detail"] = value
                self._s.snd_car_profiles = dict(self._s.snd_car_profiles or {}, **{car: prof})
        elif key in ("bcast_grit",):
            value = max(0.0, min(2.0, round(float(value), 2)))
        elif key in ("bcast_db",):
            value = max(0.0, min(12.0, round(float(value), 1)))
        elif key in ("bcast_crowd_db",):
            value = max(-24.0, min(6.0, round(float(value), 1)))
        elif key == "snd_tv_delay_ms":                         # lip-sync (#303)
            value = max(0, min(300, int(value)))
        elif key in ("snd_hp_db", "snd_tv_db"):
            value = round(float(value), 1)
        elif key == "vault_drive_quota_gb":                    # telemetry vault (2026-10-27)
            value = max(1.0, min(14.0, float(value)))
        elif key in ("vault_dir", "vault_drive_dir"):
            value = str(value or "").strip()
            if key == "vault_drive_dir" and value[:2].upper() == "H:":
                return False                                   # H: is the business Google Drive: never
        setattr(self._s, key, value)
        self._s.save()
        if key in ("spotter_volume", "race_control_volume") and self._engine is not None:   # ic165: live
            self._engine.voice.spot_volume = float(getattr(self._s, "spotter_volume", 1.0) or 0)
            self._engine.voice.rc_volume = float(getattr(self._s, "race_control_volume", 0.8) or 0)
        if key.startswith("bcast_") and getattr(self, "_bcast", None):
            self._bcast.push_settings()
        if key.startswith("vault_"):
            if key == "vault_dir":
                from . import telemetry as _T
                _T.ARCHIVE_DIR_OVERRIDE = value
            w = getattr(self, "_vault", None)
            if w:
                w.kick()
        if key == "start_with_windows":
            self._startup(bool(value))
        if key == "mic_device" and getattr(self, "_ptt", None):
            self._ptt.set_device(value or None)
        if key.startswith("snd_"):                             # sound mix (2026-10-25)
            self._audio_mix().apply(self._s, key)
        if key.startswith("shaker_") and getattr(self, "_shaker", None):
            self._shaker.apply()
        if key.startswith("pedal_") and getattr(self, "_pedal", None):
            self._pedal.apply()
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
        from .telemetry import car_name as CAR_NAME
        idx = self._idx()
        cars, tracks = {}, {}
        for v in idx.values():
            if v.get("error") or not v.get("car_path") or not v.get("track"):
                continue
            cars.setdefault(v["car_path"], v.get("car") or v["car_path"])
            t = tracks.setdefault(v["car_path"], {})
            e = t.setdefault(v["track"], {"display": v.get("track_display") or v["track"], "sessions": 0})
            e["sessions"] += 1
        # 2026-10-26 (request: "the Series tab shows Fuji and won't let me pick Le Mans"): every track on the official
        # schedules (not just the few weeks typed in by hand), and the track you're at in iRacing picked for you
        sched = {t for S in SERIES for t in S["weeks"].values()}
        try:
            from . import schedule as SC
            for S in SERIES:
                sc = SC.series(S.get("rid"), S.get("pdf"))
                for w in (sc or {}).get("weeks", []):
                    if w.get("track"):
                        sched.add(w["track"])
        except Exception as e:
            self._log(f"[prep] schedule list: {e!r}")
        pick = {"series": self._s.prep_series, "car": self._s.prep_car, "track": self._s.prep_track}
        self._track_disp = getattr(self, "_track_disp", {})
        live = None
        try:
            b = self._engine.brain if self._engine else None
            if b is not None:
                wk = b.info("WeekendInfo", {}) or {}
                d = b.drivers().get(b.me(), {}) or {}
                if wk.get("TrackName"):
                    live = {"key": wk["TrackName"], "display": wk.get("TrackDisplayName") or wk["TrackName"], "car": d.get("CarPath") or ""}
        except Exception:
            live = None
        if live:
            car = live["car"] or pick["car"] or "bmwlmdh"
            if live["car"]:
                cars.setdefault(car, CAR_NAME(car))
                pick["car"] = car
            e = tracks.setdefault(car, {}).setdefault(live["key"], {"display": live["display"], "sessions": 0})
            e["live"] = True
            pick["track"] = live["key"]
            self._track_disp[live["key"]] = live["display"]
        return {"series": series_list(), "week": week_now(), "cars": cars, "tracks": tracks, "sched_tracks": sorted(sched),
                "pick": pick, "live": live}

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
        display = rows[0][1].get("track_display") if rows else getattr(self, "_track_disp", {}).get(track_key, track_key)
        cp = car_path.lower()
        from . import cars as _cars                 # 2026-10-29 (car parity E12): known cars from the car table
        _ce = _cars.lookup(car_path)
        if _ce is not None:
            klass = _ce["cls"] or _ce["cls_text"] or ""
        else:
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
                                         "tips": [t for t in R.tips(5, seed=int(time.time() // 86400), track_key=display)
                                                  if t not in R.track_notes(display, track_key)],   # track tips: once
                                         "wet_laps": nwet, "track": R.track_notes(display, track_key),
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
            src = v.get("src")
            if src is None and s["path"].lower().endswith(".renpz"):      # not indexed yet: its marker (cheap, cached)
                try:
                    from .telemetry import recording_meta
                    src = recording_meta(s["path"])["src"]
                except Exception:
                    src = None
            if src == "replay":                                          # #344: a replay you watched, maybe not you
                label = "REPLAY  ·  " + label
            out.append({"id": s["id"], "label": label, "src": src or "ibt"})
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
            return {"sid": sid, "src": se.source, "theme": tt, "theory": theory, "notes": se.notes, "car": se.car, "track": se.track_display, "laps": se.laps, "best_n": se.best["n"],
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
    # References: your own recordings (My best here), a CSV, an .ibt file, or (2026-10-28, re-added at the owner's
    # request) a Garage 61 lap through the web API only. The Garage 61 token lives only in
    # %LOCALAPPDATA%\RaceEngineer\garage61_token.txt (see garage61.py): never in the settings JSON, never logged,
    # never sent back to the page. No Garage 61 agent, and nothing here touches .ibt files.
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

    def coach_g61_laps(self, refresh=False):
        """Fastest Garage 61 laps the token can see for the open session's car + track (cached 15 min, one click =
        a few requests at most)."""
        from . import garage61
        try:
            se = self._an["sess"]
            c = garage61.Client()
            me = garage61.cached_me(c)
            di = se.info.get("DriverInfo", {}) or {}
            drv = next((x for x in di.get("Drivers", []) or [] if x.get("CarIdx") == di.get("DriverCarIdx")), {})
            wk = se.info.get("WeekendInfo", {}) or {}
            car_id, track_id = garage61.match_ids(c, drv.get("CarID"), wk.get("TrackID"), se.car, se.track_display)
            if not car_id or not track_id:
                return {"ok": False, "error": "Couldn't match this car or track on Garage 61."}
            my_best = (se.best or {}).get("time") if getattr(se, "best", None) else None
            res = garage61.fastest_laps(c, car_id, track_id, me_id=me.get("id"), my_best=my_best, refresh=bool(refresh))
            return dict(res, ok=True, my_best=my_best)
        except garage61.G61Error as e:
            return e.as_dict()
        except Exception as e:
            self._log(f"[coach] g61 laps: {e.__class__.__name__}")
            return {"ok": False, "error": "Couldn't list Garage 61 laps."}

    def _my_best_here(self, se):
        """Your fastest clean lap with this car at this track, from your own recordings (not the open session)."""
        from . import telemetry as T
        norm = lambda x: re.sub(r"[^a-z0-9]", "", str(x or "").lower())
        car, trk = norm(se.car_path), norm(se.track_name)
        here = [x for x in T.list_sessions() if norm(x["car"]) == car and norm(x["track"]).startswith(trk)
                and os.path.abspath(x["path"]) != os.path.abspath(getattr(se, "path", "") or "")]
        best = None
        for x in here[:12]:                     # the newest dozen recordings here
            try:
                s2 = T.Session(x["path"], landmarks=se.landmarks)
            except Exception:
                continue
            if s2.best and (best is None or s2.best["time"] < best[1]):
                best = (x["path"], s2.best["time"])
        return best

    # ---------- start other programs with iRacing (2026-10-26, DRE parity) ----------
    @staticmethod
    def _running_exes():
        # 2026-10-29 (efficiency): every 4 s all race long this started a tasklist process; now one Windows call
        # (procs.py - same lower-case .exe names; falls back to tasklist if that ever fails)
        try:
            from .procs import running_exes
            return running_exes()
        except Exception:
            return set()

    def _launch_loop(self):
        """Every few seconds: when iRacing's sim starts, start each chosen program that isn't already running."""
        was = None
        while True:
            try:
                running = self._running_exes()
                sim = "iracingsim64dx11.exe" in running
                self._sim_on = sim                                   # #308: the VR colour card refuses changes while True
                if sim and was is False and getattr(self._s, "launch_with_sim_on", True):
                    self._launch_all(running)
                if sim and was is False and getattr(self._s, "vibrance_keep", False):
                    threading.Thread(target=self._vibrance_keep, args=(20,), daemon=True).start()
                # #353 race mode: close the non-essential apps for the session, reopen exactly those afterwards
                if sim and was is False and getattr(self._s, "race_mode", False):
                    threading.Thread(target=self._racemode().on_sim_start, daemon=True).start()
                if not sim and was is True and getattr(self, "_rm", None) is not None:
                    threading.Thread(target=self._rm.on_sim_stop, daemon=True).start()
                was = sim
            except Exception as e:
                self._log(f"[launch] {e!r}")
            time.sleep(4)

    def _racemode(self):
        if getattr(self, "_rm", None) is None:
            from .racemode import RaceMode
            self._rm = RaceMode(log=self._log)
        return self._rm

    # ---------- VR colour: ReShade OpenXR layer + NVIDIA vibrance (#308, 2026-10-27) ----------
    def _sim_now(self):
        v = getattr(self, "_sim_on", None)
        if v is None:
            from . import reshade as RS
            v = RS.sim_running()
        return bool(v)

    def reshade_state(self):
        from . import reshade as RS
        try:
            st = RS.status(running=self._sim_now())
        except Exception as e:
            self._log(f"[reshade] {e!r}")
            st = {"installed": False, "layer": "unknown", "error": repr(e), "site": RS.SITE, "presets": [], "sliders": []}
        st["vibrance"] = {"script": os.path.isfile(RS.VIBRANCE_SCRIPT), "keep": bool(self._s.vibrance_keep),
                          "level": int(self._s.vibrance_level), "display": self._s.vibrance_display}
        return st

    def _rs_call(self, fn, *a):
        from . import reshade as RS
        try:
            ok, msg = fn(*a, log=self._log)
        except RS.Busy as e:
            ok, msg = False, str(e)
        except Exception as e:
            self._log(f"[reshade] {e!r}")
            ok, msg = False, repr(e)
        return {"ok": bool(ok), "msg": msg, "state": self.reshade_state()}

    def reshade_layer(self, on):
        from . import reshade as RS
        return self._rs_call(RS.set_layer, bool(on), self._sim_now())

    def reshade_preset(self, name):
        from . import reshade as RS
        return self._rs_call(RS.set_preset, str(name), self._sim_now())

    def reshade_uniform(self, fx, key, value, is_int=False):
        from . import reshade as RS
        st = RS.status(running=False)
        allowed = {(u["fx"], u["name"]) for u in st.get("sliders", [])}
        if (fx, key) not in allowed:
            return {"ok": False, "msg": "not a slider of this preset", "state": self.reshade_state()}
        return self._rs_call(RS.set_uniform, st["preset_path"], fx, key, float(value), bool(is_int), self._sim_now())

    def vibrance_apply(self):
        from . import reshade as RS
        ok, msg = RS.apply_vibrance(self._s.vibrance_level, self._s.vibrance_display, self._s.vibrance_args, log=self._log)
        return {"ok": ok, "msg": msg}

    def _vibrance_keep(self, delay=0):
        """Put the vibrance back (the driver / a full-screen game can reset it): at start and when the sim starts."""
        time.sleep(delay)
        if getattr(self._s, "vibrance_keep", False):
            self.vibrance_apply()

    def _launch_all(self, running=None):
        import subprocess
        running = running if running is not None else self._running_exes()
        started = []
        for p in list(getattr(self._s, "launch_with_sim", []) or []):
            try:
                if not os.path.exists(p):
                    self._log(f"[launch] not found: {p}"); continue
                exe = os.path.basename(p).lower()
                if exe.endswith(".exe") and exe in running:
                    continue                                         # already open
                os.startfile(p)                                      # .exe / .lnk / .bat all start like a double-click
                started.append(os.path.basename(p))
            except Exception as e:
                self._log(f"[launch] {os.path.basename(p)}: {e!r}")
        if started:
            self._log(f"[launch] started with iRacing: {', '.join(started)}")
        return started

    def launch_list(self):
        return [{"path": p, "name": os.path.splitext(os.path.basename(p))[0], "ok": os.path.exists(p)} for p in (self._s.launch_with_sim or [])]

    def launch_add(self):
        try:
            import webview
            mode = getattr(getattr(webview, "FileDialog", None), "OPEN", None) or webview.OPEN_DIALOG
            r = self._win.create_file_dialog(mode, allow_multiple=False, file_types=("Programs and shortcuts (*.exe;*.lnk;*.bat;*.url)",)) if self._win else None
            p = (r[0] if isinstance(r, (list, tuple)) else r) if r else None
        except Exception as e:
            self._log(f"[launch] file dialog: {e!r}")
            p = None
        if p and p not in self._s.launch_with_sim:
            self._s.launch_with_sim = list(self._s.launch_with_sim) + [p]
            self._s.save()
        return self.launch_list()

    def launch_remove(self, i):
        lst = list(self._s.launch_with_sim or [])
        if 0 <= int(i) < len(lst):
            lst.pop(int(i)); self._s.launch_with_sim = lst; self._s.save()
        return self.launch_list()

    def launch_test(self):
        return self._launch_all()

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
        """kind = 'best' (your fastest lap here, from your own recordings), 'g61' (arg = Garage 61 lap id),
        'csv' or 'ibt' (arg = path, or None to pick a file)."""
        from . import coach, garage61
        try:
            se = self._an["sess"]
            if kind == "g61":
                ref = coach.ref_from_garage61(garage61.Client(), arg, se.track_len)
            elif kind == "best":
                b = self._my_best_here(se)
                if not b:
                    return {"ok": False, "error": "No other recording of yours with this car at this track yet."}
                ref, _ = coach.ref_from_ibt(b[0], landmarks=se.landmarks)
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
            self._team.sess_type_fn = self._sess_type_of          # 2026-10-29: no second SessionInfo parse
            self._team_hist = []
        return self._team

    def _sess_type_of(self, n):
        """The engine's session type for session number n ("" if the engine isn't on that session)."""
        b = self._engine.brain if getattr(self, "_engine", None) else None
        return (b.sess_type or "") if b is not None and b.sess_num == n else ""

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
        try:                                                   # 2026-10-26: the TV's home-theatre tuning follows replays
            now = time.time()
            if brain.g("IsOnTrack", False) and not brain.g("IsReplayPlaying", False):
                self._drive_t = now                            # 2026-10-27: the telemetry vault waits while you drive
            if now - getattr(self, "_tv_t", 0) > 1.0:
                self._tv_t = now
                try:                                           # 2026-10-26 (#209): the car sound follows the car you're in
                    self._car_sound(brain)
                except Exception as e:
                    if not getattr(self, "_cs_err", False):
                        self._cs_err = True; self._log(f"[sound] per-car: {e!r}")
                try:                                           # 2026-10-26 (#210): radio conditions (rain, far side of the lap)
                    from .voice import RadioFX
                    pct = brain.g("LapDistPct", 0) or 0
                    long_track = (brain.track_len_m() or 0) > 5500
                    RadioFX.COND = {"on": bool(getattr(self._s, "radio_realism", True)),
                                    "pitwall": bool(getattr(self._s, "radio_pitwall", True)),
                                    "pitlane": bool(brain.g("OnPitRoad", False)) and not brain.g("IsReplayPlaying", False),
                                    "rain": max(float(brain.g("Precipitation", 0) or 0), 0.0),
                                    "far": (min(pct, 1 - pct) * 2) if long_track else 0.0}
                except Exception:
                    pass
                self._audio_mix().tv_tick(self._s, brain.g("IsReplayPlaying", False))
                lt = getattr(self, "_lights", None)               # #236: the room follows the flags
                drv_ = bool(brain.g("IsOnTrack", False)) and not brain.g("IsReplayPlaying", False)
                if lt:
                    lt.update(brain.g("SessionFlags", 0), drv_)
                hr = getattr(self, "_hue", None)
                if hr:
                    hr.update(brain.g("SessionFlags", 0), drv_)
                rl_ = getattr(self, "_radiolog", None)
                if rl_:
                    try:
                        wk_ = brain.info("WeekendInfo", {}) or {}
                        rl_.update(wk_.get("SubSessionID"), brain.g("SessionNum", 0), float(brain.g("SessionTime", 0) or 0),
                                   bool(brain.g("IsReplayPlaying", False)),
                                   1 if (brain.g("ReplayPlaySpeed", 1) == 1 and not brain.g("ReplayPlaySlowMotion", False)) else 0,
                                   brain.g("CamCarIdx", -1) == brain.me(), self._s.device or None)
                    except Exception:
                        pass
                fn_ = getattr(self, "_fan", None)
                if fn_:
                    fn_.update(drv_, (brain.g("Speed", 0) or 0) * 3.6, bool(brain.g("OnPitRoad", False)))
                ck = getattr(self, "_cockpit", None)              # D1-D3: wind, rain on the roof, heartbeat
                if ck:
                    try:
                        _, ga_, _, gb_ = brain.neighbours()
                    except Exception:
                        ga_ = gb_ = None
                    lr_ = brain.g("SessionLapsRemainEx", None)
                    ck.update(drv_, (brain.g("Speed", 0) or 0) * 3.6, brain.g("Precipitation", 0) or 0,
                              max(0.0, ((brain.g("TrackWetness", 1) or 1) - 1) / 6.0), ga_, gb_,
                              lr_ if isinstance(lr_, int) and 0 <= lr_ < 32767 else None,
                              brain.is_race() if hasattr(brain, "is_race") else "race" in (brain.sess_type or "").lower(),
                              brain.g("SessionFlags", 0))
                cd = getattr(getattr(self, "_crowd", None), "director", None)     # #229: trackside camera -> the circuit's space
                if bool(getattr(cd, "trackside_cam", False)):
                    sp_ = "trackside"
                # D4 #242 (pit wall + garages echo on pit road) taken out 2026-10-26: the echo sits on everything that
                # plays on the PC, so the team radio sounded echoey in the pit lane too. Requested: "the team radio should
                # always be in my ear ... only race control should sound like that in the pit lane" -> race control gets
                # its own pit-lane echo in voice.py (RadioFX.COND["pitlane"]), the radio stays dry.
                # D5 #243 (bridge / tunnel echo on your own car) taken out 2026-10-26: the owner - the Dunlop bridge is "a very
                # very short underpass, maybe a quarter of a second"; swapping the APO file can't follow that, and its
                # 0.35 s tunnel tail sounded like a tunnel two bridges long.
                else:
                    sp_ = ""
                self._audio_mix().space(self._s, sp_)
        except Exception:
            pass
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
        if role == "ENGINEER" and self._engine is not None:
            # 2026-10-28: an approved line with an engineer clip (track wet tips) is said in his own voice (the voice
            # falls back to the stand-in until it's rendered)
            from .rain import wet_sid
            sid = wet_sid(text)
            if sid:
                from .voice import PRIO_INFO
                self._engine.voice.say(sid, prio=PRIO_INFO)
                return
        self._speaker_obj().say(role, text)

    def rc_test(self):
        """Settings > Race Control: hear the race director (green flag call)."""
        if self._engine:
            v = self._engine.voice
            v.rc_volume = float(getattr(self._s, "race_control_volume", 0.8) or 0)
            from .voice import PRIO_URGENT
            v.say("rc:green", prio=PRIO_URGENT, max_age=10)
        return True

    # sound mix (2026-10-25): Settings > Sound mix
    def _audio_mix(self):
        am = getattr(self, "_amix", None)
        if am is None:
            from .audio_tool import AudioMix
            am = self._amix = AudioMix(log=self._log)
            am.apply(self._s)                                  # the APO files (never the Voicemeeter levels at start)
        return am

    def audio_state(self):
        try:
            return self._audio_mix().state()
        except Exception as e:
            return {"voicemeeter": False, "apo": False, "apo_hooked": False, "error": str(e)[:160]}

    # crowd (2026-10-24): Settings > Race Control > Trackside crowd
    def crowd_state(self):
        cr = getattr(self, "_crowd", None)
        return cr.info() if cr else {"state": "off", "sounds": 0, "tracks": 0, "status": "", "playing": 0}

    def hue_find(self):
        from .hue_rig import find_bridge
        ip = find_bridge()
        if ip:
            self.set("lights_host", ip); self.set("lights_kind", "hue")
        return {"ok": bool(ip), "ip": ip, "msg": f"Hue bridge found at {ip}" if ip else "No Hue bridge found on the network"}

    def hue_pair(self):
        hr = getattr(self, "_hue", None)
        if not hr:
            return {"ok": False, "msg": "Hue not available"}
        r = hr.pair()
        if r.get("ok"):
            self.set("hue_user", r["user"])
        return {"ok": r.get("ok", False), "msg": r.get("msg", "")}

    def hue_lights(self):
        hr = getattr(self, "_hue", None)
        try:
            return {"ok": True, "lights": hr.list_lights() if hr else []}
        except Exception as e:
            return {"ok": False, "lights": [], "msg": str(e)[:80]}

    def hue_state(self):
        hr = getattr(self, "_hue", None)
        return {"status": hr.status if hr else "not available", "paired": bool(hr and hr.base), "flag": hr.flag if hr else ""}

    def hue_test(self):
        hr = getattr(self, "_hue", None)
        return {"ok": bool(hr and hr.test())}

    def lights_state(self):
        lt = getattr(self, "_lights", None)
        return {"status": lt.status if lt else "not available", "state": lt.state if lt else ""}

    def lights_test(self):
        lt = getattr(self, "_lights", None)
        return {"ok": bool(lt and lt.test())}

    def lights_pair(self):
        lt = getattr(self, "_lights", None)
        if not lt:
            return {"ok": False, "msg": "Lights not available"}
        r = lt.hue_pair()
        if r.get("ok"):
            self.set("hue_user", r["user"])
        return {"ok": r.get("ok", False), "msg": r.get("msg", "")}

    def shaker_state(self):
        sh = getattr(self, "_shaker", None)
        return {"status": sh.status if sh else "not available", "devices": output_devices()}

    def shaker_test(self):
        sh = getattr(self, "_shaker", None)
        return {"ok": bool(sh and sh.test()), "status": sh.status if sh else "not available"}

    def audio_mode(self, mode):
        """2026-10-26 (audio overhaul Phase B): switch Driving (VR, fastest) / Broadcast (TV). The app restarts itself so
        its own sounds (radio, crowd, cockpit) follow the new output."""
        mode = "driving" if mode == "driving" else "broadcast"
        try:
            r = self._audio_mix().set_mode(mode)
        except Exception as e:
            return {"ok": False, "msg": f"Couldn't switch: {e!r}"[:160]}
        self.set("audio_mode", mode)
        self._log(f"[sound] mode -> {mode}: {r.get('msg', '')}")
        try:
            import subprocess, threading
            lnk = os.path.join(os.path.expanduser("~"), "Desktop", "Race Engineer.lnk")
            def again():
                # 2026-10-26: "timeout" needs a console, so the old line started the new app at once - while this one
                # was still open - and the new one quit. A hidden PowerShell waits 8 s, then opens the shortcut.
                ps = f"Start-Sleep -Seconds 8; Start-Process -FilePath '{lnk}'"
                subprocess.Popen(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps],
                                 creationflags=0x08000000)
                self.close()
            threading.Timer(1.5, again).start()
        except Exception as e:
            self._log(f"[sound] restart after mode switch: {e!r}")
        return {"ok": r.get("ok", True), "msg": r.get("msg", ""), "mode": mode}

    def deck_links(self):
        """H8: the Stream Deck button addresses (Stream Deck's own "Website" action, "GET request in background")."""
        from .remote import Remote
        port, tok = self._s.remote_port, self._s.remote_token
        names = {"engineer": "Engineer on / off", "radio_check": "Radio check", "lights_test": "Lights test",
                 "mode_driving": "Sound: Driving mode (VR)", "mode_broadcast": "Sound: Broadcast mode (TV)"}
        out = [{"label": lab, "url": f"http://127.0.0.1:{port}/deck/{a}?k={tok}"} for a, (_, lab) in Remote.DECK.items()]
        out += [{"label": lab, "url": f"http://127.0.0.1:{port}/deck/{a}?k={tok}"} for a, lab in names.items()]
        return out

    def fan_state(self):
        f = getattr(self, "_fan", None)
        return {"status": f.status if f else "not available"}

    def pedal_state(self):
        sh = getattr(self, "_pedal", None)
        return {"status": sh.status if sh else "not available"}

    def pedal_test(self):
        sh = getattr(self, "_pedal", None)
        return {"ok": bool(sh and sh.test()), "status": sh.status if sh else "not available"}

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

    def name_test(self, name="", sounds_like=""):
        """#542 Settings > Driver: hear how the team will say your name."""
        if not self._engine:
            return {"ok": False, "why": "Start the engineer first"}
        ok = self._engine.voice.name_test(name or self._s.driver_name, sounds_like or getattr(self._s, "driver_name_say", ""))
        return {"ok": bool(ok), "why": "" if ok else "The stand-in voice isn't available on this PC"}

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

    def crew_test(self):
        """ic166 (Angelo: "a test button for each voice when adjusting the volume"): hear the mechanic / team voice
        (an existing mechanic line, not a new one)."""
        self._speaker_obj().say("MECHANIC", "Honestly, the car looks consistent in the data.")
        return True

    def _pit_emit(self, e):
        self._q.put(e)
        rem = getattr(self, "_remote", None)
        if rem and e.get("t") == "pit_state":
            rem.push("pit", e["s"])
        if rem and e.get("t") == "strat":
            rem.push("strat", e["s"])

    # starting points per car (the driver can change them in Settings > Sound mix; what he picks is kept per car)
    CAR_SOUND_DEFAULTS = {"bmwlmdh": {"engine": 50, "detail": 25},       # the Hybrid V8 voice (#300): firing note + body
                          "bmwm4gt3": {"engine": 20, "detail": 35}}      # the M4 GT3: straight six, more tyre / gearbox detail

    def _car_sound(self, brain):
        if not getattr(self._s, "snd_per_car", True):
            return
        car = (brain.drivers().get(brain.me(), {}) or {}).get("CarPath") or ""
        if not car or car == getattr(self, "_car_now", None):
            return
        self._car_now = car
        from .audio_tool import voice_for
        mix = self._audio_mix()
        new_voice, vobj = voice_for(car)              # car parity E4 (2026-10-29): engine-type draft voice where sourced
        voice_changed = getattr(mix, "voice", "") != new_voice
        mix.voice = new_voice
        prof = (self._s.snd_car_profiles or {}).get(car) or self.CAR_SOUND_DEFAULTS.get(car)
        if not prof:
            if voice_changed:
                mix.apply(self._s, "snd_engine")
            return
        e, d = int(prof.get("engine", 0)), int(prof.get("detail", 0))
        if (e, d) != (int(self._s.snd_engine or 0), int(self._s.snd_detail or 0)) or voice_changed:
            self._s.snd_engine, self._s.snd_detail = e, d
            self._s.save()
            mix.apply(self._s, "snd_engine")
            self._log(f"[sound] car sound for {car} ({vobj['name']} voice): engine {e}, detail {d}")

    def _sound_guard_loop(self):
        """Keeps Windows' default output on Voicemeeter Input whether or not iRacing is open (Apollo moves it to CABLE)."""
        time.sleep(5)
        while True:
            try:
                self._audio_mix().default_guard(self._s)
            except Exception:
                pass
            time.sleep(3)

    def _archive_loop(self):
        """2026-10-27: the telemetry vault (vault.py) keeps every recording - a checked copy on this PC, a packed copy
        and a summary in Google Drive - in its own background thread. If it can't start, the old plain copy runs
        (never trimming)."""
        try:
            from .vault import Worker
            self._vault = Worker(self._s, log=self._log, busy=lambda: time.time() - getattr(self, "_drive_t", 0) < 5,
                                 on_new=self._vault_new, on_kept=self._vault_kept)
            return
        except Exception as e:
            self._log(f"[vault] couldn't start: {e!r} - plain copies only")
        from .telemetry import archive_new
        time.sleep(5)
        while True:
            try:
                if archive_new(log=self._log):
                    self._an_idx = None                 # the Analysis / Series lists pick the new copies up
            except Exception as e:
                self._log(f"[archive] {e!r}")
            time.sleep(60)

    def _vault_new(self, ent, se):
        """A recording was just kept: rebuild its laps for the iPad / analysis lap memory (lap_store.py)."""
        from . import lap_store as LS
        store = getattr(getattr(self, "_remote", None), "laps", None)
        try:
            t = se.d.get("SessionTime")
            ended = (ent.get("started") or 0) + (float(t[-1] - t[0]) if t is not None and len(t) else 0)
        except Exception:
            ended = None
        for key, laps in LS.laps_from_session(se).items():
            if store is not None:
                store.merge(key, laps, ended=ended)
            else:
                LS.merge_file(key, laps, ended=ended, log=self._log)

    def _vault_kept(self, n):
        """New recordings kept: the Analysis / Series lists and the strategy database pick them up."""
        self._an_idx = None
        if getattr(self, "_bf_running", False):
            return
        self._bf_running = True
        def run():
            try:
                from .strategy import backfill
                from .telemetry import list_sessions
                backfill(list_sessions(), log=self._log, busy=self._driving_now)
            except Exception as e:
                self._log(f"[strategy] {e!r}")
            finally:
                self._bf_running = False
        threading.Thread(target=run, daemon=True).start()

    def vault_state(self):
        """Settings > Telemetry vault: the status line (last saved, waiting, Drive OK / offline)."""
        from .vault import status_line
        w = getattr(self, "_vault", None)
        st = dict(w.status) if w else ({"state": "off"} if not self._s.vault_on else {"state": "starting"})
        st["line"] = status_line(st)
        return st

    def vault_scan(self):
        w = getattr(self, "_vault", None)
        if w:
            w.kick()
        return bool(w)

    def _driving_now(self):
        """True while you're driving (live, not a replay) - the same test the telemetry vault waits on."""
        return time.time() - getattr(self, "_drive_t", 0) < 5

    def _strategy_backfill(self):
        """Store every saved telemetry file in the strategy database (only new ones; first time takes a minute)."""
        try:
            time.sleep(8)
            from .strategy import backfill
            from .telemetry import list_sessions
            n = backfill(list_sessions(), log=self._log, busy=self._driving_now)
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
        # #320 (2026-10-29): the iPad key must never change by itself (a settings file that fails to load used to
        # start a fresh key and the iPad lost its connection). The key is also kept in its own small file and
        # restored from there before a new one is ever made.
        import os
        keep = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "RaceEngineer", "remote_token.txt")
        if not self._s.remote_token:
            try:
                with open(keep, encoding="utf-8") as f:
                    old = f.read().strip()
                if old:
                    self._s.remote_token = old; self._s.save()
                    self._log("[ipad] key restored from remote_token.txt")
            except OSError:
                pass
        if not self._s.remote_token:
            import secrets
            self._s.remote_token = secrets.token_urlsafe(9); self._s.save()
        try:
            os.makedirs(os.path.dirname(keep), exist_ok=True)
            with open(keep, "w", encoding="utf-8") as f:
                f.write(self._s.remote_token)
        except OSError:
            pass
        self._remote = Remote(self, port=self._s.remote_port, token=self._s.remote_token, log=self._log)
        self._remote.start()

    # ---------------- timing screen (2026-10-25): a tab in this window, and a pop-out window for another screen ----------------
    def timing_url(self):
        rem = getattr(self, "_remote", None)
        return rem.timing_url(local=True, embed="pc") if rem else None

    def open_timing(self, view=None):
        """Its own window: drag it to the screen above the triples, then full screen (button on the page or F11).
        view="timing" / "session" gives a window with only that page, so both can be open at once on different screens."""
        rem = getattr(self, "_remote", None)
        if not rem:
            return False
        import webview
        view = view if view in ("timing", "session") else None
        wins = self.__dict__.setdefault("_tm_wins", {})
        w = wins.get(view)
        if w is not None:
            try:
                w.show(); w.restore()
                return True
            except Exception:
                wins.pop(view, None)
        app = self

        class TimingApi:
            def timing_fullscreen(_):
                try:
                    wins[view].toggle_fullscreen()
                except Exception as e:
                    app._log(f"[timing] fullscreen: {e!r}")

            def popout(_, v):
                return app.open_timing(v)

        title = {"timing": "Race Engineer - Timing", "session": "Race Engineer - Session"}.get(view, "Race Engineer - Timing & Session")
        url = rem.timing_url(local=True, **({"view": view} if view else {}))
        w = webview.create_window(title, url, js_api=TimingApi(), width=1500 if view != "session" else 1100, height=880,
                                  resizable=True, background_color="#05070C", min_size=(700, 360))
        wins[view] = w

        def _gone():
            wins.pop(view, None)
        w.events.closed += _gone
        return True

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
        if getattr(self, "_meet", None) and self._meet.get("kind") == "review":   # forensics (2026-10-27)
            from . import debrief as DB
            rv = self._meet["review"]
            return self._team_run(t, text, DB.model_context(rv, DB.answer(text, rv)))
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
                self._fx_into_debrief(pack, last)                # forensics (2026-10-27): every incident and why
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
                self._fx_into_prerace(pack, w["car"], w["track"])  # forensics (2026-10-27): where it went wrong last time
                self._prerace_setup(pack, w["car"])               # #580: the suggestion on the iPad, in words
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

    # ---------------- night review: incident forensics + team meeting (2026-10-27) ----------------
    def _fx_paths(self, hours=None, car=None, track=None):
        from .forensics import recent_sessions
        from .telemetry import list_sessions
        ss = list_sessions()
        if car and track:
            ss = [x for x in ss if x["car"] == car and x["track"].replace(" ", "").lower() == str(track).replace(" ", "").lower()] or ss
        now = time.time()
        ss = [x for x in ss if now - x.get("mtime", 0) > 60]          # iRacing may still be writing the newest one
        return recent_sessions(float(hours or getattr(self._s, "fx_hours", 18.0) or 18.0), ss)

    def _fx_run(self, paths):
        from . import forensics as F
        if not hasattr(self, "_fx_lock"):
            self._fx_lock = threading.Lock()
        with self._fx_lock:
            return F.analyse_cached(paths, log=self._log)

    def _fx_loop(self):
        """Analyse tonight's recordings in the background once they're finished (never while you drive), so the
        night review opens instantly in the morning."""
        from . import forensics as F
        time.sleep(25)
        done = None
        while True:
            try:
                # 2026-10-29: only once iRacing is closed - the analysis reads whole recordings (yaml + zip) and its
                # busy Python work chopped the engineer's own sound while sitting in the pits / garage menus
                if getattr(self._s, "fx_auto", True) and not self._in_car() and not self._sim_running():
                    paths = self._fx_paths()
                    key = F.cache_path(paths) if paths else None
                    if key and key != done:
                        res = self._fx_run(paths)
                        done = key
                        n = sum(len(x["episodes"]) for x in res.get("sessions") or [])
                        self._log(f"[forensics] {len(paths)} recording(s) analysed: {n} incident(s) explained")
                        self._q.put({"t": "fx_ready", "sessions": len(paths), "incidents": n})
            except Exception as e:
                self._log(f"[forensics] {e!r}")
            time.sleep(120)

    def fx_review(self):
        """The night review (tonight's sessions, every incident explained) as the meeting. -> {"pack", "team", "reason", "examples"}"""
        from . import debrief as DB, memory as M
        try:
            paths = self._fx_paths()
            if not paths:
                return {"error": "No recordings found in the telemetry folder."}
            res = self._fx_run(paths)
            s0 = ((res.get("sessions") or [{}])[0]).get("summary") or {}
            hist = None
            try:
                hist = M.recall(s0.get("car_path"), s0.get("track_name")) if s0.get("car_path") else None
            except Exception:
                pass
            rv = DB.night_review(res, hist)
        except Exception as e:
            self._log(f"[forensics] review: {e!r}")
            return {"error": repr(e)}
        self._meeting_setup(rv["sections"], res, paths)     # #580: the setup in words + pushed to the iPad
        self._fx = rv
        self._meet, self._team_hist = {"kind": "review", "review": rv, "title": rv["title"]}, []
        t = self._team_obj(); t.start()
        return {"pack": DB.public(rv), "team": t.state, "reason": t.reason, "examples": DB.EXAMPLES}

    def fx_ask(self, text):
        """A question about tonight answered by the forensics code (works without the AI). -> {"lines", "refs", "intent"} or {"lines": None}"""
        from . import debrief as DB
        rv = getattr(self, "_fx", None)
        if rv is None:
            r = self.fx_review()
            if r.get("error"):
                return {"lines": None, "error": r["error"]}
            rv = self._fx
        a = DB.answer(text, rv)
        return a or {"lines": None, "examples": DB.EXAMPLES}

    def fx_say(self, text):
        """Read a night-review answer out (same stand-in meeting voice as the team's answers; only when spoken answers are on)."""
        if not text or not bool(self._s.meet_voice):
            return False
        try:
            sp = self._speaker_obj(); sp.stop()
            from .meeting import Splitter
            sl = Splitter(sp.say); sl.feed(str(text)); sl.flush()
            return True
        except Exception as e:
            self._log(f"[forensics] say: {e!r}")
            return False

    def fx_review_data(self):
        """The night review for the iPad (doesn't change the Team tab)."""
        from . import debrief as DB
        rv = getattr(self, "_fx", None)
        if rv is None:
            paths = self._fx_paths()
            if not paths:
                return {"error": "No recordings found."}
            rv = DB.night_review(self._fx_run(paths))
            self._fx = rv
        return DB.public(rv)

    def fx_trace(self, sid, n):
        """One incident with its trace (speed, pedals, steering, slip around it, plus your clean laps)."""
        from . import debrief as DB
        rv = getattr(self, "_fx", None) or {}
        s, e = DB.find_episode(rv, sid, n)
        if e is None:
            return {"error": "not found"}
        return {"session": s["label"], "episode": e}

    def fx_session(self, sid):
        """Incidents of the session open in Analysis (pins on the map). -> {"incidents": [...]}"""
        try:
            path = self._an_paths[sid]
        except (AttributeError, KeyError):
            return {"incidents": []}
        try:
            from .telemetry import _sid
            paths = self._fx_paths()
            if path not in paths:
                paths = [path]
            res = self._fx_run(paths)
            fid = _sid(path)
            for x in res.get("sessions") or []:
                if x["id"] == fid or x["path"] == path:
                    keep = ("n", "kind", "title", "lap", "d", "corner", "cause_title", "why", "what", "pts", "loss")
                    return {"incidents": [{k: e.get(k) for k in keep} for e in x["episodes"]], "fx_sid": x["id"]}
        except Exception as e:
            self._log(f"[forensics] analysis pins: {e!r}")
        return {"incidents": []}

    def _fx_match(self, summary):
        """The forensics session for a stored memory summary (same car + track, recording ended near it)."""
        if not summary:
            return None, None
        paths = self._fx_paths(car=summary.get("car"), track=summary.get("track"))
        if not paths:
            return None, None
        res = self._fx_run(paths)
        best, gap = None, 1e9
        at = summary.get("at") or 0
        for x in res.get("sessions") or []:
            try:
                g = abs(os.path.getmtime(x["path"]) - at)
            except OSError:
                continue
            if g < gap:
                best, gap = x, g
        return (best, res) if best is not None and gap < 3 * 3600 else (None, res)

    def _fx_into_debrief(self, pack, summary):
        try:
            from . import debrief as DB
            x, res = self._fx_match(summary)
            if not x:
                return
            lines = []
            for e in x["episodes"]:
                lines.append(f"Lap {e['lap']}, {e['title']}" + (f" ({e['pts']}x)" if e["pts"] else "") + f": {e['cause_title']}. "
                             + " ".join(e["why"][:2]) + f" What to do: {e['what']}")
            if lines:
                pack["sections"].insert(min(3, len(pack["sections"])), {"h": "Incidents explained", "lines": lines})
            self._meeting_setup(pack["sections"], res, [x["path"]])   # #580
            pack["fx"] = {"sid": x["id"], "episodes": [{k: v for k, v in e.items() if k != "trace"} for e in x["episodes"]]}
            cur = getattr(self, "_fx", None)
            if not cur or DB.find_episode(cur, x["id"], (x["episodes"] or [{"n": 1}])[0]["n"])[0] is None:
                self._fx = DB.night_review(res)              # so the incident traces open from the debrief too
        except Exception as e:
            self._log(f"[forensics] debrief: {e!r}")

    def _meeting_setup(self, sections, res, paths):
        """#580: the team meeting gives the setup summary in words and says it is on the iPad. Text only - the
        spoken wording waits for Angelo's approval (docs/proposals/setup-ipad-lines-for-approval.md)."""
        from . import setup_sheet as SS
        try:
            changes = SS.from_meeting((res or {}).get("setup"))
            if not changes or not paths:
                return None
            newest = max(paths, key=lambda p: os.path.getmtime(p) if os.path.exists(p) else 0)
            cs, info = SS.ibt_setup(newest)
            wk = info.get("WeekendInfo") or {}
            di = info.get("DriverInfo") or {}
            me = next((d for d in di.get("Drivers") or [] if d.get("CarIdx") == di.get("DriverCarIdx")), {})
            src = {"carsetup": cs, "car_path": me.get("CarPath") or "", "track": wk.get("TrackDisplayName") or "",
                   "session": SS.session_label(info), "date": str((wk.get("WeekendOptions") or {}).get("Date") or "")}
            sug = self.setup_push(changes, src, me.get("CarScreenName") or "", "Team meeting")
            lines = SS.meeting_lines(sug)
            if lines:
                at = next((i for i, s in enumerate(sections) if s.get("h") == "Car"), None)
                sec = {"h": "Setup on your iPad", "lines": lines}
                sections.insert(at + 1 if at is not None else min(3, len(sections)), sec)
            return sug
        except Exception as e:
            self._log(f"[setup sheet] meeting: {e!r}")
            return None

    def _prerace_setup(self, pack, car):
        try:
            from . import setup_sheet as SS
            sug, _ = self._sheet_store().get()
            if sug and car and SS.norm(sug.get("car_path")) == SS.norm(car):
                lines = SS.meeting_lines(sug)
                if lines:
                    pack["sections"].insert(min(3, len(pack["sections"])), {"h": "Setup on your iPad", "lines": lines})
        except Exception as e:
            self._log(f"[setup sheet] pre-race: {e!r}")

    def _fx_into_prerace(self, pack, car, track):
        try:
            from . import debrief as DB
            rv = getattr(self, "_fx", None)
            if not rv or not rv.get("sessions"):
                paths = self._fx_paths(hours=24 * 14, car=car, track=track)
                if not paths:
                    return
                rv = DB.night_review(self._fx_run(paths[-4:]))
            s0 = rv["sessions"][0]["summary"]
            if s0.get("car_path") != car or s0.get("track_name") != track:
                return
            lines = DB.prerace_lines(rv)
            if lines:
                pack["sections"].insert(min(2, len(pack["sections"])), {"h": "Last time here", "lines": lines})
        except Exception as e:
            self._log(f"[forensics] pre-race: {e!r}")

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
        # 2026-10-29 (car parity E7): the car's own kind (GT4, TCR, Cup ...) picks its table (gtp / gt3 / other); the
        # Other button shows the kind's name, and fixes for an aid the car doesn't have (ABS / TC) are left out
        from .setup_bank import table_kind
        from . import cars as _cars
        car_k = car_kind(se) if se else "gt3"
        auto = table_kind(car_k)
        k = kind or auto
        aids = _cars.session_aids(se) if (se is not None and k == auto) else None
        out = {"kind": k, "auto": auto, "car_kind": car_k, "kind_label": _cars.KIND_LABEL.get(car_k, "Other"),
               "bank": bank_for(k, aids)}
        if se is not None:
            out.update(car=se.car, track=se.track_display, values=current_values(se) if k == auto else {},
                       detected=detected(se) if k == auto else [])
        return out

    def style_setup(self, car_path=None):
        """2026-10-28 (#491): a setup built around how you drive (style_setup.py), for the car of your newest recording."""
        from .style_setup import build
        try:
            out = build(car_path, log=self._log)
            if out.get("ok"):
                self._style_last = out                     # #514: the guided garage starts from this sheet
                if out.get("changes"):
                    self.setup_push(out["changes"], out.get("source") or {}, out.get("car") or "", "My style",
                                    notes=out.get("notes"), sessions=out.get("sessions"))      # #602: on the iPad now
            out = dict(out)
            out["source"] = {k: v for k, v in (out.get("source") or {}).items() if k != "carsetup"}
            return out
        except Exception as e:
            self._log(f"[style setup] {e!r}")
            return {"ok": False, "why": "Couldn't read your telemetry."}

    # ---- #514 (2026-10-29): guided garage - the "My style" sheet ticked off as iRacing reports each change
    def _guide_obj(self):
        g = getattr(self, "_guide", None)
        if g is None:
            from .setup_guide import Guide
            g = self._guide = Guide()
        return g

    def _guide_brain(self):
        eng = self._engine
        return eng.brain if eng else None

    def setup_guide_start(self):
        sheet = getattr(self, "_style_last", None) or self.style_setup()
        if not sheet or not sheet.get("ok") or not sheet.get("changes"):
            return {"active": False, "why": (sheet or {}).get("why") or "No changes on your style sheet."}
        self._log(f"[setup guide] started: {len(sheet['changes'])} change(s) for {sheet.get('car')}")
        return self._guide_obj().start(sheet["changes"], self._guide_brain(), sheet.get("car", ""))

    def setup_guide_status(self):
        g = getattr(self, "_guide", None)
        if g is None or not g.active:
            return {"active": False}
        try:
            return g.status(self._guide_brain())
        except Exception as e:
            self._log(f"[setup guide] {e!r}")
            return {"active": False}

    def setup_guide_tick(self, i, on=True):
        self._guide_obj().tick(int(i), bool(on))
        return self.setup_guide_status()

    def setup_guide_stop(self):
        self._guide_obj().stop()
        self._log("[setup guide] closed")
        return {"active": False}

    # ---- #602 (2026-10-30): the iPad SETUP sheet - the latest suggestion laid out like iRacing's garage menu
    def _sheet_store(self):
        st = getattr(self, "_sheet", None)
        if st is None:
            from .setup_sheet import Store
            st = self._sheet = Store()
        return st

    def setup_push(self, changes, src, car="", source="My style", notes=None, sessions=None):
        """'Push to iPad': freeze the rule-based changes against his real setup and make them the iPad's suggestion."""
        from . import setup_sheet as SS
        try:
            sug = SS.make_suggestion(changes, (src or {}).get("carsetup") or {}, (src or {}).get("car_path") or "", car,
                                     (src or {}).get("track") or "", (src or {}).get("session") or "", source,
                                     date=None, notes=notes, sessions=sessions)
            if (src or {}).get("date"):
                sug["event_date"] = src["date"]
            st = self._sheet_store()
            cur, _ = st.get()
            if SS.same(cur, sug):
                return cur                                  # the meeting opened again: same suggestion, keep its ticks
            st.push(sug)
            self._log(f"[setup sheet] pushed to the iPad: {len(sug['changes'])} change(s) for {car} ({source})")
            try:
                self._q.put({"t": "setup_pushed", "n": len(sug["changes"]), "source": source})
            except Exception:
                pass
            return sug
        except Exception as e:
            self._log(f"[setup sheet] push: {e!r}")
            return None

    def _sheet_live(self):
        """The live session's CarSetup, car and in-car brake bias (None outside a session) + whether he is on track."""
        b = self._guide_brain()
        if b is None:
            return None, None, None, False
        try:
            cs = b.info("CarSetup", {}) or {}
            d = b.drivers().get(b.me(), {}) or {}
            bias = b.g("dcBrakeBias", None)
            on = bool(b.g("IsOnTrack", False))
            return cs, d.get("CarPath"), (float(bias) if bias else None), on
        except Exception:
            return None, None, None, False

    def setup_sheet(self, sid=None):
        from . import setup_sheet as SS
        cs, car, bias, on = self._sheet_live()
        try:
            out = SS.view(self._sheet_store(), sid, cs, car, bias)
        except Exception as e:
            self._log(f"[setup sheet] {e!r}")
            out = {"has": False, "error": "Couldn't read the setup sheet.", "history": []}
        if not out.get("has") and cs:
            out = dict(SS.sheet(None, cs, car), history=out.get("history") or [])   # no suggestion yet: his live setup
        out["session_live"] = cs is not None
        out["on_track"] = on
        return out

    def setup_sheet_tick(self, sid, i, on):
        st = self._sheet_store()
        sug, _ = st.get(sid)
        if sug:
            st.tick(sug["id"], int(i), bool(on))
        return self.setup_sheet(sid)

    def review_page(self, sid=None, lap=None):
        """#582: the iPad REVIEW page (what it shows when you're not in a session): the last recordings, the chosen
        one's laps / sectors / traces, its debrief and the setup suggestion. Cached per recording (review_page.py)."""
        from . import review_page as RP
        cs, _car, _bias, on = self._sheet_live()
        return RP.view(sid, lap, store=self._sheet_store(), fx_review=getattr(self, "_fx", None),
                       can_analyse=lambda: not self._in_car() and not self._sim_running(), run_fx=self._fx_run,
                       on_track=on, session_live=cs is not None, log=self._log)

    def setup_sheet_build(self):
        """The iPad's 'Build from my laps' button: run My style now (it pushes itself)."""
        r = self.style_setup()
        out = self.setup_sheet()
        if not r.get("ok") or not r.get("changes"):
            out["why"] = r.get("why") or "No weakness repeats in your laps: no setup change suggested."
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
        try:                                                   # #239: the Hue lights go back to how they were
            hr = getattr(self, "_hue", None)
            if hr:
                hr.close()
        except Exception:
            pass
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
            for k in ("device", "mic_device", "remote_token", "radio_button", "team_button", "binds", "driver_name", "driver_name_say"):
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
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("InstabilityControl.RaceEngineer")
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


def _crash_trace():
    """#572 (2026-10-29): two crashes on 10-28 (Windows heap error 0xc0000374) left no trace. Python's own fault handler
    writes every thread's stack to %LOCALAPPDATA%\\RaceEngineer\\crash_trace.txt when the program dies that way (no
    Windows setting changed). The file is opened once and kept open (it has to be ready when the crash comes); it holds
    the last 5 starts' headers plus any trace, and is cut back when it passes 1 MB."""
    try:
        import faulthandler
        d = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "RaceEngineer")
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, "crash_trace.txt")
        if os.path.exists(p) and os.path.getsize(p) > 1_000_000:
            os.replace(p, p + ".old")
        f = open(p, "a", encoding="utf-8")
        f.write(f"\n=== started {time.strftime('%Y-%m-%d %H:%M:%S')} pid {os.getpid()} version {VERSION}\n")
        f.flush()
        faulthandler.enable(file=f, all_threads=True)
        globals()["_CRASH_FILE"] = f
    except Exception:
        pass


def main():
    import webview
    if os.environ.get("IC_CRASH_TRACE"):   # off by default: on Windows the fault handler also writes a full dump for
        _crash_trace()                     # harmless handled COM errors (0x8001010d from the window) - noise + work
    _win_setup_process()
    # 2026-10-27 (#451): the engineer's sound (radio, crowd, car sound) must never wait behind other programs while
    # iRacing + VR load the PC - run the whole app at High priority (the sim itself is protected by its anti-cheat)
    try:
        import ctypes
        k = ctypes.windll.kernel32
        k.GetCurrentProcess.restype = ctypes.c_void_p
        k.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        k.SetPriorityClass(k.GetCurrentProcess(), 0x00000080)
    except Exception:
        pass
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
