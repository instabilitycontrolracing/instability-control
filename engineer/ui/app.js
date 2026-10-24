/* Race Engineer window - ApexHUD look. Talks to Python through pywebview (window.pywebview.api). */
"use strict";

/* ------------------------------------------------------------------ watch */
/* Port of ApexHUD-Native WatchRenderer: 100x100 viewBox, dial image, fluted polished bezel, live hands. */
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
  return `<svg class="watch" viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">
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
    <image href="assets/dial.png" x="-4.56" y="-4.56" width="109.12" height="109.12" preserveAspectRatio="xMidYMid slice"/>
  </g>
  ${sub(28.8, 47.65, -25)}${sub(70.75, 47.65, 15)}${sub(49.95, 71.35, 40)}
  <g class="h-hour"><line x1="50" y1="55" x2="50" y2="28" stroke="#9C7C45" stroke-width="3.6" stroke-linecap="round"/>
    <line x1="50" y1="55" x2="50" y2="28" stroke="#F2E8D0" stroke-width="2.8" stroke-linecap="round"/></g>
  <g class="h-min"><line x1="50" y1="55" x2="50" y2="16" stroke="#9C7C45" stroke-width="2.6" stroke-linecap="round"/>
    <line x1="50" y1="55" x2="50" y2="16" stroke="#F2E8D0" stroke-width="1.9" stroke-linecap="round"/></g>
  <g class="h-sec"><line x1="50" y1="60" x2="50" y2="13" stroke="#C5A572" stroke-width=".7" stroke-linecap="round"/>
    <circle cx="50" cy="19" r="1.2" fill="#C5A572"/></g>
  <circle cx="50" cy="50" r="2.3" fill="#E4C887"/><circle cx="50" cy="50" r="1.2" fill="#7A6240"/>
  <circle cx="50" cy="50" r="46" fill="none" stroke="url(#${P}bez)" stroke-width="8"/>
  <circle cx="50" cy="50" r="46" fill="none" stroke="url(#${P}dark)" stroke-width="8"/>
  ${flutes}
  <circle cx="50" cy="50" r="42" fill="none" stroke="rgba(0,0,0,.7)" stroke-width=".55"/>
  <circle cx="50" cy="50" r="49.9" fill="none" stroke="rgba(0,0,0,.45)" stroke-width=".4"/>
  <circle cx="50" cy="50" r="46" fill="none" stroke="url(#${P}gloss)" stroke-width="8"/>
</svg>`;
}

const watches = [];
function mountWatch(el, id) {
  el.innerHTML = watchSVG(id);
  const svg = el.querySelector("svg");
  watches.push({ h: svg.querySelector(".h-hour"), m: svg.querySelector(".h-min"), s: svg.querySelector(".h-sec") });
}
function tickWatches() {
  const d = new Date();
  const sod = d.getHours() * 3600 + d.getMinutes() * 60 + d.getSeconds() + d.getMilliseconds() / 1000;
  const sa = (sod % 60) * 6, ma = (sod / 60 % 60) * 6, ha = (sod / 3600 % 12) * 30;
  for (const w of watches) {
    w.h.setAttribute("transform", `rotate(${ha.toFixed(2)} 50 50)`);
    w.m.setAttribute("transform", `rotate(${ma.toFixed(2)} 50 50)`);
    w.s.setAttribute("transform", `rotate(${sa.toFixed(2)} 50 50)`);
  }
  // full frame rate only while you're looking at this window. In the background (e.g. while you drive)
  // the hands step 8 times a second, like the real watch, so the game keeps the CPU and GPU.
  if (document.hidden) setTimeout(tickWatches, 1000);
  else if (!document.hasFocus()) setTimeout(tickWatches, 125);
  else requestAnimationFrame(tickWatches);
}
const setIdle = () => document.body.classList.toggle("idle", document.hidden || !document.hasFocus());
window.addEventListener("focus", setIdle); window.addEventListener("blur", setIdle);
document.addEventListener("visibilitychange", setIdle);

/* ------------------------------------------------------------------ bridge */
const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
let api = null;

