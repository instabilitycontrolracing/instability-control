/* Race Engineer for iPad: live telemetry, track map, radio and pit plan from the PC.
   Performance notes (2026-10-24): nothing runs per frame unless something is actually moving.
   - SSE messages only store the newest data and ask for ONE frame; the frame paints the latest state once.
   - DOM writes are diffed (no write when the text/style didn't change); no layout reads in the frame.
   - Track map: the track outline is drawn once into an offscreen canvas; a frame only blits it and draws the cars,
     and only while cars are actually moving (max 30 redraws/s). "You" is a DOM marker with a CSS pulse.
   - The watch hands are separate layers rotated with CSS transforms, ticking 8x a second (like a real movement).
   - Everything stops while the page is hidden; the feed reconnects with backoff and a watchdog. */
"use strict";
function watchSVG(id) {
  const P = id + "_";
  let flutes = "";
  for (let i = 0; i < 128; i++) {
    const a = i * Math.PI * 2 / 128, s = Math.sin(a), c = Math.cos(a);
    const x1 = (50 + 42 * s).toFixed(3), y1 = (50 - 42 * c).toFixed(3), x2 = (50 + 50 * s).toFixed(3), y2 = (50 - 50 * c).toFixed(3);
    flutes += i % 2 === 0
      ? `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="rgba(255,252,240,.55)" stroke-width=".32"/>`
      : `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="rgba(0,0,0,.55)" stroke-width=".34"/>`;
  }
  const sub = (x, y, deg) => `<line x1="${x}" y1="${y}" x2="${x}" y2="${(y - 6.5).toFixed(2)}" stroke="#2A2418" stroke-width="1.1" stroke-linecap="round" transform="rotate(${deg} ${x} ${y})"/>
    <circle cx="${x}" cy="${y}" r=".9" fill="#C5A572"/>`;
  const hand = (cls, inner) => `<svg class="hand ${cls}" viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">${inner}</svg>`;
  return `<div class="wbox"><svg class="watch" viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <clipPath id="${P}clip"><circle cx="50" cy="50" r="44"/></clipPath>
    <linearGradient id="${P}bez" gradientUnits="userSpaceOnUse" x1="50" y1="4" x2="50" y2="96">
      <stop offset="0" stop-color="#FCF7E8"/><stop offset=".22" stop-color="#EDE3CA"/><stop offset=".48" stop-color="#C7BB9C"/>
      <stop offset=".72" stop-color="#8E8267"/><stop offset="1" stop-color="#534A38"/></linearGradient>
    <radialGradient id="${P}dark" gradientUnits="userSpaceOnUse" cx="50" cy="96" r="59.8">
      <stop offset="0" stop-color="rgb(20,16,8)" stop-opacity=".55"/><stop offset=".6" stop-color="rgb(20,16,8)" stop-opacity=".1"/>
      <stop offset="1" stop-color="rgb(20,16,8)" stop-opacity="0"/></radialGradient>
    <radialGradient id="${P}gloss" gradientUnits="userSpaceOnUse" cx="33.4" cy="22.4" r="50.6">
      <stop offset="0" stop-color="rgb(255,255,250)" stop-opacity=".7"/><stop offset=".55" stop-color="rgb(255,255,250)" stop-opacity=".12"/>
      <stop offset="1" stop-color="rgb(255,255,250)" stop-opacity="0"/></radialGradient>
  </defs>
  <g clip-path="url(#${P}clip)">
    <circle cx="50" cy="50" r="44" fill="#F4F0E6"/>
    <image href="/assets/dial.png" x="-4.56" y="-4.56" width="109.12" height="109.12" preserveAspectRatio="xMidYMid slice"/>
  </g>
  ${sub(28.8, 47.65, -25)}${sub(70.75, 47.65, 15)}${sub(49.95, 71.35, 40)}
  <circle cx="50" cy="50" r="46" fill="none" stroke="url(#${P}bez)" stroke-width="8"/>
  <circle cx="50" cy="50" r="46" fill="none" stroke="url(#${P}dark)" stroke-width="8"/>
  ${flutes}
  <circle cx="50" cy="50" r="42" fill="none" stroke="rgba(0,0,0,.7)" stroke-width=".55"/>
  <circle cx="50" cy="50" r="49.9" fill="none" stroke="rgba(0,0,0,.45)" stroke-width=".4"/>
  <circle cx="50" cy="50" r="46" fill="none" stroke="url(#${P}gloss)" stroke-width="8"/>
</svg>${hand("h-hour", `<line x1="50" y1="55" x2="50" y2="28" stroke="#9C7C45" stroke-width="3.6" stroke-linecap="round"/>
    <line x1="50" y1="55" x2="50" y2="28" stroke="#F2E8D0" stroke-width="2.8" stroke-linecap="round"/>`)}${hand("h-min", `<line x1="50" y1="55" x2="50" y2="16" stroke="#9C7C45" stroke-width="2.6" stroke-linecap="round"/>
    <line x1="50" y1="55" x2="50" y2="16" stroke="#F2E8D0" stroke-width="1.9" stroke-linecap="round"/>`)}${hand("h-sec", `<line x1="50" y1="60" x2="50" y2="13" stroke="#C5A572" stroke-width=".7" stroke-linecap="round"/>
    <circle cx="50" cy="19" r="1.2" fill="#C5A572"/><circle cx="50" cy="50" r="2.3" fill="#E4C887"/><circle cx="50" cy="50" r="1.2" fill="#7A6240"/>`)}</div>`;
}


