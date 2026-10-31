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
  const S = { volume: 1, radio_strength: 1, radio_realism: true, device: "", spotter: true, gaps: true, gaps_every: 2, hold_in_corners: true,
    radio_button: null, team_button: null, autostart_engine: true, start_with_windows: false, splash: true,
    calls_pitlane: true, calls_drivers: true, low_sr_warn: true, calls_health: true, calls_fuel_extras: true,
    calls_practice_traffic: true, calls_sectors: true, calls_weather: true, calls_tyres: true, shift_beep: false, shift_pitch: 1400, shift_volume: 0.25, shift_point: 1.0, shift_length: 60, race_control: true, race_control_volume: 0.8, overlay_radio: true,
    lap_readout: [], binds: {}, chat_enabled: true, low_sr_below: 2, low_sr_rookies: false, sector_alert: 0.35,
    traffic_warn: 2.5, press_unit: "psi", press_step: 1, driver_name: "", driver_name_say: "",
    calls_racecraft: true, calls_fight_coach: true, pit_tones: true, hold_for_chat: true, net_warnings: true, auto_telemetry: true, fuel_buffer_laps: 0, vault_on: true, vault_drive_on: true, vault_drive_quota_gb: 8, vault_dir: "", vault_drive_dir: "G:\\My Drive\\Instability Control\\Telemetry",
    sig_overlap: false, sig_spray: false, sig_revlimit: false, sig_launch: false,
    crowd_on: true, crowd_volume: 0.3, crowd_max_db: -18, crowd_mute: false, crowd_pa: true, crowd_heli: true, crowd_heli_cabin: true, crowd_ambience: true, crowd_mute_pits: true, crowd_duck: true,
    snd_hp_eq: true, snd_hp_db: 0, snd_tv_db: 0, snd_tv_game: true, snd_tv_mute: false, snd_tv_delay_ms: 0, bcast_on: true, bcast_keyup: true, bcast_crowd: true, bcast_grit: 1, bcast_db: 6, bcast_crowd_db: 0, snd_engine: 0, snd_detail: 0, snd_per_car: true, shaker_on: false, shaker_device: "", shaker_gain: 0.6, shaker_engine: true, shaker_shifts: true, shaker_kerbs: true, shaker_abs: true, shaker_impacts: true, snd_tv_ht: true, snd_tv_ht_live: true, snd_tv_night: false, snd_trackside_space: true, crowd_helmet: true, shaker_limiter: true, pedal_on: false, pedal_device: "", pedal_gain: 0.6, pedal_engine: false, pedal_shifts: false, pedal_kerbs: true, pedal_abs: true, pedal_impacts: false, pedal_limiter: true, crowd_hero: "", radio_replay: true, fan_on: false, fan_kind: "url", fan_url: "", fan_plug: "", snd_driving_space: true, radio_pitwall: true, cockpit_on: true, cockpit_volume: 50, cockpit_wind: true, cockpit_rain: true, cockpit_heart: false, lights_on: false, lights_kind: "hue", hue_sync: false, hue_left: "", hue_right: "", hue_desk: "", hue_left_job: "both", hue_right_job: "both", hue_desk_job: "picture", lights_host: "", lights_bri: 80, lights_idle: 30, hue_lights: "" };   // crowd (2026-10-24), sound mix (2026-10-25)
  const push = (e) => q.push(e);
  return {
    get_state: async () => ({ settings: S, devices: ["Windows default", "Speakers (Yeti Stereo Microphone)", "Headphones (Bose 700)"], controllers: ["Thrustmaster Advanced Mode Racer"] }),
    // browser preview only (placeholder values, not read from any PC)
    reshade_state: async () => ({ installed: true, layer: "off", preset: "Day", presets: ["Off", "Day", "Night"], ini: "ReShadeVR.ini", sim_running: false, others: [],
      sliders: [{ fx: "Example.fx", name: "Vibrance", label: "Vibrance", min: -1, max: 1, step: 0.01, value: 0.35 }, { fx: "Example.fx", name: "Contrast", label: "Contrast", min: -0.5, max: 0.5, step: 0.01, value: 0.08 }],
      keys: { text: "Scroll Lock turns the effects on/off" }, vibrance: { script: true, keep: false, level: 70, display: "DISPLAY1" } }),
    reshade_layer: async (on) => ({ ok: true, msg: "preview", state: null }), reshade_preset: async () => ({ ok: true, msg: "preview", state: null }),
    reshade_uniform: async () => ({ ok: true, msg: "saved", state: null }), vibrance_apply: async () => ({ ok: true, msg: "preview" }),

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
    ...(window.fxMock ? window.fxMock(push) : {}),                 // forensics (2026-10-27): tests/make_fx_sample.py writes ui/fx_mock.js (not shipped)
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
  const order = ["radio", "series", "analysis", "setup", "team", "timing", "settings"];
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
  if (name === "timing") tiOpen();
}