function makeMock() {
  // Browser preview only (no Python): fakes loading, a connection and some radio.
  let p = 0, q = [], state = { running: false };
  const S = { volume: 1, radio_strength: 1, device: "", spotter: true, gaps: true, gaps_every: 2, hold_in_corners: true,
    radio_button: null, team_button: null, autostart_engine: true, start_with_windows: false, splash: true,
    calls_pitlane: true, calls_drivers: true, low_sr_warn: true, calls_health: true, calls_fuel_extras: true,
    calls_practice_traffic: true, calls_sectors: true, calls_weather: true, calls_tyres: true, shift_beep: false, shift_pitch: 1400, shift_volume: 0.25, shift_point: 1.0, shift_length: 60, race_control: true, race_control_volume: 0.8, overlay_radio: true,
    lap_readout: [], binds: {}, chat_enabled: true, low_sr_below: 2, low_sr_rookies: false, sector_alert: 0.35,
    traffic_warn: 2.5, press_unit: "psi", press_step: 1, driver_name: "Angelo",
    calls_racecraft: true, pit_tones: true, hold_for_chat: true, net_warnings: true, auto_telemetry: true, fuel_buffer_laps: 0,
    sig_overlap: false, sig_spray: false, sig_revlimit: false, sig_launch: false,
    crowd_on: true, crowd_volume: 0.3, crowd_max_db: -18, crowd_mute: false, crowd_pa: true, crowd_heli: true, crowd_mute_pits: true, crowd_duck: true };   // crowd (2026-10-24)
  const push = (e) => q.push(e);
  return {
    get_state: async () => ({ settings: S, devices: ["Windows default", "Speakers (Yeti Stereo Microphone)", "Headphones (Bose 700)"], controllers: ["Thrustmaster Advanced Mode Racer"] }),
    poll: async () => { const out = q; q = []; return out; },
    toggle: async () => {
      state.running = !state.running;
      push({ t: "status", st: { state: state.running ? "waiting" : "stopped", running: state.running } });
      if (state.running) setTimeout(() => {
        push({ t: "status", st: { state: "connected", running: true, track: "Circuit de Spa-Francorchamps", car: "BMW M4 GT3 EVO", session: "Race", pos: 4, progress: .18, flag: "green" } });
        const lines = [["sys", "iRacing found."], ["eng", "Radio check, Loud and clear, loud and clear."], ["eng", "Formation lap, Mode formation, Mode formation."],
          ["eng", "Green green green."], ["eng", "Car left."], ["eng", "Three wide."], ["eng", "Clear sides."], ["you", "how's the gap to the car in front"],
          ["eng", "Car ahead 1.4, Closing."], ["eng", "Black and white flag, black and white flag, Raidillon."]];
        lines.forEach((l, i) => setTimeout(() => push({ t: "log", kind: l[0], text: l[1] }), 300 + i * 260));
        setTimeout(() => push({ t: "status", st: { state: "connected", running: true, track: "Circuit de Spa-Francorchamps", car: "BMW M4 GT3 EVO", session: "Race", pos: 3, progress: .24, flag: "green" } }), 2600);
      }, 900);
      return state.running;
    },
    set: async (k, v) => { S[k] = v; return true; }, ask: async (t) => { push({ t: "log", kind: "you", text: t }); return "x"; },
    radio_check: async () => push({ t: "log", kind: "eng", text: "Radio check, Radio check." }),
    demo: async () => true, capture: async (a) => { setTimeout(() => push({ t: "bind", attr: a, binding: { device: "Thrustmaster Advanced Mode Racer", button: 1 }, label: "Thrustmaster Advanced Mode Racer  -  button 2" }), 1500); },
    clear_binding: async () => true, capture_bind: async (a) => { setTimeout(() => push({ t: "bind", attr: "bind-" + a, binding: { device: "Thrustmaster Advanced Mode Racer", button: 4 } }), 1200); },
    clear_bind: async () => true, report_problem: async () => ({ ok: true }), open_url: async () => true, app_info: async () => ({ version: "0.62 beta" }),
    // crowd (2026-10-24): ?mock&crowd=none shows the "copy from SimHub" state
    crowd_state: async () => new URLSearchParams(location.search).get("crowd") === "none"
      ? { state: "no_sounds", sounds: 0, tracks: 0, status: "", playing: 0, simhub: true, copy: "" }
      : { state: "ready", sounds: 47, tracks: 3, status: "Circuit des 24 Heures du Mans: 12 grandstands", playing: 2, simhub: true, copy: "" },
    crowd_copy: async () => ({ ok: true, copied: 49, msg: "Copied 49 files" }), crowd_test: async () => ({ ok: true, msg: "Playing a quiet cheer" }),
    marks_list: async () => [{ id: "1", name: "Sample Driver", car: "91", when: "Oct 23" }], unmark_id: async () => true, open_log: async () => true, page_ready: async () => true, minimize: async () => {}, close: async () => {},
    ...(window.coachMock ? window.coachMock() : {}),   // coach (2026-10-24): Analysis + coach sample data
    ...mockTeam(push),                                             // memory (2026-10-24)
  };
}

/* memory (2026-10-24): browser mock of the Team tab - race memory, meeting facts, what-if, and a streamed answer.
   ?mock&ai=ready shows the team AI talking; plain ?mock shows the no-AI view; &mem=rough the similar-car fallback. */