/* ================================================================ basics */
const $ = (s) => document.querySelector(s);
const E = {};
const el = (id) => E[id] || (E[id] = document.getElementById(id));
const qs = new URLSearchParams(location.search);
let KEY = qs.get("k") || "";
try { if (KEY) localStorage.setItem("re_key", KEY); else KEY = localStorage.getItem("re_key") || ""; } catch (e) {}
const isNum = (x) => typeof x === "number" && isFinite(x);
const fmtLap = (t) => { if (!isNum(t) || t <= 0) return "–"; const m = Math.floor(t / 60), s = t - m * 60; return `${m}:${s.toFixed(3).padStart(6, "0")}`; };
const fmtGap = (g) => (!isNum(g) ? "–" : g < 60 ? g.toFixed(1) : `${Math.floor(g / 60)}:${(g % 60).toFixed(0).padStart(2, "0")}`);
const fmtLeft = (s) => { if (!isNum(s) || s < 0 || s > 360000) return "–"; const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), x = Math.floor(s % 60); return h ? `${h}:${String(m).padStart(2, "0")}:${String(x).padStart(2, "0")}` : `${m}:${String(x).padStart(2, "0")}`; };
const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
const ease = (t) => 1 - Math.pow(1 - t, 3);
const easeIO = (t) => (t < .5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
const DPR = () => Math.min(2, window.devicePixelRatio || 1);      // >2 only costs fill-rate on an iPad
/* diffed DOM writes: nothing touches the DOM when the value is unchanged */
function setText(id, v) { const e = typeof id === "string" ? el(id) : id; if (!e) return; const s = v == null ? "–" : String(v); if (e._t !== s) { e._t = s; e.textContent = s; } }
function setStyle(e, prop, v) { if (!e) return; const c = e._s || (e._s = {}); if (c[prop] !== v) { c[prop] = v; e.style[prop] = v; } }
function setCls(e, cls, on) { if (!e) return; const c = e._c || (e._c = {}); on = !!on; if (c[cls] !== on) { c[cls] = on; e.classList.toggle(cls, on); } }
function replay(e, cls) { if (!e) return; e.classList.remove(cls); requestAnimationFrame(() => requestAnimationFrame(() => e.classList.add(cls))); }

/* ================================================================ watches */
const watches = [];
function mountWatch(box, id, frozenAt12) {
  box.innerHTML = watchSVG(id);
  const w = { h: box.querySelector(".h-hour"), m: box.querySelector(".h-min"), s: box.querySelector(".h-sec"), spin: frozenAt12 ? 0 : 1, el: box, last: ["", "", ""] };
  watches.push(w);
  tickWatches();
  return w;
}
function handAngles() {
  const d = new Date(), sod = d.getHours() * 3600 + d.getMinutes() * 60 + d.getSeconds() + d.getMilliseconds() / 1000;
  return [(sod / 3600 % 12) * 30, (sod / 60 % 60) * 6, (sod % 60) * 6];
}
function tickWatches() {
  if (!watches.length) return;
  const a = handAngles();
  for (const w of watches) {
    const k = ease(w.spin);      // 0 = all hands at 12, 1 = real time (the intro spins them in)
    [w.h, w.m, w.s].forEach((h, i) => {
      const v = `rotate(${(a[i] * k).toFixed(1)}deg)`;
      if (w.last[i] !== v) { w.last[i] = v; h.style.transform = v; }
    });
  }
}

/* ================================================================ intro (same as the desktop: watch first, hands at 12) */
async function intro() {
  const box = $("#intro"), iw = $("#introWatch");
  const w = mountWatch(iw, "intro", true);
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  await sleep(250);
  box.classList.add("lines");
  await sleep(450);
  // hands spin from 12 o'clock to the time
  const t0 = performance.now(), dur = 1700;
  await new Promise((res) => { const f = (now) => { w.spin = clamp((now - t0) / dur, 0, 1); tickWatches(); if (w.spin < 1 && !document.hidden) requestAnimationFrame(f); else { w.spin = 1; res(); } }; requestAnimationFrame(f); });
  await sleep(550);
  box.classList.add("leaving");
  await sleep(250);
  // fly the watch into the session bar
  document.body.classList.add("ready");
  const slot = $("#slot");
  await sleep(60);
  const a = iw.getBoundingClientRect(), b = slot.getBoundingClientRect();
  const s = b.width / a.width, dx = b.left - a.left, dy = b.top - a.top;
  const f0 = performance.now(), fd = 1050;
  await new Promise((res) => {
    const f = (now) => {
      const t = document.hidden ? 1 : easeIO(clamp((now - f0) / fd, 0, 1));
      const arcY = -Math.sin(t * Math.PI) * 40;     // a little lift as it flies
      iw.style.transform = `translate3d(${dx * t}px, ${dy * t + arcY}px, 0) scale(${1 + (s - 1) * t}) rotate(${-8 * Math.sin(t * Math.PI)}deg)`;
      if (t < 1) requestAnimationFrame(f); else res();
    };
    requestAnimationFrame(f);
  });
  // hand over: the bar's own watch takes its place
  mountWatch(slot, "bar", false);
  watches.splice(watches.indexOf(w), 1);
  box.classList.add("gone");
  setTimeout(() => box.remove(), 900);
}

/* ================================================================ frame scheduler */
let rafId = 0, dirtyT = true;
function kick() { if (!rafId && !document.hidden) rafId = requestAnimationFrame(frame); }
function frame(now) {
  rafId = 0;
  const lap = document.body.classList.contains("lapmode");
  if (dirtyT && !lap) { dirtyT = false; try { renderT(); } catch (e) { console.warn("render", e); } }
  let again = false;
  if (!lap) again = drawMap(now) || again;
  if (window.LAP && LAP.draw(now)) again = true;
  if (again) kick();
}
window.REDRAW_ALL = () => { dirtyT = true; MAP.dirty = true; kick(); };

/* ================================================================ live data + connection */
let FULL = null, T = null, PIT = null, lastT = 0;
const PREV = {};
const CONN = { es: null, backoff: 1000, retryT: 0, retryAt: 0, lastMsg: 0, hb: false, badSince: 0, hideT: 0 };
function connect() {
  clearTimeout(CONN.retryT); CONN.retryT = 0; CONN.retryAt = 0;
  if (CONN.es) { CONN.es.close(); CONN.es = null; }
  if (!KEY) { setText("iStep", "Open the link from the PC (it has your key)"); setText("waitT", "Open the link from the PC: Settings > General > iPad"); return; }
  const es = (CONN.es = new EventSource(`/events?k=${encodeURIComponent(KEY)}`));
  CONN.lastMsg = Date.now();
  const on = (name, fn) => es.addEventListener(name, (e) => {
    if (es !== CONN.es) return;
    alive();
    let d = {};
    try { d = e.data ? JSON.parse(e.data) : {}; } catch (err) { return; }
    try { fn(d || {}); } catch (err) { console.warn(name, err); }
  });
  es.addEventListener("open", () => { if (es !== CONN.es) return; alive(); CONN.backoff = 1000; setText("iStep", "Connected"); chip("ok", "PC linked"); });
  es.addEventListener("error", () => {
    if (es !== CONN.es) return;
    if (!CONN.badSince) CONN.badSince = Date.now();
    if (es.readyState === 2) retryLater();            // the browser gave up (server down / refused): we retry ourselves
    else chip("wait", "Reconnecting");                // the browser retries by itself
  });
  on("full", onFull);
  on("t", onT);
  on("pit", onPit);
  on("log", onLog);
  on("strat", onStrat);
  on("hb", () => { CONN.hb = true; });
  on("off", () => { T = null; CARS.clear(); MAP.dirty = true; document.body.classList.add("idle"); chip("wait", "Waiting for iRacing"); kick(); });
}
function alive() { CONN.lastMsg = Date.now(); if (CONN.badSince) { CONN.badSince = 0; setOffline(false); } }
function retryLater() {
  if (CONN.es) { CONN.es.close(); CONN.es = null; }
  if (CONN.retryT) return;
  if (!CONN.badSince) CONN.badSince = Date.now();
  const d = CONN.backoff * (0.8 + Math.random() * 0.4);
  CONN.backoff = Math.min(CONN.backoff * 2, 15000);
  CONN.retryAt = Date.now() + d;
  CONN.retryT = setTimeout(connect, d);
  chip("lost", "Reconnecting");
}
function setOffline(on) {
  setCls(document.body, "offline", on);
  if (!on && T) chip("ok", T.on ? (T.pit ? "Pit lane" : "Live") : "In garage");
}
function chip(cls, txt) { const c = el("chip"); const k = "chip " + cls; if (c._k !== k) { c._k = k; c.className = k; } setText("chipT", txt); }
// once a second: connection watchdog, "no data" state, reconnect countdown
setInterval(() => {
  if (document.hidden) return;
  const now = Date.now();
  // the server sends a heartbeat every 5 s; a silent stream for 12 s is a dead stream (iOS Wi-Fi sleep, PC asleep)
  if (CONN.es && CONN.hb && now - CONN.lastMsg > 12000) { CONN.badSince = CONN.badSince || now; retryLater(); }
  const bad = CONN.badSince && now - CONN.badSince > 2500;
  setCls(document.body, "offline", bad);
  if (bad) setText("connT", CONN.retryAt > now ? `Retrying in ${Math.ceil((CONN.retryAt - now) / 1000)} s` : "Reconnecting…");
  if (T && performance.now() - lastT > 4000) { document.body.classList.add("idle"); if (!bad) chip("wait", "No data"); }
}, 1000);
document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    if (rafId) { cancelAnimationFrame(rafId); rafId = 0; }
    // brief app switches keep the stream; a longer absence closes it so the PC isn't queueing for nobody
    CONN.hideT = setTimeout(() => { if (CONN.es) { CONN.es.close(); CONN.es = null; } }, 15000);
  } else {
    clearTimeout(CONN.hideT);
    if (window.LAP && LAP.gap) LAP.gap();
    if (!CONN.es || CONN.es.readyState === 2 || Date.now() - CONN.lastMsg > 6000) { CONN.backoff = 1000; connect(); }
    tickWatches();
    window.REDRAW_ALL();
  }
});
el("connBtn").addEventListener("click", () => { CONN.backoff = 1000; connect(); });

