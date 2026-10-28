/* Live lap analysis on the iPad.
   2026-10-24: every lap recorded from the feed, the best clean lap is the reference, the current lap drawn over it live.
   2026-10-26 rebuild (request: "make the lap analysis on the iPad just as good as on the PC, but real time, so I can drag
   my finger across a section of the track or the telemetry, just like on the PC app - and elevate the visuals"):
     * the track map shaded by where you gain (green) / lose (red) time against the reference, corner chips with the time
     * five telemetry lanes - delta, speed, pedals, steering, gear - yours over the reference
     * touch: a finger on the map or the lanes scrubs (readout follows it); drag across to select a section, which zooms
       the lanes and fills the section panel (brake point, entry / apex / exit speed, throttle points, what to change);
       tap a corner to select it; double-tap to clear
     * study any lap (tap it in the list) or the live one, which keeps updating as you drive
   Everything is computed here from the 10-per-second feed (and the PC's lap memory), nothing waits on the PC. */
(() => {
  const SECS = [1 / 3, 2 / 3];
  const MAX_PTS = 8000;
  const L = { cur: null, laps: [], best: null, lapNo: null, xy: null, pts: null, dirty: true, lastFeed: 0, bestSec: [null, null, null], met: null, parts: [] };
  const V = { lap: null, sel: null, hover: null, drag: null, lastTap: 0, stops: [] };   // what the screen is showing
  const newLap = (no) => ({ no, p: [], s: [], th: [], br: [], st: [], gr: [], t: [], dl: [], sec: [null, null, null], clean: true, start: null });
  const isNum = (x) => typeof x === "number" && isFinite(x);
  const fmt = (t) => { if (!isNum(t) || !(t > 0)) return "–"; const m = Math.floor(t / 60), s = t - m * 60; return m ? `${m}:${s.toFixed(3).padStart(6, "0")}` : s.toFixed(3); };
  const fmtD = (d) => (!isNum(d) ? "–" : (d > 0 ? "+" : d < 0 ? "−" : "±") + Math.abs(d).toFixed(2));
  const $l = (s) => document.querySelector(s);
  const dpr = () => Math.min(2, window.devicePixelRatio || 1);
  const txt = (e, v) => { if (e && e._t !== v) { e._t = v; e.textContent = v; } };
  const cls = (e, v) => { if (e && e._k !== v) { e._k = v; e.className = v; } };
  const isOn = () => document.body.classList.contains("lapmode");
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const lenM = () => ((typeof MAP !== "undefined" && MAP && MAP.len) || 0);
  const metres = (p) => (lenM() ? p * lenM() : null);

  // ------------------------------------------------------------------ lap maths
  function idxAt(P, pct) { let lo = 0, hi = P.length - 1; while (hi - lo > 1) { const m = (lo + hi) >> 1; if (P[m] < pct) lo = m; else hi = m; } return lo; }
  function valAt(lap, key, pct) {                    // any channel at a point of the lap (interpolated)
    const P = lap.p, A = lap[key]; if (!P.length || !A || !A.length) return null;
    const off = P.length - A.length;                 // older laps may lack the newer channels at the start
    if (pct <= P[0]) return A[Math.max(0, -off)] ?? null;
    if (pct >= P[P.length - 1]) return A[A.length - 1] ?? null;
    const i = idxAt(P, pct), j = i - off;
    if (j < 0 || j + 1 >= A.length) return A[Math.max(0, Math.min(A.length - 1, j))] ?? null;
    const f = (pct - P[i]) / ((P[i + 1] - P[i]) || 1);
    return A[j] + (A[j + 1] - A[j]) * f;
  }
  const timeAt = (lap, pct) => valAt(lap, "t", pct);
  const reach = (lap) => (lap && lap.p.length ? lap.p[lap.p.length - 1] : 0);
  const split = (l, k) => (k === 0 ? l.sec[0] : k === 1 ? (l.sec[1] && l.sec[0] ? l.sec[1] - l.sec[0] : null) : l.sec[2]);

  // 2026-10-28 (#321): the PC also keeps the sector times of laps that weren't clean full laps (a restart mid-lap, a
  // pit stop, an off); the clean ones ("ok") count toward the best sectors, all of them show in the list
  function bestSecs() {
    return [0, 1, 2].map((k) => {
      let b = null;
      for (const l of L.laps) { const v = split(l, k); if (v && (b == null || v < b)) b = v; }
      for (const x of L.parts) { const v = (x.split || [])[k], ok = (x.ok || [])[k]; if (ok && isNum(v) && v > 0 && (b == null || v < b)) b = v; }
      return b;
    });
  }
  function viewLap() { return V.lap == null ? L.cur : (L.laps.find((l) => l.no === V.lap) || L.cur); }
  function refLap(me) {                              // your best clean lap; if you're studying the best, the next best
    if (!L.best) return null;
    if (me !== L.best) return L.best;
    return L.laps.filter((l) => l !== L.best && l.time).sort((a, b) => a.time - b.time)[0] || null;
  }
  const deltaAt = (me, ref, p) => { const a = timeAt(me, p), b = timeAt(ref, p); return a != null && b != null ? a - b : null; };

  // ------------------------------------------------------------------ the feed
  function feed(t) {
    if (!t || t.err) return;
    const now = performance.now();
    const gapped = L.lastFeed && now - L.lastFeed > 2500;
    L.lastFeed = now;
    if (L.lapNo !== t.lap) {
      const done = L.cur;
      if (done && t.last > 0 && done.clean && done.start != null && done.start < 0.06 && done.p.length > 50
          && done.p[done.p.length - 1] > 0.94) {
        done.time = t.last;
        if (done.sec[0] && done.sec[1]) done.sec[2] = t.last - done.sec[1];
        L.laps.unshift(done); if (L.laps.length > 12) L.laps.pop();
        if (!L.best || done.time < L.best.time) L.best = done;
        L.bestSec = bestSecs();
        renderList();
      }
      L.cur = newLap(t.lap); L.lapNo = t.lap; L.dirty = true;
    }
    const c = L.cur, pct = t.pct;
    if (t.pit || !t.on || gapped || t.form) c.clean = false;          // t.form: the formation lap is never a lap
    if (!isNum(pct) || !isNum(t.cur)) return;
    if (c.start == null) c.start = pct;
    const lastP = c.p.length ? c.p[c.p.length - 1] : -1;
    if (pct < lastP - 0.5) return;
    if (pct <= lastP || c.p.length >= MAX_PTS) return;
    for (let k = 0; k < 2; k++) if (!c.sec[k] && lastP >= 0 && lastP < SECS[k] && pct >= SECS[k]) {
      const tl = c.t[c.t.length - 1], f = (SECS[k] - lastP) / ((pct - lastP) || 1);
      const at = tl + (t.cur - tl) * f;
      c.sec[k] = k === 0 ? at : at - c.sec[0];
      if (k === 1) c.sec[1] = at;
    }
    c.p.push(pct); c.s.push(isNum(t.spd) ? t.spd : 0); c.th.push(isNum(t.thr) ? t.thr : 0); c.br.push(isNum(t.brk) ? t.brk : 0);
    c.st.push(isNum(t.steer) ? t.steer : 0); c.gr.push(isNum(t.gear) ? t.gear : 0); c.t.push(t.cur);
    const ref = L.best ? timeAt(L.best, pct) : null;
    c.dl.push(ref != null ? t.cur - ref : (isNum(t.delta) ? t.delta : null));
    L.met = t.met;
    if (V.lap == null) L.dirty = true;
    else L.dirtyTop = true;
  }

  // ------------------------------------------------------------------ geometry
  const SIZE = new Map();
  function fit(cv) {
    const r = SIZE.get(cv); if (!r) return false;
    const k = dpr(), w = Math.max(10, Math.round(r[0] * k)), h = Math.max(10, Math.round(r[1] * k));
    if (cv.width !== w || cv.height !== h) { cv.width = w; cv.height = h; return true; }
    return false;
  }
  const RO = new ResizeObserver((es) => { for (const e of es) SIZE.set(e.target, [e.contentRect.width, e.contentRect.height]); L.dirty = true; if (isOn() && window.REDRAW_ALL) window.REDRAW_ALL(); });
  function project(cv) {
    if (!(typeof MAP !== "undefined" && MAP) || !MAP.pts) { L.xy = null; L.pts = null; return; }
    const k = dpr(), pts = MAP.pts;
    let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
    for (const [x, y] of pts) { x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y); }
    // a long track in a tall panel: turned a quarter so it fills the space (2026-10-26)
    if (cv.height > cv.width * 1.15 && (x1 - x0) > (y1 - y0) * 1.15) {
      const rot = pts.map(([x, y]) => [y, -x]);
      x0 = Infinity; x1 = -Infinity; y0 = Infinity; y1 = -Infinity;
      for (const [x, y] of rot) { x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y); }
      const pad = 34 * k;
      const sc = Math.min((cv.width - 2 * pad) / (x1 - x0 || 1), (cv.height - 2 * pad) / (y1 - y0 || 1));
      const ox = (cv.width - (x1 - x0) * sc) / 2, oy = (cv.height - (y1 - y0) * sc) / 2;
      L.xy = rot.map(([x, y]) => [ox + (x - x0) * sc, cv.height - (oy + (y - y0) * sc)]);
      L.pts = pts; L.projW = cv.width; L.projH = cv.height;
      return;
    }
    const pad = 34 * k;
    const sc = Math.min((cv.width - 2 * pad) / (x1 - x0 || 1), (cv.height - 2 * pad) / (y1 - y0 || 1));
    const ox = (cv.width - (x1 - x0) * sc) / 2, oy = (cv.height - (y1 - y0) * sc) / 2;
    L.xy = pts.map(([x, y]) => [ox + (x - x0) * sc, cv.height - (oy + (y - y0) * sc)]);
    L.pts = pts; L.projW = cv.width; L.projH = cv.height;
  }
  function pt(pct) {
    const D = MAP.d, len = MAP.len, d = ((pct % 1) + 1) % 1 * len;
    let lo = 0, hi = D.length - 1;
    while (lo < hi) { const m = (lo + hi) >> 1; if (D[m] < d) lo = m + 1; else hi = m; }
    const i = Math.max(1, lo), a = L.xy[i - 1], b = L.xy[i % L.xy.length], f = Math.max(0, Math.min(1, (d - D[i - 1]) / ((D[i] - D[i - 1]) || 1)));
    return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f];
  }
  function rr(g, x, y, w, h, r) { g.beginPath(); g.moveTo(x + r, y); g.arcTo(x + w, y, x + w, y + h, r); g.arcTo(x + w, y + h, x, y + h, r); g.arcTo(x, y + h, x, y, r); g.arcTo(x, y, x + w, y, r); g.closePath(); }
  function lossCol(rate, a) {                        // seconds per lap-fraction: green gain, red loss, ivory even
    const v = Math.max(-1, Math.min(1, rate / 12));
    if (Math.abs(v) < 0.06) return `rgba(232,234,240,${0.78 * a})`;
    return v > 0 ? `rgba(255,${Math.round(150 - 110 * v)},${Math.round(150 - 100 * v)},${a})` : `rgba(${Math.round(150 + 100 * v)},${Math.round(225 + 10 * -v)},${Math.round(150 + 20 * v)},${a})`;
  }

  // ------------------------------------------------------------------ the map
  function drawMap() {
    const cv = $l("#lapMap"); if (!cv) return;
    if (fit(cv) || L.pts !== ((typeof MAP !== "undefined" && MAP) && MAP.pts) || L.projW !== cv.width || L.projH !== cv.height) project(cv);
    const g = cv.getContext("2d"), k = dpr(), W = cv.width, H = cv.height;
    g.clearRect(0, 0, W, H);
    const dot = $l("#lapDot");
    if (!L.xy) { if (dot) dot.classList.remove("on"); return; }
    const P = L.xy, me = viewLap(), ref = refLap(me), far = reach(me);
    g.lineCap = "round"; g.lineJoin = "round";
    // the circuit: a soft shadow, a dark bed, a faint rail
    g.beginPath(); g.moveTo(P[0][0], P[0][1]); for (const q of P) g.lineTo(q[0], q[1]); g.closePath();
    g.save(); g.shadowColor = "rgba(0,0,0,.65)"; g.shadowBlur = 18 * k; g.strokeStyle = "rgba(4,6,12,.85)"; g.lineWidth = 16 * k; g.stroke(); g.restore();
    g.strokeStyle = "rgba(255,255,255,.10)"; g.lineWidth = 9 * k; g.stroke();
    // your lap, shaded by the rate you gain or lose time against the reference
    const N = 420;
    if (me && me.p.length > 1) {
      let prev = null;
      g.lineWidth = 6 * k;
      for (let i = 0; i <= N; i++) {
        const p = i / N; if (p > far) break;
        const d = ref ? deltaAt(me, ref, p) : null;
        if (prev) {
          const rate = prev.d != null && d != null ? (d - prev.d) / (p - prev.p) : 0;
          const a = pt(prev.p), b = pt(p);
          g.strokeStyle = ref ? lossCol(rate, 1) : "rgba(240,205,126,.95)";
          g.beginPath(); g.moveTo(a[0], a[1]); g.lineTo(b[0], b[1]); g.stroke();
        }
        prev = { p, d };
      }
    }
    // the selected section glows on top
    const sel = V.drag ? [Math.min(V.drag.a, V.drag.b), Math.max(V.drag.a, V.drag.b)] : V.sel;
    if (sel) {
      g.save(); g.shadowColor = "rgba(240,205,126,.8)"; g.shadowBlur = 16 * k; g.strokeStyle = "rgba(240,205,126,.95)"; g.lineWidth = 12 * k;
      g.beginPath(); const n = 80; for (let i = 0; i <= n; i++) { const q = pt(sel[0] + (sel[1] - sel[0]) * i / n); i ? g.lineTo(q[0], q[1]) : g.moveTo(q[0], q[1]); } g.stroke(); g.restore();
      g.strokeStyle = "rgba(10,12,18,.85)"; g.lineWidth = 4 * k;
      g.beginPath(); const n2 = 80; for (let i = 0; i <= n2; i++) { const q = pt(sel[0] + (sel[1] - sel[0]) * i / n2); i ? g.lineTo(q[0], q[1]) : g.moveTo(q[0], q[1]); } g.stroke();
    }
    // sector marks + start / finish
    for (const s of SECS) { const [x, y] = pt(s); g.fillStyle = "rgba(240,205,126,.95)"; g.beginPath(); g.arc(x, y, 3.2 * k, 0, 7); g.fill(); }
    { const a = pt(0), b = pt(0.003), ang = Math.atan2(b[1] - a[1], b[0] - a[0]) + Math.PI / 2;
      g.strokeStyle = "#F5F3EE"; g.lineWidth = 3 * k; g.beginPath(); g.moveTo(a[0] + Math.cos(ang) * 11 * k, a[1] + Math.sin(ang) * 11 * k); g.lineTo(a[0] - Math.cos(ang) * 11 * k, a[1] - Math.sin(ang) * 11 * k); g.stroke(); }
    // corner chips: the biggest gains and losses, placed so they never overlap
    if (ref && V.stops.length) {
      const rows = corners(me, ref).filter((r) => r.d != null).sort((a, b) => Math.abs(b.d) - Math.abs(a.d)).slice(0, 7);
      g.font = `600 ${11 * k}px Inter, sans-serif`; g.textBaseline = "middle";
      const placed = [], hit = (b) => placed.some((o) => !(b.x + b.w < o.x || o.x + o.w < b.x || b.y + b.h < o.y || o.y + o.h < b.y));
      for (const r of rows) {
        const [x, y] = pt((r.a + r.b) / 2);
        const lab = `${r.name}`, val = `${r.d > 0 ? "+" : "−"}${Math.abs(r.d).toFixed(2)}`;
        g.font = `600 ${10.5 * k}px Inter, sans-serif`; const w1 = g.measureText(lab).width;
        g.font = `600 ${11 * k}px Timing, Inter, sans-serif`; const w2 = g.measureText(val).width;
        const w = w1 + w2 + 22 * k, h = 22 * k;
        const tries = [[10, -11], [-10 - w / k, -11], [-w / 2 / k, -34], [-w / 2 / k, 12], [10, -34], [10, 12], [-10 - w / k, -34], [-10 - w / k, 12]];
        let box = null;
        for (const [ox, oy] of tries) { const b = { x: x + ox * k, y: y + oy * k, w, h }; if (!hit(b) && b.x > 2 && b.x + w < W - 2 && b.y > 2 && b.y + h < H - 2) { box = b; break; } }
        if (!box) continue;
        placed.push(box);
        const col = r.d > 0.04 ? "#FF6B7A" : r.d < -0.04 ? "#4ADE80" : "#D5DAE3";
        g.fillStyle = col; g.beginPath(); g.arc(x, y, 3.4 * k, 0, 7); g.fill();
        g.fillStyle = "rgba(6,8,14,.86)"; rr(g, box.x, box.y, w, h, 6 * k); g.fill();
        g.strokeStyle = "rgba(255,255,255,.08)"; g.lineWidth = 1 * k; g.stroke();
        g.font = `600 ${10.5 * k}px Inter, sans-serif`; g.fillStyle = "#D5DAE3"; g.fillText(lab, box.x + 8 * k, box.y + h / 2);
        g.font = `600 ${11 * k}px Timing, Inter, sans-serif`; g.fillStyle = col; g.fillText(val, box.x + 14 * k + w1, box.y + h / 2);
      }
    }
    // the finger
    if (V.hover != null) {
      const [x, y] = pt(V.hover);
      g.fillStyle = "rgba(240,205,126,.25)"; g.beginPath(); g.arc(x, y, 16 * k, 0, 7); g.fill();
      g.fillStyle = "#F0CD7E"; g.strokeStyle = "#120E05"; g.lineWidth = 2 * k; g.beginPath(); g.arc(x, y, 6.5 * k, 0, 7); g.fill(); g.stroke();
    }
    // the car (live lap only)
    if (dot) {
      if (V.lap == null && L.cur && L.cur.p.length) { const [x, y] = pt(L.cur.p[L.cur.p.length - 1]); dot.style.transform = `translate3d(${(x / k).toFixed(1)}px, ${(y / k).toFixed(1)}px, 0)`; dot.classList.add("on"); }
      else dot.classList.remove("on");
    }
  }

  // ------------------------------------------------------------------ the telemetry lanes
  const LANES = [["Δ", 0.17], ["SPEED", 0.33], ["PEDALS", 0.22], ["STEER", 0.16], ["GEAR", 0.12]];
  const GUT = 54;                                    // left gutter for lane labels (css px)
  function range() {
    const sel = V.sel;
    if (sel) { const span = sel[1] - sel[0], pad = Math.max(0.01, span * 0.25); return [Math.max(0, sel[0] - pad), Math.min(1, sel[1] + pad)]; }
    return [0, 1];
  }
  function drawTrace() {
    const cv = $l("#lapTrace"); if (!cv) return;
    fit(cv);
    const g = cv.getContext("2d"), k = dpr(), W = cv.width, H = cv.height;
    g.clearRect(0, 0, W, H);
    const me = viewLap(), ref = refLap(me);
    const [r0, r1] = range(), Lx = GUT * k, Rx = W - 12 * k;
    const X = (p) => Lx + (p - r0) / ((r1 - r0) || 1) * (Rx - Lx);
    const box = {}; let y = 4 * k;
    for (const [n, f] of LANES) { const h = (H - 26 * k) * f; box[n] = [y + 4 * k, y + h - 4 * k]; y += h; }
    // corner bands with names
    g.font = `600 ${9.5 * k}px Inter, sans-serif`; g.textBaseline = "bottom";
    let lastEnd = -1e9;
    for (const s of V.stops) {
      if (s.straight || s.s1 < s.s0 || s.s1 < r0 || s.s0 > r1) continue;
      const xa = Math.max(Lx, X(s.s0)), xb = Math.min(Rx, X(s.s1));
      g.fillStyle = "rgba(255,255,255,.028)"; g.fillRect(xa, 0, xb - xa, H - 18 * k);
      if (xa > lastEnd + 6 * k) { g.fillStyle = "rgba(240,205,126,.7)"; g.fillText(s.name, xa + 3 * k, H - 3 * k); lastEnd = xa + g.measureText(s.name).width + 3 * k; }
    }
    // selection shading
    const sel = V.drag ? [Math.min(V.drag.a, V.drag.b), Math.max(V.drag.a, V.drag.b)] : V.sel;
    if (sel) { g.fillStyle = V.drag ? "rgba(240,205,126,.12)" : "rgba(240,205,126,.06)"; g.fillRect(X(sel[0]), 0, X(sel[1]) - X(sel[0]), H - 18 * k); }
    // lane labels + hairlines
    g.textBaseline = "middle";
    for (const [n] of LANES) {
      const [a, b] = box[n];
      g.font = `600 ${8.5 * k}px Inter, sans-serif`; g.fillStyle = "rgba(142,152,172,.85)"; g.fillText(n, 8 * k, (a + b) / 2);
      g.fillStyle = "rgba(255,255,255,.055)"; g.fillRect(Lx, b + 3.5 * k, Rx - Lx, 1 * k);
    }
    if (!me || me.p.length < 2) { g.font = `500 ${12 * k}px Inter, sans-serif`; g.fillStyle = "rgba(142,152,172,.8)"; g.textAlign = "center"; g.fillText("Telemetry appears as you drive", (Lx + Rx) / 2, H / 2); g.textAlign = "left"; return; }
    const N = Math.max(120, Math.round((Rx - Lx) / k / 1.5));
    const far = reach(me);
    const sample = (lap, key, lim) => { const out = []; for (let i = 0; i <= N; i++) { const p = r0 + (r1 - r0) * i / N; out.push(p > lim ? null : valAt(lap, key, p)); } return out; };
    const draw = (vals, lo, hi, lane, col, w, dash, fill) => {
      const [a, b] = box[lane], Yv = (v) => b - (v - lo) / ((hi - lo) || 1) * (b - a);
      g.beginPath(); let on = false, firstX = 0, lastX = 0;
      for (let i = 0; i <= N; i++) { const v = vals[i]; if (v == null) { on = false; continue; } const px = X(r0 + (r1 - r0) * i / N), py = Yv(v); if (!on) { g.moveTo(px, py); on = true; if (!firstX) firstX = px; } else g.lineTo(px, py); lastX = px; }
      if (fill) { g.lineTo(lastX, b); g.lineTo(firstX, b); g.closePath(); g.fillStyle = fill; g.fill(); return; }
      g.strokeStyle = col; g.lineWidth = w * k; g.setLineDash(dash ? dash.map((x) => x * k) : []); g.stroke(); g.setLineDash([]);
    };
    // Δ lane: time against the reference, from the start of what's on screen
    if (ref) {
      const dl = []; let base = null;
      for (let i = 0; i <= N; i++) { const p = r0 + (r1 - r0) * i / N; const d = p > far ? null : deltaAt(me, ref, p); if (base == null && d != null) base = d; dl.push(d == null ? null : d - (sel ? base : 0)); }
      const mx = Math.max(0.15, ...dl.filter((v) => v != null).map(Math.abs));
      const [a, b] = box["Δ"], mid = (a + b) / 2;
      g.fillStyle = "rgba(255,255,255,.12)"; g.fillRect(Lx, mid, Rx - Lx, 1 * k);
      // filled area: red above (slower), green below (faster)
      g.save(); g.beginPath(); g.rect(Lx, a - 2 * k, Rx - Lx, mid - a + 2 * k); g.clip();
      draw(dl.map((v) => (v == null ? null : Math.max(0, v))), -mx, mx, "Δ", null, 0, null, "rgba(255,77,94,.28)"); g.restore();
      g.save(); g.beginPath(); g.rect(Lx, mid, Rx - Lx, b - mid + 2 * k); g.clip();
      const neg = dl.map((v) => (v == null ? null : Math.min(0, v)));
      { const Yv = (v) => b - (v + mx) / (2 * mx) * (b - a); g.beginPath(); let on = false, fx = 0, lx = 0;
        for (let i = 0; i <= N; i++) { const v = neg[i]; if (v == null) continue; const px = X(r0 + (r1 - r0) * i / N); if (!on) { g.moveTo(px, mid); fx = px; on = true; } g.lineTo(px, Yv(v)); lx = px; }
        if (on) { g.lineTo(lx, mid); g.lineTo(fx, mid); g.closePath(); g.fillStyle = "rgba(52,210,123,.28)"; g.fill(); } }
      g.restore();
      draw(dl, -mx, mx, "Δ", "#F0CD7E", 1.6);
      g.font = `500 ${9 * k}px Timing, Inter, sans-serif`; g.fillStyle = "rgba(142,152,172,.8)"; g.textAlign = "right";
      g.fillText(`+${mx.toFixed(2)}`, Rx - 2 * k, a + 6 * k); g.fillText(`−${mx.toFixed(2)}`, Rx - 2 * k, b - 6 * k); g.textAlign = "left";
    }
    // speed
    const sMe = sample(me, "s", far), sRef = ref ? sample(ref, "s", 2) : [];
    const sv = sMe.concat(sRef).filter((v) => v != null);
    const vlo = sv.length ? Math.min(...sv) - 6 : 0, vhi = sv.length ? Math.max(...sv) + 6 : 300;
    if (ref) draw(sRef, vlo, vhi, "SPEED", "rgba(96,165,250,.9)", 1.4);
    draw(sMe, vlo, vhi, "SPEED", "rgba(245,243,238,.18)", 0, null, null);
    draw(sMe, vlo, vhi, "SPEED", "#F5F3EE", 1.9);
    g.font = `500 ${9 * k}px Timing, Inter, sans-serif`; g.fillStyle = "rgba(142,152,172,.8)"; g.textAlign = "right";
    g.fillText(`${Math.round(vhi)}`, Rx - 2 * k, box.SPEED[0] + 6 * k); g.fillText(`${Math.round(vlo)}`, Rx - 2 * k, box.SPEED[1] - 6 * k); g.textAlign = "left";
    // pedals: throttle green, brake red (reference dashed)
    if (ref) { draw(sample(ref, "th", 2), 0, 1.05, "PEDALS", "rgba(74,222,128,.55)", 1.1, [4, 3]); draw(sample(ref, "br", 2), 0, 1.05, "PEDALS", "rgba(248,113,113,.55)", 1.1, [4, 3]); }
    const thMe = sample(me, "th", far), brMe = sample(me, "br", far);
    draw(brMe, 0, 1.05, "PEDALS", null, 0, null, "rgba(255,77,94,.16)");
    draw(thMe, 0, 1.05, "PEDALS", "#34D27B", 1.7); draw(brMe, 0, 1.05, "PEDALS", "#FF4D5E", 1.7);
    // steering
    const stMe = sample(me, "st", far), stRef = ref ? sample(ref, "st", 2) : [];
    const sm = Math.max(0.15, ...stMe.concat(stRef).filter((v) => v != null).map(Math.abs));
    { const [a, b] = box.STEER; g.fillStyle = "rgba(255,255,255,.08)"; g.fillRect(Lx, (a + b) / 2, Rx - Lx, 1 * k); }
    if (ref) draw(stRef, -sm, sm, "STEER", "rgba(96,165,250,.75)", 1.2);
    draw(stMe, -sm, sm, "STEER", "#F5F3EE", 1.5);
    // gear (steps)
    const grMe = sample(me, "gr", far).map((v) => (v == null ? null : Math.round(v)));
    if (ref) draw(sample(ref, "gr", 2).map((v) => (v == null ? null : Math.round(v))), 0, 8.5, "GEAR", "rgba(96,165,250,.6)", 1.1);
    draw(grMe, 0, 8.5, "GEAR", "#F0CD7E", 1.6);
    // the finger: a line through every lane and a readout
    if (V.hover != null && V.hover >= r0 && V.hover <= r1) {
      const x = X(V.hover), p = V.hover;
      g.strokeStyle = "rgba(240,205,126,.75)"; g.lineWidth = 1 * k; g.beginPath(); g.moveTo(x, 0); g.lineTo(x, H - 18 * k); g.stroke();
      const v = p <= far ? valAt(me, "s", p) : null, vr = ref ? valAt(ref, "s", p) : null, d = ref && p <= far ? deltaAt(me, ref, p) : null;
      const gr = p <= far ? valAt(me, "gr", p) : null, m = metres(p);
      const u = L.met === false ? "mph" : "km/h";
      const parts = [v != null ? `${Math.round(v)} ${u}` : null, vr != null ? `ref ${Math.round(vr)}` : null, gr != null ? `G${Math.round(gr)}` : null, d != null ? `Δ ${fmtD(d)}` : null, m != null ? `${Math.round(m)} m` : null].filter(Boolean);
      const s = parts.join("   ");
      g.font = `600 ${11.5 * k}px Inter, sans-serif`; const w = g.measureText(s).width + 20 * k;
      const bx = Math.max(Lx, Math.min(x + 12 * k, Rx - w)), by = 6 * k;
      g.fillStyle = "rgba(6,8,14,.92)"; rr(g, bx, by, w, 24 * k, 7 * k); g.fill();
      g.strokeStyle = "rgba(240,205,126,.45)"; g.lineWidth = 1 * k; g.stroke();
      g.fillStyle = "#F5F3EE"; g.textBaseline = "middle"; g.fillText(s, bx + 10 * k, by + 12 * k);
    }
  }

  // ------------------------------------------------------------------ corners + sections
  function corners(me, ref) {                        // time by named stop (corners and straights), where both laps cover it
    const far = reach(me), out = [];
    for (const s of V.stops) {
      if (s.s1 < s.s0) continue;                     // a stop across the line: skipped
      const d = s.s1 <= far ? (deltaAt(me, ref, s.s1) ?? 0) - (deltaAt(me, ref, s.s0) ?? 0) : null;
      out.push({ name: s.name, a: s.s0, b: s.s1, d, straight: s.straight });
    }
    return out;
  }
  function metrics(lap, a, b) {                      // brake point, speeds, throttle points inside a section
    const n = 160, far = reach(lap); if (far < a) return null;
    const pts = []; for (let i = 0; i <= n; i++) { const p = a + (b - a) * i / n; if (p > far) break; pts.push({ p, s: valAt(lap, "s", p), th: valAt(lap, "th", p), br: valAt(lap, "br", p) }); }
    if (pts.length < 4) return null;
    const brk = pts.find((q) => q.br > 0.12);
    let mi = 0; for (let i = 1; i < pts.length; i++) if (pts[i].s < pts[mi].s) mi = i;
    const after = pts.slice(mi);
    const thOn = after.find((q) => q.th > 0.2), full = after.find((q) => q.th > 0.95);
    const top = Math.max(...pts.map((q) => q.s));
    return { entry: pts[0].s, apex: pts[mi].s, exit: pts[pts.length - 1].s, top, brake: brk ? brk.p : null, thOn: thOn ? thOn.p : null, full: full ? full.p : null, done: far >= b };
  }
  function renderSect() {
    const body = $l("#lapSect"), head = $l("#lapSectH"); if (!body) return;
    const me = viewLap(), ref = refLap(me), u = L.met === false ? "mph" : "km/h";
    if (!ref) { head.innerHTML = "Time by corner"; body.innerHTML = `<div class="hint">Drive one clean lap and it becomes your reference -<br>every lap after that is compared against it here.</div>`; return; }
    if (!V.sel) {
      head.innerHTML = `Time by corner<span class="meta">vs L${ref.no} · ${fmt(ref.time)}</span>`;
      const rows = corners(me, ref).filter((r) => r.d != null);
      if (!rows.length) { body.innerHTML = `<div class="hint">${V.stops.length ? "Corner times fill in as the lap goes on." : "Corner names come from the broadcast (Grandstand) - drag across the map to study any section."}</div>`; return; }
      rows.sort((x, y) => y.d - x.d);
      const mx = Math.max(0.08, ...rows.map((r) => Math.abs(r.d)));
      body.innerHTML = rows.map((r) => `<div class="cr" data-a="${r.a}" data-b="${r.b}"><span class="n">${esc(r.name)}</span><span class="bar"><i class="${r.d > 0 ? "lose" : "gain"}" style="width:${(Math.abs(r.d) / mx * 50).toFixed(1)}%"></i></span><b class="${r.d > 0.005 ? "lose" : r.d < -0.005 ? "gain" : ""}">${fmtD(r.d)}</b></div>`).join("");
      body.querySelectorAll(".cr").forEach((e) => e.addEventListener("click", () => select(+e.dataset.a, +e.dataset.b)));
      return;
    }
    const [a, b] = V.sel;
    const names = V.stops.filter((s) => s.s1 >= s.s0 && s.s1 > a && s.s0 < b).map((s) => s.name);
    const far = reach(me), done = far >= b;
    const d = done ? (deltaAt(me, ref, b) ?? 0) - (deltaAt(me, ref, a) ?? 0) : null;
    const M = metrics(me, a, b), R = metrics(ref, a, b);
    const m = (p) => (p == null ? "–" : lenM() ? `${Math.round((p - a) * lenM())} m` : `${((p - a) * 100).toFixed(1)}%`);
    const sp = (v) => (v == null ? "–" : `${Math.round(v)}`);
    const cmpCls = (mine, theirs, higherBetter) => (mine == null || theirs == null ? "" : Math.abs(mine - theirs) < (higherBetter == null ? 1e-9 : 2) ? "" : (higherBetter ? mine > theirs : mine < theirs) ? "gain" : "lose");
    head.innerHTML = `Section<span class="meta">${lenM() ? `${Math.round(a * lenM())}–${Math.round(b * lenM())} m` : ""}</span>`;
    let h = `<div class="s-head"><div class="nm">${names.length ? esc(names.join("  →  ")) : "Your section"}</div><div class="d ${d > 0.005 ? "lose" : d < -0.005 ? "gain" : ""}">${done ? fmtD(d) : "…"}</div></div>`;
    if (M && R) {
      h += `<table class="s-t"><tr><th></th><th>You</th><th>Best L${ref.no}</th></tr>
        <tr><td>Brake at</td><td class="${cmpCls(R.brake, M.brake, true)}"><b>${m(M.brake)}</b></td><td><i>${m(R.brake)}</i></td></tr>
        <tr><td>Entry ${u}</td><td class="${cmpCls(M.entry, R.entry, true)}"><b>${sp(M.entry)}</b></td><td><i>${sp(R.entry)}</i></td></tr>
        <tr><td>Apex ${u}</td><td class="${cmpCls(M.apex, R.apex, true)}"><b>${sp(M.apex)}</b></td><td><i>${sp(R.apex)}</i></td></tr>
        <tr><td>Throttle on</td><td class="${cmpCls(M.thOn, R.thOn, false)}"><b>${m(M.thOn)}</b></td><td><i>${m(R.thOn)}</i></td></tr>
        <tr><td>Full throttle</td><td class="${cmpCls(M.full, R.full, false)}"><b>${m(M.full)}</b></td><td><i>${m(R.full)}</i></td></tr>
        <tr><td>Exit ${u}</td><td class="${cmpCls(M.exit, R.exit, true)}"><b>${M.done ? sp(M.exit) : "…"}</b></td><td><i>${sp(R.exit)}</i></td></tr></table>`;
      const tips = [], L0 = lenM();
      const dm = (x, y) => (L0 ? Math.round(Math.abs(x - y) * L0) : null);
      if (M.brake != null && R.brake != null && dm(M.brake, R.brake) >= 8) tips.push(M.brake < R.brake ? `You braked ${dm(M.brake, R.brake)} m earlier than your best - try braking later.` : `You braked ${dm(M.brake, R.brake)} m later than your best${M.apex < R.apex - 2 ? " and lost apex speed - brake a touch earlier, release smoother." : "."}`);
      if (M.apex != null && R.apex != null && R.apex - M.apex >= 3) tips.push(`Carry ${Math.round(R.apex - M.apex)} ${u} more through the slowest point.`);
      if (M.thOn != null && R.thOn != null && dm(M.thOn, R.thOn) >= 10 && M.thOn > R.thOn) tips.push(`Back on the throttle ${dm(M.thOn, R.thOn)} m later than your best - pick it up earlier.`);
      if (M.full != null && R.full != null && dm(M.full, R.full) >= 15 && M.full > R.full) tips.push(`Full throttle ${dm(M.full, R.full)} m later - straighten the exit and commit sooner.`);
      if (M.done && M.exit != null && R.exit != null && R.exit - M.exit >= 4) tips.push(`Exit ${Math.round(R.exit - M.exit)} ${u} slower - that costs you down the next straight.`);
      if (!tips.length && done && d < -0.02) tips.push("Quicker than your best here - remember what you did.");
      if (tips.length) h += `<ul class="tips">${tips.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`;
    } else h += `<div class="hint">Not reached yet on this lap.</div>`;
    body.innerHTML = h;
  }

  // ------------------------------------------------------------------ top bar + list
  function renderTop() {
    const c = L.cur, last = c && c.dl.length ? c.dl[c.dl.length - 1] : null;
    const d = $l("#lapDelta");
    txt(d, fmtD(last)); cls(d, "ld " + (last == null ? "" : last <= 0 ? "gain" : "loss"));
    const now = (typeof T !== "undefined" && T) ? T.cur : null;
    txt($l("#lapNow"), fmt(now));
    txt($l("#lapNo"), (typeof T !== "undefined" && T && T.form) ? "· formation" : String(L.lapNo ?? "–"));
    txt($l("#lapBest"), L.best ? fmt(L.best.time) : "–");
    const me = viewLap();
    for (let k = 0; k < 3; k++) {
      const e = $l("#lapS" + (k + 1)); if (!e) continue;
      const v = me ? split(me, k) : null, b = L.bestSec[k];
      txt(e.querySelector("b"), v ? v.toFixed(3) : "–");
      cls(e, "sec" + (v == null ? "" : b == null || v <= b ? " pb" : " slow"));
    }
    const vb = $l("#lapView");
    if (vb) { cls(vb, "viewing" + (V.lap == null ? "" : " past")); txt($l("#lapViewT"), V.lap == null ? "Live lap" : `Lap ${V.lap} · back to live`); }
    const ref = refLap(me);
    txt($l("#lapTrMeta"), me ? `${V.lap == null ? "Live" : "Lap " + V.lap}${ref ? ` vs L${ref.no}` : ""} · drag to zoom` : "drag across to zoom a section");
    txt($l("#lapMapMeta"), V.sel ? "double-tap to clear" : "tap a corner · drag a section");
  }
  function renderList() {
    const box = $l("#lapList"); if (!box) return;
    const live = `<div class="lr live${V.lap == null ? " view" : ""}" data-no=""><span>LIVE</span><b>${L.cur && L.cur.p.length ? "Lap " + (L.lapNo ?? "") : "–"}</b><i></i><i></i><i></i></div>`;
    const rows = L.laps.map((l) => ({ no: l.no, l })).concat(L.parts.filter((x) => !L.laps.some((l) => l.no === x.no)).map((x) => ({ no: x.no, x })));
    rows.sort((a, b) => (b.no || 0) - (a.no || 0));
    box.innerHTML = live + (rows.map(({ l, x }) => {
      if (x) return `<div class="lr part"><span>L${x.no}</span><b>part</b>` + [0, 1, 2].map((k) => { const v = (x.split || [])[k], ok = (x.ok || [])[k];
        return `<i class="${ok && v && L.bestSec[k] && Math.abs(v - L.bestSec[k]) < 0.0005 ? "pb" : ok ? "" : "dim"}">${isNum(v) && v > 0 ? v.toFixed(2) : "–"}</i>`; }).join("") + `</div>`;
      const b = L.best === l;
      return `<div class="lr${b ? " best" : ""}${V.lap === l.no ? " view" : ""}" data-no="${l.no}"><span>L${l.no}</span><b>${fmt(l.time)}</b>` +
        [0, 1, 2].map((k) => { const v = split(l, k); return `<i class="${v && L.bestSec[k] && Math.abs(v - L.bestSec[k]) < 0.0005 ? "pb" : ""}">${v ? v.toFixed(2) : "–"}</i>`; }).join("") + `</div>`;
    }).join("") || `<div class="lr none">Laps appear here as you complete them</div>`);
    box.querySelectorAll(".lr[data-no]").forEach((e) => e.addEventListener("click", () => { V.lap = e.dataset.no === "" ? null : +e.dataset.no; renderList(); L.dirty = true; if (window.REDRAW_ALL) window.REDRAW_ALL(); }));
  }

  // ------------------------------------------------------------------ touch
  function select(a, b) { V.sel = [Math.max(0, Math.min(a, b)), Math.min(1, Math.max(a, b))]; L.dirty = true; if (window.REDRAW_ALL) window.REDRAW_ALL(); }
  function pctFromMap(e) {
    const cv = $l("#lapMap"); if (!L.xy) return null;
    const r = cv.getBoundingClientRect(), k = cv.width / r.width, px = (e.clientX - r.left) * k, py = (e.clientY - r.top) * k;
    let bi = -1, bd = Infinity;
    for (let i = 0; i < L.xy.length; i++) { const dx = L.xy[i][0] - px, dy = L.xy[i][1] - py, q = dx * dx + dy * dy; if (q < bd) { bd = q; bi = i; } }
    if (bi < 0 || bd > (48 * dpr()) ** 2) return null;
    return MAP.d[bi] / (MAP.len || 1);
  }
  function pctFromTrace(e) {
    const cv = $l("#lapTrace"), r = cv.getBoundingClientRect(), x = e.clientX - r.left;
    const [r0, r1] = range(), L0 = GUT, R0 = r.width - 12;
    return r0 + Math.max(0, Math.min(1, (x - L0) / ((R0 - L0) || 1))) * (r1 - r0);
  }
  function wire(id, toPct) {
    const cv = document.getElementById(id); if (!cv) return;
    cv.addEventListener("pointerdown", (e) => {
      const p = toPct(e); if (p == null) return;
      cv.setPointerCapture(e.pointerId);
      V.drag = { a: p, b: p, id }; V.hover = p; L.dirty = true; if (window.REDRAW_ALL) window.REDRAW_ALL();
      e.preventDefault();
    });
    cv.addEventListener("pointermove", (e) => {
      const p = toPct(e); if (p == null) return;
      V.hover = p; if (V.drag) V.drag.b = p;
      L.dirty = true; if (window.REDRAW_ALL) window.REDRAW_ALL();
    });
    const end = (e) => {
      if (!V.drag) return;
      const { a, b } = V.drag; V.drag = null;
      const now = performance.now();
      if (Math.abs(b - a) < 0.004) {                 // a tap
        if (now - V.lastTap < 320) { V.sel = null; V.hover = null; V.lastTap = 0; }   // double-tap: clear
        else {
          V.lastTap = now;
          const s = V.stops.find((q) => q.s1 >= q.s0 && a >= q.s0 - 0.004 && a <= q.s1 + 0.004 && !q.straight) || V.stops.find((q) => q.s1 >= q.s0 && a >= q.s0 && a <= q.s1);
          if (s) select(s.s0, s.s1);
        }
      } else select(a, b);
      L.dirty = true; if (window.REDRAW_ALL) window.REDRAW_ALL();
    };
    cv.addEventListener("pointerup", end); cv.addEventListener("pointercancel", end);
  }

  // ------------------------------------------------------------------ frame
  function draw() {
    if (!isOn()) return false;
    if (!L.dirty && !L.dirtyTop) return false;
    const full = L.dirty; L.dirty = false; L.dirtyTop = false;
    try { renderTop(); if (full) { drawMap(); drawTrace(); renderSect(); } } catch (e) { console.warn("lap draw", e); }
    return false;
  }
  function toggle(on) {
    document.body.classList.toggle("lapmode", on ?? !isOn());
    renderList();
    L.dirty = true;
    if (window.REDRAW_ALL) window.REDRAW_ALL();
  }
  function gap() { if (L.cur) L.cur.clean = false; L.dirty = true; }
  function setStops(arr) {
    V.stops = (Array.isArray(arr) ? arr : []).filter((s) => s && s.name && isNum(s.s0) && isNum(s.s1));
    L.dirty = true;
  }
  // the PC keeps every lap (lap_store.py) and sends them when the page connects
  function load(d) {
    if (!d || !Array.isArray(d.laps)) return;
    const mk = (l) => Object.assign(newLap(l.no), l, { dl: l.dl || [], st: l.st || [], gr: l.gr || [] });
    L.laps = d.laps.map(mk);
    L.parts = Array.isArray(d.parts) ? d.parts.filter((x) => x && x.no != null) : [];
    L.best = L.laps.find((l) => l.no === d.best_no) || L.laps.reduce((b, l) => (l.time && (!b || l.time < b.time) ? l : b), null);
    L.bestSec = bestSecs();
    if (d.cur && d.lap_no != null && (L.lapNo == null || L.lapNo === d.lap_no) && (!L.cur || (d.cur.p || []).length > L.cur.p.length)) {
      const c = mk(d.cur); c.start = d.cur.start ?? (c.p.length ? c.p[0] : null);
      c.dl = c.p.map((p, i) => { const r = L.best ? timeAt(L.best, p) : null; return r != null ? c.t[i] - r : null; });
      L.cur = c; L.lapNo = d.lap_no;
    }
    if (typeof d.met === "boolean") L.met = d.met;
    if (V.lap != null && !L.laps.some((l) => l.no === V.lap)) V.lap = null;
    L.dirty = true; renderList();
    if (window.REDRAW_ALL) window.REDRAW_ALL();
  }
  // the iPad keeps its own copy too (IndexedDB) so a reload shows the laps at once
  const IDB = { db: null, key: null, t: 0 };
  function idb(cb) {
    if (IDB.db) return cb(IDB.db);
    try {
      const r = indexedDB.open("re_laps", 1);
      r.onupgradeneeded = () => r.result.createObjectStore("s");
      r.onsuccess = () => { IDB.db = r.result; cb(IDB.db); };
    } catch (e) {}
  }
  function cacheSave(force) {
    const now = Date.now();
    if (!force && now - IDB.t < 10000) return;
    IDB.t = now;
    const rec = { key: IDB.key, laps: L.laps.map((l) => Object.assign({}, l, { dl: undefined })), best_no: L.best ? L.best.no : null, met: L.met, saved: now };
    idb((db) => { try { const tx = db.transaction("s", "readwrite"); tx.objectStore("s").put(rec, "last"); if (IDB.key) tx.objectStore("s").put(rec, "k:" + IDB.key); } catch (e) {} });
  }
  let gotPc = false;
  const load0 = load;
  function loadPc(d) { gotPc = true; if (d && d.key) IDB.key = d.key; load0(d); cacheSave(true); }
  setTimeout(() => {
    if (gotPc) return;
    idb((db) => { try { const r = db.transaction("s").objectStore("s").get("last"); r.onsuccess = () => { if (!gotPc && r.result && r.result.laps && r.result.laps.length) { IDB.key = r.result.key; load0(Object.assign({}, r.result, { cur: null })); } }; } catch (e) {} });
  }, 1500);
  function feedC(t) { const n = L.laps.length; feed(t); if (L.laps.length !== n) { cacheSave(true); renderList(); } }
  function setParts(d) {
    if (!d || !Array.isArray(d.parts)) return;
    L.parts = d.parts.filter((x) => x && x.no != null);
    L.bestSec = bestSecs(); renderList(); L.dirty = true;
  }
  window.LAP = { feed: feedC, draw, toggle, gap, load: loadPc, stops: setStops, parts: setParts, _L: L, _V: V };
  for (const id of ["lapMap", "lapTrace"]) { const c = document.getElementById(id); if (c) RO.observe(c); }
  wire("lapMap", pctFromMap); wire("lapTrace", pctFromTrace);
  const btn = document.getElementById("lapBtn"); if (btn) btn.addEventListener("click", () => toggle());
  const back = document.getElementById("lapBack"); if (back) back.addEventListener("click", () => toggle(false));
  const vb = document.getElementById("lapView"); if (vb) vb.addEventListener("click", () => { V.lap = null; renderList(); L.dirty = true; if (window.REDRAW_ALL) window.REDRAW_ALL(); });
  renderList();
  const pend = window.LAP_PENDING; window.LAP_PENDING = null;          // anything that arrived before this file loaded
  if (pend) { if (pend.stops) setStops(pend.stops); if (pend.laps) loadPc(pend.laps); }
})();