function mockTeam(push) {
  const qs = new URLSearchParams(location.search), ai = qs.get("ai") || "missing", rough = qs.get("mem") === "rough";
  const ag = { sessions: 6, races: 2, laps: 118, best: 138.204, typical: 139.112, fuel_lap: 3.08, pit_loss: 27, tyre_deg: 0.04, spins: 0.7, offs: 2.2,
    trouble: [{ name: "Pouhon", lost: 0.41, sessions: 5 }, { name: "Bus Stop", lost: 0.24, sessions: 6 }, { name: "Les Combes", lost: 0.17, sessions: 4 }],
    hotspots: ["Bus Stop", "Raidillon"], finishes: [5, 8] };
  const mem = { car: "BMW M4 GT3 EVO", track: "Circuit de Spa-Francorchamps", live: false, source: rough ? "similar car (rough guide)" : "this car",
    from_cars: rough ? ["Mercedes-AMG GT3 2020"] : [], ag,
    sessions: [{ date: "2026-10-23 21:10", session: "Race", laps: 24, best: 138.61, pos: 5 }, { date: "2026-10-23 20:20", session: "Practice", laps: 31, best: 138.204 },
      { date: "2026-10-21 19:05", session: "Race", laps: 23, best: 139.02, pos: 8 }, { date: "2026-10-20 18:40", session: "Practice", laps: 40, best: 138.9 }] };
  const pre = { kind: "prerace", title: "Pre-race meeting", car: mem.car, track: mem.track, source: mem.source, sections: [
    { h: "Strategy", lines: [...(rough ? ["ROUGH GUIDE: no laps of this car here, so the strategy uses your laps in the Mercedes-AMG GT3 2020 (same class)."] : []),
      "Race length from this week's race in the schedule.", "Race: 60 minutes, about 26 laps. Fuel per lap 3.1 L, a full tank (100.0 L) lasts 32.5 laps; the race needs about 80.1 L.",
      "Plan A: 0 stops: no stop.", "Plan B: 1 stop: lap 13 (12 litres, tyres) (+41 s vs plan A).", "No stop needed: a tank covers the race.",
      "Tyre fade: about 0.04 s a lap slower for every lap on a set; over a 26-lap stint that's about 1.0 s a lap by the end.",
      "Learned from your own laps: fuel effect, tyre wear, pit lane loss. The rest uses standard values."] },
    { h: "Your history here", lines: ["6 sessions here (2 races), 118 laps, last on 2026-10-23 21:10.", "Best lap 2:18.204, typical 2:19.112.",
      "Where you usually lose time (your usual vs your best there): Pouhon +0.41 s; Bus Stop +0.24 s; Les Combes +0.17 s.",
      "On average 0.7 spins and 2.2 offs a session, most at Bus Stop, Raidillon.", "Recent finishes here: P5, P8."] },
    { h: "How to be fastest here", lines: ["Biggest gain: Pouhon, 0.41 s between your usual and your best there.",
      "Keep it on the track at Bus Stop: that's where most of your spins and offs happen.", "Consistency: your typical lap is 0.91 s off your best here."] },
    { h: "Car", lines: ["MECHANIC RECOMMENDATIONS (the only setup changes allowed):", "- Pouhon: Try: one click softer rear anti-roll bar."] },
    { h: "Your radio notes here", lines: ['2026-10-23 lap 9 at Pouhon: "rear loose on entry"', '2026-10-21 lap 4 at Bus Stop: "locking the fronts"'] }] };
  const deb = { kind: "debrief", title: "Race debrief", car: mem.car, track: mem.track, source: "this car", date: "2026-10-23 21:10", sections: [
    { h: "Result", lines: ["Finished P5 in class, started P9 (+4 places).", "Your best lap was 3rd fastest in class.", "iRating about +31."] },
    { h: "Laps and pace", lines: ["24 laps, 21 clean.", "Best 2:18.610, typical 2:19.300.", "Your best ever here is 2:18.204 (+0.406 s)."] },
    { h: "Stints and stops", lines: ["No stop.", "Stints: 24 laps."] },
    { h: "Incidents", lines: ["4 incident points.", "1 spin: Raidillon.", "2 offs (track limits): Bus Stop."] },
    { h: "Where the time went", lines: ["Time lost per corner (your usual vs your best there, clean laps):", "Pouhon: +0.38 s", "Bus Stop: +0.22 s"] },
    { h: "Fuel and tyres", lines: ["Fuel per lap 3.1 L (usual here 3.1 L).", "4.2 L left at the flag, about 1.4 laps.", "Tyre fade in your longest stint: 0.05 s a lap per lap."] },
    { h: "What you said on the radio", lines: ['lap 9 at Pouhon: "rear loose on entry"'] },
    { h: "Car", lines: ["Setup: spa_race_v2.", "MECHANIC RECOMMENDATIONS (the only setup changes allowed): none - the car is consistent, the time is in the driving."] }] };
  const say = "ENGINEER: Sixty minutes, about twenty-six laps, and one tank does it: plan A is no stop. Plan B, a stop on lap 13, only if something goes wrong.\n\nENGINEER: Your time is in Pouhon, four tenths between your usual and your best. And keep it clean at the Bus Stop, that's where the offs come.\n\nMECHANIC: You said the rear is loose into Pouhon. One click softer on the rear bar, that's the one change.";
  const stream = (text) => { let i = 0; const step = () => { if (i < text.length) { push({ t: "team_tok", text: text.slice(i, i + 6) }); i += 6; setTimeout(step, 18); } else push({ t: "team_done" }); }; step(); };
  return {
    team_open: async () => ({ state: ai, reason: ai === "missing" ? "AI not installed" : "" }), team_close: async () => true, team_reset: async () => true,
    meet_state: async () => ({ voice: false, live: false, want_live: false }), meet_voice: async () => true, meet_live: async () => false, meet_stop: async () => true,
    mem_state: async () => mem,
    team_meeting: async (kind) => ({ pack: kind === "debrief" ? deb : pre, team: ai, reason: ai === "missing" ? "AI not installed" : "" }),
    team_whatif: async (q) => /rain/i.test(q) ? { kind: "rain", lines: ["If it rains: take wets once the track is lightly wet.", "Track lightly wet: wets are about 6 s a lap faster. An extra stop costs ~48 s, so box if more than 8 laps are left."] }
      : /caution/i.test(q) ? { kind: "caution", lines: ["Under a caution a stop costs about 11 s instead of 27 s, because the field is slow.", "Plan A has no stop, so a caution only saves fuel; stay out."] }
      : /one stop/i.test(q) ? { kind: "stops", lines: ["1 stop: lap 13 (12 litres, tyres).", "That's 41 s slower than plan A over the race."] } : { lines: null },
    team_ask: async () => { setTimeout(() => stream(say), 300); return true; },
  };
}