function onFull(f) {
  FULL = f;
  if (f.pit) onPit(f.pit);
  if (f.strat) onStrat(f.strat);
  if (!f.live) { document.body.classList.add("idle"); chip("ok", "Waiting for iRacing"); return; }
  setText("trk", f.track || "–"); setText("car", f.car || ""); setText("sess", f.session || "Session");
  const th = f.theme, img = el("tlogo");
  if (th && th.logo) {
    const src = "/" + th.logo;
    if (img._src !== src) { img._src = src; img.classList.remove("on"); img.onload = () => img.classList.add("on"); img.src = src; }
    img.classList.toggle("light", !!th.dark);
  } else { img._src = null; img.classList.remove("on"); }
  const root = document.documentElement;
  const c1 = th && th.a1 ? th.a1 : "#FFD876", c2 = th && th.a2 ? th.a2 : (th && th.a1) || "#C5A572";
  root.style.setProperty("--ta1", c1); root.style.setProperty("--ta2", c2);
  if (MAP.c1 !== c1 || MAP.c2 !== c2) { MAP.c1 = c1; MAP.c2 = c2; MAP.layer = null; MAP.dirty = true; }
  setMap(f.map);
  buildTicks();
  dirtyT = true; kick();
}

function onT(t) {
  if (!t || t.err) return;
  const now = performance.now();
  if (window.LAP) LAP.feed(t);
  PREV.was = PREV.was || T;
  const dt = lastT ? now - lastT : 130;
  T = t; lastT = now;
  document.body.classList.remove("idle");
  // cars -> smooth movement on the map, interpolated over the real message interval
  const dur = clamp(dt, 60, 260);
  let moved = false;
  const cars = Array.isArray(t.cars) ? t.cars : [];
  for (const c of cars) {
    if (!Array.isArray(c) || !isNum(c[1])) continue;
    const k = c[0], p = c[1], s = CARS.get(k);
    if (!s) { CARS.set(k, { from: p, to: p, t0: now, dur, cls: c[2], col: c[2] ? hexCol(c[2]) : "#9CA3AF", pos: c[3], pit: c[4], num: c[5], shown: p, seen: now }); moved = true; continue; }
    let to = p; const cur = s.shown;
    if (to - cur < -0.5) to += 1; else if (to - cur > 0.5) to -= 1;
    if (Math.abs(to - cur) > 1e-6 || s.pit !== c[4]) moved = true;
    if (s.cls !== c[2]) { s.cls = c[2]; s.col = c[2] ? hexCol(c[2]) : "#9CA3AF"; }
    s.from = cur; s.to = to; s.t0 = now; s.dur = dur; s.pos = c[3]; s.pit = c[4]; s.num = c[5]; s.seen = now;
  }
  for (const [k, s] of CARS) if (now - s.seen > 3000) { CARS.delete(k); moved = true; }
  if (moved) { MAP.animUntil = now + dur + 20; MAP.dirty = true; }
  // gap trend history needs every sample, so it's kept here (cheap, bounded to 5 s)
  gapHist("A", t.ga, now); gapHist("B", t.gb, now);
  dirtyT = true;
  kick();
}

