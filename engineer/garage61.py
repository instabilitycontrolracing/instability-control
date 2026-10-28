"""Garage 61 (garage61.net) API client for the driving coach: your token, the laps it can see, and a lap's
telemetry as CSV. Standard library only (urllib).

API facts (from the official OpenAPI spec, https://garage61.net/api/openapi/v1.json, read 2026-10-24):
  * Base URL https://garage61.net/api/v1, personal access token sent as "Authorization: Bearer <token>".
  * GET /me                -> who you are, subscriptionPlan, apiPermissions (the token's permissions).
  * GET /cars, GET /tracks -> Garage 61 ids; platform_id is the iRacing CarID / TrackID.
  * GET /laps              -> lap search (needs the token's `driving_data` permission). "By default, applications
                              can only query laps driven by the authenticated user or their teammates. Some
                              applications may additionally be approved to search all visible laps."
                              seeTelemetry / seeGhostLap / seeSetup filters "require the calling user to have a Pro plan".
  * GET /laps/{id}/csv     -> the lap's telemetry as CSV (driving_data; only laps visible to you).
So with a personal token, alien laps from other drivers are normally NOT reachable through the API unless they
are your Garage 61 teammates. The coach then falls back to your own fastest lap, a CSV you export from the
website, or an .ibt file.

2026-10-28 (re-added, API ONLY): this module talks to the web API and nothing else. It never installs or runs the
Garage 61 desktop agent and never reads, moves or deletes iRacing .ibt files. The only files it writes are the
token file and small JSON/CSV caches under %LOCALAPPDATA%\\RaceEngineer\\cache.

BE GENTLE (Garage 61: free for non-commercial use, please don't overload the API): every call is made by a user
click, never by a loop or a timer. /me is kept for the session, /cars and /tracks for a week on disk, a lap list for
15 minutes per car + track, and a downloaded lap CSV forever (laps don't change). One "Garage 61" click is at most
4 requests the first time (me, cars, tracks, laps) and 0-1 after that; loading a lap is at most 2.

THE TOKEN: kept only in one local file, TOKEN_FILE (%LOCALAPPDATA%\\RaceEngineer\\garage61_token.txt).
Never in engineer_settings.json, never logged or printed, never returned to the window, never in problem reports.
"""
import json, os, socket, ssl, time, urllib.error, urllib.parse, urllib.request

BASE = "https://garage61.net/api/v1"
APP_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "RaceEngineer")
TOKEN_FILE = os.path.join(APP_DIR, "garage61_token.txt")
UA = "InstabilityControl-Coach/1.0"
LIST_TTL = 15 * 60            # a lap list is reused for 15 minutes
IDS_TTL = 7 * 24 * 3600        # the cars / tracks id lists for a week
_MEM = {}                      # in-process cache: ("me",) and ("laps", car, track) -> (time, value)


class G61Error(Exception):
    """kind: no_token | bad_token | permission | not_found | rate_limited | network | server"""
    def __init__(self, kind, message, trace=None):
        super().__init__(message)
        self.kind, self.message, self.trace = kind, message, trace

    def as_dict(self):
        return {"ok": False, "kind": self.kind, "error": self.message}


# ---------------------------------------------------------------- the token (local file only)
def load_token(path=None):
    try:
        with open(path or TOKEN_FILE, encoding="utf-8") as f:
            return f.read().strip() or None
    except OSError:
        return None


def save_token(token, path=None):
    token = (token or "").strip()
    p = path or TOKEN_FILE
    if not token:
        return clear_token(p)
    _MEM.clear()                # a new token may be a different account
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(token)
    try:
        os.chmod(p, 0o600)      # no-op on Windows; the folder is per-user there anyway
    except OSError:
        pass
    return True


def clear_token(path=None):
    p = path or TOKEN_FILE
    if os.path.basename(p) != "garage61_token.txt":     # only ever our own token file
        return False
    try:
        os.remove(p)
    except OSError:
        pass
    _MEM.clear()
    return True


def has_token(path=None):
    return bool(load_token(path))