function waitForApi() {
  return new Promise((res) => {
    if (window.pywebview && window.pywebview.api) return res(window.pywebview.api);
    let done = false;
    window.addEventListener("pywebviewready", () => { if (!done) { done = true; res(window.pywebview.api); } });
    setTimeout(() => { if (!done) { done = true; res(location.protocol === "file:" || location.search.includes("mock") ? makeMock() : (window.pywebview?.api || makeMock())); } }, 1500);
  });
}

/* ------------------------------------------------------------------ reveal */
/* The intro itself is drawn natively (engineer/intro.py). The page starts looking exactly like the
   intro's last frame (empty window, session bar plate, watch in the bar) and brings its content in on "reveal". */
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let revealed = false;
function reveal() {
  if (revealed) return; revealed = true;
  document.body.classList.add("ready");
  requestAnimationFrame(moveInk);
}
/* ------------------------------------------------------------------ app */
let S = {};
let curPanel = "radio", lastMain = "radio";
function showSettings(page) {
  if (page) $$(".set-tab").forEach((t) => t.classList.toggle("active", t.dataset.s === page));
  if (page) $$(".set-page").forEach((p) => p.classList.toggle("active", p.id === "sp-" + page));
  showPanel("settings");
  requestAnimationFrame(() => { window._segRefresh && window._segRefresh(); if (page === "calls" && window._showMarks) window._showMarks(); });
}

function toast(msg) {
  const t = $("#toast"); t.textContent = msg; t.classList.add("show");
  clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.remove("show"), 1800);
}

function moveInk() {
  const a = $(".tab.active"), ink = $("#tabInk"), nav = $("#tabs");
  if (!a) return;
  const r = a.getBoundingClientRect(), n = nav.getBoundingClientRect();
  ink.style.left = (r.left - n.left) + "px"; ink.style.width = r.width + "px";
}

function showPanel(name) {
  if (name === curPanel) return;
  const order = ["radio", "series", "analysis", "setup", "team", "settings"];
  if (name !== "settings") lastMain = name;
  const fwd = order.indexOf(name) > order.indexOf(curPanel);
  const old = $("#p-" + curPanel), nw = $("#p-" + name);
  old.classList.remove("active"); old.classList.toggle("left", fwd);
  nw.classList.remove("left");
  if (!fwd) { nw.style.transition = "none"; nw.classList.add("left"); nw.offsetWidth; nw.style.transition = ""; nw.classList.remove("left"); }
  nw.classList.add("active");
  curPanel = name;
  $$(".tab").forEach((t) => t.classList.toggle("active", t.dataset.p === name));
  $("#tabs").classList.toggle("none", name === "settings");
  $("#setBtn").classList.toggle("active", name === "settings");
  moveInk();
  if (name === "analysis" && window.anInit) setTimeout(() => window.anInit(), 380);
  if (name === "team" && window.tmOpen) window.tmOpen();
  if (name === "setup" && window.suOpen) window.suOpen();
  if (name === "series" && window.srOpen) window.srOpen();
}