/* paint the newest telemetry once per frame (several messages between frames collapse into one paint) */
function renderT() {
  const t = T, was = PREV.was; PREV.was = null;
  drawGauge(t);
  if (!t) return;
  if (!document.body.classList.contains("offline")) chip("ok", t.on ? (t.pit ? "Pit lane" : "Live") : "In garage");
  // header
  const pn = t.pos || null;
  setText("posN", pn ?? "–"); setText("posOf", t.n_class ? `/${t.n_class}` : "");
  if (was && was.pos && pn && pn !== was.pos) { const pos = el("pos"); pos.classList.remove("up", "down"); replay(pos, pn < was.pos ? "up" : "down"); }
  setText("cls", t.class || "Class");
  flags(t.flags);
  if (isNum(t.left) && t.left > 0) { PREV.maxLeft = Math.max(PREV.maxLeft || 0, t.left); setStyle(el("prog"), "transform", `scaleX(${(1 - t.left / PREV.maxLeft).toFixed(3)})`); }
  // drive
  setText("spd", isNum(t.spd) ? t.spd : "–"); setText("spdU", t.met === false ? "MPH" : "KM/H");
  gear(t.gear);
  // timers + delta
  setText("lapN", isNum(t.lap) ? t.lap : "");
  setText("cur", fmtLap(t.cur));
  if (was && t.last !== was.last && t.last > 0) {
    const lb = el("lastBox"); lb.classList.remove("flip", "pb"); replay(lb, "flip");
    if (t.best > 0 && Math.abs(t.best - t.last) < 0.0005 && (!was.best || was.best <= 0 || t.best < was.best - 0.0005)) lb.classList.add("pb");
  }
  setText("last", fmtLap(t.last)); setText("best", fmtLap(t.best));
  const d = t.delta, bar = el("dBar");
  if (!isNum(d)) { setStyle(bar, "transform", "scaleX(0)"); setText("dTxt", "–"); }
  else {
    const w = clamp(Math.abs(d) / 1.5, 0, 1);
    setStyle(bar, "transform", `scaleX(${(d > 0 ? w : -w).toFixed(3)})`);
    setCls(bar, "loss", d > 0);
    setText("dTxt", (d > 0 ? "+" : d < 0 ? "−" : "±") + Math.abs(d).toFixed(2));
  }
  // gaps (closing = the gap shrank over the last 5 s)
  gapBox("A", t.ga, t.ahead, true); gapBox("B", t.gb, t.behind, false);
  // fuel
  if (isNum(t.fuel)) PREV.tank = Math.max(PREV.tank || 0, t.fuel);
  const tank = (PIT && PIT.tank) || PREV.tank || null;
  const fr = tank && isNum(t.fuel) ? clamp(t.fuel / tank, 0, 1) : 0, ring = el("fRing"), C = 2 * Math.PI * 50;
  setStyle(ring, "strokeDasharray", String(C)); setStyle(ring, "strokeDashoffset", (C * (1 - fr)).toFixed(1));
  const u = t.met === false ? "gal" : "L", cv = (x) => (t.met === false ? x / 3.785 : x);
  setText("fLaps", isNum(t.fuel_laps) ? t.fuel_laps.toFixed(1) : "–");
  setText("fNow", isNum(t.fuel) ? `${cv(t.fuel).toFixed(1)} ${u}` : "–");
  setText("fLap", isNum(t.fuel_lap) && t.fuel_lap ? `${cv(t.fuel_lap).toFixed(2)} ${u}` : "–");
  setText("ltg", t.ltg != null ? `${t.ltg} laps` : "–"); setText("left", fmtLeft(t.left));
  // car settings on the wheel
  dash([["BB", t.bb, 1], ["F ARB", t.farb], ["R ARB", t.rarb], ["TC", t.tc], ["TC2", t.tc2], ["ABS", t.abs], ["MIG", t.mig]]);
}

function gear(g) {
  const e = el("gear"), txt = !isNum(g) ? "–" : g < 0 ? "R" : g === 0 ? "N" : String(g);
  if (e.dataset.g === txt) return;
  e.dataset.g = txt;
  e.innerHTML = `<span class="in">${txt}</span>`;
}

