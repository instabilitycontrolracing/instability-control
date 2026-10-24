/* Lap analysis tab: track map from GPS coloured by time gained/lost, linked traces, drag to analyse a section. */
"use strict";

const AN = { sessions: [], cur: null, cmp: null, sel: null, hover: null, drag: null, mapPts: null, busy: false, ready: false };
const fmtLap = (t) => { if (t == null) return "-"; const m = Math.floor(t / 60), s = t - m * 60; return `${m}:${s.toFixed(3).padStart(6, "0")}`; };
const fmtD = (x) => (x > 0 ? "+" : x < 0 ? "−" : "") + Math.abs(x).toFixed(2) + " s";

function anEl(id) { return document.getElementById(id); }

async function anInit() {
  if (AN.ready) { anResize(); return; }
  AN.ready = true;
  anEl("anSess").addEventListener("change", () => anOpen(anEl("anSess").value));
  anEl("anLap").addEventListener("change", anCompare);
  anEl("anRef").addEventListener("change", anCompare);
  const map = anEl("anMap"), tr = anEl("anTrace");
  map.addEventListener("mousemove", (e) => anPointer(e, "map"));
  map.addEventListener("mouseleave", () => { AN.hover = null; anDraw(); });
  map.addEventListener("mousedown", (e) => anDragStart(e, "map"));
  tr.addEventListener("mousemove", (e) => anPointer(e, "trace"));
  tr.addEventListener("mouseleave", () => { AN.hover = null; anDraw(); });
  tr.addEventListener("mousedown", (e) => anDragStart(e, "trace"));
  window.addEventListener("mouseup", anDragEnd);
  window.addEventListener("resize", anResize);
  anEl("anClear").addEventListener("click", () => { AN.sel = null; anSide(); anDraw(); });
  await anLoadSessions();
}

async function anLoadSessions() {
  anStatus("Loading…");
  let list = [];
  try { list = await api.an_sessions(); } catch (e) {}
  AN.sessions = list || [];
  const s = anEl("anSess"); s.innerHTML = "";
  for (const x of AN.sessions) { const o = document.createElement("option"); o.value = x.id; o.textContent = x.label; s.appendChild(o); }
  if (!AN.sessions.length) { anStatus("No telemetry yet"); return; }
  await anOpen(AN.sessions[0].id);
}

function anStatus(t) { anEl("anInfo").textContent = t || ""; }

async function anOpen(id) {
  anStatus("Reading…");
  AN.busy = true;
  let r = null;
  try { r = await api.an_open(id); } catch (e) { r = { error: String(e) }; }
  AN.busy = false;
  if (!r || r.error) { anStatus(r && r.error ? r.error : "Can't read session"); return; }
  AN.cur = r; AN.sel = null;
  anTheme(r.theme);
  const lap = anEl("anLap"); lap.innerHTML = "";
  for (const L of r.laps) {
    const o = document.createElement("option"); o.value = L.n;
    o.textContent = `Lap ${L.n}  ·  ${fmtLap(L.time)}${L.valid ? "" : L.pit ? "  (pit)" : !L.complete ? "  (partial)" : "  (incident)"}`;
    if (!L.complete) o.disabled = true;
    lap.appendChild(o);
  }
  const usable = r.laps.filter((L) => L.complete);
  // default: the slowest clean lap vs your best, so there is something to learn from; else the best
  const others = usable.filter((L) => L.n !== r.best_n);
  lap.value = others.length ? others[others.length - 1].n : r.best_n;
  const ref = anEl("anRef"); ref.innerHTML = "";
  for (const x of r.refs) { const o = document.createElement("option"); o.value = x.key; o.textContent = x.label; ref.appendChild(o); }
  prepMap(); anResize();
  await anCompare();
}

async function anCompare() {
  if (!AN.cur) return;
  anStatus("Comparing…");
  let r = null;
  try { r = await api.an_compare(+anEl("anLap").value, anEl("anRef").value); } catch (e) {}
  if (!r || r.error) { anStatus((r && r.error) || "Can't compare"); return; }
  AN.cmp = r;
  anStatus("");
  if (AN.sel) await anSection(AN.sel[0], AN.sel[1]); else anSide();
  anDraw();
}

