"""Synthetic laps for testing the coach (no real iRacing data here).

A tiny point-mass car on a made-up 3 km track: curvature -> grip-limited speed, a power curve with gears,
brakes, and a driver whose inputs are set per corner. The reference driver brakes as late as the grip
allows and trail-brakes to the apex; a test lap copies him and makes ONE mistake in ONE corner.
Output: traces on a 1 m grid with the same keys as telemetry.Session.trace(), plus a writer for a
minimal .ibt file so the real telemetry.Session reader can be exercised too.
"""
import math, struct
import numpy as np

L = 3000.0
DS = 0.5
G_LAT = 17.0            # m/s2 cornering grip
B_DEC = 19.0            # m/s2 at 100 % brake
CORNERS = [  # apex, radius, half length, direction (+ = left)
    (450.0, 28.0, 45.0, +1), (1000.0, 65.0, 60.0, -1), (1550.0, 130.0, 80.0, +1),
    (2150.0, 40.0, 50.0, -1), (2650.0, 85.0, 60.0, +1)]
NAMES = ["Hairpin", "Esses", "Fast Left", "Turn Four", "Last Corner"]
TOPS = [0, 24, 34, 44, 54, 65, 82]       # m/s at 7300 rpm per gear
RPM_TOP = 7300.0


def corners_meta():
    return [{"name": n, "key": n.lower().replace(" ", "_"), "start": a - h - 20, "end": a + h * 0.6}
            for n, (a, R, h, s) in zip(NAMES, CORNERS)]


def curvature(d):
    k = np.zeros_like(d)
    for a, R, h, s in CORNERS:
        u = np.abs(d - a) / h
        k += np.where(u < 1, s / R * 0.5 * (1 + np.cos(np.pi * np.clip(u, 0, 1))), 0)
    return k


def default_params():
    return [dict(brake_d=a - 150, peak=0.95, build_s=0.12, rel_start=a - 45, rel_end=a - 5, rel_scale=1.0,
                 thr_on=a + 0.0, ramp_m=50.0, lift_d=None, grip=1.0, gear_plus=0, shift_rpm=7000.0,
                 hesitate=False, wobble=0.0, line=0.0, cap=None) for a, R, h, s in CORNERS]


def _power(rpm):
    if rpm >= 7400:
        return 0.0
    if rpm <= 6500:
        return max(0.2, 0.35 + 0.65 * rpm / 6500)
    return 1.0 - (rpm - 6500) / 3000


