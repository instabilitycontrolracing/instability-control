"""The team (engineer + mechanic) as a local AI model, run by llama.cpp (llama-server).

- The model only runs when the driver is NOT driving. The moment the car is on track and moving
  (or in any race session while in the car) the server is shut down and the graphics memory is freed.
- The analysis code does the maths. The model only gets FACTS (lap times, corner numbers, advice,
  setup values) and turns them into conversation, so it never has to calculate from raw telemetry.
"""
import json, os, subprocess, threading, time, urllib.request, glob

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LLM = os.path.join(ROOT, "llm")
PORT = 8765

SYSTEM = """You are the race team on the pit wall for {DRIVER}, a sim racer in iRacing. Two people talk:
ENGINEER - the race engineer and driving coach. Italian, calm, short clear sentences, warm but direct.
MECHANIC - the car's setup mechanic. Practical, explains why, suggests ONE setup change at a time.

Rules:
- Use ONLY the facts in the DATA block. Never invent lap times, speeds, distances or setup values. If something isn't in the data, say you don't have it.
- Start every paragraph with who is speaking: "ENGINEER:" or "MECHANIC:". Driving technique is the engineer; car setup is the mechanic. Use both only when both are useful.
- Be specific: corner names, metres, km/h, tenths. Lead with the biggest gain first.
- Technique before setup: if the data says a problem is technique, don't change the car for it.
- Setup changes: ONLY suggest a change that appears under MECHANIC RECOMMENDATIONS in the DATA, word for word in meaning, and only ONE. If there are none, say the car looks consistent and the time is in the driving. Never invent a setup change, a direction or a value.
- If the data says something is technique, the mechanic says so and does not change the car.
- Keep it short: what he would hear in a debrief, not an essay. No bullet lists longer than 3 items.
"""


def fmt_lap(t):
    return f"{int(t // 60)}:{t % 60:06.3f}" if t else "-"


def build_context(sess, cmp, lap_n, ref_label, section=None, mech_summary=None):
    """Compact fact sheet for the model."""
    lap = sess.lap(lap_n) if sess else None
    lines = [f"Track: {sess.track_display}. Car: {sess.car}{' (GTP hybrid)' if sess.gtp else ''}.",
             f"Lap analysed: lap {lap_n}, {fmt_lap(lap and lap['time'])}. Reference: {ref_label}. " +
             (f"Total: {cmp['total']:+.3f} s vs reference." if cmp.get("total") is not None else
              f"Total: unknown. {cmp.get('delta_note') or 'Time gap not shown.'} Do NOT quote any time gained or lost; talk only about the driving numbers.")]
    lines.append("Corners (time lost vs reference, then key numbers you/ref, then advice):")
    _s = lambda x: f"{x:+.2f} s" if x is not None else "time n/a"           # 2026-10-27 (#344): impossible deltas are None
    for c in sorted(cmp["corners"], key=lambda r: -(r["lost"] or 0)):
        m, r = c["me"], c["ref"]
        nums = (f"brake {m.get('brake_d') or '-'}/{r.get('brake_d') or '-'} m, apex {m['min_kmh']:.0f}/{r['min_kmh']:.0f} km/h, "
                f"exit {m['exit_kmh']:.0f}/{r['exit_kmh']:.0f} km/h, full throttle {m.get('full_throttle_d') or '-'}/{r.get('full_throttle_d') or '-'} m, coast {m.get('coast_m', 0):.0f}/{r.get('coast_m', 0):.0f} m")
        lines.append(f"- {c['name']}: {_s(c['lost'])}. {nums}. Advice: {' | '.join(c['tips'][:3]) or 'none'}")
    if section:
        names = " -> ".join(c["name"] for c in section.get("corners", [])) or f"{section['from']:.0f}-{section['to']:.0f} m"
        lines.append(f"SELECTED SECTION (the driver is looking at this): {names}, {_s(section.get('lost'))}.")
        for n in section.get("notes", []):
            lines.append(f"  note: {n}")
        for c in section.get("corners", []):
            for t in c.get("mech", []):
                lines.append(f"  mechanic data for {c['name']}: {t}")
    if mech_summary:
        lines.append("Mechanic's read of the car this session: " + " ".join(mech_summary))
    recs = []
    try:
        from .mechanic import corner_advice
        for c in sess.find_corners():
            for n in corner_advice(sess, c["key"]):
                if "Try:" in n or "technique" in n or "bottoming" in n or "close to the ground" in n:
                    recs.append(f"- {c['name']}: {n}")
    except Exception:
        pass
    lines.append("MECHANIC RECOMMENDATIONS (the only setup changes allowed):" + ("\n" + "\n".join(recs[:8]) if recs else " none - the car is consistent, the time is in the driving."))
    st = setup_brief(sess)
    if st:
        lines.append("Current setup: " + st)
    return "\n".join(lines)