/* ---------------- geometry ---------------- */
function prepMap() {
  // rotate the track so its longest direction runs across the (wide) panel
  const m = AN.cur.map, n = m.x.length;
  const mx = m.x.reduce((a, b) => a + b, 0) / n, my = m.y.reduce((a, b) => a + b, 0) / n;
  let sxx = 0, syy = 0, sxy = 0;
  for (let i = 0; i < n; i++) { const dx = m.x[i] - mx, dy = m.y[i] - my; sxx += dx * dx; syy += dy * dy; sxy += dx * dy; }
  const ang = 0.5 * Math.atan2(2 * sxy, sxx - syy), c = Math.cos(-ang), s = Math.sin(-ang);
  const pts = [];
  for (let i = 0; i < n; i++) { const dx = m.x[i] - mx, dy = m.y[i] - my; pts.push({ x: dx * c - dy * s, y: dx * s + dy * c, d: m.d[i] }); }
  AN.mapPts = pts;
}

function anResize() {
  for (const id of ["anMap", "anTrace"]) {
    const c = anEl(id), r = c.getBoundingClientRect(), k = window.devicePixelRatio || 1;
    c.width = Math.max(10, r.width * k); c.height = Math.max(10, r.height * k);
  }
  anDraw();
}

function mapXf() {
  const c = anEl("anMap"), k = window.devicePixelRatio || 1, W = c.width, H = c.height, pad = 34 * k;
  const top = AN.cur && AN.cur.theme && AN.cur.theme.logo ? 86 * k : pad;      // room for the track logo
  const xs = AN.mapPts.map((p) => p.x), ys = AN.mapPts.map((p) => p.y);
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  const s = Math.min((W - 2 * pad) / (x1 - x0 || 1), (H - pad - top) / (y1 - y0 || 1));
  const ox = (W - (x1 - x0) * s) / 2, oy = pad + (H - pad - top - (y1 - y0) * s) / 2;
  return { k, s, X: (x) => ox + (x - x0) * s, Y: (y) => H - (oy + (y - y0) * s) };
}

function dToIdx(arr, d) { let lo = 0, hi = arr.length - 1; while (lo < hi) { const m = (lo + hi) >> 1; if (arr[m] < d) lo = m + 1; else hi = m; } return lo; }

function rateAt(d) { const c = AN.cmp; if (!c) return 0; return c.rate[dToIdx(c.d, d)] || 0; }

function lossColor(rate, a = 1) {
  // ms lost per metre: green = gaining, red = losing
  const x = Math.max(-1, Math.min(1, rate / 2.2));
  if (x >= 0) { const t = x; return `rgba(${Math.round(110 + 129 * t)},${Math.round(118 - 50 * t)},${Math.round(128 - 60 * t)},${a})`; }
  const t = -x; return `rgba(${Math.round(110 - 76 * t)},${Math.round(118 + 79 * t)},${Math.round(128 - 34 * t)},${a})`;
}

/* ---------------- drawing ---------------- */
function anDraw() {
  if (!AN.cur || !AN.mapPts) return;
  drawMap(); drawTraces();
}