function gapHist(which, g, now) {
  const hist = (PREV["gap" + which] = PREV["gap" + which] || []);
  while (hist.length && now - hist[0][0] > 5000) hist.shift();
  if (isNum(g)) hist.push([now, g]);
  if (hist.length > 120) hist.splice(0, hist.length - 120);
}
function gapBox(which, g, num, ahead) {
  const lw = which.toLowerCase();
  setText(`g${lw}`, fmtGap(g)); setText(`g${lw}N`, num ? `#${num}` : "");
  const hist = PREV["gap" + which] || [];
  const trend = hist.length > 5 ? hist[hist.length - 1][1] - hist[0][1] : 0;
  const box = el(`g${which}`);
  setCls(box, "closing", ahead && trend < -0.15);
  setCls(box, "danger", !ahead && trend < -0.15);
}

function dash(items) {
  const box = el("dash");
  const show = items.filter(([, v]) => isNum(v));
  const sig = show.map((x) => x[0]).join();
  if (box.dataset.sig !== sig) {
    box.dataset.sig = sig;
    box.innerHTML = show.map(([k]) => `<div class="dv" data-k="${k}"><div class="lbl">${k}</div><div class="v">–</div></div>`).join("");
    box._els = {}; for (const n of box.children) box._els[n.dataset.k] = [n, n.querySelector(".v")];
  }
  for (const [k, v, dec] of show) {
    const [e, vv] = box._els[k], txt = dec ? v.toFixed(1) : (Math.round(v * 10) / 10).toString();
    if (vv._t !== txt) {
      if (vv._t && vv._t !== "–") { e.classList.remove("pop"); replay(e, "pop"); clearTimeout(e._pt); e._pt = setTimeout(() => e.classList.remove("pop"), 1600); }
      vv._t = txt; vv.textContent = txt;
    }
  }
}

const FLAG_COL = [[0x10000, "#111827"], [0x10, "#DC2626"], [0x4000 | 0x8000 | 0x8 | 0x100, "#FFC107"], [0x20, "#3B82F6"], [0x1, "#FFFFFF"], [0x2, "#FFFFFF"]];
function flags(f) {
  const bar = el("bar"), v = isNum(f) ? f : 0;
  const hit = FLAG_COL.find(([m]) => v & m);
  setCls(bar, "flagged", !!hit);
  if (hit && bar._flag !== hit[1]) { bar._flag = hit[1]; bar.style.setProperty("--flag", hit[1]); }
}

/* ================================================================ RPM gauge + shift lights */
let ARC_LEN = 0;
function buildTicks() {
  const g = el("ticks"); if (g.childElementCount) return;
  let h = "";
  for (let i = 0; i <= 10; i++) {
    const a = (135 + i * 27) * Math.PI / 180;    // 270° sweep, same as the arc
    const r1 = 91, r2 = i % 5 === 0 ? 99 : 95;
    h += `<line x1="${100 + r1 * Math.cos(a)}" y1="${100 + r1 * Math.sin(a)}" x2="${100 + r2 * Math.cos(a)}" y2="${100 + r2 * Math.sin(a)}"/>`;
  }
  g.innerHTML = h;
}
const LED_CLS = (i) => (i < 4 ? "g" : i < 7 ? "y" : "r");
function drawGauge(t) {
  const arc = el("rpmArc"), glow = el("rpmGlow");
  if (!ARC_LEN) { ARC_LEN = arc.getTotalLength() || 377; arc.style.strokeDasharray = ARC_LEN; glow.style.strokeDasharray = ARC_LEN; }
  const rpm = t && isNum(t.rpm) ? t.rpm : 0;
  const red = (FULL && FULL.redline) || PREV.maxRpm || 8000;
  if (t) PREV.maxRpm = Math.max(PREV.maxRpm || 0, rpm);
  const f = clamp(rpm / red, 0, 1);
  const off = (ARC_LEN * (1 - f)).toFixed(1);
  setStyle(arc, "strokeDashoffset", off); setStyle(glow, "strokeDashoffset", off);
  setStyle(glow, "opacity", Math.max(0, (f - .7) / .3).toFixed(2));
  const shift = (FULL && FULL.shift) || red * 0.97, lo = shift * 0.78;
  const leds = el("leds"); if (!leds.childElementCount) { leds.innerHTML = "<i></i>".repeat(10); leds._k = []; }
  const n = t ? Math.round(clamp((rpm - lo) / (shift - lo), 0, 1) * 10) : 0;
  const flash = !!(t && rpm >= shift && t.gear > 0);
  setCls(leds, "flash", flash);
  for (let i = 0; i < 10; i++) { const k = !flash && i < n ? LED_CLS(i) : ""; if (leds._k[i] !== k) { leds._k[i] = k; leds.children[i].className = k; } }
  setCls(el("gear"), "shift", flash);
  const thr = t && isNum(t.thr) ? clamp(t.thr, 0, 1) : 0, brk = t && isNum(t.brk) ? clamp(t.brk, 0, 1) : 0;
  setStyle(el("thr"), "transform", `translateY(${(100 - thr * 100).toFixed(0)}%)`);
  setStyle(el("brk"), "transform", `translateY(${(100 - brk * 100).toFixed(0)}%)`);
  setStyle(el("wheel"), "transform", `rotate(${t && isNum(t.steer) ? (-t.steer * 180 / Math.PI).toFixed(0) : 0}deg)`);
}