function feed(kind, text) {
  kind = kind || "sys";
  const f = $("#feed");
  if (kind === "sys" && /^\[/.test(text) && !/error/i.test(text)) return;
  const d = new Date(), t = d.toTimeString().slice(0, 5);
  const el = document.createElement("div");
  el.className = "msg " + kind;
  if (kind === "sys" && text.startsWith("NOTE: ")) { kind = "note"; text = text.slice(6); }
  const who = kind === "eng" ? "ENGINEER" : kind === "you" ? "YOU" : kind === "note" ? "NOTE" : "";
  el.innerHTML = `<span class="t">${t}</span>${who ? `<span class="who">${who}</span>` : ""}<span class="x"></span>`;
  el.querySelector(".x").textContent = text;
  f.appendChild(el);
  while (f.children.length > 300) f.firstChild.remove();
  f.scrollTo({ top: f.scrollHeight, behavior: "smooth" });
  if (kind === "eng") onAir(Math.min(6000, 1400 + text.length * 55));
}

let lastPos = null, airing = false, lastChip = ["", "Off"];
function onAir(ms) {
  airing = true; paintChip();
  $("#barWatchSlot").classList.add("air");
  clearTimeout(onAir._t);
  onAir._t = setTimeout(() => { airing = false; paintChip(); $("#barWatchSlot").classList.remove("air"); }, ms);
}
let listening = false;
function paintChip() {
  const chip = $("#chip"); chip.className = "chip";
  const [cls, txt] = listening ? ["listen", "Listening"] : airing ? ["air", "On air"] : lastChip;
  if (cls) chip.classList.add(cls);
  $("#chipTxt").textContent = txt;
}
function status(st) {
  const on = !!st.running;
  const go = $("#go"); go.textContent = on ? "Stop" : "Start"; go.classList.toggle("on", on);
  const map = { connected: ["ok", "Connected"], waiting: ["wait", "Waiting"], stopped: ["", "Off"], error: ["", "Problem"] };
  lastChip = map[st.state] || ["", "Off"];
  paintChip();
  const conn = st.state === "connected";
  $("#vTrack").textContent = conn ? (st.track || "-") : (st.state === "waiting" ? "Waiting for iRacing" : "Engineer off");
  $("#vTrack").classList.toggle("dim", !conn);
  $("#vCar").textContent = conn ? ((st.car || "-") + (st.gtp ? "  ·  hybrid" : "")) : "-";
  $("#vCar").classList.toggle("dim", !conn);
  $("#vSess").textContent = conn && st.session ? st.session : "Session";
  const pos = $("#vPos");
  const p = conn && st.pos ? st.pos : null;
  pos.innerHTML = `<small>P</small>${p ?? "0"}`;
  pos.classList.toggle("none", p === null);
  if (p !== null && lastPos !== null && p !== lastPos) { pos.classList.add("bump"); setTimeout(() => pos.classList.remove("bump"), 420); }
  lastPos = p;
  $("#prog").style.width = conn && st.progress != null ? (Math.max(0, Math.min(1, st.progress)) * 100) + "%" : "0%";
  const flagCol = { yellow: "#FFC107", red: "#DC2626", blue: "#3B82F6", white: "#FFFFFF", checkered: "#FFFFFF" }[st.flag];
  const bar = $("#bar");
  bar.classList.toggle("flagged", !!flagCol);
  if (flagCol) bar.style.setProperty("--flag", flagCol);
}

function setRange(el, v, min, max) { el.value = v; el.style.setProperty("--p", ((v - min) / (max - min) * 100) + "%"); }
function radioName(x) { return x < .15 ? "Clean" : x < .8 ? "Light" : x <= 1.2 ? "Your pick" : x < 1.8 ? "Heavy" : "TV radio"; }
function bindLabel(b) { return b ? `${b.device}  ·  button ${b.button + 1}` : "Not set"; }

async function initUI(state) {
  S = state.settings;
  // tabs
  $$(".tab").forEach((t) => t.addEventListener("click", () => showPanel(t.dataset.p)));
  window.addEventListener("resize", moveInk);
  // header
  $("#go").addEventListener("click", async () => { await api.toggle(); });
  // radio
  const ask = async () => { const v = $("#ask").value.trim(); if (!v) return; $("#ask").value = ""; await api.ask(v); };
  $("#askBtn").addEventListener("click", ask);
  $("#ask").addEventListener("keydown", (e) => { if (e.key === "Enter") ask(); });
  $("#rc").addEventListener("click", () => api.radio_check());
  $("#demo").addEventListener("click", async () => {
    const b = $("#demo"); b.disabled = true; b.textContent = "Playing...";
    try { await api.demo(); } catch (e) {}
    b.disabled = false; b.textContent = "Demo race";
  });
  // sound
  const vol = $("#vol"), rad = $("#rad");
  setRange(vol, Math.round(S.volume * 100), 0, 150); $("#volR").textContent = Math.round(S.volume * 100) + "%";
  setRange(rad, Math.round(S.radio_strength * 100), 0, 200); $("#radR").textContent = radioName(S.radio_strength);
  vol.addEventListener("input", () => { setRange(vol, +vol.value, 0, 150); $("#volR").textContent = vol.value + "%"; api.set("volume", vol.value / 100); });
  rad.addEventListener("input", () => { setRange(rad, +rad.value, 0, 200); $("#radR").textContent = radioName(rad.value / 100); api.set("radio_strength", rad.value / 100); });
  $("#radReset").addEventListener("click", () => { setRange(rad, 100, 0, 200); $("#radR").textContent = "Your pick"; api.set("radio_strength", 1.0); });
  const dev = $("#dev");
  for (const d of state.devices) { const o = document.createElement("option"); o.value = o.textContent = d; dev.appendChild(o); }
  dev.value = S.device && state.devices.includes(S.device) ? S.device : "Windows default";
  dev.addEventListener("change", () => { api.set("device", dev.value === "Windows default" ? "" : dev.value); toast("Output changed"); });
  $("#test").addEventListener("click", () => api.radio_check());
  // Race Control page: shift beep tuning (2026-10-24)
  const sb = (id, key, min, max, toUi, fromUi, label) => {
    const el = $(id), r = $(id + "R");
    const v = toUi(S[key]); setRange(el, v, min, max); r.textContent = label(v);
    el.addEventListener("input", () => { setRange(el, +el.value, min, max); r.textContent = label(+el.value); S[key] = fromUi(+el.value); api.set(key, S[key]); });
  };
  sb("#sbPitch", "shift_pitch", 300, 3000, (x) => x || 1400, (x) => x, (v) => v + " Hz");
  sb("#sbVol", "shift_volume", 0, 60, (x) => Math.round((x ?? 0.25) * 100), (x) => x / 100, (v) => v + "%");
  sb("#sbPoint", "shift_point", 90, 104, (x) => Math.round((x || 1) * 100), (x) => x / 100, (v) => v === 100 ? "At the shift light" : v < 100 ? (100 - v) + "% early" : (v - 100) + "% late");
  sb("#sbLen", "shift_length", 30, 250, (x) => x || 60, (x) => x, (v) => v + " ms");
  $("#sbTest").addEventListener("click", () => api.beep_test && api.beep_test());
  sb("#rcVol", "race_control_volume", 0, 100, (x) => Math.round((x ?? 0.8) * 100), (x) => x / 100, (v) => v + "%");
  $("#rcTest").addEventListener("click", () => api.rc_test && api.rc_test());
  // crowd (2026-10-24): Trackside crowd card
  sb("#crowdVol", "crowd_volume", 0, 100, (x) => Math.round((x ?? 0.3) * 100), (x) => x / 100, (v) => v + "%");
  sb("#crowdMax", "crowd_max_db", -48, -6, (x) => Math.round(x ?? -18), (x) => x, (v) => "\u2212" + Math.abs(v) + " dB");
  const crowdShow = (c) => {
    const el = $("#crowdStatus"); if (!c) return;
    let t, cls = "";
    if (c.device_error) { t = "Sound device problem, so the crowd stays silent: " + c.device_error; cls = "bad"; }
    else if (c.state === "loading") t = "Loading the crowd sounds\u2026";
    else if (c.state === "no_sounds") t = c.simhub ? "No crowd sounds here yet. Copy them from SimHub (it copies, nothing is moved or deleted)." : "No crowd sounds yet, and no SimHub Trackside Crowd found. Put your .wav files in Trackside\\sounds.";
    else if (c.state === "off") t = "Crowd not running.";
    else { t = `${c.sounds} sounds \u00b7 ${c.tracks} track files` + (c.status ? ` \u00b7 ${c.status}` : "") + ` \u00b7 ${c.playing} playing`; cls = "ok"; }
    if (c.copy) t += "  \u2014  " + c.copy;
    el.textContent = t; el.className = "g61-status" + (cls ? " " + cls : "");
    $("#crowdCopy").disabled = !c.simhub;
  };
  const crowdPoll = async () => {
    if (!api.crowd_state || curPanel !== "settings" || !$("#sp-racecontrol").classList.contains("active")) return;
    try { crowdShow(await api.crowd_state()); } catch (e) {}
  };
  setInterval(crowdPoll, 1500);
  $$('.set-tab[data-s="racecontrol"]').forEach((t) => t.addEventListener("click", () => setTimeout(crowdPoll, 50)));
  $("#crowdCopy").addEventListener("click", async () => {
    const b = $("#crowdCopy"); b.disabled = true; toast("Copying the crowd sounds\u2026");
    try { const r = await api.crowd_copy(); toast(r && r.msg ? r.msg : "Done"); } catch (e) { toast("Couldn't copy"); }
    b.disabled = false; crowdPoll();
  });
  $("#crowdTest").addEventListener("click", async () => {
    try { const r = await api.crowd_test(); toast(r && r.msg ? r.msg : "Test"); } catch (e) {}
  });
  const spv = $("#spotVoice");
  for (const n of state.spotters_builtin || []) { const o = document.createElement("option"); o.value = n; o.textContent = n; spv.appendChild(o); }
  for (const n of state.spotters || []) { const o = document.createElement("option"); o.value = "cc:" + n; o.textContent = n + " (from your CrewChief)"; spv.appendChild(o); }
  const spName = (S.spotter_voice || "");
  const want = (state.spotters_builtin || []).includes(spName) ? spName : (state.spotters || []).includes(spName.replace(/^cc:/, "")) ? "cc:" + spName.replace(/^cc:/, "") : "";
  spv.value = want;
  spv.addEventListener("change", () => { S.spotter_voice = spv.value; api.set("spotter_voice", spv.value); });
  $("#spotTest").addEventListener("click", () => api.spot_test && api.spot_test());
  const sv = $("#stratVoice");
  sv.value = S.strat_voice || "chatterbox";
  sv.addEventListener("change", () => { S.strat_voice = sv.value; api.set("strat_voice", sv.value); });
  $("#stratTest").addEventListener("click", () => api.strat_test && api.strat_test());
  const mic = $("#mic");
  for (const d of state.mics || ["Windows default"]) { const o = document.createElement("option"); o.value = o.textContent = d; mic.appendChild(o); }
  mic.value = S.mic_device && (state.mics || []).includes(S.mic_device) ? S.mic_device : "Windows default";
  mic.addEventListener("change", () => { api.set("mic_device", mic.value === "Windows default" ? "" : mic.value); toast("Microphone changed"); });
  // switches
  $$(".sw").forEach((sw) => {
    const k = sw.dataset.k; sw.classList.toggle("on", !!S[k]);
    sw.addEventListener("click", () => { S[k] = !S[k]; sw.classList.toggle("on", S[k]); api.set(k, S[k]); });
  });
  // gap segments
  const seg = $("#seg"), btns = [...seg.querySelectorAll("button")];
  const segSet = (v) => {
    btns.forEach((b) => b.classList.toggle("active", +b.textContent === v));
    const a = btns.find((b) => +b.textContent === v) || btns[1];
    seg.querySelector(".ink").style.left = a.offsetLeft + "px";
  };
  btns.forEach((b) => b.addEventListener("click", () => { segSet(+b.textContent); api.set("gaps_every", +b.textContent); }));
  // buttons
  for (const a of ["radio_button", "team_button"]) {
    const el = $("#b-" + a); el.textContent = bindLabel(S[a]); el.classList.toggle("unset", !S[a]);
  }
  $$("[data-set]").forEach((b) => b.addEventListener("click", () => {
    const a = b.dataset.set, el = $("#b-" + a);
    el.textContent = "Press a button…"; el.className = "bind grow listening";
    api.capture(a);
  }));
  $$("[data-clear]").forEach((b) => b.addEventListener("click", () => {
    const a = b.dataset.clear, el = $("#b-" + a); api.clear_binding(a);
    el.textContent = "Not set"; el.className = "bind grow unset";
  }));
  // generic segment pickers (Settings > Calls > Sensitivity)
  const PRESS = { psi: ["0.5", "1", "2"], kpa: ["1", "3", "5"] };
  const buildSeg = (el) => {
    const k = el.dataset.k;
    const vals = el.id === "pressStep" ? PRESS[S.press_unit === "kpa" ? "kpa" : "psi"] : el.dataset.vals.split(",");
    const labels = el.dataset.labels ? el.dataset.labels.split(",") : vals.map((v) => v + (el.dataset.suf || ""));
    el.innerHTML = `<div class="ink"></div>` + vals.map((v, i) => `<button data-v="${v}">${labels[i]}</button>`).join("");
    const pick = (v) => {
      const bs = [...el.querySelectorAll("button")];
      const a = bs.find((b) => String(b.dataset.v) === String(v)) || bs.find((b) => +b.dataset.v === +v);
      bs.forEach((b) => b.classList.toggle("active", b === a));
      const ink = el.querySelector(".ink");
      ink.style.opacity = a ? 1 : 0;
      if (a) { ink.style.left = a.offsetLeft + "px"; ink.style.width = a.offsetWidth + "px"; }
    };
    el.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
      const v = isNaN(+b.dataset.v) ? b.dataset.v : +b.dataset.v;
      S[k] = v; api.set(k, v); pick(v);
      if (k === "press_unit") { S.press_step = v === "kpa" ? 3 : 1; api.set("press_step", S.press_step); buildSeg($("#pressStep")); }
    }));
    el._pick = () => pick(S[k]);
    requestAnimationFrame(el._pick);
  };
  $$(".seg.gen").forEach(buildSeg);
  window._segRefresh = () => $$(".seg.gen").forEach((el) => el._pick && el._pick());
  // marked drivers
  const showMarks = async () => {
    let list = [];
    try { list = (await api.marks_list()) || []; } catch (e) {}
    const box = $("#marks");
    if (!list.length) { box.innerHTML = `<div class="empty">Nobody marked yet.</div>`; return; }
    box.innerHTML = list.map((m) => `<div class="mark-row"><span class="num">#${m.car || "?"}</span><span class="who"></span>
      <span class="when">${m.when || ""}</span><button class="btn sm" data-unmark="${m.id}">Remove</button></div>`).join("");
    [...box.querySelectorAll(".who")].forEach((el, i) => (el.textContent = list[i].name || "Driver"));
    box.querySelectorAll("[data-unmark]").forEach((b) => b.addEventListener("click", async () => { await api.unmark_id(b.dataset.unmark); showMarks(); }));
  };
  window._showMarks = showMarks;
  showMarks();
  // per-lap readout chips
  const lr = new Set(S.lap_readout || []);
  $$("#lapReadout button").forEach((b) => {
    b.classList.toggle("on", lr.has(b.dataset.v));
    b.addEventListener("click", () => {
      lr.has(b.dataset.v) ? lr.delete(b.dataset.v) : lr.add(b.dataset.v);
      b.classList.toggle("on", lr.has(b.dataset.v));
      S.lap_readout = [...lr]; api.set("lap_readout", S.lap_readout);
    });
  });
  // command buttons (wheel button -> question)
  const CMDS = [["say_again", "Say again"], ["gap_ahead", "Gap ahead"], ["gap_behind", "Gap behind"], ["position", "Position"],
    ["fuel", "Fuel"], ["laps_left", "Laps left"], ["pit_plan", "Box plan"], ["pit_out", "Where we come out"],
    ["damage", "Damage"], ["tyres", "Tyres"], ["irating", "iRating"], ["weather", "Weather"],
    ["mark_behind", "Mark car behind"], ["mark_ahead", "Mark car ahead"], ["quiet", "Radio quiet"], ["talk", "Radio back on"]];
  const binds = S.binds || {};
  $("#cmdBinds").innerHTML = CMDS.map(([k, n]) => `<div class="cmd-row"><span class="name">${n}</span>
    <div class="bind grow ${binds[k] ? "" : "unset"}" id="b-bind-${k}">${bindLabel(binds[k])}</div>
    <button class="btn gold sm" data-bset="${k}">Set</button><button class="btn sm" data-bclear="${k}">Clear</button></div>`).join("");
  $$("[data-bset]").forEach((b) => b.addEventListener("click", () => {
    const el = $("#b-bind-" + b.dataset.bset); el.textContent = "Press a button…"; el.className = "bind grow listening";
    api.capture_bind(b.dataset.bset);
  }));
  $$("[data-bclear]").forEach((b) => b.addEventListener("click", () => {
    const el = $("#b-bind-" + b.dataset.bclear); api.clear_bind(b.dataset.bclear);
    el.textContent = "Not set"; el.className = "bind grow unset";
  }));
  ctrls(state.controllers);
  $("#log").addEventListener("click", () => api.open_log());
  // driver name, report a problem, about links
  const dn = $("#driverName");
  dn.value = S.driver_name || "";
  dn.addEventListener("change", () => { const v = dn.value.trim(); S.driver_name = v; api.set("driver_name", v); toast(v ? "Name saved" : "Name cleared"); });
  $("#report").addEventListener("click", async () => {
    toast("Saving the report…");
    try { const r = await api.report_problem(); toast(r && r.ok ? "Report saved to your Desktop" : "Couldn't save the report"); } catch (e) { toast("Couldn't save the report"); }
  });
  $$("[data-url]").forEach((b) => b.addEventListener("click", () => api.open_url(b.dataset.url)));
  try { const ai = await api.app_info(); if (ai) $("#aboutVer").textContent = ai.version; } catch (e) {}
  // settings area + tutorial
  $("#setBtn").addEventListener("click", () => (curPanel === "settings" ? showPanel(lastMain) : showSettings()));
  $("#setClose").addEventListener("click", () => showPanel(lastMain));
  $$(".set-tab").forEach((t) => t.addEventListener("click", () => showSettings(t.dataset.s)));
  $("#helpBtn").addEventListener("click", () => window.tourStart && window.tourStart());
  // iPad link + QR (Settings > General)
  try { const ri = await api.remote_info(); if (ri && ri.on) { $("#ipadUrl").textContent = ri.url; if (ri.qr) $("#ipadQr").src = ri.qr; } else $("#ipadUrl").textContent = "Off"; } catch (e) {}
  requestAnimationFrame(() => { moveInk(); segSet(S.gaps_every); });
}