def setup_brief(sess):
    """The setup values that matter for handling, as one line."""
    want = ("RearWingAngle", "RearWingPosition", "WingSetting", "ArbSize", "ArbBlades", "ArbSetting", "FrontArb", "RearArb",
            "BrakePressureBias", "BrakeBiasMigration", "TractionControlGain", "TractionControlSlip", "TractionControl",
            "Preload", "CoastDriveRampAngles", "ClutchFrictionPlates", "StartingPressure", "RideHeight", "SpringRate",
            "HeaveSpring", "ThirdSpring", "Camber", "AbsSetting", "DiffPreload")
    out = []

    def walk(d, path):
        for k, v in (d or {}).items():
            if isinstance(v, dict):
                walk(v, path + [k])
            elif k in want:
                where = ".".join(p for p in path[-2:] if p not in ("Chassis", "BrakesDriveUnit", "TiresAero"))
                out.append(f"{where + ' ' if where else ''}{k}={v}")
    walk(sess.setup, [])
    seen, res = set(), []
    for x in out:            # left/right duplicates read the same; keep the first
        key = x.replace("Left", "").replace("Right", "")
        if key not in seen:
            seen.add(key); res.append(x)
    return "; ".join(res[:30])


class Team:
    def __init__(self, settings, log=print, emit=None):
        self.s, self.log = settings, log
        self.emit = emit or (lambda e: None)
        self.proc = None
        self.state = "off"           # off | loading | ready | blocked | missing | error
        self.reason = ""
        self.want = False            # the driver opened the team room
        self.driving = False
        self._lock = threading.Lock()
        self._ir = None
        threading.Thread(target=self._guard, daemon=True).start()

    # ---------------- files ----------------
    def server_exe(self):
        hits = glob.glob(os.path.join(LLM, "bin", "**", "llama-server.exe"), recursive=True)
        return hits[0] if hits else None

    def model_path(self):
        ft = os.path.join(LLM, "models", "race-team-q4.gguf")      # our fine-tuned model, once trained
        if os.path.exists(ft):
            return ft
        base = glob.glob(os.path.join(LLM, "models", "*.gguf"))
        return base[0] if base else None

    # ---------------- driving guard ----------------
    def _driving_now(self):
        try:
            if self._ir is None:
                import irsdk
                self._ir = irsdk.IRSDK()
            ir = self._ir
            if not (ir.is_initialized and ir.is_connected):
                if not ir.startup():
                    return False
            ir.freeze_var_buffer_latest()
            in_car = bool(ir["IsOnTrackCar"]) or bool(ir["IsOnTrack"])
            if not in_car:
                return False
            sess = ""
            try:
                n = ir["SessionNum"]
                for x in (ir["SessionInfo"] or {}).get("Sessions", []):
                    if x.get("SessionNum") == n:
                        sess = (x.get("SessionType") or "").lower()
            except Exception:
                pass
            if "race" in sess:
                return True                      # never during a race while in the car
            in_box = bool(ir["PlayerCarInPitStall"]) and (ir["Speed"] or 0) < 0.5
            if in_box and getattr(self.s, "team_in_pitbox", False):
                return False                     # practice/quali, parked in the box, and allowed
            return True
        except Exception:
            return False

    def _guard(self):
        while True:
            d = self._driving_now()
            if d != self.driving:
                self.driving = d
                if d:
                    if self.proc:
                        self.log("[team] you're driving - the team goes to the pit wall (AI unloaded).")
                    self._stop()
                    self._set("blocked", "Not while driving")
                elif self.want:
                    self.start()
                else:
                    self._set("off", "")
            time.sleep(1.0)

    def _set(self, state, reason=""):
        self.state, self.reason = state, reason
        self.emit({"t": "team_state", "state": state, "reason": reason})

    # ---------------- server ----------------
    def start(self):
        self.want = True
        if not getattr(self.s, "team_enabled", True):
            self._set("off", "Off in settings"); return
        if self.driving:
            self._set("blocked", "Not while driving"); return
        with self._lock:
            if self.proc and self.proc.poll() is None:
                return
            exe, model = self.server_exe(), self.model_path()
            if not exe or not model:
                self._set("missing", "AI not installed"); return
            self._set("loading", "Loading")
            args = [exe, "-m", model, "--port", str(PORT), "--host", "127.0.0.1", "-c", "8192", "-ngl", "99",
                    "--no-webui", "-t", "4"]
            dev = getattr(self.s, "team_gpu", "") or self._auto_device(exe)
            if dev:
                args += ["--device", dev]
            flags = 0x08000000 if os.name == "nt" else 0          # CREATE_NO_WINDOW
            self.proc = subprocess.Popen(args, cwd=os.path.dirname(exe), stdout=subprocess.DEVNULL,
                                         stderr=open(os.path.join(LLM, "server_log.txt"), "w"), creationflags=flags | (0x4000 if os.name == "nt" else 0))
        _tie_to_this_program(self.proc)
        self.log("[team] loading the AI on the graphics card...")
        threading.Thread(target=self._wait_ready, daemon=True).start()

    def _auto_device(self, exe):
        """Pick the graphics card for the AI: on a 2-GPU PC, the one that isn't running the game."""
        try:
            out = subprocess.run([exe, "--list-devices"], capture_output=True, text=True, timeout=20,
                                 creationflags=0x08000000 if os.name == "nt" else 0).stdout + ""
            devs = [l.split(":")[0].strip() for l in out.splitlines() if l.strip().startswith("Vulkan")]
            names = {l.split(":")[0].strip(): l for l in out.splitlines() if l.strip().startswith("Vulkan")}
            for d in devs:
                if "3060" in names[d]:
                    return d
            return devs[-1] if len(devs) > 1 else (devs[0] if devs else "")
        except Exception:
            return ""

    def _wait_ready(self):
        t0 = time.time()
        while time.time() - t0 < 120:
            if not self.proc or self.proc.poll() is not None:
                self._set("error", "AI didn't start (llm/server_log.txt)"); return
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=2) as r:
                    if r.status == 200:
                        self._set("ready", ""); self.log("[team] the team is ready."); return
            except Exception:
                pass
            time.sleep(0.5)
        self._set("error", "AI start timed out")

    def _stop(self):
        with self._lock:
            if self.proc:
                try:
                    self.proc.terminate(); self.proc.wait(5)
                except Exception:
                    try:
                        self.proc.kill()
                    except Exception:
                        pass
                self.proc = None

    def stop(self):
        self.want = False
        self._stop()
        self._set("off", "")

    # ---------------- talking ----------------
    def ask(self, question, context, history, on_text, on_done):
        if self.state != "ready":
            on_done(self.reason or "Not ready"); return
        name = (getattr(self.s, "driver_name", "") or "the driver").strip()
        msgs = [{"role": "system", "content": SYSTEM.replace("{DRIVER}", name) + "\n\nDATA:\n" + context}]
        msgs += history[-8:]
        msgs.append({"role": "user", "content": question})
        body = json.dumps({"messages": msgs, "stream": True, "temperature": 0.5, "top_p": 0.9, "max_tokens": 600}).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{PORT}/v1/chat/completions", data=body,
                                     headers={"Content-Type": "application/json"})
        full = ""
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                for raw in r:
                    line = raw.decode("utf-8", "ignore").strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        delta = json.loads(data)["choices"][0]["delta"].get("content") or ""
                    except Exception:
                        continue
                    if delta:
                        full += delta
                        on_text(delta)
                    if self.driving:            # went out on track mid-answer
                        break
            on_done(None, full)
        except Exception as e:
            on_done(f"Lost the line ({e.__class__.__name__})", full)


_JOB = None


def _tie_to_this_program(proc):
    """Windows job object: if Race Engineer closes or crashes, the AI server goes with it (no orphan
    holding graphics memory)."""
    global _JOB
    if os.name != "nt" or not proc:
        return
    try:
        import ctypes
        from ctypes import wintypes
        k = ctypes.windll.kernel32
        k.CreateJobObjectW.restype = wintypes.HANDLE
        k.OpenProcess.restype = wintypes.HANDLE
        k.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        k.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        if _JOB is None:
            class BASIC(ctypes.Structure):
                _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                            ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                            ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                            ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]
            class IO(ctypes.Structure):
                _fields_ = [(n, ctypes.c_uint64) for n in ("r", "w", "o", "rb", "wb", "ob")]
            class EXT(ctypes.Structure):
                _fields_ = [("Basic", BASIC), ("Io", IO), ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                            ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]
            job = k.CreateJobObjectW(None, None)
            info = EXT()
            info.Basic.LimitFlags = 0x2000          # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            k.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))
            _JOB = job
        h = k.OpenProcess(0x0100 | 0x0001, False, proc.pid)   # SET_QUOTA | TERMINATE
        k.AssignProcessToJobObject(_JOB, h)
        k.CloseHandle(h)
    except Exception:
        pass
