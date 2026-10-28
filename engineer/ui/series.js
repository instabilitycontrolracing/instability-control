/* Series tab: what you're practising for -> format, what to watch for, your numbers, fuel and stops. */
"use strict";
const SR = { state: null, info: null, req: 0, inited: false };
const srEl = (id) => document.getElementById(id);
const srEsc = (s) => String(s ?? "").replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
const srLap = (t) => { if (t == null) return "–"; const m = Math.floor(t / 60), s = t - m * 60; return `${m}:${s.toFixed(3).padStart(6, "0")}`; };

async function srOpen() {
  if (!SR.inited) {
    SR.inited = true;
    srEl("srSeries").addEventListener("change", srLoad);
    srEl("srCar").addEventListener("change", () => { srTracks(); srLoad(); });
    srEl("srTrack").addEventListener("change", srLoad);
  }
  let st = null;
  try { st = await api.prep_state(); } catch (e) {}
  if (!st) return;
  SR.state = st;
  const fill = (sel, items, val) => {
    sel.innerHTML = "";
    for (const [k, label] of items) { const o = document.createElement("option"); o.value = k; o.textContent = label; sel.appendChild(o); }
    if (val != null && items.some(([k]) => k === val)) sel.value = val;
  };
  fill(srEl("srSeries"), st.series.map((x) => [x.id, x.label]), st.pick.series);
  const cars = Object.entries(st.cars);
  if (!cars.some(([k]) => k === "bmwlmdh")) cars.unshift(["bmwlmdh", "BMW M Hybrid V8"]);
  fill(srEl("srCar"), cars, st.pick.car);
  srTracks(st.pick.track);
  srEl("srWeek").lastElementChild.textContent = `Week ${st.week}`;
  await srLoad();
}

function srTracks(pick) {
  const st = SR.state, car = srEl("srCar").value, sel = srEl("srTrack");
  const mine = Object.entries(st.tracks[car] || {}).sort((a, b) => b[1].sessions - a[1].sessions);
  const have = new Set(mine.map(([, v]) => v.display.toLowerCase()));
  const items = mine.map(([k, v]) => [k, `${v.display}  ·  ${v.live ? "you're here" + (v.sessions ? " · " + v.sessions : "") : v.sessions}`]);
  for (const t of st.sched_tracks) if (!have.has(t.toLowerCase())) items.push([t, `${t}  ·  no laps`]);
  const want = pick ?? sel.value;
  sel.innerHTML = "";
  for (const [k, label] of items) { const o = document.createElement("option"); o.value = k; o.textContent = label; sel.appendChild(o); }
  if (items.some(([k]) => k === want)) sel.value = want;
}

async function srLoad() {
  let r = null;
  try { r = await api.prep_info(srEl("srSeries").value, srEl("srCar").value, srEl("srTrack").value); } catch (e) {}
  if (!r) return;
  SR.info = r; SR.req = r.req; SR.stats = null;
  srRender();
}