/* ================================================================ track map with every car */
const MAP = { pts: null, d: null, len: 1, prog: 1, t0: 0, c1: "#FFD876", c2: "#C5A572", trail: [], sig: null, layer: null, dirty: true, animUntil: 0, lastDraw: 0, w: 0, h: 0, k: 1 };
const CARS = new Map();
const MAP_MIN_DT = 1000 / 30 - 2;     // the map never redraws more than ~30x a second
function setMap(m) {
  if (!m || !Array.isArray(m.x) || !Array.isArray(m.y) || !Array.isArray(m.d) || m.x.length < 3) { MAP.pts = null; MAP.xy = null; MAP.sig = null; MAP.dirty = true; return; }
  const sig = m.x.length + ":" + m.x[0] + ":" + m.y[0] + ":" + (m.len || 0);
  if (sig === MAP.sig) return;              // same track again (e.g. after a reconnect): don't redraw the intro pen
  MAP.sig = sig;
  const n = m.x.length, mx = m.x.reduce((a, b) => a + b, 0) / n, my = m.y.reduce((a, b) => a + b, 0) / n;
  let sxx = 0, syy = 0, sxy = 0;
  for (let i = 0; i < n; i++) { const dx = m.x[i] - mx, dy = m.y[i] - my; sxx += dx * dx; syy += dy * dy; sxy += dx * dy; }
  const ang = 0.5 * Math.atan2(2 * sxy, sxx - syy), c = Math.cos(-ang), s = Math.sin(-ang);
  MAP.pts = m.x.map((x, i) => { const dx = x - mx, dy = m.y[i] - my; return [dx * c - dy * s, dx * s + dy * c]; });
  MAP.d = m.d; MAP.len = m.len || m.d[m.d.length - 1] || 1;
  MAP.prog = 0; MAP.t0 = performance.now(); MAP.trail = [];
  projectMap();
  kick();
}
function sizeMap(w, h) {
  const c = el("map"), k = DPR();
  MAP.k = k; MAP.cw = w; MAP.ch = h;
  const W = Math.max(10, Math.round(w * k)), H = Math.max(10, Math.round(h * k));
  if (c.width !== W || c.height !== H) { c.width = W; c.height = H; }
  projectMap();
}
function projectMap() {
  const c = el("map");
  MAP.layer = null; MAP.dirty = true; MAP.trail = [];
  if (!MAP.pts) { MAP.xy = null; return; }
  const k = MAP.k, xs = MAP.pts.map((p) => p[0]), ys = MAP.pts.map((p) => p[1]);
  let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
  for (let i = 0; i < xs.length; i++) { x0 = Math.min(x0, xs[i]); x1 = Math.max(x1, xs[i]); y0 = Math.min(y0, ys[i]); y1 = Math.max(y1, ys[i]); }
  const pad = 34 * k;
  const sc = Math.min((c.width - 2 * pad) / (x1 - x0 || 1), (c.height - 2 * pad) / (y1 - y0 || 1));
  const ox = (c.width - (x1 - x0) * sc) / 2, oy = (c.height - (y1 - y0) * sc) / 2;
  MAP.xy = MAP.pts.map(([x, y]) => [ox + (x - x0) * sc, c.height - (oy + (y - y0) * sc)]);
  kick();
}
new ResizeObserver((es) => { for (const e of es) { const r = e.contentRect; sizeMap(r.width, r.height); } }).observe(el("mapbox"));
function at(pct) {
  const d = ((pct % 1) + 1) % 1 * MAP.len, D = MAP.d;
  let lo = 0, hi = D.length - 1;
  while (lo < hi) { const m = (lo + hi) >> 1; if (D[m] < d) lo = m + 1; else hi = m; }
  const i = Math.max(1, lo), a = MAP.xy[i - 1], b = MAP.xy[i % MAP.xy.length], f = clamp((d - D[i - 1]) / ((D[i] - D[i - 1]) || 1), 0, 1);
  return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f];
}
const hexCol = (n) => "#" + (Number(n) >>> 0).toString(16).padStart(6, "0").slice(-6);
function trackPath(g, P, m) { g.beginPath(); g.moveTo(P[0][0], P[0][1]); for (let i = 1; i < m; i++) g.lineTo(P[i][0], P[i][1]); if (m >= P.length) g.closePath(); }
function strokeTrack(g, P, upto, W, H, k, glow) {
  g.lineCap = "round"; g.lineJoin = "round";
  trackPath(g, P, upto); g.strokeStyle = "rgba(0,0,0,.6)"; g.lineWidth = 16 * k; g.stroke();
  const grad = g.createLinearGradient(0, 0, W, H); grad.addColorStop(0, MAP.c1); grad.addColorStop(1, MAP.c2);
  g.strokeStyle = grad; g.globalAlpha = .28; g.lineWidth = 14 * k;
  if (glow) { g.shadowColor = MAP.c1; g.shadowBlur = 18 * k; }
  g.stroke(); g.globalAlpha = 1; g.shadowBlur = 0;
  g.strokeStyle = "rgba(229,231,235,.85)"; g.lineWidth = 4 * k; g.stroke();
}
/* the static part (track + glow + start line) is drawn ONCE into an offscreen canvas */
function mapLayer(W, H, k) {
  if (MAP.layer && MAP.layer.width === W && MAP.layer.height === H) return MAP.layer;
  const cv = document.createElement("canvas"); cv.width = W; cv.height = H;
  const g = cv.getContext("2d"), P = MAP.xy;
  strokeTrack(g, P, P.length, W, H, k, true);
  const s0 = P[0], s1 = P[2]; const ang = Math.atan2(s1[1] - s0[1], s1[0] - s0[0]) + Math.PI / 2;
  g.strokeStyle = "#fff"; g.lineWidth = 3 * k; g.beginPath(); g.moveTo(s0[0] + Math.cos(ang) * 10 * k, s0[1] + Math.sin(ang) * 10 * k); g.lineTo(s0[0] - Math.cos(ang) * 10 * k, s0[1] - Math.sin(ang) * 10 * k); g.stroke();
  return (MAP.layer = cv);
}
/* returns true while it still needs frames */
function drawMap(now) {
  const animating = now < MAP.animUntil || MAP.prog < 1 || MAP.fading;
  if (!MAP.dirty && !animating) return false;
  if (now - MAP.lastDraw < MAP_MIN_DT) return true;     // 30 fps cap (also for data-driven redraws); ask for another frame
  MAP.lastDraw = now; MAP.dirty = false;
  const c = el("map"), g = c.getContext("2d"), k = MAP.k, W = c.width, H = c.height;
  const me = el("meDot");
  g.clearRect(0, 0, W, H);
  if (!MAP.xy) { setCls(me, "on", false); return false; }
  const P = MAP.xy, n = P.length;
  if (MAP.prog < 1) {                                      // the pen drawing the track (first 1.8 s only)
    MAP.prog = clamp((now - MAP.t0) / 1800, 0, 1);
    if (MAP.prog < 1) {
      const upto = Math.max(2, Math.floor(ease(MAP.prog) * n));
      strokeTrack(g, P, upto, W, H, k, false);
      const h = P[upto - 1]; g.fillStyle = "rgba(255,216,118,.35)"; g.beginPath(); g.arc(h[0], h[1], 12 * k, 0, 7); g.fill();
      g.fillStyle = "#fff"; g.beginPath(); g.arc(h[0], h[1], 6 * k, 0, 7); g.fill();
      setCls(me, "on", false);
      return true;
    }
  }
  g.drawImage(mapLayer(W, H, k), 0, 0);
  if (!T) { setCls(me, "on", false); return false; }
  const myIdx = T.me;
  let busy = false;
  // everyone else
  g.lineWidth = 2 * k; g.strokeStyle = "rgba(5,7,12,.9)";
  const labels = [];
  for (const [idx, s] of CARS) {
    const f = clamp((now - s.t0) / (s.dur || 110), 0, 1); s.shown = s.from + (s.to - s.from) * f;
    if (f < 1) busy = true;
    if (idx === myIdx) continue;
    const [x, y] = at(s.shown);
    g.globalAlpha = s.pit ? .35 : 1;
    g.fillStyle = s.col;
    g.beginPath(); g.arc(x, y, 6 * k, 0, 7); g.fill(); g.stroke();
    if ((T.ahead && String(s.num) === String(T.ahead)) || (T.behind && String(s.num) === String(T.behind))) labels.push([x, y, s.num]);
  }
  g.globalAlpha = 1;
  if (labels.length) { g.font = `700 ${11 * k}px Inter, sans-serif`; g.fillStyle = "#E5E7EB"; for (const [x, y, num] of labels) g.fillText("#" + num, x + 9 * k, y - 8 * k); }
  // you: comet trail on the canvas, the dot + pulsing ring are a DOM marker (CSS animation, no canvas work)
  const mine = CARS.get(myIdx);
  if (mine) {
    const [x, y] = at(mine.shown);
    const tr = MAP.trail, last = tr[tr.length - 1];
    if (!last || Math.abs(last[0] - x) + Math.abs(last[1] - y) > 0.5) { tr.push([x, y]); if (tr.length > 24) tr.shift(); }
    else if (tr.length > 1) tr.shift();                    // car stopped: let the comet tail shrink away, then stop drawing
    MAP.fading = tr.length > 1 && !busy;
    for (let i = 1; i < tr.length; i++) {
      const a = i / tr.length;
      g.strokeStyle = `rgba(255,216,118,${(a * a * .8).toFixed(2)})`; g.lineWidth = (2 + 7 * a) * k;
      g.beginPath(); g.moveTo(tr[i - 1][0], tr[i - 1][1]); g.lineTo(tr[i][0], tr[i][1]); g.stroke();
    }
    setStyle(me, "transform", `translate3d(${(x / k).toFixed(1)}px, ${(y / k).toFixed(1)}px, 0)`);
    setText("meN", T.pos || "");
    setCls(me, "on", true);
  } else setCls(me, "on", false);
  return busy || MAP.fading;
}