def simulate(P, v0=60.0):
    """P = per-corner driver params. -> dict of arrays on the DS grid (+ 'over' = speed clamped by grip)."""
    d = np.arange(0, L, DS)
    kap = curvature(d)
    n = len(d)
    vlim_base = np.sqrt(G_LAT / np.maximum(np.abs(kap), 1e-6))
    vlim = np.minimum(vlim_base, 120.0)
    grip = np.ones(n)
    owner = np.full(n, -1)
    for i, (a, R, h, s) in enumerate(CORNERS):
        w = (d > a - 400) & (d < a + 300)
        owner[w & (owner < 0)] = i
        g = (d > a - h - 30) & (d < a + h + 30)
        grip[g] = P[i]["grip"]
    vlim = vlim * grip
    v = np.empty(n); thr = np.empty(n); brk = np.empty(n); gear = np.empty(n); rpm = np.empty(n); over = np.zeros(n)
    vc, gc = v0, 6
    tb = None   # time since brake start
    for j in range(n):
        x = d[j]
        i = owner[j]
        p = P[i] if i >= 0 else None
        a_apex = CORNERS[i][0] if i >= 0 else None
        # ---- driver: brake
        b = 0.0
        if p and p["brake_d"] <= x < p["rel_end"] + (0 if not p.get("hold_to") else 0):
            if tb is None:
                tb = 0.0
            build = min(1.0, tb / max(1e-3, p["build_s"]))
            if x < p["rel_start"]:
                b = p["peak"] * build
            else:
                f = (x - p["rel_start"]) / max(1e-3, p["rel_end"] - p["rel_start"])
                b = p["peak"] * build * max(0.0, 1 - f) ** 1.4 * p["rel_scale"]
                b = min(b, p["peak"])
            tb += DS / max(vc, 1)
        else:
            tb = None
        # ---- driver: throttle
        t_ = 1.0
        if p:
            lift = p["lift_d"] if p["lift_d"] is not None else p["brake_d"] - 1
            if lift <= x < p["thr_on"]:
                t_ = 0.0
            elif p["thr_on"] <= x < p["thr_on"] + p["ramp_m"]:
                f = (x - p["thr_on"]) / p["ramp_m"]
                t_ = 0.15 + 0.85 * f
                if p["hesitate"] and 0.35 < f < 0.55:
                    t_ = 0.2
                if p["hesitate"] and 0.7 < f < 0.8:
                    t_ = 0.35
            if b > 0:
                t_ = 0.0
        # ---- gears
        r_now = vc / TOPS[gc] * RPM_TOP
        sp = p["shift_rpm"] if p and x > a_apex else 7000.0
        if r_now > sp and gc < 6:
            gc += 1
        elif gc > 1 and r_now < 4200 and vc / TOPS[gc - 1] * RPM_TOP < 7200:
            gc -= 1
        g_use = gc
        if p and p["gear_plus"] and p["brake_d"] < x < a_apex + 90:
            g_use = min(6, gc + p["gear_plus"])
        r_use = vc / TOPS[g_use] * RPM_TOP
        # ---- car
        acc = t_ * min(9.5, 330.0 * _power(r_use) / max(vc, 5)) - 0.00065 * vc * vc - b * B_DEC
        vn = math.sqrt(max(1.0, vc * vc + 2 * acc * DS))
        cap = vlim[j]
        if p and p["cap"] and abs(x - a_apex) < 60:
            cap = min(cap, vlim[j] * p["cap"])
        if vn > cap:
            over[j] = vn - cap
            vn = cap
        v[j], thr[j], brk[j], gear[j], rpm[j] = vc, t_, b, g_use, min(r_use, 7400)
        vc = vn
    t = np.concatenate([[0], np.cumsum(DS / np.maximum(v[:-1], 1))])
    steer = kap * 2.7 * 12
    for i, p in enumerate(P):
        if p["wobble"]:
            a = CORNERS[i][0]
            m = np.abs(d - a) < 70
            steer[m] += p["wobble"] * np.sin((d[m] - a) / 6.0)
    lat = v * v * kap * grip
    lon = np.gradient(v) * v / DS
    yaw = v * kap
    # geometry for Lat/Lon
    th = np.cumsum(kap) * DS
    xx = np.cumsum(np.cos(th)) * DS
    yy = np.cumsum(np.sin(th)) * DS
    for i, p in enumerate(P):
        if p["line"]:
            a, R, h, s = CORNERS[i]
            u = np.clip(np.abs(d - a) / 50.0, 0, 1)
            bump = 0.5 * (1 + np.cos(np.pi * u))
            # +line = towards the inside (left normal for a left turn)
            nx, ny = -np.sin(th), np.cos(th)
            xx = xx + nx * s * p["line"] * bump
            yy = yy + ny * s * p["line"] * bump
    lat0, lon0 = 50.0, 6.0
    R_e = 6371000.0
    la = lat0 + yy / R_e * 180 / math.pi
    lo = lon0 + xx / (R_e * math.cos(math.radians(lat0))) * 180 / math.pi
    return {"d": d, "t": t, "Speed": v, "Throttle": thr, "Brake": brk, "Gear": gear, "RPM": rpm, "SteeringWheelAngle": steer,
            "LatAccel": lat, "LongAccel": lon, "YawRate": yaw, "Lat": la, "Lon": lo, "over": over}


def to_trace(sim, position=True):
    grid = np.arange(0, L - 1, 1.0)
    tr = {"d": grid}
    for k, v in sim.items():
        if k in ("d", "over"):
            continue
        if not position and k in ("Lat", "Lon"):
            continue
        tr[k] = np.interp(grid, sim["d"], v)
    tr["Gear"] = np.round(tr["Gear"])
    tr["kmh"] = tr["Speed"] * 3.6
    return tr


_REF = None


def _tune(P, i):
    """Latest brake point for corner i without overshooting the grip (bisection), the rest of P as given."""
    a = CORNERS[i][0]
    p = P[i]
    rel = (p["rel_start"] - p["brake_d"], p["rel_end"] - p["brake_d"], p["thr_on"] - p["brake_d"])
    lo, hi = a - 450, a - 60          # lo = safe (early), hi = too late
    for _ in range(16):
        mid = (lo + hi) / 2
        p["brake_d"] = mid
        sim = simulate(P)
        w = (sim["d"] > mid) & (sim["d"] < a)
        if sim["over"][w].sum() > 0.6:
            hi = mid
        else:
            lo = mid
    p["brake_d"] = lo