function drawMap() {
  const c = anEl("anMap"), g = c.getContext("2d"), { k, X, Y } = mapXf(), P = AN.mapPts;
  g.clearRect(0, 0, c.width, c.height);
  g.lineCap = "round"; g.lineJoin = "round";
  // under-glow
  g.strokeStyle = "rgba(0,0,0,.55)"; g.lineWidth = 14 * k; g.beginPath();
  P.forEach((p, i) => (i ? g.lineTo(X(p.x), Y(p.y)) : g.moveTo(X(p.x), Y(p.y)))); g.closePath(); g.stroke();
  // coloured by time gained/lost
  g.lineWidth = 6.5 * k;
  for (let i = 1; i < P.length; i++) {
    g.strokeStyle = lossColor(rateAt(P[i].d));
    g.beginPath(); g.moveTo(X(P[i - 1].x), Y(P[i - 1].y)); g.lineTo(X(P[i].x), Y(P[i].y)); g.stroke();
  }
  // selection
  if (AN.sel || AN.drag) {
    const [a, b] = AN.drag ? [Math.min(AN.drag.d0, AN.drag.d1), Math.max(AN.drag.d0, AN.drag.d1)] : AN.sel;
    g.strokeStyle = tc(1, .95); g.lineWidth = 11 * k; g.shadowColor = tc(1, .6); g.shadowBlur = 14 * k;
    g.beginPath(); let started = false;
    for (const p of P) { if (p.d < a || p.d > b) continue; if (!started) { g.moveTo(X(p.x), Y(p.y)); started = true; } else g.lineTo(X(p.x), Y(p.y)); }
    g.stroke(); g.shadowBlur = 0;
    g.lineWidth = 5 * k;
    for (let i = 1; i < P.length; i++) { if (P[i].d < a || P[i].d > b) continue; g.strokeStyle = lossColor(rateAt(P[i].d)); g.beginPath(); g.moveTo(X(P[i - 1].x), Y(P[i - 1].y)); g.lineTo(X(P[i].x), Y(P[i].y)); g.stroke(); }
  }
  // start/finish
  const s0 = P[0];
  g.fillStyle = "#FCFAF5"; g.beginPath(); g.arc(X(s0.x), Y(s0.y), 4.5 * k, 0, 7); g.fill();
  // corner labels (placed so they don't overlap each other)
  g.font = `600 ${11 * k}px Inter`; g.textBaseline = "middle";
  const rows = AN.cmp ? AN.cmp.corners : [];
  const ds = P.map((q) => q.d), placed = [];
  const hit = (b) => placed.some((o) => !(b.x + b.w < o.x || o.x + o.w < b.x || b.y + b.h < o.y || o.y + o.h < b.y));
  const order = [...rows].sort((a, b) => Math.abs(b.lost) - Math.abs(a.lost));
  for (const cr of order) {
    const p = P[dToIdx(ds, cr.me.apex_d || (cr.start + cr.end) / 2)]; if (!p) continue;
    const x = X(p.x), y = Y(p.y), lost = cr.lost;
    g.fillStyle = lost > 0.08 ? "#F87171" : lost < -0.05 ? "#4ADE80" : "#C9CED6";
    g.beginPath(); g.arc(x, y, 3.2 * k, 0, 7); g.fill();
    const label = `${cr.name}  ${lost > 0 ? "+" : ""}${lost.toFixed(2)}`;
    const w = g.measureText(label).width + 12 * k, h = 20 * k;
    const tries = [[8, -10], [-8 - w / k, -10], [-w / 2 / k, -30], [-w / 2 / k, 10], [8, -32], [8, 12], [-8 - w / k, -32], [-8 - w / k, 12]];
    let box = null;
    for (const [ox, oy] of tries) { const b = { x: x + ox * k, y: y + oy * k, w, h }; if (!hit(b) && b.x > 0 && b.x + w < c.width && b.y > 0 && b.y + h < c.height) { box = b; break; } }
    if (!box) continue;
    placed.push(box);
    g.fillStyle = "rgba(8,10,16,.8)"; roundRect(g, box.x, box.y, w, h, 6 * k); g.fill();
    g.fillStyle = "#E5E7EB"; g.fillText(label, box.x + 6 * k, box.y + h / 2 + 0.5 * k);
  }
  // driver's radio notes
  for (const n of (AN.cur.notes || [])) {
    if (n.dist == null) continue;
    const p = P[dToIdx(ds, n.dist)]; if (!p) continue;
    const x = X(p.x), y = Y(p.y);
    g.save(); g.translate(x, y); g.rotate(Math.PI / 4);
    g.fillStyle = "#A78BFA"; g.strokeStyle = "#0B0F18"; g.lineWidth = 2 * k;
    g.fillRect(-5 * k, -5 * k, 10 * k, 10 * k); g.strokeRect(-5 * k, -5 * k, 10 * k, 10 * k); g.restore();
  }
  // hover
  if (AN.hover != null) {
    const p = P[dToIdx(P.map((q) => q.d), AN.hover)];
    g.fillStyle = tc(1, 1); g.strokeStyle = "#120E05"; g.lineWidth = 2 * k;
    g.beginPath(); g.arc(X(p.x), Y(p.y), 6 * k, 0, 7); g.fill(); g.stroke();
  }
}

function roundRect(g, x, y, w, h, r) { g.beginPath(); g.moveTo(x + r, y); g.arcTo(x + w, y, x + w, y + h, r); g.arcTo(x + w, y + h, x, y + h, r); g.arcTo(x, y + h, x, y, r); g.arcTo(x, y, x + w, y, r); g.closePath(); }