function srRender() {
  const r = SR.info, S = r.series, t = r.theme, st = SR.stats;
  const logo = t && t.logo ? `<div class="sr-logo ${t.dark ? "light" : ""}"><img src="${srEsc(t.logo)}" alt=""></div>` : `<div class="sr-logo none">${srEsc(r.track)}</div>`;
  const chips = [...S.classes.map((c) => `<span class="sr-chip ${c === r.klass ? "gtp" : ""}">${srEsc(c)}</span>`),
    S.minutes && S.classes.length ? `<span class="sr-chip gold">${S.minutes} min</span>` : "",
    S.setup ? `<span class="sr-chip">${srEsc(S.setup)}</span>` : "", S.license ? `<span class="sr-chip">${srEsc(S.license)}</span>` : ""].join("");
  let wk = "";
  if (S.classes.length) {
    const here = r.here_weeks.length ? `Here: week ${r.here_weeks.join(", ")}` : (r.schedule ? "Not on the schedule" : "Week here: check iRacing");
    wk = `<div class="sr-week"><div class="lbl">This week</div><div class="big">${srEsc(r.this_week ? shortTrack(r.this_week) : `W${r.week}`)}</div>
      <div class="small">${srEsc(here)}${r.schedule ? "" : ' · <a id="srPdf">schedule</a>'}</div></div>`;
  }
  let h = `<div class="card sr-hero">${logo}<div><div class="sr-name">${srEsc(r.track)}</div>
    <div class="sr-sub">${srEsc(S.name)}${S.tag ? " · " + srEsc(S.tag) : ""} · ${srEsc(r.car)}</div><div class="sr-chips">${chips}</div></div>${wk}</div>`;
  // watch for
  let w = `<div class="card"><h3>Watch for</h3>`;
  w += r.watch.length ? `<ul class="sr-list">${r.watch.map((x) => `<li>${srEsc(x)}</li>`).join("")}</ul>` : `<div class="empty" style="margin-top:8px">No notes for this track yet.</div>`;
  if (r.multi.length) w += `<div class="sr-h4">Traffic</div><ul class="sr-list traffic">${r.multi.map((x) => `<li>${srEsc(x)}</li>`).join("")}</ul>`;
  const extra = [...(r.car_notes || []), ...(S.notes || [])];
  if (extra.length) w += `<div class="sr-h4">Car</div><ul class="sr-list car">${extra.map((x) => `<li>${srEsc(x)}</li>`).join("")}</ul>`;
  w += `</div>`;
  // your numbers
  const q = r.quick;
  let y = `<div class="card"><h3>You here</h3>`;
  if (!q.sessions) y += `<div class="empty" style="margin-top:8px">No laps here yet in this car.</div></div>`;
  else {
    const n = st && st.nums;
    const tile = (l, v, cls = "") => `<div class="sr-tile ${cls}"><div class="lbl">${l}</div><div class="v">${v}</div></div>`;
    y += `<div class="sr-tiles">${tile("Best", srLap(q.best))}${tile("Target", st && st.theory ? srLap(st.theory) : "…", "hot")}
      ${tile("Typical", n && n.typical ? srLap(n.typical) : "…")}${tile("Spread", n && n.spread != null ? `±${n.spread.toFixed(2)}<small>s</small>` : "…")}
      ${tile("Clean laps", n ? `${n.clean}<small>/ ${n.laps}</small>` : `…`)}${tile("Sessions", q.sessions)}</div>`;
    if (!st) y += `<div class="sr-wait">Reading your laps…<i><b id="srProg"></b></i></div>`;
    y += `</div>`;
  }
  // race + focus
  let rc = "";
  if (q.sessions && S.classes.length) {
    const p = st && st.plan, n = st && st.nums;
    const tile = (l, v, cls = "") => `<div class="sr-tile ${cls}"><div class="lbl">${l}</div><div class="v">${v}</div></div>`;
    rc = `<div class="card"><h3>Race · ${S.minutes} min</h3><div class="sr-tiles">
      ${tile("Laps", p ? p.laps : "…")}${tile("Fuel / lap", n && n.fuel_lap ? `${n.fuel_lap.toFixed(2)}<small>L</small>` : "…")}
      ${tile("Tank (last time)", n && n.tank ? `${n.tank.toFixed(1)}<small>L</small>` : "…")}${tile("Laps / tank", p && p.laps_per_tank ? p.laps_per_tank : "…")}
      ${tile("Fuel to finish", p && p.fuel ? `${p.fuel}<small>L</small>` : "…")}${tile("Stops", p && p.stops != null ? p.stops : "…", p && p.stops === 0 ? "good" : "hot")}</div></div>`;
  }
  let fc = "";
  if (st && ((st.focus && st.focus.length) || (st.nums && (st.nums.offs.length || st.nums.incidents.length)))) {
    fc = `<div class="card"><h3>Practice focus</h3>`;
    if (st.focus.length) fc += `<div class="sr-h4" style="margin-top:6px">Typical loss vs your best</div>` + st.focus.map((f) => `<div class="sr-row"><span>${srEsc(f.name)}</span><b>+${f.loss.toFixed(2)}</b></div>`).join("");
    if (st.nums.offs.length) fc += `<div class="sr-h4">Off track</div>` + st.nums.offs.map(([nm, c]) => `<div class="sr-row"><span>${srEsc(nm)}</span><b class="n">${c}×</b></div>`).join("");
    if (st.nums.incidents.length) fc += `<div class="sr-h4">Incident points</div>` + st.nums.incidents.map(([nm, c]) => `<div class="sr-row"><span>${srEsc(nm)}</span><b class="n">${c}x</b></div>`).join("");
    fc += `</div>`;
  }
  // race strategy from everything you've stored (your race sims)
  let sg = "";
  const S2 = st && st.strategy;
  if (q.sessions && S.classes.length) {
    if (!st) sg = "";
    else if (!S2 || !S2.plans || !S2.plans.length) sg = `<div class="card sr-strat"><h3>Race strategy</h3><div class="empty" style="margin-top:8px">Not enough laps with fuel data yet. Do a long run.</div></div>`;
    else {
      const c = S2.cond || {};
      const pace = c.pace_diff != null ? `Latest laps ${Math.abs(c.pace_diff).toFixed(1)} s ${c.pace_diff < 0 ? "faster" : "slower"} than your race sims` : "";
      const cond = S2.sims ? `${c.label || ""}${c.temp_diff != null && Math.abs(c.temp_diff) >= 1 ? ` (${c.temp_diff > 0 ? "+" : ""}${c.temp_diff.toFixed(0)}°)` : ""}` : "no race sim yet";
      sg = `<div class="card sr-strat"><h3>Race strategy</h3>
        <div class="sr-sub" style="margin:2px 0 12px">${srEsc(S2.n)} laps · ${srEsc(S2.sims)} race sim${S2.sims === 1 ? "" : "s"} · ${pace ? srEsc(pace) + " · " : ""}${srEsc(cond)}</div>
        <div class="sr-plans">${S2.plans.map((p, i) => `<div class="sr-plan ${i === 0 ? "a" : ""}" style="animation-delay:${i * 90}ms">
          <div class="pl">${p.name}</div><div class="pt"><b>${srEsc(p.text)}</b><span>${p.laps} laps${i ? ` · +${p.vs_a < 900 ? p.vs_a.toFixed(1) + " s" : "1 lap"}` : " · fastest"}</span></div></div>`).join("")}</div>
        ${fmtNext(S2)}
        ${fmtEvent(S2.event, S2.race_min, !!S2.next)}
        <div class="sr-sub" style="margin-top:10px">Learned: ${srEsc((S2.learned || []).join(", ") || "nothing yet, using defaults")}. No safety cars assumed.</div></div>`;
    }
  }
  sg += fmtRain(S2 && S2.rain);
  srEl("srBody").innerHTML = h + `<div style="display:flex;flex-direction:column;gap:10px">${sg}${w}</div>` + `<div style="display:flex;flex-direction:column;gap:10px">${fmtSchedule(r)}${y}${rc}${fc}</div>`;
  const pdf = srEl("srPdf"); if (pdf) pdf.addEventListener("click", () => api.open_url && api.open_url(r.schedule_url));
}