def reference_params():
    global _REF
    if _REF is not None:
        return [dict(p) for p in _REF]
    P = default_params()
    for i in range(len(CORNERS)):
        _tune(P, i)
    _REF = [dict(p) for p in P]
    return [dict(p) for p in P]


MISTAKES = {   # name -> (corner index, change, expected finding code)
    "brake_early": (0, dict(brake_d=-20, rel_start=-20, rel_end=-10), "BRAKE_EARLY"),
    "abrupt_release": (1, dict(rel_start=+28, rel_end=-3, grip=0.93), "BRAKE_RELEASE_ABRUPT"),
    "early_lift": (2, dict(lift=-70), "EARLY_LIFT"),
    "slow_mid": (3, dict(cap=0.9), "MIN_SPEED_LOW"),
    "wrong_gear": (4, dict(gear_plus=1), "GEAR_DIFF"),
    "coasting": (0, dict(rel_start=-25, rel_end=-30, thr_on=+20), "COASTING"),
    "throttle_late": (1, dict(thr_on=+30), "THROTTLE_LATE"),
    "hesitation": (3, dict(hesitate=True), "THROTTLE_HESITATION"),
    "shift_early": (2, dict(shift_rpm=5600.0), "SHIFT_EARLY"),
    "corrections": (4, dict(wobble=0.12, grip=0.96), "STEER_CORRECTIONS"),
    "brake_late": (0, dict(brake_d=+14, cap=0.82), "BRAKE_LATE"),
    "wide_apex": (2, dict(line=-3.0), "LINE_WIDE_APEX"),
}


def with_mistake(name, P=None, scale=1.0, adapt=True):
    P = [dict(p) for p in (P or reference_params())]
    i, ch, _ = MISTAKES[name]
    p = P[i]
    a = CORNERS[i][0]
    for k, v in ch.items():
        if k == "lift":
            p["lift_d"] = p["brake_d"] + v * scale
        elif k in ("brake_d", "rel_start", "rel_end", "thr_on"):
            p[k] = p[k] + v * scale
        else:
            p[k] = v
    if adapt:   # otherwise a good driver: re-find the brake point of the next corner (he arrives at another speed)
        for j in range(i + 1, min(i + 2, len(CORNERS))):
            _tune(P, j)
    return P


# ---------------------------------------------------------------- minimal .ibt writer
_TYPES = {"i": 2, "f": 4, "d": 5, "b": 1}