function traceRange() {
  const c = AN.cmp, D = c.d[c.d.length - 1];
  if (AN.sel) { const span = AN.sel[1] - AN.sel[0], pad = Math.max(60, span * 0.25); return [Math.max(0, AN.sel[0] - pad), Math.min(D, AN.sel[1] + pad)]; }
  return [0, D];
}

function drawTraces() {
  const c = anEl("anTrace"), g = c.getContext("2d"), k = window.devicePixelRatio || 1, W = c.width, H = c.height;
  g.clearRect(0, 0, W, H);
  const cm = AN.cmp; if (!cm) return;
  const [d0, d1] = traceRange(), L = 54 * k, R = W - 14 * k;
  const X = (d) => L + (d - d0) / (d1 - d0) * (R - L);
  const lanes = [["Δ", .16], ["km/h", .38], ["pedals", .26], ["steer", .20]];
  let y = 6 * k; const box = {};
  for (const [n, f] of lanes) { const h = (H - 12 * k) * f; box[n] = [y, y + h - 6 * k]; y += h; }
  const i0 = Math.max(0, dToIdx(cm.d, d0) - 1), i1 = Math.min(cm.d.length - 1, dToIdx(cm.d, d1) + 1);
  // selection shading
  if (AN.sel) { g.fillStyle = tc(1, .07); g.fillRect(X(AN.sel[0]), 0, X(AN.sel[1]) - X(AN.sel[0]), H); }
  if (AN.drag) { const a = Math.min(AN.drag.d0, AN.drag.d1), b = Math.max(AN.drag.d0, AN.drag.d1); g.fillStyle = tc(1, .12); g.fillRect(X(a), 0, X(b) - X(a), H); }
  // corner bands + names
  g.font = `600 ${10 * k}px Inter`; g.textBaseline = "top";
  let lastEnd = -1e9;
  for (const cr of cm.corners) {
    if (cr.end < d0 || cr.start > d1) continue;
    g.fillStyle = "rgba(255,255,255,.03)"; g.fillRect(X(cr.start), 0, X(cr.end) - X(cr.start), H);
    const tx = X(cr.start) + 4 * k;
    if (tx > lastEnd + 8 * k) { g.fillStyle = tc(1, .75); g.fillText(cr.name, tx, H - 14 * k); lastEnd = tx + g.measureText(cr.name).width; }
  }
  const lane = (name, series, lo, hi, color, width, dash) => {
    const [ya, yb] = box[name], Yv = (v) => yb - (v - lo) / (hi - lo || 1) * (yb - ya);
    g.strokeStyle = color; g.lineWidth = width * k; g.setLineDash(dash ? dash.map((x) => x * k) : []);
    g.beginPath();
    for (let i = i0; i <= i1; i++) { const px = X(cm.d[i]), py = Yv(series[i]); i === i0 ? g.moveTo(px, py) : g.lineTo(px, py); }
    g.stroke(); g.setLineDash([]);
  };
  // labels / grid
  g.font = `700 ${9 * k}px Inter`; g.fillStyle = "#6B7280"; g.textBaseline = "middle";
  for (const [n] of lanes) { const [a, b] = box[n]; g.fillText(n.toUpperCase(), 8 * k, (a + b) / 2); g.fillStyle = "rgba(255,255,255,.04)"; g.fillRect(L, b + 2 * k, R - L, 1); g.fillStyle = "#6B7280"; }
  // delta lane (relative to start of range)
  const dl = cm.delta.slice(i0, i1 + 1), base = dl[0] || 0, mx = Math.max(0.15, ...dl.map((v) => Math.abs(v - base)));
  const rel = cm.delta.map((v) => v - base);
  const [da, db] = box["Δ"]; g.fillStyle = "rgba(255,255,255,.08)"; g.fillRect(L, (da + db) / 2, R - L, 1);
  lane("Δ", rel, -mx, mx, tc(1, 1), 1.6);
  // speed
  const vs = cm.me.kmh.slice(i0, i1 + 1).concat(cm.ref.kmh.slice(i0, i1 + 1)); const vlo = Math.min(...vs) - 5, vhi = Math.max(...vs) + 5;
  lane("km/h", cm.ref.kmh, vlo, vhi, "rgba(96,165,250,.85)", 1.4);
  lane("km/h", cm.me.kmh, vlo, vhi, "#FCFAF5", 1.8);
  // pedals
  lane("pedals", cm.ref.thr, 0, 1.05, "rgba(74,222,128,.45)", 1.2, [4, 3]);
  lane("pedals", cm.ref.brk, 0, 1.05, "rgba(248,113,113,.45)", 1.2, [4, 3]);
  lane("pedals", cm.me.thr, 0, 1.05, "#22C55E", 1.7);
  lane("pedals", cm.me.brk, 0, 1.05, "#EF4444", 1.7);
  // steering
  const st = cm.me.steer.slice(i0, i1 + 1).concat(cm.ref.steer.slice(i0, i1 + 1)); const sm = Math.max(0.2, ...st.map(Math.abs));
  lane("steer", cm.ref.steer, -sm, sm, "rgba(96,165,250,.7)", 1.2);
  lane("steer", cm.me.steer, -sm, sm, "#FCFAF5", 1.5);
  // hover readout
  if (AN.hover != null && AN.hover >= d0 && AN.hover <= d1) {
    const i = dToIdx(cm.d, AN.hover), x = X(cm.d[i]);
    g.strokeStyle = tc(1, .7); g.lineWidth = 1 * k; g.beginPath(); g.moveTo(x, 0); g.lineTo(x, H); g.stroke();
    const txt = `${cm.me.kmh[i].toFixed(0)} km/h (ref ${cm.ref.kmh[i].toFixed(0)})  ·  gear ${Math.round(cm.me.gear[i])}  ·  Δ ${fmtD(cm.delta[i] - base)}  ·  ${cm.d[i].toFixed(0)} m`;
    g.font = `600 ${11 * k}px Inter`; const w = g.measureText(txt).width + 16 * k;
    const bx = Math.min(x + 10 * k, W - w - 6 * k);
    g.fillStyle = "rgba(8,10,16,.9)"; roundRect(g, bx, 6 * k, w, 22 * k, 6 * k); g.fill();
    g.fillStyle = "#FCFAF5"; g.textBaseline = "middle"; g.fillText(txt, bx + 8 * k, 17 * k);
  }
}

