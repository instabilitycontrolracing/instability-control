"""iPad / tablet page: live telemetry, track map with every car, the radio and the pit plan.

Served by the Race Engineer on your home Wi-Fi (http://<this PC>:8770/). Open it in Safari on the iPad and
"Add to Home Screen": it then opens full screen like an app. Data and pit buttons need the key that's in
the link (so nobody else on the network can change your pit stop).
"""
import io, json, math, os, queue, socket, threading, time, urllib.parse, urllib.request
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

HERE = os.path.dirname(os.path.abspath(__file__))
UI = os.path.join(HERE, "ui")
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css",
         ".png": "image/png", ".ttf": "font/ttf", ".webmanifest": "application/manifest+json", ".json": "application/json",
         ".svg": "image/svg+xml", ".ico": "image/x-icon"}


def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


def _g(v):
    """m/s^2 -> g (3 decimals), None when missing."""
    try:
        return round(float(v) / 9.80665, 3) if v is not None else None
    except (TypeError, ValueError):
        return None


class Remote:
    def __init__(self, api, port=8770, token="", log=print):
        self.api, self.port, self.token, self.log = api, port, token, log
        self.clients = []                      # queues, one per open iPad page
        self._only = {}                        # id(queue) -> the event kinds that page asked for (None = all but timing)
        self.lock = threading.Lock()
        self.last = None
        self._t_last = 0
        self._drv_key, self._drv = None, {}
        self._map_cache = {}
        self._track = None
        self.srv = None
        from .timing import Timing
        self.timing = Timing(log=log)            # timing screen / session screen (always tracking, see timing.py)
        self.timing_last = None
        self._tm_last = 0
        from .lap_store import LapStore
        self.laps = LapStore(log=log)            # iPad lap analysis memory, kept across restarts (lap_store.py)
        self._places = {"track": None, "stops": [], "t": 0.0}   # 2026-10-25: the lap's named stops + themes, from Grandstand
        self._places_busy = False
        from .aids import Aids
        self.aids = Aids()                       # 2026-10-25: the TC / LOCK pods, like the overlay
        from .replay_dc import ReplayDC
        self.replay_dc = ReplayDC(log=self.log)  # 2026-10-28 (#490): your in-car settings during a replay of your race
        # 2026-10-25: team radio on the iPad - each clip the PC puts on air is kept briefly as a WAV and announced
        # numbers never repeat across restarts (the iPad must never get a stale clip with the same number)
        self._clips, self._clip_n = {}, int(time.time()) * 100
        try:
            from . import voice as _voice
            _voice.TAPS.append(self._on_voice)
        except Exception as e:
            log(f"[remote] radio tap: {e!r}")

    # ------------------------------------------------------------- Stream Deck (H8)
    DECK = {                                   # action -> (setting to flip, what the button says)
        "tv_mute": ("snd_tv_mute", "TV sound"), "late_night": ("snd_tv_night", "Late-night mode"),
        "crowd": ("crowd_mute", "Crowd"), "lights": ("hue_sync", "Hue sync"), "helmet": ("crowd_helmet", "Helmet"),
        "cockpit": ("cockpit_on", "Cockpit sounds"), "fan": ("fan_on", "Speed fan"), "shaker": ("shaker_on", "Bass shaker"),
        "trackside_echo": ("snd_trackside_space", "Trackside echo"), "team_radio_replay": ("radio_replay", "Team radio in replays"),
    }

    def deck(self, action):
        """GET /deck/<action>?k=<key>: flips one setting (or runs one thing) and says what it is now."""
        a = self.api
        try:
            if action in self.DECK:
                key, label = self.DECK[action]
                cur = bool(getattr(a._s, key, False))
                a.set(key, not cur)
                now = bool(getattr(a._s, key, False))
                on = (not now) if key in ("snd_tv_mute", "crowd_mute") else now      # mute switches read "off" when muted
                return {"ok": True, "action": action, "state": "ON" if on else "OFF", "label": label}
            if action in ("mode_driving", "mode_broadcast"):
                r = a.audio_mode(action[5:]); return {"ok": bool(r.get("ok")), "action": action, "msg": r.get("msg", "")}
            if action == "lights_test":
                r = a.hue_test(); return {"ok": bool(r.get("ok")), "action": action}
            if action == "radio_check":
                a.radio_check(); return {"ok": True, "action": action}
            if action == "engineer":
                a.toggle(); return {"ok": True, "action": action}
            if action == "list":
                return {"ok": True, "actions": sorted(list(self.DECK) + ["lights_test", "radio_check", "engineer", "mode_driving", "mode_broadcast"])}
        except Exception as e:
            return {"ok": False, "action": action, "error": str(e)[:120]}
        return {"ok": False, "action": action, "error": "unknown action - try /deck/list"}

    # ------------------------------------------------------------- server
    def start(self):
        remote = self
        _make_icons()

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _ok(self, q):
                return (q.get("k") or [""])[0] == remote.token

            def do_GET(self):
                u = urllib.parse.urlparse(self.path)
                q = urllib.parse.parse_qs(u.query)
                if u.path == "/timing":
                    self.send_response(302); self.send_header("Location", "/timing/" + (("?" + u.query) if u.query else "")); self.end_headers(); return
                if u.path in ("/", "/ipad"):
                    self.send_response(302); self.send_header("Location", "/ipad/" + (("?" + u.query) if u.query else "")); self.end_headers(); return
                if u.path == "/events":
                    if not self._ok(q):
                        return self._send(403, b"no key", "text/plain")
                    only = set(((q.get("only") or [""])[0]).split(",")) - {""}
                    return remote._sse(self, only or None)
                if u.path == "/place.png":                       # 2026-10-25: the stop's themed label, drawn by Grandstand
                    if not self._ok(q):
                        return self._send(403, b"no key", "text/plain")
                    try:
                        qs = urllib.parse.urlencode({"name": (q.get("name") or [""])[0], "eye": (q.get("eye") or ["INTO"])[0]})
                        with urllib.request.urlopen(f"http://127.0.0.1:8790/api/placelabel?{qs}", timeout=1.5) as rsp:
                            return self._send(200, rsp.read(), "image/png", cache="max-age=600")
                    except Exception:
                        return self._send(404, b"", "text/plain")
                if u.path == "/themebg/playstation.png":           # 2026-10-25: the user's PlayStation star picture for the iPad backdrop
                    if not self._ok(q):
                        return self._send(403, b"no key", "text/plain")
                    f = os.path.join(os.path.expanduser("~"), "Documents", "iRacing", "Grandstand", "corner_logos", "playstation bg.png")
                    if not os.path.isfile(f):
                        return self._send(404, b"", "text/plain")
                    return self._send(200, open(f, "rb").read(), "image/png", cache="max-age=86400")
                if u.path.startswith("/voice/"):                  # 2026-10-25: a team-radio clip for the iPad
                    if not self._ok(q):
                        return self._send(403, b"no key", "text/plain")
                    try:
                        n = int(u.path[len("/voice/"):].split(".")[0])
                    except ValueError:
                        n = -1
                    data = remote._clips.get(n)
                    if data is None:
                        return self._send(404, b"", "text/plain")
                    return self._send(200, data, "audio/wav", cache="no-store")
                if u.path.startswith("/deck/"):                   # 2026-10-26 (H8): Stream Deck buttons
                    if not self._ok(q):
                        return self._send(403, b"no key", "text/plain")
                    return self._json(remote.deck(u.path[len("/deck/"):].strip("/")))
                if u.path in ("/api/review", "/api/fxtrace"):      # forensics (2026-10-27): the night review on the iPad
                    if not self._ok(q):
                        return self._send(403, b"no key", "text/plain")
                    try:
                        if u.path == "/api/review":
                            return self._json(remote.api.fx_review_data())
                        return self._json(remote.api.fx_trace((q.get("sid") or [""])[0], int((q.get("n") or ["0"])[0])))
                    except Exception as e:
                        return self._json({"error": repr(e)})
                if u.path == "/api/state":
                    if not self._ok(q):
                        return self._send(403, b"no key", "text/plain")
                    return self._json(remote.snapshot_full())
                if u.path == "/api/setupguide":                   # #514: the guided garage checklist
                    if not self._ok(q):
                        return self._send(403, b"no key", "text/plain")
                    return self._json(remote.api.setup_guide_status())
                if u.path == "/api/setupsheet":                   # #602: the SETUP sheet (garage layout + suggestion)
                    if not self._ok(q):
                        return self._send(403, b"no key", "text/plain")
                    return self._json(remote.api.setup_sheet((q.get("id") or [None])[0]))
                path = urllib.parse.unquote(u.path)
                if path.startswith("/ipad/"):
                    rel = path[len("/ipad/"):] or "index.html"
                    f = os.path.normpath(os.path.join(UI, "ipad", rel))
                    base = os.path.join(UI, "ipad")
                elif path.startswith("/timing/"):
                    rel = path[len("/timing/"):] or "index.html"
                    f = os.path.normpath(os.path.join(UI, "timing", rel))
                    base = os.path.join(UI, "timing")
                elif path.startswith("/assets/"):
                    f = os.path.normpath(os.path.join(UI, path.lstrip("/")))
                    base = os.path.join(UI, "assets")
                else:
                    return self._send(404, b"", "text/plain")
                if not f.startswith(base) or not os.path.isfile(f):
                    return self._send(404, b"", "text/plain")
                data = open(f, "rb").read()
                self._send(200, data, TYPES.get(os.path.splitext(f)[1].lower(), "application/octet-stream"),
                           cache="no-cache" if f.endswith((".html", ".js")) else "max-age=86400")

            def do_POST(self):
                u = urllib.parse.urlparse(self.path)
                q = urllib.parse.parse_qs(u.query)
                if not self._ok(q):
                    return self._send(403, b"no key", "text/plain")
                n = int(self.headers.get("Content-Length") or 0)
                try:
                    body = json.loads(self.rfile.read(n) or b"{}")
                except ValueError:
                    body = {}
                a = remote.api
                out = {"ok": False}
                if u.path == "/api/pit":
                    act = body.get("action")
                    if act == "propose":
                        out["ok"] = a.pit_propose()
                    elif act == "apply":
                        out["ok"] = a.pit_apply(body.get("plan") or {})
                    elif act == "clear":
                        out["ok"] = a.pit_clear()
                    out["state"] = a.pit_state()
                elif u.path == "/api/setupguide":                 # #514: start / tick / stop the guided garage
                    act = body.get("action")
                    if act == "start":
                        out = a.setup_guide_start()
                    elif act == "tick":
                        out = a.setup_guide_tick(body.get("i", -1), body.get("on", True))
                    elif act == "stop":
                        out = a.setup_guide_stop()
                    else:
                        out = a.setup_guide_status()
                elif u.path == "/api/setupsheet":                 # #602: tick a change / build from my laps
                    act = body.get("action")
                    if act == "tick":
                        out = a.setup_sheet_tick(body.get("id"), body.get("i", -1), body.get("on", True))
                    elif act == "build":
                        out = a.setup_sheet_build()
                    else:
                        out = a.setup_sheet(body.get("id"))
                elif u.path == "/api/ask":
                    t = (body.get("text") or "").strip()
                    if t:
                        threading.Thread(target=a._heard, args=(t, "radio"), daemon=True).start()
                        out["ok"] = True
                self._json(out)

            def _json(self, obj):
                self._send(200, json.dumps(obj, default=_num).encode(), "application/json")

            def _send(self, code, data, ctype, cache="no-cache"):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", cache)
                self.end_headers()
                try:
                    self.wfile.write(data)
                except OSError:
                    pass

        try:
            self.srv = ThreadingHTTPServer(("0.0.0.0", self.port), H)
        except OSError as e:
            self.log(f"[ipad] port {self.port} busy: {e}")
            return
        self.srv.daemon_threads = True
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.log(f"[ipad] open on your iPad: {self.url()}")

    def url(self):
        return f"http://{lan_ip()}:{self.port}/ipad/?k={self.token}"

    def timing_url(self, local=True, **extra):
        host = "127.0.0.1" if local else lan_ip()
        q = "&".join(f"{k}={v}" for k, v in extra.items())
        return f"http://{host}:{self.port}/timing/?k={self.token}" + (("&" + q) if q else "")

    def qr_data_uri(self):
        try:
            import qrcode, base64
            img = qrcode.make(self.url(), border=2, box_size=8)
            b = io.BytesIO(); img.save(b, format="PNG")
            return "data:image/png;base64," + base64.b64encode(b.getvalue()).decode()
        except Exception:
            return None

    # ------------------------------------------------------------- live stream
    def _sse(self, h, only=None):
        # the iPad dashboard doesn't want the timing table (60 cars twice a second); the timing page wants only that
        want = (lambda k: k in only) if only else (lambda k: k != "timing")
        h.send_response(200)
        h.send_header("Content-Type", "text/event-stream")
        h.send_header("Cache-Control", "no-cache")
        h.send_header("Connection", "keep-alive")
        h.end_headers()
        q = queue.Queue(maxsize=200)
        with self.lock:
            self.clients.append(q)
            self._only[id(q)] = only
        try:
            # retry: the browser's own reconnect delay; then everything that changes rarely
            h.wfile.write(b"retry: 2000\n\n")
            if not only or "full" in only:
                self._write(h, "full", self.snapshot_full())
            if not only or "laps" in only:
                try:
                    self._write(h, "laps", self.laps.payload())    # every recorded lap, so a reloaded page starts complete
                except Exception as e:
                    self.log(f"[laps] send: {e!r}")
            if only and "timing" in only and self.timing_last is not None:
                self._write(h, "timing", self.timing_last)
            while True:
                try:
                    items = [q.get(timeout=5)]
                except queue.Empty:
                    # a real (named) event, so the page can tell a quiet stream from a dead one; old pages ignore it
                    h.wfile.write(b"event: hb\ndata: {}\n\n"); h.wfile.flush(); continue
                while True:                      # drain the backlog: a slow iPad gets the NEWEST telemetry, not a 20 s old queue
                    try:
                        items.append(q.get_nowait())
                    except queue.Empty:
                        break
                items = [it for it in items if want(it[0])]
                if not items:
                    continue
                # only the newest telemetry / timing frame of a backlog is worth sending
                last = {k: max((i for i, it in enumerate(items) if it[0] == k), default=-1) for k in ("t", "timing")}
                out = b"".join(blob for i, (kind, blob) in enumerate(items) if kind not in last or i == last[kind])
                h.wfile.write(out); h.wfile.flush()
        except (OSError, ValueError):
            pass
        finally:
            with self.lock:
                if q in self.clients:
                    self.clients.remove(q)
                self._only.pop(id(q), None)

    @staticmethod
    def _enc(kind, data):
        return f"event: {kind}\ndata: {json.dumps(data, default=_num, separators=(',', ':'))}\n\n".encode()

    def _write(self, h, kind, data):
        h.wfile.write(self._enc(kind, data))
        h.wfile.flush()

    def push(self, kind, data):
        with self.lock:
            cl = list(self.clients)
        if not cl:
            return
        blob = self._enc(kind, data)            # serialise once, not once per iPad
        for q in cl:
            try:
                q.put_nowait((kind, blob))
            except queue.Full:
                pass

    def _on_voice(self, audio, sr, kind="team"):
        """A clip just went on air on the PC: keep it as a 16-bit WAV (last 16) and tell the open iPads."""
        if not self.clients or audio is None or not len(audio):
            return
        import io, wave
        import numpy as np
        x = np.asarray(audio, dtype=np.float32).reshape(-1)
        if sr < 44100:            # 2026-10-25: iPad Safari drops low-rate WAVs (the driver's mic is 16 kHz) - send 48 kHz
            n_out = int(round(len(x) * 48000 / float(sr)))
            x = np.interp(np.linspace(0, len(x) - 1, n_out), np.arange(len(x)), x).astype(np.float32)
            sr = 48000
        audio = x
        pcm = (np.clip(x, -1.0, 1.0) * 32767).astype("<i2").tobytes()
        b = io.BytesIO()
        with wave.open(b, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(int(sr)); w.writeframes(pcm)
        with self.lock:
            self._clip_n += 1
            n = self._clip_n
            self._clips[n] = b.getvalue()
            for k in [k for k in self._clips if k <= n - 16]:
                del self._clips[k]
        self.push("voice", {"id": n, "dur": round(len(audio) / float(sr), 2), "kind": kind})
        if kind == "you":
            self.log(f"[remote] driver radio -> iPad: clip {n}, {len(audio) / float(sr):.1f} s, {len(self.clients)} page(s)")

    def push_log(self, kind, text):
        if self.clients:
            self.push("log", {"kind": kind, "text": text, "t": time.strftime("%H:%M")})

    # called by the engine about 15 times a second
    def feed(self, brain, pit):
        now = time.time()
        if brain is None:
            if self.last is not None:
                self.last = None
                self.push("off", {})
            return
        self.timing.tick(brain)
        self.laps.tick(brain)
        np_ = len(getattr(self.laps, "parts", None) or [])
        if np_ != getattr(self, "_parts_n", np_) or (np_ and (self.laps.parts[0].get("no") != getattr(self, "_parts_top", None))):
            try:                 # 2026-10-28 (#321): a partial lap's sectors were just kept - the iPad list gets them now
                self.push("parts", {"key": self.laps.key, "parts": self.laps.payload()["parts"]})
            except Exception as e:
                self.log(f"[laps] parts: {e!r}")
        self._parts_n = np_
        self._parts_top = self.laps.parts[0].get("no") if np_ else None
        # Efficiency (2026-10-29): the timing table (60 cars, ~4 ms) and the telemetry frame are only built while an open
        # page actually takes them - the iPad dashboard never takes "timing", the timing page never takes "t"
        if self.clients and now - self._tm_last >= 0.5 and self._wanted("timing"):
            self._tm_last = now
            try:
                self.timing_last = self.timing.build(brain)
                self.push("timing", self.timing_last)
            except Exception as e:
                self.log(f"[timing] build: {e!r}")
        if not self.clients or now - self._t_last < 0.1:
            return
        self._t_last = now
        if self._wanted("t"):
            try:
                snap = self.snapshot(brain, pit)
            except Exception as e:
                snap = {"err": repr(e)}
            self.last = snap
            self.push("t", snap)
        elif self.last is None:
            self.last = {}                      # "a session was live" - so "off" still goes out when iRacing closes
        tn = (brain.info("WeekendInfo", {}) or {}).get("TrackName")
        if tn != self._track:
            self._track = tn
            self.push("full", self.snapshot_full())

    def _wanted(self, kind):
        """Does any open page take this kind of event? (a page that isn't listed - e.g. a test's queue - takes all)"""
        with self.lock:
            cl = list(self.clients)
            only = dict(getattr(self, "_only", {}) or {})
        for q in cl:
            o = only.get(id(q))
            if (kind != "timing") if not o else (kind in o):
                return True
        return False

    def _drivers(self, b):
        key = b.g("SessionInfoUpdate", 0)
        if key != self._drv_key:
            self._drv_key = key
            self._drv = b.drivers()
        return self._drv

    def snapshot(self, b, pit):
        g = b.g
        met = b.metric()
        drv = self._drivers(b)
        me = b.me()
        ahead, ga, behind, gb = b.neighbours()
        cid, cname = b.my_class()
        pct = g("CarIdxLapDistPct") or []
        onp = g("CarIdxOnPitRoad") or []
        cpos = g("CarIdxClassPosition") or []
        cars = []
        for i, d in drv.items():
            if i < len(pct) and pct[i] is not None and pct[i] >= 0:
                cars.append([i, round(pct[i], 4), d.get("CarClassColor") or 0, int(cpos[i]) if i < len(cpos) else 0,
                             1 if (i < len(onp) and onp[i]) else 0, d.get("CarNumber", "")])
        fl = pit.fuel_per_lap() if pit else None
        fuel = g("FuelLevel")
        dlt = g("LapDeltaToBestLap") if g("LapDeltaToBestLap_OK", False) else None
        # 2026-10-25 (request: "the delta between the laps doesn't work"): iRacing's delta isn't there in replays (and
        # sometimes not live) - then our own, from the recorded laps; in replays the lap / distance / lap clock come from
        # the lap recorder (the player fields don't move in a replay)
        lv = getattr(self.laps, "live", None) or {}
        if dlt is None:
            try:
                dlt = self.laps.delta()
            except Exception:
                dlt = None
        r = _r
        out = {
            "on": bool(g("IsOnTrack", False)) or bool(lv.get("replay")), "pit": bool(g("OnPitRoad", False)), "met": met,
            "spd": round((g("Speed", 0) or 0) * (3.6 if met else 2.23694)), "gear": g("Gear", 0), "rpm": round(g("RPM", 0) or 0),
            "thr": round(g("Throttle", 0) or 0, 3), "brk": round(g("Brake", 0) or 0, 3),
            # 2026-10-28 (#484): lateral / longitudinal g for the iPad's background (None when iRacing doesn't send them)
            "glat": _g(g("LatAccel")), "glon": _g(g("LongAccel")), "steer": round(g("SteeringWheelAngle", 0) or 0, 3),
            "lap": (g("LapCompleted", 0) or 0) + 1, "cur": r(g("LapCurrentLapTime"), 3), "last": r(g("LapLastLapTime"), 3),
            "best": r(g("LapBestLapTime"), 3), "delta": round(dlt, 3) if dlt is not None else None,
            "pct": round(g("LapDistPct", 0) or 0, 4), "me": me, "my_class": cid,
            "pos": int(cpos[me]) if me < len(cpos) else 0, "n_class": len(b.class_cars(cid)), "class": cname,
            "ga": r(ga, 2), "gb": r(gb, 2), "ahead": b.car_num(ahead) if ahead is not None else None, "behind": b.car_num(behind) if behind is not None else None,
            "fuel": r(fuel, 3), "fuel_lap": r(fl, 4), "fuel_laps": r((fuel / fl) if (fuel and fl) else None, 2), "ltg": b.laps_to_go(),
            "left": r(g("SessionTimeRemain"), 1), "flags": g("SessionFlags", 0), "inc": g("PlayerCarMyIncidentCount"), "inc_lim": b.incident_limit(),
            "bb": r(g("dcBrakeBias"), 2), "farb": r(g("dcAntiRollFront"), 2), "rarb": r(g("dcAntiRollRear"), 2), "tc": r(g("dcTractionControl"), 2),
            "tc2": r(g("dcTractionControl2"), 2), "abs": r(g("dcABS"), 2), "mig": r(g("dcBrakeMisc"), 2),
            "tt": r(g("TrackTempCrew"), 1), "air": r(g("AirTemp"), 1), "wet": g("TrackWetness"), "cars": cars,
        }
        # 2026-10-26 (request: "the iPad app needs to know when the formation lap is, so it isn't counting it as a lap"):
        # a race before the green flag (grid, warm-up, formation / parade lap) - shown as FORMATION, never recorded as a lap
        try:
            ss = int(g("SessionState", 0) or 0)
        except (TypeError, ValueError):
            ss = 0
        out["ss"] = ss
        out["form"] = "race" in str(getattr(b, "sess_type", "") or "").lower() and 0 < ss < 4
        rdc = None
        if lv.get("replay"):
            if lv.get("lap") is not None: out["lap"] = lv["lap"]
            if lv.get("pct") is not None: out["pct"] = round(lv["pct"], 4)
            if lv.get("cur") is not None: out["cur"] = r(lv["cur"], 3)
            # 2026-10-28 (#490): a replay reads the in-car settings as 0 - play them back from your recording of that race
            # (replay_dc), else leave them out (the iPad shows '-', never a made-up 0)
            try:
                rdc = self.replay_dc.values(b, g)
            except Exception:
                rdc = None
            for k, n in (("bb", "dcBrakeBias"), ("farb", "dcAntiRollFront"), ("rarb", "dcAntiRollRear"), ("tc", "dcTractionControl"),
                         ("tc2", "dcTractionControl2"), ("abs", "dcABS"), ("mig", "dcBrakeMisc")):
                out[k] = r(rdc.get(n), 2) if rdc else None
            out["dc_src"] = "recording" if rdc else None
        # 2026-10-26 (#197, request: "take the format of how things show on the steering wheel display and mirror it"): the
        # extra values the wheel's screen shows (BMW M4 GT3 Evo / M Hybrid V8). Anything iRacing doesn't send stays out (the
        # iPad shows a dash there - never a made-up number)
        def tp(k):
            v = g(k + "pressure")
            if v is None: v = g(k + "airPressure")
            return r(v, 1)
        wh = {"tp": [tp("LF"), tp("RF"), tp("LR"), tp("RR")], "tmot": r(g("WaterTemp"), 1), "toil": r(g("OilTemp"), 1),
              "poil": r(g("OilPress"), 1), "soc": r(g("EnergyERSBatteryPct"), 4), "map": r((rdc or {}).get("dcThrottleShape") if lv.get("replay") else g("dcThrottleShape"), 2),
              "tyre": g("PlayerTireCompound"), "st": r(g("SessionTime"), 1),
              "lim": bool((g("EngineWarnings", 0) or 0) & 0x10)}
        try:
            wh["kgl"] = (b.info("DriverInfo", {}) or {}).get("DriverCarFuelKgPerLtr")
        except Exception:
            wh["kgl"] = None
        out["wh"] = wh
        out["place"] = self.place_at(out.get("pct"))
        out["bg"] = self._places.get("bg") or ""         # 2026-10-25: the track logo's background colour (page background)
        try:
            out["aid"] = self.aids.tick(g)
        except Exception:
            out["aid"] = None
        return out

    def place_at(self, pct):
        """2026-10-25 (request: the iPad map should "reflect the themes and stuff for the corners and straights"): where
        the car is - INTO / THROUGH / DOWN + the stop's name and theme (Grandstand's corner themes, fetched from it)."""
        P = self._places
        if (time.time() - P["t"] > 20 or not P["stops"]) and not self._places_busy:
            self._places_busy = True
            threading.Thread(target=_places_fetch, args=(self,), daemon=True).start()
        if pct is None or not P["stops"]:
            return None
        def inside(st):
            a, e = st["s0"], st["s1"]
            return a <= pct < e if a <= e else (pct >= a or pct < e)
        for st in P["stops"]:
            if inside(st):
                return {"eye": "DOWN" if st.get("straight") else "THROUGH", "name": st["name"], "kind": st.get("kind") or "",
                        "c1": st.get("eye") or "", "c2": st.get("rule") or "", "her": st.get("heritage") or ""}
        # between stops: the next one coming up
        nxt = min(P["stops"], key=lambda st: (st["s0"] - pct) % 1.0)
        return {"eye": "INTO", "name": nxt["name"], "kind": nxt.get("kind") or "", "c1": nxt.get("eye") or "",
                "c2": nxt.get("rule") or "", "her": nxt.get("heritage") or ""}

    def stops_payload(self):
        """The lap's named corners and straights (from Grandstand) for the iPad lap analysis: name, start, end (lap %)."""
        return [{"name": s.get("name"), "s0": s.get("s0"), "s1": s.get("s1"), "straight": bool(s.get("straight"))}
                for s in (self._places.get("stops") or []) if s.get("name") is not None and s.get("s0") is not None]

    def snapshot_full(self):
        """Everything that changes rarely: session, track, map, pit state."""
        eng = getattr(self.api, "_engine", None)
        b = eng.brain if eng else None
        pit = getattr(self.api, "_pit", None)
        out = {"live": b is not None, "pit": pit.state() if pit else {"live": False}, "stops": self.stops_payload()}
        try:
            out["strat"] = self.api.strat_state()
        except Exception:
            pass
        if b is None:
            return out
        wk = b.info("WeekendInfo", {}) or {}
        d = b.drivers().get(b.me(), {})
        di = b.info("DriverInfo", {}) or {}
        out.update({"track": wk.get("TrackDisplayName", ""), "track_id": wk.get("TrackName", ""), "car": d.get("CarScreenName", ""), "car_path": d.get("CarPath", ""),
                    "session": b.sess_type, "redline": di.get("DriverCarRedLine"), "shift": di.get("DriverCarSLShiftRPM"),
                    "map": self.track_map(wk.get("TrackName", ""), wk.get("TrackDisplayName", "")),
                    "theme": _theme(wk.get("TrackDisplayName", ""), wk.get("TrackName", ""))})
        return out

    def track_map(self, track, display):
        if track in self._map_cache:
            return self._map_cache[track]
        from .telemetry import CACHE_DIR
        p = os.path.join(CACHE_DIR, "maps", f"{track}.json".replace(" ", "_"))
        m = None
        try:
            m = json.load(open(p, encoding="utf-8"))
        except (OSError, ValueError):
            try:
                idx = getattr(self.api, "_idx", lambda: {})()
                # 2026-10-27 (#344): never from a replay recording (no GPS there: its outline IS this cached map)
                v = next((v for v in idx.values() if v.get("track") == track and v.get("best") and not v.get("error")
                          and v.get("src") != "replay"), None)
                if v:
                    from .telemetry import Session
                    s = Session(v["path"])
                    m = s.track_map(points=700)
                    m["len"] = s.track_len
                    if m.get("frame") == "gps":             # a placeholder loop must never become the cached map
                        os.makedirs(os.path.dirname(p), exist_ok=True)
                        json.dump(m, open(p, "w", encoding="utf-8"))
            except Exception as e:
                self.log(f"[ipad] map: {e!r}")
        m = _compact_map(m)
        self._map_cache[track] = m
        return m


def _places_fetch(remote):
    try:
        with urllib.request.urlopen("http://127.0.0.1:8790/api/places", timeout=1.5) as rsp:
            d = json.loads(rsp.read().decode("utf-8"))
        old = [(s.get("name"), s.get("s0"), s.get("s1")) for s in (remote._places.get("stops") or [])]
        remote._places = {"track": d.get("track"), "stops": d.get("stops") or [], "t": time.time(), "bg": d.get("bg") or ""}
        if [(s.get("name"), s.get("s0"), s.get("s1")) for s in remote._places["stops"]] != old:
            remote.push("stops", {"stops": remote.stops_payload()})       # 2026-10-26: the iPad lap analysis names corners
    except Exception:
        remote._places["t"] = time.time()
    finally:
        remote._places_busy = False


def _r(x, n):
    """Round a float for the wire (keeps None / ints / non-numbers as they are). Fewer digits = smaller messages."""
    if isinstance(x, float):
        return round(x, n) if math.isfinite(x) else None
    try:
        import numpy as np
        if isinstance(x, np.floating):
            v = float(x)
            return round(v, n) if math.isfinite(v) else None
    except Exception:
        pass
    return x


def _compact_map(m):
    """The track map goes to the iPad on every (re)connect: decimetre precision is plenty and halves its size."""
    if not isinstance(m, dict):
        return m
    out = dict(m)
    for k in ("x", "y", "d"):
        v = m.get(k)
        if isinstance(v, (list, tuple)):
            try:
                out[k] = [round(float(a), 1) for a in v]
            except (TypeError, ValueError):
                pass
    if isinstance(out.get("len"), float):
        out["len"] = round(out["len"], 1)
    return out


def _theme(display, raw):
    try:
        from .track_theme import theme
        return theme(display, raw)
    except Exception:
        return None


def _num(o):
    try:
        import numpy as np
        if isinstance(o, np.generic):
            return o.item()
    except Exception:
        pass
    return str(o)


def _make_icons():
    """Home-screen icon for the iPad: the watch on the navy glass."""
    out = os.path.join(UI, "ipad", "icon-180.png")
    if os.path.exists(out):
        return
    try:
        from PIL import Image, ImageDraw
        from .watch_skia import render_icon_png
        tmp = os.path.join(UI, "ipad", "_watch.png")
        render_icon_png(tmp, 400)
        for size, name in ((180, "icon-180.png"), (512, "icon-512.png")):
            bg = Image.new("RGBA", (size, size))
            d = ImageDraw.Draw(bg)
            for y in range(size):
                t = y / size
                d.line([(0, y), (size, y)], fill=(int(19 - 12 * t), int(30 - 18 * t), int(56 - 30 * t), 255))
            w = Image.open(tmp).resize((int(size * .8), int(size * .8)), Image.LANCZOS)
            bg.alpha_composite(w, ((size - w.width) // 2, (size - w.height) // 2))
            bg.convert("RGB").save(os.path.join(UI, "ipad", name))
        os.remove(tmp)
    except Exception as e:
        print("ipad icon:", e)
