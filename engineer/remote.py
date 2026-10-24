"""iPad / tablet page: live telemetry, track map with every car, the radio and the pit plan.

Served by the Race Engineer on your home Wi-Fi (http://<this PC>:8770/). Open it in Safari on the iPad and
"Add to Home Screen": it then opens full screen like an app. Data and pit buttons need the key that's in
the link (so nobody else on the network can change your pit stop).
"""
import io, json, math, os, queue, socket, threading, time, urllib.parse
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


class Remote:
    def __init__(self, api, port=8770, token="", log=print):
        self.api, self.port, self.token, self.log = api, port, token, log
        self.clients = []                      # queues, one per open iPad page
        self.lock = threading.Lock()
        self.last = None
        self._t_last = 0
        self._drv_key, self._drv = None, {}
        self._map_cache = {}
        self._track = None
        self.srv = None

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
                if u.path in ("/", "/ipad"):
                    self.send_response(302); self.send_header("Location", "/ipad/" + (("?" + u.query) if u.query else "")); self.end_headers(); return
                if u.path == "/events":
                    if not self._ok(q):
                        return self._send(403, b"no key", "text/plain")
                    return remote._sse(self)
                if u.path == "/api/state":
                    if not self._ok(q):
                        return self._send(403, b"no key", "text/plain")
                    return self._json(remote.snapshot_full())
                path = urllib.parse.unquote(u.path)
                if path.startswith("/ipad/"):
                    rel = path[len("/ipad/"):] or "index.html"
                    f = os.path.normpath(os.path.join(UI, "ipad", rel))
                    base = os.path.join(UI, "ipad")
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

    def qr_data_uri(self):
        try:
            import qrcode, base64
            img = qrcode.make(self.url(), border=2, box_size=8)
            b = io.BytesIO(); img.save(b, format="PNG")
            return "data:image/png;base64," + base64.b64encode(b.getvalue()).decode()
        except Exception:
            return None

    # ------------------------------------------------------------- live stream
    def _sse(self, h):
        h.send_response(200)
        h.send_header("Content-Type", "text/event-stream")
        h.send_header("Cache-Control", "no-cache")
        h.send_header("Connection", "keep-alive")
        h.end_headers()
        q = queue.Queue(maxsize=200)
        with self.lock:
            self.clients.append(q)
        try:
            # retry: the browser's own reconnect delay; then everything that changes rarely
            h.wfile.write(b"retry: 2000\n\n")
            self._write(h, "full", self.snapshot_full())
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
                last_t = max((i for i, it in enumerate(items) if it[0] == "t"), default=-1)
                out = b"".join(blob for i, (kind, blob) in enumerate(items) if kind != "t" or i == last_t)
                h.wfile.write(out); h.wfile.flush()
        except (OSError, ValueError):
            pass
        finally:
            with self.lock:
                if q in self.clients:
                    self.clients.remove(q)

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
        if not self.clients or now - self._t_last < 0.1:
            return
        self._t_last = now
        try:
            snap = self.snapshot(brain, pit)
        except Exception as e:
            snap = {"err": repr(e)}
        self.last = snap
        self.push("t", snap)
        tn = (brain.info("WeekendInfo", {}) or {}).get("TrackName")
        if tn != self._track:
            self._track = tn
            self.push("full", self.snapshot_full())

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
        r = _r
        return {
            "on": bool(g("IsOnTrack", False)), "pit": bool(g("OnPitRoad", False)), "met": met,
            "spd": round((g("Speed", 0) or 0) * (3.6 if met else 2.23694)), "gear": g("Gear", 0), "rpm": round(g("RPM", 0) or 0),
            "thr": round(g("Throttle", 0) or 0, 3), "brk": round(g("Brake", 0) or 0, 3), "steer": round(g("SteeringWheelAngle", 0) or 0, 3),
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

    def snapshot_full(self):
        """Everything that changes rarely: session, track, map, pit state."""
        eng = getattr(self.api, "_engine", None)
        b = eng.brain if eng else None
        pit = getattr(self.api, "_pit", None)
        out = {"live": b is not None, "pit": pit.state() if pit else {"live": False}}
        try:
            out["strat"] = self.api.strat_state()
        except Exception:
            pass
        if b is None:
            return out
        wk = b.info("WeekendInfo", {}) or {}
        d = b.drivers().get(b.me(), {})
        di = b.info("DriverInfo", {}) or {}
        out.update({"track": wk.get("TrackDisplayName", ""), "track_id": wk.get("TrackName", ""), "car": d.get("CarScreenName", ""),
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
                v = next((v for v in idx.values() if v.get("track") == track and v.get("best") and not v.get("error")), None)
                if v:
                    from .telemetry import Session
                    s = Session(v["path"])
                    m = s.track_map(points=700)
                    m["len"] = s.track_len
                    os.makedirs(os.path.dirname(p), exist_ok=True)
                    json.dump(m, open(p, "w", encoding="utf-8"))
            except Exception as e:
                self.log(f"[ipad] map: {e!r}")
        m = _compact_map(m)
        self._map_cache[track] = m
        return m


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