/* ---------------- interaction ---------------- */
function eventD(e, where) {
  const c = anEl(where === "map" ? "anMap" : "anTrace"), r = c.getBoundingClientRect(), k = window.devicePixelRatio || 1;
  const px = (e.clientX - r.left) * k, py = (e.clientY - r.top) * k;
  if (where === "map") {
    const { X, Y } = mapXf(); let best = null, bd = 1e18;
    for (const p of AN.mapPts) { const dx = X(p.x) - px, dy = Y(p.y) - py, q = dx * dx + dy * dy; if (q < bd) { bd = q; best = p; } }
    return bd < (40 * k) ** 2 ? best.d : null;
  }
  const [d0, d1] = traceRange(), L = 54 * k, R = c.width - 14 * k;
  return d0 + Math.max(0, Math.min(1, (px - L) / (R - L))) * (d1 - d0);
}
function anPointer(e, where) {
  if (!AN.cmp) return;
  const d = eventD(e, where);
  AN.hover = d;
  if (AN.drag && d != null) AN.drag.d1 = d;
  anDraw();
}
function anDragStart(e, where) {
  if (!AN.cmp) return;
  const d = eventD(e, where); if (d == null) return;
  AN.drag = { d0: d, d1: d, where };
  e.preventDefault();
}
async function anDragEnd() {
  if (!AN.drag) return;
  const a = Math.min(AN.drag.d0, AN.drag.d1), b = Math.max(AN.drag.d0, AN.drag.d1);
  AN.drag = null;
  if (b - a < 25) {   // a click: pick the corner under the pointer
    const cr = AN.cmp.corners.find((c) => a >= c.start - 80 && a <= c.end + 80);
    if (cr) await anSection(cr.span[0], cr.span[1]); else anDraw();
    return;
  }
  await anSection(a, b);
}

async function anSection(a, b) {
  AN.sel = [a, b];
  anDraw();
  let r = null;
  try { r = await api.an_section(a, b); } catch (e) {}
  anSide(r);
  anDraw();
}

/* ---------------- side panel ---------------- */
function esc(s) { return String(s).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c])); }