def write_ibt(path, laps, track="synth ring", hz=60, car_path="bmwm4gt3", car="BMW M4 GT3"):
    """laps = list of sims (from simulate()). Writes them back to back, then a short in-lap."""
    chans = {k: [] for k in ("SessionTime", "Lap", "LapDist", "LapDistPct", "LapLastLapTime", "Speed", "Throttle", "Brake",
                             "SteeringWheelAngle", "Gear", "RPM", "LatAccel", "LongAccel", "YawRate", "Lat", "Lon",
                             "IsOnTrack", "OnPitRoad", "PlayerTrackSurface", "PlayerCarMyIncidentCount")}
    t0, last = 0.0, 0.0
    seq = list(laps) + [laps[-1]]
    for li, sim in enumerate(seq):
        T = sim["t"][-1] + DS / max(sim["Speed"][-1], 1)
        n = int(T * hz)
        if li == len(seq) - 1:
            n = int(n * 0.3)         # partial in-lap so the previous lap is closed
        ts = np.arange(n) / hz
        dd = np.interp(ts, sim["t"], sim["d"])
        for k in ("Speed", "Throttle", "Brake", "SteeringWheelAngle", "Gear", "RPM", "LatAccel", "LongAccel", "YawRate", "Lat", "Lon"):
            chans[k].append(np.interp(ts, sim["t"], sim[k]))
        chans["SessionTime"].append(t0 + ts)
        chans["Lap"].append(np.full(n, li + 1))
        chans["LapDist"].append(dd)
        chans["LapDistPct"].append(dd / L)
        post = np.full(n, last)
        chans["LapLastLapTime"].append(post)
        chans["IsOnTrack"].append(np.ones(n))
        chans["OnPitRoad"].append(np.zeros(n))
        chans["PlayerTrackSurface"].append(np.full(n, 3))
        chans["PlayerCarMyIncidentCount"].append(np.zeros(n))
        t0 += n / hz
        last = float(T)
    data = {k: np.concatenate(v) for k, v in chans.items()}
    kinds = {"SessionTime": "d", "Lap": "i", "Gear": "i", "IsOnTrack": "b", "OnPitRoad": "b", "PlayerTrackSurface": "i",
             "PlayerCarMyIncidentCount": "i", "Lat": "d", "Lon": "d"}
    names = list(data)
    offs, off = {}, 0
    for k in names:
        offs[k] = off
        off += {"i": 4, "f": 4, "d": 8, "b": 1}[kinds.get(k, "f")]
    buf_len = off
    yaml = (f"WeekendInfo:\n TrackName: {track}\n TrackDisplayName: Synth Ring\n TrackLength: {L / 1000:.2f} km\n TrackID: 999\n"
            f"DriverInfo:\n DriverCarIdx: 0\n Drivers:\n - CarIdx: 0\n   UserName: Test Driver\n   CarPath: {car_path}\n"
            f"   CarScreenName: {car}\n   CarID: 132\n   CarClassShortName: GT3\nCarSetup:\n UpdateCount: 1\n...\n").encode()
    nv = len(names)
    vh_off = 144
    si_off = vh_off + nv * 144
    buf_off = si_off + len(yaml) + 16
    rec = len(data["Lap"])
    head = bytearray(144)
    struct.pack_into("<10i", head, 0, 2, 1, hz, 1, len(yaml), si_off, nv, vh_off, 1, buf_len)
    struct.pack_into("<2i", head, 48, rec, buf_off)
    struct.pack_into("<i", head, 112 + 28, rec)
    vh = bytearray()
    for k in names:
        h = bytearray(144)
        struct.pack_into("<3i", h, 0, _TYPES[kinds.get(k, "f")], offs[k], 1)
        h[16:16 + len(k)] = k.encode()
        vh += h
    rows = np.zeros((rec, buf_len), np.uint8)
    for k in names:
        dt = {"i": "<i4", "f": "<f4", "d": "<f8", "b": "u1"}[kinds.get(k, "f")]
        col = data[k].astype(dt)
        rows[:, offs[k]:offs[k] + col.itemsize] = col.view(np.uint8).reshape(rec, col.itemsize)
    with open(path, "wb") as f:
        f.write(head); f.write(vh); f.write(yaml); f.write(b"\x00" * 16); f.write(rows.tobytes())
    return path


def write_g61_csv(path, sim, hz=60):
    """A lap in Garage 61's CSV layout (header copied from a public Garage 61 sample export)."""
    T = sim["t"][-1]
    ts = np.arange(int(T * hz)) / hz
    g = lambda k: np.interp(ts, sim["t"], sim[k])
    cols = ["Speed", "LapDistPct", "Lat", "Lon", "Brake", "Throttle", "RPM", "SteeringWheelAngle", "Gear", "Clutch", "ABSActive",
            "DRSActive", "P2PActive", "LatAccel", "LongAccel", "VertAccel", "Yaw", "YawRate", "PositionType"]
    data = {"Speed": g("Speed"), "LapDistPct": np.interp(ts, sim["t"], sim["d"]) / L, "Lat": g("Lat"), "Lon": g("Lon"),
            "Brake": g("Brake"), "Throttle": g("Throttle"), "RPM": g("RPM"), "SteeringWheelAngle": g("SteeringWheelAngle"),
            "Gear": np.round(g("Gear")), "LatAccel": g("LatAccel"), "LongAccel": g("LongAccel"), "YawRate": g("YawRate")}
    with open(path, "w", encoding="utf-8") as f:
        f.write(",".join(cols) + "\n")
        for i in range(len(ts)):
            row = []
            for c in cols:
                if c in data:
                    row.append(f"{data[c][i]:.6f}" if c not in ("Gear",) else str(int(data[c][i])))
                elif c in ("ABSActive", "DRSActive", "P2PActive"):
                    row.append("false")
                elif c == "PositionType":
                    row.append("3")
                elif c == "Clutch":
                    row.append("1")
                else:
                    row.append("0")
            f.write(",".join(row) + "\n")
    return path