function ctrls(names) {
  const c = $("#ctrls");
  const key = JSON.stringify(names || []);
  if (c.dataset.k === key) return;
  c.dataset.k = key;
  c.innerHTML = names && names.length ? names.map((n) => `<div class="ctrl"></div>`).join("") : `<div class="empty">None found</div>`;
  [...c.querySelectorAll(".ctrl")].forEach((el, i) => (el.textContent = names[i]));
}

async function pump() {
  try {
    const evs = await api.poll();
    for (const e of evs || []) {
      if (e.t === "log") feed(e.kind, e.text);
      else if (e.t === "status") status(e.st);
      else if (e.t === "bind") { const el = $("#b-" + e.attr); el.textContent = bindLabel(e.binding); el.className = "bind grow"; toast("Button saved"); }
      else if (e.t === "controllers") ctrls(e.names);
      else if (e.t === "toast") toast(e.text);
      else if (e.t === "reveal") reveal();
      else if (e.t === "goto") (["sound", "calls", "buttons", "general"].includes(e.tab) ? showSettings(e.tab) : showPanel(e.tab));
      else if (e.t === "an_ref" && window.anRefUpdate) window.anRefUpdate(e);
      else if ((e.t === "prep_stats" || e.t === "prep_prog") && window.srEvent) window.srEvent(e);
      else if (e.t === "pit_state" && window.pcState) window.pcState(e.s);
      else if (e.t === "strat" && window.pcStrat) window.pcStrat(e.s);
      else if (e.t === "ptt") { listening = e.on; paintChip(); $("#barWatchSlot").classList.toggle("listen", e.on); }
      else if (e.t === "team_heard" && window.tmHeard) window.tmHeard(e.text);
      else if (e.t && e.t.startsWith("meet_") && window.mtEvent) window.mtEvent(e);
      else if (e.t && e.t.startsWith("team_") && window.tmEvent) window.tmEvent(e);
      else if ((e.t === "mem" || e.t === "mem_review") && window.mmEvent) window.mmEvent(e);   // memory (2026-10-24)
    }
  } catch (err) {}
  setTimeout(pump, document.body.classList.contains("idle") ? 300 : 120);
}