function anSide(sec) {
  const el = anEl("anSide"), cm = AN.cmp; if (!cm) { el.innerHTML = ""; return; }
  if (window.coSide && window.coSide(sec)) return;   // coach (2026-10-24): the coach view owns the panel when on
  const lapT = AN.cur.laps.find((L) => L.n === +anEl("anLap").value)?.time;
  let h = `<div class="an-head"><div><div class="lbl">This lap</div><div class="an-big">${fmtLap(lapT)}</div></div>
    <div class="an-vs"><div class="lbl">vs ref</div><div class="an-big ${cm.total > 0 ? "lose" : "gain"}">${fmtD(cm.total)}</div></div></div>`;
  h += anTheoryHtml(false);
  if (!sec) {
    h += `<div class="an-sub">Time lost</div>`;
    const rows = [...cm.corners].sort((a, b) => b.lost - a.lost);
    const mx = Math.max(0.1, ...rows.map((r) => Math.abs(r.lost)));
    for (const r of rows) {
      h += `<div class="an-row" data-a="${r.span[0]}" data-b="${r.span[1]}"><span class="n">${esc(r.name)}</span>
        <span class="bar"><i class="${r.lost > 0 ? "lose" : "gain"}" style="width:${Math.abs(r.lost) / mx * 100}%"></i></span>
        <span class="v ${r.lost > 0 ? "lose" : "gain"}">${r.lost > 0 ? "+" : ""}${r.lost.toFixed(2)}</span></div>`;
    }
    h += anTheoryHtml(true);
    const nts = AN.cur.notes || [];
    if (nts.length)
      h += `<div class="an-mech" style="margin-top:14px;background:rgba(167,139,250,.08);box-shadow:inset 3px 0 0 #A78BFA"><div class="lbl" style="color:#C4B5FD">Radio notes</div>${nts.map((n) => `<p>Lap ${n.lap ?? "?"}${n.corner ? " · " + esc(n.corner) : ""}: “${esc(n.text)}”</p>`).join("")}</div>`;
    if (cm.mech_summary && cm.mech_summary.length)
      h += `<div class="an-mech" style="margin-top:14px"><div class="lbl">Mechanic</div>${cm.mech_summary.map((m) => `<p>${esc(m)}</p>`).join("")}</div>`;
    h += `<div class="an-hint">Drag to select · click a corner</div>`;
    el.innerHTML = h;
    el.querySelectorAll(".an-row, .an-piece").forEach((r) => r.addEventListener("click", () => anSection(+r.dataset.a, +r.dataset.b)));
    anEl("anClear").style.visibility = "hidden";
    return;
  }
  anEl("anClear").style.visibility = "visible";
  const names = sec.corners.map((c) => c.name);
  h += `<div class="an-sec"><div class="lbl">${names.length ? esc(names.join("  →  ")) : `${sec.from.toFixed(0)}–${sec.to.toFixed(0)} m`}</div>
    <div class="an-big ${sec.lost > 0 ? "lose" : "gain"}">${fmtD(sec.lost)}</div></div>`;
  for (const n of sec.notes || []) h += `<div class="an-note">${esc(n)}</div>`;
  for (const c of sec.corners) {
    h += `<div class="an-corner"><div class="an-ch"><span>${esc(c.name)}</span><b class="${c.lost > 0 ? "lose" : "gain"}">${fmtD(c.lost)}</b></div>`;
    if (c.tips.length) h += `<ol class="an-tips">${c.tips.map((t) => `<li>${esc(t)}</li>`).join("")}</ol>`;
    const M = c.me, R = c.ref, f = (v, u = "") => (v == null ? "-" : `${Math.round(v)}${u}`);
    h += `<table class="an-t"><tr><th></th><th>You</th><th>Ref</th></tr>
      <tr><td>Brake at</td><td>${f(M.brake_d, " m")}</td><td>${f(R.brake_d, " m")}</td></tr>
      <tr><td>Entry</td><td>${f(M.entry_kmh)}</td><td>${f(R.entry_kmh)}</td></tr>
      <tr><td>Apex</td><td>${f(M.min_kmh)}</td><td>${f(R.min_kmh)}</td></tr>
      <tr><td>Throttle on</td><td>${f(M.throttle_on_d, " m")}</td><td>${f(R.throttle_on_d, " m")}</td></tr>
      <tr><td>Full throttle</td><td>${f(M.full_throttle_d, " m")}</td><td>${f(R.full_throttle_d, " m")}</td></tr>
      <tr><td>Exit</td><td>${f(M.exit_kmh)}</td><td>${f(R.exit_kmh)}</td></tr></table>`;
    if (c.mech && c.mech.length) h += `<div class="an-mech"><div class="lbl">Mechanic</div>${c.mech.map((m) => `<p>${esc(m)}</p>`).join("")}</div>`;
    h += `</div>`;
  }
  el.innerHTML = h;
  el.scrollTop = 0;
}