# ---------------------------------------------------------------- client
class Client:
    def __init__(self, token=None, timeout=20, opener=None):
        self._token = token if token is not None else load_token()
        self.timeout = timeout
        self._open = opener or urllib.request.urlopen     # tests swap this

    def __repr__(self):                                     # never show the token
        return f"<garage61.Client token={'set' if self._token else 'none'}>"

    def _get(self, path, params=None, raw=False):
        if not self._token:
            raise G61Error("no_token", "No Garage 61 token yet. Paste it in Analysis > Coach > Garage 61 (or Settings > General > Garage 61).")
        q = ""
        if params:
            flat = {}
            for k, v in params.items():
                if v is None:
                    continue
                if isinstance(v, (list, tuple)):
                    v = ",".join(str(x) for x in v)            # the API takes comma lists (explode=false)
                elif isinstance(v, bool):
                    v = "true" if v else "false"
                flat[k] = v
            q = "?" + urllib.parse.urlencode(flat)
        req = urllib.request.Request(BASE + path + q, headers={
            "Authorization": "Bearer " + self._token, "Accept": "text/csv" if raw else "application/json", "User-Agent": UA})
        try:
            with self._open(req, timeout=self.timeout) as r:
                body = r.read()
        except urllib.error.HTTPError as e:
            msg, trace = "", None
            try:
                j = json.loads(e.read().decode("utf-8", "replace"))
                msg, trace = j.get("message", ""), j.get("trace")
            except Exception:
                pass
            code = e.code
            if code == 401:
                raise G61Error("bad_token", "Garage 61 didn't accept the token (expired or mistyped). Make a new one on garage61.net and paste it again.", trace)
            if code == 403:
                raise G61Error("permission", "The token is missing a permission for this. When you make the token on garage61.net, tick "
                                             "\"driving data\" (driving_data)." + (f" ({msg})" if msg else ""), trace)
            if code == 404:
                raise G61Error("not_found", "Garage 61 can't find that lap, or it isn't visible to you.", trace)
            if code == 429:
                raise G61Error("rate_limited", "Garage 61 says too many requests. Wait a minute and try again.", trace)
            raise G61Error("server", f"Garage 61 error {code}" + (f": {msg}" if msg else ""), trace)
        except (urllib.error.URLError, socket.timeout, ssl.SSLError, ConnectionError, TimeoutError) as e:
            raise G61Error("network", "Can't reach garage61.net (no internet or the site is down).")
        if raw:
            return body.decode("utf-8-sig", "replace")
        try:
            return json.loads(body.decode("utf-8"))
        except ValueError:
            raise G61Error("server", "Garage 61 sent something unexpected.")

    # ---- endpoints ----
    def me(self):
        return self._get("/me")

    def cars(self):
        return self._get("/cars").get("items", [])

    def tracks(self):
        return self._get("/tracks").get("items", [])

    def find_laps(self, cars=None, tracks=None, drivers=None, group="driver", limit=50, **extra):
        p = {"cars": cars, "tracks": tracks, "drivers": drivers, "group": group, "limit": limit}
        p.update(extra)
        return self._get("/laps", p)

    def lap(self, lap_id):
        return self._get("/laps/" + urllib.parse.quote(str(lap_id), safe=""))

    def lap_csv(self, lap_id):
        return self._get("/laps/" + urllib.parse.quote(str(lap_id), safe="") + "/csv", raw=True)


# ---------------------------------------------------------------- helpers for the app
def test_token(client=None):
    """Settings > Garage 61 > Test. -> {"ok", "name", "plan", "driving_data", "status"} (never the token)."""
    try:
        c = client or Client()
        me = c.me()
        _MEM[("me",)] = (time.time(), me)
    except G61Error as e:
        return dict(e.as_dict(), status=e.message)
    perms = [str(x) for x in (me.get("apiPermissions") or [])]
    name = " ".join(x for x in (me.get("firstName"), me.get("lastName")) if x) or me.get("nickName") or "you"
    plan = me.get("subscriptionPlan") or "free"
    dd = "driving_data" in perms
    st = f"Connected as {name} ({plan} plan)."
    st += " Driving data: yes." if dd else " Driving data permission is missing: make a token with \"driving data\" ticked."
    st += " The API shows your own and your teammates' laps; for another driver's lap, export its CSV on garage61.net and load it here."
    return {"ok": True, "name": name, "plan": plan, "permissions": perms, "driving_data": dd, "status": st}


