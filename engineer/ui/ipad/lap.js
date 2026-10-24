/* Live lap analysis on the iPad (2026-10-24, Angelo: "watch and track the lap analysis as I drive").
   Everything is built here from the 10-per-second feed the iPad already gets: every lap is recorded
   (distance, speed, throttle, brake, time), the best clean lap becomes the reference, and the current
   lap draws over it live - speed trace, pedals, a track map coloured where you gain (green) or lose
   (red), the live delta and F1-style sector times. Nothing new is needed on the PC side.
   Performance: draws only when a new sample arrived (never per frame), the track outline / grid / reference
   lap are cached in offscreen canvases, and the coloured lap line is drawn incrementally (only new segments). */
(() => {
  const SECS = [1 / 3, 2 / 3];
  const MAX_PTS = 8000;                              // hard cap per lap (a 10-minute lap at 10 Hz is 6000)
  const L = { cur: null, laps: [], best: null, lapNo: null, xy: null, pts: null, dirty: true, lastFeed: 0, bestSec: [null, null, null],
              mapLayer: null, lapDrawn: 0, lapOf: null, traceBg: null, traceKey: "" };
  const newLap = (no) => ({ no, p: [], s: [], th: [], br: [], t: [], dl: [], sec: [null, null, null], clean: true, start: null });
  const isNum = (x) => typeof x === "number" && isFinite(x);
  const fmt = (t) => { if (!isNum(t) || !(t > 0)) return "–"; const m = Math.floor(t / 60), s = t - m * 60; return m ? `${m}:${s.toFixed(3).padStart(6, "0")}` : s.toFixed(3); };
  const fmtD = (d) => (!isNum(d) ? "–" : (d > 0 ? "+" : d < 0 ? "−" : "±") + Math.abs(d).toFixed(2));
  const $l = (s) => document.querySelector(s);
  const dpr = () => Math.min(2, window.devicePixelRatio || 1);
  const txt = (e, v) => { if (e && e._t !== v) { e._t = v; e.textContent = v; } };
  const cls = (e, v) => { if (e && e._k !== v) { e._k = v; e.className = v; } };
  const isOn = () => document.body.classList.contains("lapmode");

  function timeAt(lap, pct) {                       // interpolated lap time at a distance (reference lap)
    const P = lap.p; if (!P.length) return null;
    let lo = 0, hi = P.length - 1;
    if (pct <= P[0]) return lap.t[0]; if (pct >= P[hi]) return lap.t[hi];
    while (hi - lo > 1) { const m = (lo + hi) >> 1; if (P[m] < pct) lo = m; else hi = m; }
    const f = (pct - P[lo]) / ((P[hi] - P[lo]) || 1);
    return lap.t[lo] + (lap.t[hi] - lap.t[lo]) * f;
  }

  function feed(t) {
    if (!t || t.err) return;
    const now = performance.now();
    const gapped = L.lastFeed && now - L.lastFeed > 2500;   // the feed dropped out: this lap can't be a reference
    L.lastFeed = now;
    if (L.lapNo !== t.lap) {                         // a new lap started
      const done = L.cur;
      if (done && t.last > 0 && done.clean && done.start != null && done.start < 0.06 && done.p.length > 50
          && done.p[done.p.length - 1] > 0.94) {
        done.time = t.last;
        if (done.sec[0] && done.sec[1]) done.sec[2] = t.last - done.sec[1];
        L.laps.unshift(done); if (L.laps.length > 12) L.laps.pop();
        if (!L.best || done.time < L.best.time) L.best = done;
        L.bestSec = [0, 1, 2].map((k) => { let b = null; for (const l of L.laps) { const v = split(l, k); if (v && (b == null || v < b)) b = v; } return b; });
        renderList();
      }
      L.cur = newLap(t.lap); L.lapNo = t.lap; L.dirty = true;
    }
    const c = L.cur, pct = t.pct;
    if (t.pit || !t.on || gapped) c.clean = false;
    if (!isNum(pct) || !isNum(t.cur)) return;
    if (c.start == null) c.start = pct;
    const lastP = c.p.length ? c.p[c.p.length - 1] : -1;
    if (pct < lastP - 0.5) return;                   // still the end of the previous lap
    if (pct <= lastP || c.p.length >= MAX_PTS) return;
    // sector crossings (time at the line, interpolated)
    for (let k = 0; k < 2; k++) if (!c.sec[k] && lastP >= 0 && lastP < SECS[k] && pct >= SECS[k]) {
      const tl = c.t[c.t.length - 1], f = (SECS[k] - lastP) / ((pct - lastP) || 1);
      const at = tl + (t.cur - tl) * f;
      c.sec[k] = k === 0 ? at : at - c.sec[0];
      if (k === 1) c.sec[1] = at;                    // store cumulative for S2; split shown as difference
    }
    c.p.push(pct); c.s.push(isNum(t.spd) ? t.spd : 0); c.th.push(isNum(t.thr) ? t.thr : 0); c.br.push(isNum(t.brk) ? t.brk : 0); c.t.push(t.cur);
    const ref = L.best ? timeAt(L.best, pct) : null;
    c.dl.push(ref != null ? t.cur - ref : (isNum(t.delta) ? t.delta : null));
    L.met = t.met;
    L.dirty = true;
  }

  // ------------------------------------------------------------------ drawing
  function project(cv) {
    L.mapLayer = null; L.lapDrawn = 0;
    if (!(typeof MAP !== "undefined" && MAP) || !MAP.pts) { L.xy = null; L.pts = null; return; }
    const k = dpr(), pts = MAP.pts;
    let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
    for (const [x, y] of pts) { x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y); }
    const pad = 26 * k;
    const sc = Math.min((cv.width - 2 * pad) / (x1 - x0 || 1), (cv.height - 2 * pad) / (y1 - y0 || 1));
    const ox = (cv.width - (x1 - x0) * sc) / 2, oy = (cv.height - (y1 - y0) * sc) / 2;
    L.xy = pts.map(([x, y]) => [ox + (x - x0) * sc, cv.height - (oy + (y - y0) * sc)]);
    L.pts = pts;
  }
  function pt(pct) {
    const D = MAP.d, len = MAP.len, d = ((pct % 1) + 1) % 1 * len;
    let lo = 0, hi = D.length - 1;
    while (lo < hi) { const m = (lo + hi) >> 1; if (D[m] < d) lo = m + 1; else hi = m; }
    const i = Math.max(1, lo), a = L.xy[i - 1], b = L.xy[i % L.xy.length], f = Math.max(0, Math.min(1, (d - D[i - 1]) / ((D[i] - D[i - 1]) || 1)));
    return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f];
  }
  // canvas sizes come from a ResizeObserver: no layout reads while drawing
  const SIZE = new Map();
  function fit(cv) {
    const r = SIZE.get(cv); if (!r) return false;
    const k = dpr(), w = Math.max(10, Math.round(r[0] * k)), h = Math.max(10, Math.round(r[1] * k));
    if (cv.width !== w || cv.height !== h) { cv.width = w; cv.height = h; return true; }
    return false;
  }
  const RO = new ResizeObserver((es) => { for (const e of es) SIZE.set(e.target, [e.contentRect.width, e.contentRect.height]); L.dirty = true; if (isOn() && window.REDRAW_ALL) window.REDRAW_ALL(); });
  const offscreen = (w, h) => { const c = document.createElement("canvas"); c.width = w; c.height = h; return c; };

  function drawMap() {
    const cv = $l("#lapMap"); if (!cv) return;
    if (fit(cv) || L.pts !== ((typeof MAP !== "undefined" && MAP) && MAP.pts)) project(cv);
    const g = cv.getContext("2d"), k = dpr(), W = cv.width, H = cv.height;
    const dot = $l("#lapDot");
    const c = L.cur;
    // full repaint only on a new lap / resize / new track; otherwise just the new segments are added to the canvas
    const full = !L.mapLayer || L.lapOf !== c || !c || c.p.length < L.lapDrawn;
    if (full) { g.clearRect(0, 0, W, H); L.lapOf = c; L.lapDrawn = 1; }
    if (!L.xy) { if (dot) dot.classList.remove("on"); return; }
    if (!L.mapLayer) {                               // track outline + sector marks: drawn once
      const m = (L.mapLayer = offscreen(W, H)), mg = m.getContext("2d"), P = L.xy;
      mg.lineCap = "round"; mg.lineJoin = "round";
      mg.beginPath(); mg.moveTo(P[0][0], P[0][1]); for (const p of P) mg.lineTo(p[0], p[1]); mg.closePath();
      mg.strokeStyle = "rgba(0,0,0,.55)"; mg.lineWidth = 15 * k; mg.stroke();
      mg.strokeStyle = "rgba(229,231,235,.22)"; mg.lineWidth = 7 * k; mg.stroke();
      for (const s of SECS) { const [x, y] = pt(s); mg.fillStyle = "rgba(255,216,118,.8)"; mg.beginPath(); mg.arc(x, y, 4 * k, 0, 7); mg.fill(); }
    }
    if (full) g.drawImage(L.mapLayer, 0, 0);
    if (!c || c.p.length < 2) { if (dot) dot.classList.remove("on"); return; }
    // this lap so far, coloured by gain (green) / loss (red) against the best lap
    const lg = g;
    lg.lineCap = "round"; lg.lineJoin = "round"; lg.lineWidth = 7 * k;
    let col = null, open = false;
    for (let i = L.lapDrawn; i < c.p.length; i++) {
      const d0 = c.dl[i - 1], d1 = c.dl[i];
      let cc = "rgba(255,216,118,.95)";
      if (d0 != null && d1 != null) { const dd = d1 - d0; cc = dd < -0.002 ? "#22C55E" : dd > 0.002 ? "#EF4444" : "rgba(229,231,235,.9)"; }
      const a = pt(c.p[i - 1]), b = pt(c.p[i]);
      if (cc !== col) { if (open) lg.stroke(); lg.strokeStyle = col = cc; lg.beginPath(); lg.moveTo(a[0], a[1]); open = true; }
      lg.lineTo(b[0], b[1]);
    }
    if (open) lg.stroke();
    L.lapDrawn = c.p.length;
    // the car is a DOM marker moved with a transform (so the canvas never has to be erased under it)
    if (dot) { const [x, y] = pt(c.p[c.p.length - 1]); dot.style.transform = `translate3d(${(x / k).toFixed(1)}px, ${(y / k).toFixed(1)}px, 0)`; dot.classList.add("on"); }
  }

  function drawTrace() {
    const cv = $l("#lapTrace"); if (!cv) return;
    fit(cv);
    const g = cv.getContext("2d"), k = dpr(), W = cv.width, H = cv.height;
    const top = 10 * k, sH = H * 0.58, pH = H * 0.16, gap = 12 * k;
    const sY0 = top, thY0 = top + sH + gap, brY0 = thY0 + pH + gap * 0.6;
    let vmax = 1; for (const l of [L.best, L.cur]) if (l) for (const v of l.s) if (v > vmax) vmax = v;
    vmax = Math.ceil(vmax / 20) * 20;
    const line = (gg, lap, arr, y0, h, max, col, w, fill) => {
      if (!lap || lap.p.length < 2) return;
      gg.beginPath();
      for (let i = 0; i < lap.p.length; i++) { const x = lap.p[i] * W, y = y0 + h - (arr[i] / max) * h; i ? gg.lineTo(x, y) : gg.moveTo(x, y); }
      if (fill) { gg.lineTo(lap.p[lap.p.length - 1] * W, y0 + h); gg.lineTo(lap.p[0] * W, y0 + h); gg.closePath(); gg.fillStyle = fill; gg.fill(); }
      else { gg.strokeStyle = col; gg.lineWidth = w * k; gg.stroke(); }
    };
    // background (grid, sector lines, labels, the reference lap) is cached until the best lap / scale / size changes
    const key = [W, H, vmax, L.met, L.best ? L.best.no + ":" + L.best.time : ""].join("|");
    if (L.traceKey !== key || !L.traceBg) {
      L.traceKey = key;
      const bg = (L.traceBg = offscreen(W, H)), b = bg.getContext("2d");
      b.strokeStyle = "rgba(255,255,255,.06)"; b.lineWidth = 1 * k;
      for (let i = 1; i < 4; i++) { const y = sY0 + sH * i / 4; b.beginPath(); b.moveTo(0, y); b.lineTo(W, y); b.stroke(); }
      b.strokeStyle = "rgba(255,216,118,.25)"; b.setLineDash([4 * k, 6 * k]);
      for (const s of SECS) { b.beginPath(); b.moveTo(W * s, 0); b.lineTo(W * s, H); b.stroke(); }
      b.setLineDash([]);
      line(b, L.best, L.best ? L.best.s : [], sY0, sH, vmax, "rgba(156,163,175,.75)", 2);
      line(b, L.best, L.best ? L.best.th : [], thY0, pH, 1, "rgba(34,197,94,.35)", 1.5);
      line(b, L.best, L.best ? L.best.br : [], brY0, pH, 1, "rgba(239,68,68,.35)", 1.5);
      b.font = `700 ${11 * k}px Inter, sans-serif`; b.fillStyle = "rgba(156,163,175,.9)";
      b.fillText(`${vmax} ${L.met === false ? "MPH" : "KM/H"}`, 6 * k, sY0 + 12 * k);
      b.fillText("THROTTLE", 6 * k, thY0 + 11 * k); b.fillText("BRAKE", 6 * k, brY0 + 11 * k);
    }
    g.clearRect(0, 0, W, H);
    g.drawImage(L.traceBg, 0, 0);
    g.lineJoin = "round";
    line(g, L.cur, L.cur ? L.cur.s : [], sY0, sH, vmax, "#FFD876", 2.6);
    line(g, L.cur, L.cur ? L.cur.th : [], thY0, pH, 1, null, 0, "rgba(34,197,94,.55)");
    line(g, L.cur, L.cur ? L.cur.br : [], brY0, pH, 1, null, 0, "rgba(239,68,68,.6)");
  }

  function renderTop() {
    const c = L.cur, last = c && c.dl.length ? c.dl[c.dl.length - 1] : null;
    const d = $l("#lapDelta");
    txt(d, fmtD(last)); cls(d, "ld " + (last == null ? "" : last <= 0 ? "gain" : "loss"));
    const now = (typeof T !== "undefined" && T) ? T.cur : null;
    txt($l("#lapNow"), fmt(now));
    txt($l("#lapNo"), String(L.lapNo ?? "–"));
    txt($l("#lapBest"), L.best ? fmt(L.best.time) : "–");
    // sector chips: green = your best for that sector, yellow = slower
    for (let k = 0; k < 3; k++) {
      const e = $l("#lapS" + (k + 1)); if (!e) continue;
      const v = c ? split(c, k) : null, b = L.bestSec[k];
      txt(e.querySelector("b"), v ? v.toFixed(3) : "–");
      cls(e, "sec" + (v == null ? "" : b == null || v <= b ? " pb" : " slow"));
    }
  }
  const split = (l, k) => (k === 0 ? l.sec[0] : k === 1 ? (l.sec[1] && l.sec[0] ? l.sec[1] - l.sec[0] : null) : l.sec[2]);

  function renderList() {
    const box = $l("#lapList"); if (!box) return;
    box.innerHTML = L.laps.map((l) => {
      const b = L.best === l;
      return `<div class="lr${b ? " best" : ""}"><span>L${l.no}</span><b>${fmt(l.time)}</b>` +
        [0, 1, 2].map((k) => `<i>${split(l, k) ? split(l, k).toFixed(2) : "–"}</i>`).join("") + `</div>`;
    }).join("") || `<div class="lr none">Laps appear here as you complete them</div>`;
  }

  // called from the page's frame; draws only when there's something new. Never asks for more frames.
  function draw() {
    if (!isOn() || !L.dirty) return false;
    L.dirty = false;
    try { renderTop(); drawMap(); drawTrace(); } catch (e) { console.warn("lap draw", e); }
    return false;
  }
  function toggle(on) {
    document.body.classList.toggle("lapmode", on ?? !isOn());
    renderList();
    L.dirty = true;
    if (window.REDRAW_ALL) window.REDRAW_ALL();
  }
  function gap() { if (L.cur) L.cur.clean = false; L.dirty = true; }
  window.LAP = { feed, draw, toggle, gap };
  for (const id of ["lapMap", "lapTrace"]) { const c = document.getElementById(id); if (c) RO.observe(c); }
  const btn = document.getElementById("lapBtn"); if (btn) btn.addEventListener("click", () => toggle());
  const back = document.getElementById("lapBack"); if (back) back.addEventListener("click", () => toggle(false));
  renderList();
})();