/* ---------------- track identity: logo + colours from the logo ---------------- */
const TC = { a1: [255, 216, 118], a2: [197, 165, 114] };
function hexRgb(h) { const m = /^#?([0-9a-f]{6})$/i.exec(h || ""); if (!m) return null; const n = parseInt(m[1], 16); return [n >> 16, (n >> 8) & 255, n & 255]; }
function tc(i, a) { const c = i === 2 ? TC.a2 : TC.a1; return `rgba(${c[0]},${c[1]},${c[2]},${a})`; }
function anTheme(t) {
  const p = anEl("p-analysis"), logo = anEl("anLogo"), img = logo.querySelector("img");
  const a1 = hexRgb(t && t.a1) || [255, 216, 118], a2 = hexRgb(t && t.a2) || (t && t.a1 ? a1 : [197, 165, 114]);
  TC.a1 = a1; TC.a2 = a2;
  p.style.setProperty("--ta1", `rgb(${a1})`); p.style.setProperty("--ta2", `rgb(${a2})`);
  const pl = hexRgb(t && t.plate);
  p.style.setProperty("--tpl", pl ? `rgba(${pl},.95)` : `rgba(${a1},.10)`);
  logo.classList.remove("on");
  if (t && t.logo) {
    setTimeout(() => {
      img.onload = () => logo.classList.add("on");
      logo.classList.toggle("light", !!t.dark); logo.classList.toggle("plated", !!t.plate);
      img.src = t.logo;
    }, 250);
  }
  if (typeof anDraw === "function") setTimeout(anDraw, 50);
}

/* ---------------- theoretical best ---------------- */
function anTheoryHtml(pieces) {
  const c = AN.cur; if (!c) return "";
  const best = c.laps.find((L) => L.n === c.best_n)?.time;
  const row = (label, th) => th ? `<div class="an-theory"><span class="lbl">${label}</span><span><b>${fmtLap(th.time)}</b>${th.gain > 0.0005 ? `<small>−${th.gain.toFixed(2)}</small>` : ""}</span></div>` : "";
  if (pieces) {
    const key = anEl("anRef").value, th = key === "theory" ? c.theory : key === "theory_all" ? c.theory_all : null;
    if (!th || !th.segs) return "";
    return `<div class="an-sub">Best pieces</div><div class="an-pieces">` + th.segs.map((g) => `<div class="an-piece" data-a="${g.from}" data-b="${g.to}"><span>${esc(g.name)}</span>
      <span>${g.where === "this session" ? "lap " + g.lap : esc(g.where) + " · lap " + g.lap}</span><span>${g.vs_best > 0.0005 ? "−" + g.vs_best.toFixed(2) : "best"}</span></div>`).join("") + `</div>`;
  }
  let h = row("Theoretical best", c.theory) + row("All-time theoretical", c.theory_all && (!c.theory || c.theory_all.time < c.theory.time) ? { time: c.theory_all.time, gain: best ? best - c.theory_all.time : 0 } : null);
  return h;
}

function anRefUpdate(e) {
  if (!AN.cur || AN.cur.sid !== e.sid) return;
  AN.cur.theory_all = e.theory;
  const ref = anEl("anRef");
  let o = [...ref.options].find((x) => x.value === e.key);
  if (!o) {
    o = document.createElement("option"); o.value = e.key;
    const after = [...ref.options].find((x) => x.value === "theory") || [...ref.options].find((x) => x.value === "best");
    after ? after.after(o) : ref.prepend(o);
  }
  o.textContent = e.label;
  if (AN.cmp && !AN.sel) anSide();
}

window.anInit = anInit; window.anRefUpdate = anRefUpdate;