def _cached(name, fetch, cache_dir, ttl=IDS_TTL):
    p = os.path.join(cache_dir, name)
    try:
        if time.time() - os.path.getmtime(p) < ttl:
            with open(p, encoding="utf-8") as f:
                return json.load(f)
    except (OSError, ValueError):
        pass
    items = fetch()
    try:
        os.makedirs(cache_dir, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(items, f)
    except OSError:
        pass
    return items


def cached_me(client):
    """/me once per app session (it only changes when the token does)."""
    hit = _MEM.get(("me",))
    if hit:
        return hit[1]
    me = client.me()
    _MEM[("me",)] = (time.time(), me)
    return me


def lap_csv_cached(client, lap_id, cache_dir=None):
    """A lap's telemetry CSV, downloaded once and kept in the cache (a driven lap never changes)."""
    from .telemetry import CACHE_DIR
    d = os.path.join(cache_dir or CACHE_DIR, "g61_laps")
    p = os.path.join(d, "".join(ch for ch in str(lap_id) if ch.isalnum() or ch in "-_")[:80] + ".csv")
    try:
        with open(p, encoding="utf-8") as f:
            return f.read()
    except OSError:
        pass
    text = client.lap_csv(lap_id)
    try:
        os.makedirs(d, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
    except OSError:
        pass
    return text


def match_ids(client, ir_car_id, ir_track_id, car_name="", track_name="", cache_dir=None):
    """iRacing CarID/TrackID -> Garage 61 (car id, track id). Name match as a fallback."""
    from .telemetry import CACHE_DIR
    cd = cache_dir or CACHE_DIR
    cars = _cached("g61_cars.json", client.cars, cd)
    tracks = _cached("g61_tracks.json", client.tracks, cd)
    pick = lambda items, pid, nm: next((x["id"] for x in items if x.get("platform") in (None, "iracing") and str(x.get("platform_id")) == str(pid)), None) \
        or next((x["id"] for x in items if nm and (x.get("name") or "").lower() == nm.lower()), None)
    return pick(cars, ir_car_id, car_name), pick(tracks, ir_track_id, track_name)


REACH_HELP = ("Garage 61 only lets this app see laps driven by you and your Garage 61 teammates (other drivers' laps "
              "need an approval this app doesn't have). To get a faster lap here: ask a fast driver to join your team on "
              "garage61.net (Teams), or join a team with fast drivers in this car. Or open any lap you can see on "
              "garage61.net, export its telemetry CSV and use 'CSV file'.")


def fastest_laps(client, car_id, track_id, me_id=None, my_best=None, limit=25, refresh=False):
    """Fastest visible laps for this car + track (one per driver), cached 15 minutes.
    -> {"laps": [...], "only_mine": bool, "faster": int|None, "note", "cached": bool}"""
    key = ("laps", str(car_id), str(track_id))
    hit = _MEM.get(key)
    cached = bool(hit and not refresh and time.time() - hit[0] < LIST_TTL)
    if cached:
        res = hit[1]
    else:
        res = client.find_laps(cars=[car_id], tracks=[track_id], group="driver", limit=limit)
        _MEM[key] = (time.time(), res)
    out = []
    for L in res.get("items", []):
        drv = L.get("driver") or {}
        out.append({"id": L.get("id"), "time": L.get("lapTime"), "driver": " ".join(x for x in (drv.get("firstName"), drv.get("lastName")) if x) or "?",
                    "driver_id": drv.get("id"), "rating": L.get("driverRating"), "telemetry": bool(L.get("canViewTelemetry")),
                    "clean": L.get("clean"), "date": (L.get("startTime") or "")[:10]})
    out.sort(key=lambda x: x["time"] or 1e9)
    for x in out:
        x["mine"] = bool(me_id and x["driver_id"] == me_id)
    others = [x for x in out if me_id and x["driver_id"] and x["driver_id"] != me_id]
    only_mine = bool(out) and not others
    faster = None
    if my_best:
        faster = sum(1 for x in others if x["time"] and x["time"] < float(my_best) and x["telemetry"])
    note = None
    if not out:
        note = "Garage 61 shows no laps you can see for this car and track. " + REACH_HELP
    elif only_mine:
        note = "Only your own laps are visible here. " + REACH_HELP
    elif faster == 0:
        note = "None of the laps Garage 61 lets you see is faster than your best in this session. " + REACH_HELP
    return {"laps": out, "only_mine": only_mine, "faster": faster, "note": note, "cached": cached}