// timing tab: the timing / session screen served by the iPad link, in a frame; POP OUT opens its own window
// 2026-10-27: was also called tmOpen, which replaced the Team tab's tmOpen (team.js) - the Team tab's buttons never got wired
async function tiOpen() {
  const fr = $("#tmFrame"); if (!fr || fr.dataset.ok) return;
  try {
    const a = api || await waitForApi(); const url = a.timing_url ? await a.timing_url() : null;
    if (url) { fr.src = url; fr.dataset.ok = "1"; } else fr.parentElement.classList.add("off");
  } catch (e) { fr.parentElement.classList.add("off"); }
}
window.addEventListener("message", async (e) => {
  if (e.data && e.data.timing === "popout") { try { const a = api || await waitForApi(); if (a.open_timing) a.open_timing(e.data.view || null); } catch (x) {} }
});

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
  $("#vTrack").textContent = conn ? (st.track_full || st.track || "-") : (st.state === "waiting" ? "Waiting for iRacing" : "Engineer off");
  $("#vSessL").textContent = conn && st.session ? st.session : "Track";
  const lg = $("#vLogo"), th = conn ? st.theme : null;              // 2026-10-26: the track logo, like the iPad's strip
  if (th && th.logo) {
    if (lg.dataset.src !== th.logo) { lg.dataset.src = th.logo; lg.classList.remove("on"); lg.onload = () => lg.classList.add("on"); lg.src = th.logo; }
    lg.classList.toggle("light", !!th.dark);
  } else if (lg.dataset.src) { lg.dataset.src = ""; lg.classList.remove("on"); lg.removeAttribute("src"); }
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
  // #515: up to 3x; 2026-10-31 (Angelo: "up to 3 times as loud as it currently is", he sits at 150 %): up to 500 %.
  // The peak limiter keeps it from clipping. (The readout line used to sit inside this comment, so it never showed.)
  setRange(vol, Math.round(S.volume * 100), 0, 500); $("#volR").textContent = Math.round(S.volume * 100) + "%";
  setRange(rad, Math.round(S.radio_strength * 100), 0, 200); $("#radR").textContent = radioName(S.radio_strength);
  vol.addEventListener("input", () => { setRange(vol, +vol.value, 0, 500); $("#volR").textContent = vol.value + "%"; api.set("volume", vol.value / 100); });
  rad.addEventListener("input", () => { setRange(rad, +rad.value, 0, 200); $("#radR").textContent = radioName(rad.value / 100); api.set("radio_strength", rad.value / 100); });
  $("#radReset").addEventListener("click", () => { setRange(rad, 100, 0, 200); $("#radR").textContent = "Your pick"; api.set("radio_strength", 1.0); });
  const dev = $("#dev");
  for (const d of state.devices) { const o = document.createElement("option"); o.value = o.textContent = d; dev.appendChild(o); }
  dev.value = S.device && state.devices.includes(S.device) ? S.device : "Windows default";
  dev.addEventListener("change", () => { api.set("device", dev.value === "Windows default" ? "" : dev.value); toast("Output changed"); });
  $("#test").addEventListener("click", () => api.radio_check());
  // bass shaker (2026-10-26, #211)
  (() => {
    const sel = $("#shDev"); if (!sel) return;
    const none = document.createElement("option"); none.value = ""; none.textContent = "Pick the shaker's output"; sel.appendChild(none);
    for (const d of state.devices.filter((x) => x !== "Windows default")) { const o = document.createElement("option"); o.value = o.textContent = d; sel.appendChild(o); }
    sel.value = S.shaker_device || "";
    sel.addEventListener("change", () => { S.shaker_device = sel.value; api.set("shaker_device", sel.value).then(shStat); });
    const g = $("#shGain"), gr = $("#shGainR");
    const gv = Math.round((S.shaker_gain ?? 0.6) * 100); setRange(g, gv, 0, 150); gr.textContent = gv + "%";
    g.addEventListener("input", () => { setRange(g, +g.value, 0, 150); gr.textContent = g.value + "%"; api.set("shaker_gain", g.value / 100); });
    const shStat = () => api.shaker_state().then((r) => { const e = $("#shStatus"); if (e && r) e.textContent = r.status === "off" ? "Off" : r.status; }).catch(() => {});
    $("#shTest").addEventListener("click", () => api.shaker_test().then((r) => toast(r && r.ok ? "Shaker test: 2 s rising rumble" : "Turn the shaker on and pick its output first")));
    setTimeout(shStat, 800); setInterval(shStat, 5000);
  })();
  // D11 pedals / cushion transducer (2026-10-26, #249)
  (() => {
    const sel = $("#pdDev"); if (!sel) return;
    const none = document.createElement("option"); none.value = ""; none.textContent = "Pick its output"; sel.appendChild(none);
    for (const d of state.devices.filter((x) => x !== "Windows default")) { const o = document.createElement("option"); o.value = o.textContent = d; sel.appendChild(o); }
    sel.value = S.pedal_device || "";
    const st = () => api.pedal_state().then((r) => { const e = $("#pdStatus"); if (e && r) e.textContent = r.status === "off" ? "Off" : r.status; }).catch(() => {});
    sel.addEventListener("change", () => { S.pedal_device = sel.value; api.set("pedal_device", sel.value).then(st); });
    const g = $("#pdGain"), gr = $("#pdGainR");
    const gv = Math.round((S.pedal_gain ?? 0.6) * 100); setRange(g, gv, 0, 150); gr.textContent = gv + "%";
    g.addEventListener("input", () => { setRange(g, +g.value, 0, 150); gr.textContent = g.value + "%"; api.set("pedal_gain", g.value / 100); });
    $("#pdTest").addEventListener("click", () => api.pedal_test().then((r) => toast(r && r.ok ? "Pedal test: 2 s rising rumble" : "Turn it on and pick its output first")));
    setTimeout(st, 900); setInterval(st, 5000);
  })();
  // Sound mode: Driving / Broadcast (2026-10-26)
  (() => { const d = $("#modeDrive"), b = $("#modeBroad"), n = $("#modeNow"); if (!d) return;
    n.textContent = "Now: " + ((S.audio_mode || "broadcast") === "driving" ? "Driving" : "Broadcast");
    const go = (m) => api.audio_mode(m).then((r) => toast((r && r.msg ? r.msg : "Switched") + " - restarting the app"));
    d.addEventListener("click", () => go("driving")); b.addEventListener("click", () => go("broadcast")); })();
  // H8 Stream Deck addresses (2026-10-26)
  (() => { const box = $("#deckList"); if (!box || !api.deck_links) return;
    api.deck_links().then((l) => { box.innerHTML = ""; for (const it of l || []) { const d = document.createElement("div");
      const b = document.createElement("b"); b.textContent = it.label + ": "; const c = document.createElement("span"); c.textContent = it.url; c.style.cursor = "copy";
      c.title = "Click to copy"; c.addEventListener("click", () => { try { navigator.clipboard.writeText(it.url); toast("Copied"); } catch (e) {} });
      d.appendChild(b); d.appendChild(c); box.appendChild(d); } }).catch(() => {}); })();
  // D12 speed fan (2026-10-26, #250)
  (() => { const k = $("#fanKind"); if (!k) return; k.value = S.fan_kind || "url";
    const show = () => { $("#fanUrlRow").style.display = k.value === "url" ? "" : "none"; $("#fanPlugRow").style.display = k.value === "hue" ? "" : "none"; };
    k.addEventListener("change", () => { S.fan_kind = k.value; api.set("fan_kind", k.value); show(); }); show();
    const u = $("#fanUrl"); u.value = S.fan_url || ""; u.addEventListener("change", () => { S.fan_url = u.value.trim(); api.set("fan_url", u.value.trim()); }); })();
  (() => { // telemetry vault (2026-10-27): folders, "check now", and the status line
    const bind = (id, key) => { const el = $(id); if (!el) return; el.value = S[key] || "";
      el.addEventListener("change", () => { const v = el.value.trim();
        if (key === "vault_drive_dir" && /^\s*h:/i.test(v)) { toast("H: is the business Drive - pick a folder on G:"); el.value = S[key] || ""; return; }
        S[key] = v; api.set(key, v); toast("Saved"); }); };
    bind("#vaultDir", "vault_dir"); bind("#vaultDriveDir", "vault_drive_dir");
    const st = () => { if (!api.vault_state) return; api.vault_state().then((r) => { const e = $("#vaultStatus"); if (e && r) e.textContent = r.line || "–"; }).catch(() => {}); };
    const b = $("#vaultScan"); if (b) b.addEventListener("click", () => { if (api.vault_scan) api.vault_scan().then(() => { toast("Checking for new recordings"); setTimeout(st, 4000); }); });
    st(); setInterval(st, 5000); })();
  // #308 VR colour (ReShade OpenXR layer + vibrance), Settings > General (2026-10-27)
  (() => { const card = $("#rsCard"); if (!card || !api.reshade_state) return;
    const el = (t, cls, txt) => { const e = document.createElement(t); if (cls) e.className = cls; if (txt != null) e.textContent = txt; return e; };
    let busy = false, last = null;
    const paint = (r) => { if (!r) return; last = r;
      const run = !!r.sim_running, inst = !!r.installed;
      const lay = { on: "on", off: "off", "not registered": "not set up", unknown: "can't be read" }[r.layer] || r.layer;
      const st = $("#rsStatus");
      st.textContent = inst ? `ReShade for the headset: ${lay}` + (r.preset ? `  ·  preset: ${r.preset}` : "") +
        ((r.others || []).filter((o) => o.on).length ? `  ·  other OpenXR layers on: ${r.others.filter((o) => o.on).map((o) => o.name).join(", ")}` : "")
        : "ReShade for the headset: not installed";
      st.className = "st-line" + (r.layer === "on" ? " ok" : "");
      const w = $("#rsWarn"); w.style.display = run ? "" : "none"; w.textContent = run ? "iRacing is running - close it to change anything here." : "";
      $("#rsInstall").style.display = inst ? "none" : "";
      $("#rsOn").disabled = run || busy || !inst || r.layer === "on"; $("#rsOff").disabled = run || busy || r.layer === "off" || r.layer === "not registered";
      const pb = $("#rsPresets"); pb.innerHTML = "";
      for (const n of ["Off", "Day", "Night"]) { const has = (r.presets || []).includes(n);
        const b = el("button", "btn sm" + (r.preset === n ? " gold" : ""), n); b.disabled = run || busy || !has || !r.ini;
        b.title = !r.ini ? "ReShadeVR.ini isn't in the iRacing folder" : has ? "" : n + ".ini isn't in C:\\SimRacing\\ReShade";
        b.addEventListener("click", () => act(() => api.reshade_preset(n))); pb.appendChild(b); }
      const box = $("#rsSliders"); box.innerHTML = "";
      for (const u of r.sliders || []) {
        const row = el("div", "row"); const name = el("span", "name", u.label); name.style.width = "110px"; if (u.tip) name.title = u.tip;
        const inp = el("input"); inp.type = "range"; inp.min = u.min; inp.max = u.max; inp.step = u.step || 0.01; inp.disabled = run || busy;
        const ro = el("div", "readout"); const show = () => { ro.textContent = u.int ? String(Math.round(+inp.value)) : (+inp.value).toFixed(2); };
        setRange(inp, u.value, u.min, u.max); show();
        inp.addEventListener("input", () => { setRange(inp, +inp.value, u.min, u.max); show(); });
        inp.addEventListener("change", () => act(() => api.reshade_uniform(u.fx, u.name, +inp.value, !!u.int), true));
        row.appendChild(name); row.appendChild(inp); row.appendChild(ro); box.appendChild(row); }
      const k = r.keys || {}; $("#rsKeys").textContent = inst ? (k.text ? "In the headset: " + k.text + ". " : "") + "Sliders change the preset that's picked now." + (r.sliders && r.sliders.length ? "" : (r.preset && r.preset !== "Off" ? " (no sliders: the preset's effect files weren't found)" : "")) : "";
      const v = r.vibrance || {}; const vs = $("#vibStatus"); vs.textContent = v.script ? `Main display (${v.display || "DISPLAY1"}): ${v.level}%` + (v.keep ? ", kept" : "") : "nv_vibrance.py isn't in C:\\SimRacing\\Tools - vibrance can't be set from here";
      $("#vibApply").disabled = !v.script; };
    const act = async (fn, quiet) => { if (busy) return; busy = true; paint(last);
      if (!quiet) toast("Working… (Windows may ask for permission)");
      let r = null; try { r = await fn(); } catch (e) {}
      busy = false; if (r) { toast(r.msg || (r.ok ? "Done" : "Not changed")); paint(r.state); } else refresh(); };
    const refresh = () => api.reshade_state().then(paint).catch(() => {});
    $("#rsOn").addEventListener("click", () => act(() => api.reshade_layer(true)));
    $("#rsOff").addEventListener("click", () => act(() => api.reshade_layer(false)));
    const g = $("#vibLvl"), gr = $("#vibLvlR"); const gv = +(S.vibrance_level ?? 70); setRange(g, gv, 0, 100); gr.textContent = gv + "%";
    g.addEventListener("input", () => { setRange(g, +g.value, 0, 100); gr.textContent = g.value + "%"; });
    g.addEventListener("change", () => { S.vibrance_level = +g.value; api.set("vibrance_level", +g.value).then(refresh); });
    $("#vibApply").addEventListener("click", () => api.vibrance_apply().then((r) => toast(r && r.msg ? r.msg : "Done")).catch(() => {}));
    refresh(); setInterval(() => { if (!busy && card.offsetParent) refresh(); }, 6000); })();
  // C1 home hero (2026-10-26, #283)
  (() => { const h = $("#crHero"); if (!h) return; h.value = S.crowd_hero || "";
    h.addEventListener("change", () => { S.crowd_hero = h.value.trim(); api.set("crowd_hero", h.value.trim()); toast(h.value.trim() ? "The crowd now cheers car " + h.value.trim() : "Home hero off"); }); })();
  // lights (2026-10-26, #236 flags; #239-#240 the Hue lamps + desk strip)
  (() => {
    const kind = $("#ltKind"); if (!kind) return;
    kind.value = S.lights_kind || "hue";
    const show = () => { $("#hueBox").style.display = kind.value === "hue" ? "" : "none"; $("#ltOther").style.display = kind.value === "hue" ? "none" : ""; };
    kind.addEventListener("change", () => { S.lights_kind = kind.value; api.set("lights_kind", kind.value); show(); });
    show();
    const host = $("#ltHost"); host.value = S.lights_host || "";
    host.addEventListener("change", () => { S.lights_host = host.value.trim(); api.set("lights_host", host.value.trim()); });
    for (const [id, key] of [["#ltBri", "lights_bri"], ["#ltIdle", "lights_idle"]]) {
      const el = $(id), r = $(id + "R"); const v = S[key] ?? (key === "lights_bri" ? 80 : 30);
      setRange(el, v, 0, 100); r.textContent = v + "%";
      el.addEventListener("input", () => { setRange(el, +el.value, 0, 100); r.textContent = el.value + "%"; api.set(key, +el.value); });
    }
    const JOBS = [["both", "Flags + picture"], ["flags", "Flags only"], ["picture", "Picture only"], ["off", "Leave alone"]];
    document.querySelectorAll(".hue-j").forEach((sel) => {
      for (const [v, t] of JOBS) { const o = document.createElement("option"); o.value = v; o.textContent = t; sel.appendChild(o); }
      sel.value = S[sel.dataset.k] || (sel.dataset.k === "hue_desk_job" ? "picture" : "both");
      sel.addEventListener("change", () => { S[sel.dataset.k] = sel.value; api.set(sel.dataset.k, sel.value); });
    });
    const fillLights = () => api.hue_lights().then((r) => {
      document.querySelectorAll(".hue-l").forEach((sel) => {
        sel.innerHTML = ""; const n = document.createElement("option"); n.value = ""; n.textContent = "- none -"; sel.appendChild(n);
        for (const l of (r && r.lights) || []) { const o = document.createElement("option"); o.value = l.id; o.textContent = l.name; sel.appendChild(o); }
        sel.value = S[sel.dataset.k] || "";
        sel.onchange = () => { S[sel.dataset.k] = sel.value; api.set(sel.dataset.k, sel.value); };
      });
    }).catch(() => {});
    $("#hueIp").textContent = S.lights_host ? S.lights_host + (S.hue_user ? " (paired)" : " (not paired)") : "not found yet";
    $("#hueFind").addEventListener("click", () => api.hue_find().then((r) => { toast(r.msg); if (r.ok) { S.lights_host = r.ip; $("#hueIp").textContent = r.ip; kind.value = "hue"; show(); } }));
    $("#huePair").addEventListener("click", () => api.hue_pair().then((r) => { toast(r.msg); if (r.ok) { S.hue_user = "x"; $("#hueIp").textContent = (S.lights_host || "") + " (paired)"; fillLights(); } }));
    const st = () => (kind.value === "hue" ? api.hue_state() : api.lights_state()).then((r) => { const e = $("#ltStatus"); if (e && r) e.textContent = r.status === "off" ? "Off" : r.status; }).catch(() => {});
    $("#ltTest").addEventListener("click", () => (kind.value === "hue" ? api.hue_test() : api.lights_test()).then((r) => toast(r && r.ok ? "Lights test: every flag colour, 7 s" : "Switch the sync on and set the lights up first")));
    if (S.hue_user) fillLights();
    setTimeout(st, 900); setInterval(st, 5000);
  })();
  // Race Control page: shift beep tuning (2026-10-24)
  const sb = (id, key, min, max, toUi, fromUi, label) => {
    const el = $(id), r = $(id + "R");
    const v = toUi(S[key]); setRange(el, v, min, max); r.textContent = label(v);
    el.addEventListener("input", () => { setRange(el, +el.value, min, max); r.textContent = label(+el.value); S[key] = fromUi(+el.value); api.set(key, S[key]); });
  };
  sb("#sbPitch", "shift_pitch", 300, 3000, (x) => x || 1400, (x) => x, (v) => v + " Hz");
  sb("#sbVol", "shift_volume", 0, 100, (x) => Math.round((x ?? 0.25) * 100), (x) => x / 100, (v) => v + "%");
  sb("#sbPoint", "shift_point", 90, 104, (x) => Math.round((x || 1) * 100), (x) => x / 100, (v) => v === 100 ? "At the shift light" : v < 100 ? (100 - v) + "% early" : (v - 100) + "% late");
  sb("#sbLen", "shift_length", 30, 250, (x) => x || 60, (x) => x, (v) => v + " ms");
  // start with iRacing (2026-10-26)
  const lpaint = (lst) => {
    const box = $("#launchList"); if (!box) return;
    box.innerHTML = (lst || []).map((x, i) => `<div class="row" style="justify-content:space-between;gap:10px"><span class="name" style="font:600 14px Inter;${x.ok ? "" : "color:var(--red)"}" title="${x.path.replace(/"/g, "&quot;")}">${x.name.replace(/</g, "&lt;")}${x.ok ? "" : " (missing)"}</span><button class="btn sm" data-i="${i}">Remove</button></div>`).join("")
      || `<p class="note" style="margin:0">Nothing yet - add SimHub, a dash, music, anything.</p>`;
    box.querySelectorAll("button[data-i]").forEach((b) => b.addEventListener("click", async () => lpaint(await api.launch_remove(+b.dataset.i))));
  };
  if ($("#launchList") && api.launch_list) {
    api.launch_list().then(lpaint).catch(() => {});
    $("#launchAdd").addEventListener("click", async () => lpaint(await api.launch_add()));
    $("#launchTest").addEventListener("click", async () => { const s = await api.launch_test(); toast(s && s.length ? "Started: " + s.join(", ") : "Everything is already open"); });
  }
  if ($("#spCall")) {                      // spotter timing (2026-10-26)
    sb("#spCall", "spot_call_ms", 0, 400, (x) => x ?? 120, (x) => x, (v) => v ? v + " ms" : "instant");
    sb("#spClear", "spot_clear_ms", 0, 1000, (x) => x ?? 350, (x) => x, (v) => v ? v + " ms" : "instant");
    sb("#spStill", "spot_still_s", 2, 15, (x) => Math.round(x ?? 5), (x) => x, (v) => v + " s");
    sb("#spMin", "spot_min_kmh", 0, 120, (x) => x ?? 30, (x) => x, (v) => v ? v + " km/h" : "always");
  }
  $("#sbTest").addEventListener("click", () => api.beep_test && api.beep_test());
  sb("#rcVol", "race_control_volume", 0, 100, (x) => Math.round((x ?? 0.8) * 100), (x) => x / 100, (v) => v + "%");
  $("#rcTest").addEventListener("click", () => api.rc_test && api.rc_test());
  // crowd (2026-10-24): Trackside crowd card
  sb("#crowdVol", "crowd_volume", 0, 100, (x) => Math.round((x ?? 0.3) * 100), (x) => x / 100, (v) => v + "%");
  // sound mix (2026-10-25)
  const dbLab = (v) => (v > 0 ? "+" : "") + v + " dB";
  const pctLab = (v) => (v === 0 ? "Off" : v + "%");
  if ($("#sndHp")) {
    sb("#sndHp", "snd_hp_db", -40, 6, (x) => Math.round(x ?? 0), (x) => x, dbLab);
    sb("#sndTv", "snd_tv_db", -60, 6, (x) => Math.round(x ?? 0), (x) => x, dbLab);
    if ($("#sndTvDelay")) sb("#sndTvDelay", "snd_tv_delay_ms", 0, 300, (x) => x ?? 0, (x) => x, (v) => (v === 0 ? "In sync" : "TV sound " + v + " ms later"));
    if ($("#bcGrit")) {   // broadcast radio (#515)
      sb("#bcGrit", "bcast_grit", 0, 200, (x) => Math.round((x ?? 1) * 100), (x) => x / 100, (v) => (v === 0 ? "Same as headset" : v <= 60 ? "Light" : v <= 130 ? "Clear radio" : "Heavy"));
      sb("#bcDb", "bcast_db", 0, 12, (x) => Math.round(x ?? 6), (x) => x, (v) => "+" + v + " dB");
      sb("#bcCrowd", "bcast_crowd_db", -24, 6, (x) => Math.round(x ?? 0), (x) => x, dbLab);
    }
    sb("#sndEng", "snd_engine", 0, 100, (x) => x ?? 0, (x) => x, pctLab);
    sb("#sndDet", "snd_detail", 0, 100, (x) => x ?? 0, (x) => x, pctLab);
  }
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
    el.textContent = t; el.className = "st-line" + (cls ? " " + cls : "");
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
  // sound mix: live meters + status while the page is open
  setInterval(async () => {
    if (!api.audio_state || curPanel !== "settings" || !$("#sp-sound") || !$("#sp-sound").classList.contains("active")) return;
    try {
      const st = await api.audio_state();
      const m = (id, v) => { const e = $(id); if (e) e.style.width = Math.min(100, Math.round(Math.sqrt(v || 0) * 100)) + "%"; };
      m("#sndHpM", st.hp_level); m("#sndTvM", st.tv_level);
      $("#sndStatus").textContent = !st.voicemeeter ? "Voicemeeter isn't running - the levels can't be set until it is."
        : !st.apo ? "Equalizer APO isn't installed - the EQ and car sound can't work."
        : !st.apo_hooked ? "Equalizer APO isn't reading our files yet (needs a one-time setup)."
        : st.error ? st.error : "All connected: Voicemeeter and Equalizer APO.";
      const tvs = $("#sndTvStatus");
      if (tvs) tvs.textContent = !st.tv_apo ? "Home theatre needs Equalizer APO on the TV path once: run its Configurator, tick CABLE Input, restart the PC."
        : !st.tv_hooked ? "Home theatre needs a one-time setup line in Equalizer APO's config."
        : st.tv_on ? "Home theatre is ON on the TV (a replay is playing)." : "Home theatre ready - it switches on when a replay plays.";
    } catch (e) {}
  }, 500);
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
  const dns = $("#driverNameSay");   // #542: how the voice should say it
  dns.value = S.driver_name_say || "";
  dns.addEventListener("change", () => { const v = dns.value.trim(); S.driver_name_say = v; api.set("driver_name_say", v); toast(v ? "Saved - press Hear it" : "Cleared - said as written"); });
  $("#driverNameHear").addEventListener("click", async () => {
    try { const r = await api.name_test(dn.value.trim(), dns.value.trim()); toast(r && r.ok ? "Listen…" : ((r && r.why) || "Couldn't play it")); } catch (e) { toast("Couldn't play it"); }
  });
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
      else if (e.t === "fx_ready" && window.fxEvent) window.fxEvent(e);                        // forensics (2026-10-27)
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
  // #322: a slow first get_state used to fall back to empty settings, so the buttons showed "Not set" after a restart
  // (the binding was still saved). Try again before giving up.
  for (let i = 0; i < 3 && !state; i++) {
    try { state = await withTimeout(api.get_state(), 6000 + i * 6000); } catch (e) { try { api.js_error("get_state (try " + (i + 1) + "): " + e); } catch (x) {} }
  }
  if (!state) state = { settings: {}, devices: ["Windows default"], controllers: [] };
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