/* ================================================================ radio */
function onLog(m) {
  if (!m || !m.text) return;
  const f = el("feed"), e = document.createElement("div");
  e.className = "msg " + (m.kind === "you" ? "you" : "");
  e.innerHTML = `<span class="t"></span><span class="x"></span>`;
  e.querySelector(".t").textContent = m.t || ""; e.querySelector(".x").textContent = m.text;
  f.appendChild(e); while (f.children.length > 8) f.firstChild.remove();
  if (m.kind === "eng") { const s = el("slot"); s.classList.add("air"); clearTimeout(onLog._t); onLog._t = setTimeout(() => s.classList.remove("air"), Math.min(6000, 1500 + String(m.text).length * 55)); }
}

/* ================================================================ pit */
let DRAFT = null;
function onPit(s) {
  PIT = s;
  if (!s || !s.live) { setText("menuSum", "Not in a session"); return; }
  const met = s.metric !== false, u = met ? "L" : "gal", cv = (x) => (met ? x : x / 3.785);
  setText("sLaps", s.laps ?? "–"); setText("sBest", fmtLap(s.best));
  setText("sDeg", isNum(s.deg) ? (s.deg > 0 ? "+" : "") + s.deg.toFixed(2) : "–");
  const cm = (Array.isArray(s.complaints) ? s.complaints : []).slice(-3).reverse().map((c) => `<div class="cmp">L${esc(c.lap ?? "?")}${c.corner ? " · " + esc(c.corner) : ""}: ${esc(c.text)}</div>`).join("");
  const cmps = el("cmps"); if (cmps._h !== cm) { cmps._h = cm; cmps.innerHTML = cm; }
  const m = s.menu || {}, tyres = m.lf || m.rf || m.lr || m.rr;
  const parts = []; if (isNum(m.fuel) && m.fuel) parts.push(`${cv(m.fuel).toFixed(0)} ${u}`); if (tyres) parts.push(m.lf && m.rf && m.lr && m.rr ? "4 tyres" : "some tyres");
  if (m.ws) parts.push("tear-off"); if (m.fr) parts.push("repair");
  setText("menuSum", "In the car: " + (parts.length ? parts.join(" · ") : "nothing"));
  setCls(el("pitCard"), "ask", !!s.awaiting);
  const pj = s.plan ? JSON.stringify(s.plan) : null;
  if (pj && (!DRAFT || DRAFT._from !== pj)) DRAFT = Object.assign({}, s.plan, { _from: pj });
  if (!DRAFT) DRAFT = { fuel: m.fuel || 0, tyres: !!tyres, ws: !!m.ws, fr: !!m.fr, pressure: null };
  paintDraft();
}
function paintDraft() {
  if (!DRAFT || !PIT) return;
  const met = PIT.metric !== false;
  setText("pFuel", !isNum(DRAFT.fuel) ? "–" : DRAFT.fuel >= 900 ? "FULL" : (met ? DRAFT.fuel : DRAFT.fuel / 3.785).toFixed(met ? 0 : 1));
  setText("pFuelU", met ? "LITRES" : "GALLONS");
  setCls(el("pTyres"), "on", !!DRAFT.tyres); setCls(el("pWs"), "on", !!DRAFT.ws); setCls(el("pFr"), "on", !!DRAFT.fr);
  const p = DRAFT.pressure; setCls(el("pPress"), "on", !!p);
  setText("pPress", p ? `${p.end === "front" ? "Fronts" : "Rears"} −0.5 psi` : "Pressure");
}
function esc(s) { return String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }
async function post(path, body) {
  try {
    const ctl = typeof AbortController !== "undefined" ? new AbortController() : null;
    const to = ctl && setTimeout(() => ctl.abort(), 8000);
    const r = await fetch(`${path}?k=${encodeURIComponent(KEY)}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal: ctl && ctl.signal });
    clearTimeout(to);
    return await r.json();
  } catch (e) { return null; }
}
function wirePit() {
  const tap = (id, fn) => el(id).addEventListener("click", fn);
  const tank = () => (PIT && PIT.tank) || 0;
  const step = () => (PIT && PIT.metric === false ? 3.785 : 1);
  tap("pPlan", async () => { const r = await post("/api/pit", { action: "propose" }); if (r && r.state) { DRAFT = null; onPit(r.state); } });
  tap("fMinus", () => { if (!DRAFT) return; DRAFT.fuel = Math.max(0, (DRAFT.fuel >= 900 ? tank() : DRAFT.fuel || 0) - step()); paintDraft(); });
  tap("fPlus", () => { if (!DRAFT) return; DRAFT.fuel = Math.min(tank() || 999, (DRAFT.fuel >= 900 ? 0 : DRAFT.fuel || 0) + step()); paintDraft(); });
  tap("pTyres", () => { if (!DRAFT) return; DRAFT.tyres = !DRAFT.tyres; if (!DRAFT.tyres) DRAFT.pressure = null; paintDraft(); });
  tap("pWs", () => { if (!DRAFT) return; DRAFT.ws = !DRAFT.ws; paintDraft(); });
  tap("pFr", () => { if (!DRAFT) return; DRAFT.fr = !DRAFT.fr; paintDraft(); });
  tap("pPress", () => { if (!DRAFT) return; const p = DRAFT.pressure; DRAFT.pressure = !p ? { end: "front", psi: -0.5 } : p.end === "front" ? { end: "rear", psi: -0.5 } : null; if (DRAFT.pressure) DRAFT.tyres = true; paintDraft(); });
  tap("pClear", async () => { const r = await post("/api/pit", { action: "clear" }); DRAFT = null; if (r && r.state) onPit(r.state); });
  tap("pSend", async () => {
    if (!DRAFT) return;
    const { fuel, tyres, ws, fr, pressure } = DRAFT;
    const r = await post("/api/pit", { action: "apply", plan: { fuel, tyres, ws, fr, pressure } });
    if (r && r.ok) { const s = el("sent"); s.classList.remove("go"); replay(s, "go"); }
    if (r && r.state) onPit(r.state);
  });
}

/* ================================================================ race plans A / B / C */
function ipRuns(r) {
  if (!r || !Array.isArray(r.plan) || !r.plan.length) return "";
  return r.plan.map((x, i) => `<div class="pp run ${x.done ? "done" : i === r.cur ? "rec" : ""}" style="animation-delay:${i * 80}ms"><b>${i + 1}</b>${esc(x.name)}${i === r.cur && r.active ? ` · lap ${Math.min(r.laps, x.laps)}/${x.laps}` : ` · ${x.laps} laps`}</div>`).join("");
}
function onStrat(s) {
  const box = el("sPlans");
  if (!s || ((!Array.isArray(s.plans) || !s.plans.length) && !s.runplan)) return;
  const plans = Array.isArray(s.plans) ? s.plans : [];
  const sig = JSON.stringify(plans.map((p) => p.text)) + s.rec + JSON.stringify(s.runplan || "");
  if (box.dataset.sig === sig) return;
  box.dataset.sig = sig;
  box.innerHTML = ipRuns(s.runplan) + plans.map((p, i) => {
    const beat = (p.outlook || []).filter((x) => x.beat).map((x) => "#" + esc(x.num));
    const det = Array.isArray(p.detail) ? p.detail : [];
    const short = det.length ? det.map((d) => "L" + d.lap + (d.tyres ? "·T" : "")).join(" ") : "no stop";
    return `<div class="pp ${i === s.rec ? "rec" : ""}" style="animation-delay:${i * 80}ms"><b>${esc(p.name)}</b>${p.stops} stop${p.stops === 1 ? "" : "s"} · ${short}${p.save ? ` · save ${p.save}%` : ""}${beat.length ? ` <em>› ${beat.join(" ")}</em>` : ""}</div>`;
  }).join("");
}

/* ================================================================ start */
setInterval(() => { if (!document.hidden) tickWatches(); }, 125);     // 8 beats a second, like a real movement
wirePit();
kick();
intro();
connect();