// 2026-10-24: any script error is written to the engineer log, and the window always shows itself
window.addEventListener("error", (e) => { try { api && api.js_error && api.js_error(String(e.message) + " @ " + (e.filename || "").split("/").pop() + ":" + e.lineno); } catch (x) {} });
window.addEventListener("unhandledrejection", (e) => { try { api && api.js_error && api.js_error("promise: " + String(e.reason && (e.reason.stack || e.reason))); } catch (x) {} });
function withTimeout(p, ms) { return Promise.race([p, new Promise((_, rej) => setTimeout(() => rej(new Error("timed out")), ms))]); }
(async function main() {
  setTimeout(reveal, window.pywebview ? 9000 : 400);   // safety net first, so nothing below can leave the window empty
  requestAnimationFrame(tickWatches); setIdle();
  api = await waitForApi();
  let state;
  try { state = await withTimeout(api.get_state(), 6000); } catch (e) { state = { settings: {}, devices: ["Windows default"], controllers: [] }; try { api.js_error("get_state: " + e); } catch (x) {} }
  mountWatch($("#barWatchSlot"), "bar");
  try { await initUI(state); } catch (e) { try { api.js_error("initUI: " + (e.stack || e)); } catch (x) {} }
  // tell Python the page is painted, so the intro can hand over to the real window
  try { await document.fonts.ready; } catch (e) {}
  await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
  try { await api.page_ready(); } catch (e) {}
  pump();
  // window controls (no Windows title bar: the bar is the drag handle)
  $("#wMin").addEventListener("click", () => api.minimize && api.minimize());
  $("#wMax").addEventListener("click", () => api.toggle_max && api.toggle_max());
  // drag the window from the top bar (our own move: the built-in drag region didn't move it)
  let drag = null, dragQueued = false;
  $("#bar").addEventListener("mousedown", async (e) => {
    if (e.button !== 0 || e.detail > 1 || e.target.closest("button, input, select, a, .winctl") || !api.win_pos) return;
    const p = await api.win_pos();
    drag = { sx: e.screenX, sy: e.screenY, wx: p[0], wy: p[1], x: e.screenX, y: e.screenY };
  });
  document.addEventListener("mousemove", (e) => {
    if (!drag) return;
    drag.x = e.screenX; drag.y = e.screenY;
    if (dragQueued) return; dragQueued = true;
    requestAnimationFrame(() => { dragQueued = false; if (drag) api.win_move(drag.wx + drag.x - drag.sx, drag.wy + drag.y - drag.sy); });
  });
  document.addEventListener("mouseup", () => { drag = null; });
  $("#bar").addEventListener("dblclick", (e) => { if (!e.target.closest("button")) api.toggle_max && api.toggle_max(); });
  $("#wClose").addEventListener("click", () => api.close && api.close());
  $$(".sessionbar button, .winctl button").forEach((b) => b.addEventListener("mousedown", (e) => e.stopPropagation()));
})();

window.showPanel = showPanel; window.showSettings = showSettings;