/* local race times from "every 120 min from 00:45:00" (UTC) or a list of UTC start times */
function localTimes(t, date) {
  if (!t) return "";
  const m = /every (\d+) min from (\d\d):(\d\d)/.exec(t);
  const fmt = (d) => d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  if (m) {
    const d = new Date(`${date}T${m[2]}:${m[3]}:00Z`), rep = +m[1];
    const first = new Date(d); return `every ${rep / 60} h at :${String(first.getMinutes()).padStart(2, "0")} (${fmt(first)}, ${fmt(new Date(+first + rep * 60000))}…)`;
  }
  return t.split(",").slice(0, 4).map((x) => { const d = new Date(x); return d.toLocaleDateString(undefined, { weekday: "short" }) + " " + fmt(d); }).join(" · ");
}
function fmtNext(S2) {
  const n = S2.next; if (!n) return "";
  const bits = [`${n.min ? n.min + " min" : n.laps + " laps"}`, n.fuel ? `fuel ${n.fuel}% (${S2.tank ? S2.tank.toFixed(1) + " L" : ""})` : "",
    n.kg ? `+${n.kg} kg` : "", n.temp ? `${Math.round(Math.max(...n.temp))}° air` : "", n.rain != null ? (n.rain >= 1 ? `${Math.round(n.rain)}% rain` : "dry") : "",
    n.sim ? "in-sim " + new Date(n.sim).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" }) : "", n.start ? n.start.toLowerCase() + " start" : ""].filter(Boolean);
  const d = new Date(n.date + "T12:00:00").toLocaleDateString(undefined, { day: "numeric", month: "short" });
  return `<div class="sr-event next"><span class="lbl">Week ${n.wk} here · from ${d} · official schedule</span><div>${bits.map((b) => `<span>${srEsc(b)}</span>`).join("")}</div>
    ${n.rain >= 25 ? `<div class="sr-rain">${Math.round(n.rain)}% chance of rain: practise a few laps on a wet track too.</div>` : ""}</div>`;
}
function fmtSchedule(r) {
  const s = r.schedule; if (!s) return "";
  const nd = (r.track || "").toLowerCase();
  return `<div class="card"><h3>Season</h3><div class="sr-sub" style="margin:2px 0 10px">${srEsc(s.name)} · ${srEsc(s.source)}${s.fixed != null ? (s.fixed ? " · fixed" : " · open") : ""}${s.inc ? ` · ${s.inc}x limit` : ""}</div>
    <div class="sr-sched">${s.weeks.map((w) => { const here = r.here_weeks.includes(w.wk), cur = s.current === w.wk;
      return `<div class="sr-wk ${cur ? "cur" : ""} ${here ? "here" : ""}"><b>W${w.wk}</b><span class="d">${new Date(w.date + "T12:00:00").toLocaleDateString(undefined, { day: "numeric", month: "short" })}</span>
        <span class="t">${srEsc(shortTrack(w.track))}${w.cfg && !/full|grand prix|road course|international|24 heures/i.test(w.cfg) ? " · " + srEsc(w.cfg) : ""}</span>
        <span class="m">${w.min ? w.min + "'" : (w.laps || "") + " L"}</span><span class="r">${w.rain >= 1 ? Math.round(w.rain) + "%☂" : ""}</span><span class="f">${w.fuel ? w.fuel + "%" : ""}</span></div>`; }).join("")}</div>
    ${s.weeks[0] && s.weeks[0].times ? `<div class="sr-sub" style="margin-top:10px">Race times: ${srEsc(localTimes(s.weeks[0].times, s.weeks[(s.current || 1) - 1]?.date || s.weeks[0].date))}</div>` : ""}</div>`;
}
function fmtEvent(ev, mins, hasNext) {
  if (!ev) return hasNext ? "" : `<div class="sr-sub" style="margin-top:10px">Race length: ${mins} min (series default). Join a race here once and it uses the real format.</div>`;
  const d = ev.at ? new Date(ev.at * 1000).toLocaleDateString(undefined, { day: "numeric", month: "short" }) : "";
  const bits = [`${Math.round(ev.race_s / 60)} min race`, ev.fixed ? "fixed setup" : "open setup",
    [ev.weather, ev.skies].filter(Boolean).join(" ").toLowerCase() + " weather", ev.tod, ev.track_temp != null ? `${Math.round(ev.track_temp)}° track` : "",
    ev.incident_limit && ev.incident_limit !== "unlimited" ? `${ev.incident_limit}x limit` : "", ev.fast_repairs ? `${ev.fast_repairs} fast repair` : "",
    ev.standing_start ? "standing start" : "rolling start"].filter(Boolean);
  return `<div class="sr-event"><span class="lbl">Race format · your last race here${d ? " (" + d + ")" : ""}</span><div>${bits.map((b) => `<span>${srEsc(b)}</span>`).join("")}</div></div>`;
}

function shortTrack(t) { return t.replace(/ (International )?(Motor )?(Speedway|Raceway|Street Circuit|Circuit)$/i, "").replace("Michelin Raceway ", ""); }

function srEvent(e) {
  if (e.req !== SR.req) return;
  if (e.t === "prep_prog") { const b = srEl("srProg"); if (b) b.style.width = (e.i / e.n * 100) + "%"; return; }
  if (e.t === "prep_stats") { SR.stats = e.error ? { nums: null } : e; if (!e.error) srRender(); }
}
window.srOpen = srOpen; window.srEvent = srEvent;

/* rain: plan around it + how to drive it (only when rain is possible) */
function fmtRain(R) {
  if (!R || !(R.chance >= 15)) return "";
  const li = (xs) => xs.map((t) => `<li>${srEsc(t)}</li>`).join("");
  const own = R.wet_laps ? `${R.wet_laps} wet laps of yours` : "No wet laps of yours yet: do a few in a wet test session";
  return `<div class="card sr-rain"><h3>Rain <span class="sr-pct">${Math.round(R.chance)}%</span></h3>
    <div class="sr-sub" style="margin:2px 0 10px">${srEsc(own)}</div>
    <div class="sr-k">Plan</div><ul class="sr-ul">${li(R.plan || [])}</ul>
    <div class="sr-k">Driving</div><ul class="sr-ul">${li(R.tips || [])}</ul>${(R.track || []).length ? `
    <div class="sr-k">This track</div><ul class="sr-ul">${li(R.track)}</ul>` : ""}</div>`;
}
