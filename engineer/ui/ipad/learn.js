/* ic186 (#729): the iPad TRACK page. Data from /api/tracklearn (the PC's tracklearn.py). Nothing is computed here but
   the drawing and the visualisation timer - every number comes from his own laps on the PC. Missing data shows "—". */
"use strict";
(function () {
  const qs = new URLSearchParams(location.search);
  let KEY = qs.get("k") || "";
  try { if (KEY) localStorage.setItem("re_key", KEY); else KEY = localStorage.getItem("re_key") || ""; } catch (e) {}
  const $ = (id) => document.getElementById(id);
  const E = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const DASH = '<span class="x">—</span>';
  const S = { d: null, sig: "", timer: 0 };
  const lapT = (t) => t == null ? DASH : `${Math.floor(t / 60)}:${(t % 60).toFixed(3).padStart(6, "0")}`;
  const secT = (t) => t == null ? DASH : t.toFixed(3);
  const sgn = (x, dp) => x == null ? DASH : (x > 0 ? "+" : x < 0 ? "−" : "") + Math.abs(x).toFixed(dp == null ? 3 : dp);
  const num = (x, u) => x == null ? DASH : `${x}${u || ""}`;

  async function api() {
    try { const r = await fetch(`/api/tracklearn?k=${encodeURIComponent(KEY)}`); return r.ok ? await r.json() : null; }
    catch (e) { return null; }
  }
  function stat(lbl, v, s2, cls) {
    return `<div class="panel stat"><span class="lbl">${lbl}</span><div class="v ${cls || ""}">${v}</div><div class="s">${s2}</div></div>`;
  }

  function paintStats(d) {
    const st = d.stage, run = d.run, t = d.target || {};
    const stageS = st ? `${st.clean_laps} clean lap${st.clean_laps === 1 ? "" : "s"}${st.to_next != null ? ` · ${st.to_next} more to ${E(st.next)}` : ""}${st.race_prep ? " · race prep" : ""}` : "car or laps not known yet";
    const runS = !run ? "not in a session" : run.banker ? `banker lap: lap ${run.banker} · coach can talk` : run.run ? "<b>waiting for the banker lap</b> (clean, within 10 % of your best)" : "not out yet";
    return `<div class="stats">`
      + stat("Practice stage", st ? E(st.name) : DASH, stageS, "word")
      + stat("Run", run && run.run ? `${run.run}` : DASH, runS)
      + stat("Best lap", lapT(d.best && d.best.time), d.best ? `lap ${d.best.no} · compared with ${d.laps_used.length - 1} more of your fastest` : "needs a clean lap", d.best ? "purple" : "")
      + stat("Target lap", t.ok ? lapT(t.target) : DASH, t.ok ? `median of your best 5 clean laps + ${t.add.toFixed(1)} s` : E(t.why || "needs 5 clean laps"))
      + `</div>`;
  }

  function paintPlan(d) {
    const st = d.stage;
    const todo = st ? `<ul class="todo">${st.todo.map((x) => `<li>${E(x)}</li>`).join("")}</ul><p class="small">Counted from ${E(st.counted || "")}. Learn &lt; 15 · Refine &lt; 50 · Push &lt; 150 · Race pace from 150 (or race prep).</p>` : `<div class="emp">The stage needs the car and track of the session (it's read when you're in iRacing).</div>`;
    let drills = "";
    if ((d.drills || []).length) {
      drills = `<p class="small" style="margin-top:12px"><span class="lbl">Endurance drills</span>${d.endurance === true ? ` · the race here is ${Math.round(d.race_s / 3600 * 10) / 10} h` : " · if your next race is an endurance race"}</p>`
        + d.drills.map((x) => `<div class="it"><div class="t">${E(x.t)}</div><div class="d">${E(x.d)}</div></div>`).join("");
    }
    return `<div class="panel card"><div class="hd"><span class="lbl">What to do now</span></div>${todo}${drills}</div>`;
  }

  function paintFocus(d) {
    const f = d.focus || [];
    const body = f.length ? f.map((x, i) => `<div class="it"><span class="num">${x.lost.toFixed(2)} s</span><div class="t">${i + 1}. ${E(x.corner)} · ${E(x.title)}</div>`
      + `<div class="w">${E(x.detail)}</div><div class="d">${E(x.drill)}</div>`
      + `<div class="chain">Fix first: <b>${E(x.link)}</b>${x.chain.length > 1 ? " → then " + x.chain.slice(1).map((c) => E(c.title.toLowerCase())).join(" → ") : ""} · ${E(x.seen)}${x.straight_m ? ` · ${x.straight_m} m straight after` : ""}</div></div>`).join("")
      : `<div class="emp">${E(d.why || "Nothing repeats over your fastest laps yet: no focus item. Keep the laps clean.")}</div>`;
    return `<div class="panel card"><div class="hd"><span class="lbl">Focus (max 3)</span><span class="src">vs your fastest lap through each corner</span></div>${body}`
      + `<p class="small">Only what repeats on your best lap and your next fastest ones. Corners onto long straights count more.</p></div>`;
  }

  function paintChecks(d) {
    const c = d.checks, u = d.units === "kmh" ? "km/h" : "mph";
    if (!c) return `<div class="panel card"><div class="hd"><span class="lbl">Checks</span></div><div class="emp">${E(d.why || "No clean laps to check yet.")}</div></div>`;
    const rows = [];
    for (const x of c.coasting) if (x.repeat) rows.push(`<div class="it"><span class="num">${x.s.toFixed(1)} s</span><div class="t">Coasting · ${E(x.corner)}</div><div class="d">neither pedal on, ${x.laps} of ${x.of} laps (fine if you're saving fuel)</div></div>`);
    for (const x of c.lifts) if (x.repeat) rows.push(`<div class="it"><span class="num">${x.s.toFixed(1)} s</span><div class="t">Lift on the straight · ${E(x.straight)}</div><div class="d">under 80 % throttle where your best lap is flat, ${x.laps} of ${x.of} laps</div></div>`);
    for (const x of c.square) rows.push(`<div class="it"><div class="t">Square braking · ${E(x.corner)}</div><div class="d">brake fully off before you turn in, ${x.laps} of ${x.of} laps (best lap trails ${x.trail_m} m)</div></div>`);
    const ms = c.min_speed.map((x) => `<tr><td class="n">${E(x.corner)}</td><td>${num(x.best_lap)}</td><td>${num(x.others)}</td><td class="${x.diff < -1 ? "up" : ""}">${x.diff == null ? DASH : sgn(x.diff, 1)}</td><td>${num(x.session_top)}</td></tr>`).join("");
    return `<div class="panel card"><div class="hd"><span class="lbl">Checks</span><span class="src">over ${c.laps} clean laps</span></div>`
      + (rows.join("") || `<div class="emp">No repeated coasting, lifts on straights or square braking.</div>`)
      + `<table><thead><tr><th>MIN SPEED · ${u}</th><th>BEST LAP</th><th>OTHERS</th><th>DIFF</th><th>TOP</th></tr></thead><tbody>${ms}</tbody></table></div>`;
  }

  function paintSteps(d) {
    const s = d.steps || [];
    const rows = s.map((x) => `<tr><td class="n">${E(x.corner)}</td><td>${num(x.now_before, " m")}</td><td>${num(x.best_before, " m")}</td>`
      + `<td>${x.next_before != null ? `<b style="color:var(--gold2)">${x.next_before} m</b>` : DASH}</td><td><span class="tag ${x.status}">${E((x.status || "").replace("_", " ").toUpperCase())}</span></td><td class="txt">${E(x.text)}</td></tr>`).join("");
    return `<div class="panel card wide"><div class="hd"><span class="lbl">Braking boards</span><span class="src">brake over 20 %, metres before the turn-in (your last 3 clean laps)</span></div>`
      + (rows ? `<table><thead><tr><th>CORNER</th><th>NOW</th><th>BEST LAP</th><th>NEXT STEP</th><th></th><th style="text-align:left">WHAT TO DO</th></tr></thead><tbody>${rows}</tbody></table>`
        : `<div class="emp">${E(d.why || "No braking zones read yet.")}</div>`)
      + `<p class="small">Steps of 10-20 m, never more than 5 m past your best lap's point. An off or an incident at a corner stops the steps there. Lock-ups aren't in the lap data, so watch for them yourself.</p></div>`;
  }

  function paintTarget(d) {
    const t = d.target || {};
    if (!t.ok) return `<div class="panel card"><div class="hd"><span class="lbl">Target pace</span></div><div class="emp">${E(t.why || "Needs 5 clean laps.")}</div></div>`;
    const L = t.last;
    const sec = [0, 1, 2].map((k) => `<tr><td class="n">Sector ${k + 1}</td><td>${t.sectors ? secT(t.sectors[k]) : DASH}</td><td class="${L && L.sec_delta[k] > 0.1 ? "up" : L && L.sec_delta[k] <= 0 ? "dn" : ""}">${L ? sgn(L.sec_delta[k]) : DASH}</td></tr>`).join("");
    return `<div class="panel card"><div class="hd"><span class="lbl">Target pace</span><span class="src">from laps ${t.from.join(", ")}</span></div>`
      + `<table><thead><tr><th></th><th>TARGET</th><th>LAST LAP${L ? " (" + L.no + ")" : ""}</th></tr></thead><tbody>`
      + `<tr><td class="n">Lap</td><td>${lapT(t.target)}</td><td class="${L && L.delta > 0 ? "up" : "dn"}">${L ? sgn(L.delta) : DASH}</td></tr>${sec}</tbody></table>`
      + `<p class="small">Sectors are thirds of the lap. For race-pace runs: hit the target every lap rather than one fast lap.</p></div>`;
  }

  function paintSheet(d) {
    const u = d.units === "kmh" ? "km/h" : "mph";
    const rows = (d.sheet || []).map((x) => `<tr><td class="n">${E(x.corner)}</td><td>${num(x.before, " m")}</td><td>${num(x.brake_d)}</td><td>${num(x.turnin_d)}</td><td>${num(x.apex_d)}</td><td>${num(x.exit_d)}</td><td>${num(x.min)}</td><td>${num(x.gear)}</td><td class="note"></td></tr>`).join("");
    return `<div class="panel card wide"><div class="hd"><span class="lbl">Reference points</span><span class="src">from your best lap${d.best ? " (lap " + d.best.no + ")" : ""} · lap distance in metres</span></div>`
      + (rows ? `<table><thead><tr><th>CORNER</th><th>BRAKE · BEFORE TURN-IN</th><th>BRAKE AT</th><th>TURN-IN</th><th>APEX</th><th>FULL THROTTLE</th><th>MIN ${u}</th><th>GEAR</th><th style="text-align:left">NIGHT NOTES</th></tr></thead><tbody>${rows}</tbody></table>`
        : `<div class="emp">${E(d.why || "Needs a clean lap.")}</div>`) + `</div>`;
  }

  function paint(d) {
    if (!d) { $("whereA").textContent = "Can't reach the Race Engineer on the PC."; return; }
    const sig = JSON.stringify(d);
    if (sig === S.sig) return;
    S.sig = sig; S.d = d;
    $("whereA").textContent = [d.track, d.car].filter(Boolean).join(" · ") || "Track learning";
    const s = d.settings || {};
    $("whereB").innerHTML = (d.live ? "<i>this session</i>" : "your last recorded session") + ` · live calls: coach ${s.calls_track_coach ? "on" : "off"}, target pace ${s.calls_target_pace ? "on" : "off"}, brake cues ${s.calls_brake_cues ? "on" : "off"}`;
    $("page").innerHTML = paintStats(d) + `<div class="cards">${paintPlan(d)}${paintFocus(d)}${paintChecks(d)}${paintSteps(d)}${paintTarget(d)}${paintSheet(d)}</div>`;
    paintViz();
  }

  // ------------------------------------------------------------------ visualisation timer (iPad only)
  const V = { t0: null, el: null, raf: 0 };
  function vzNow() { return V.t0 != null ? (performance.now() - V.t0) / 1000 : V.el; }
  function vzFmt(t) { return t == null ? "0:00.0" : `${Math.floor(t / 60)}:${(t % 60).toFixed(1).padStart(4, "0")}`; }
  function vzTick() { $("vzClock").textContent = vzFmt(vzNow()); if (V.t0 != null) V.raf = requestAnimationFrame(vzTick); }
  function paintViz() {
    const d = S.d || {}, el = V.el;
    const rows = [["Your best lap", d.best && d.best.time], ["Your last lap", d.last_lap && d.last_lap.time]].map(([n, t]) => {
      const diff = el != null && t != null ? el - t : null;
      return `<div><u>${n}</u><span>${lapT(t)}</span><span class="${diff == null ? "" : Math.abs(diff) <= 1 ? "ok" : "bad"}">${diff == null ? "" : sgn(diff, 2) + " s"}</span></div>`;
    }).join("");
    $("vzCmp").innerHTML = `<div><u>In your head</u><span>${el != null ? vzFmt(el) : DASH}</span><span></span></div>${rows}`;
  }
  $("vzStart").addEventListener("click", () => { V.t0 = performance.now(); V.el = null; $("vzClock").classList.add("run"); cancelAnimationFrame(V.raf); vzTick(); paintViz(); });
  $("vzStop").addEventListener("click", () => { if (V.t0 == null) return; V.el = (performance.now() - V.t0) / 1000; V.t0 = null; $("vzClock").classList.remove("run"); vzTick(); paintViz(); });
  $("vzReset").addEventListener("click", () => { V.t0 = null; V.el = null; $("vzClock").classList.remove("run"); vzTick(); paintViz(); });

  // ------------------------------------------------------------------ ic187 (#734/#733): segment timer
  const G = { sig: "", timer: 0 };
  const setS = (x) => !x ? DASH : `TC ${x.tc_lat ?? "–"}/${x.tc_lon ?? "–"} · BB ${x.bias ?? "–"} · MIG ${x.mig ?? "–"}`;
  async function segApi() {
    try { const r = await fetch(`/api/segments?k=${encodeURIComponent(KEY)}`); return r.ok ? await r.json() : null; }
    catch (e) { return null; }
  }
  function paintSeg(d) {
    const sig = JSON.stringify(d);
    if (sig === G.sig) return;
    G.sig = sig;
    if (!d || !d.ok) { $("segBody").innerHTML = `<div class="emp">${E((d && d.why) || "Can't reach the Race Engineer on the PC.")}</div>`; return; }
    const segs = d.segments || [];
    const rows = segs.map((s) => {
      const b = s.best, l = s.last, dl = b && l ? l.t - b.t : null;
      return `<tr class="${s.running ? "run" : ""}"><td class="n">${E(s.name)}</td><td class="${l && l.off ? "offc" : ""}">${l ? secT(l.t) : DASH}</td>`
        + `<td class="best">${b ? secT(b.t) : DASH}</td><td class="${dl == null ? "" : dl > 0.05 ? "up" : "dn"}">${dl == null ? DASH : sgn(dl)}</td>`
        + `<td>${s.n}</td><td>${l && l.min != null ? l.min.toFixed(0) : DASH}</td><td>${l ? l.exit.toFixed(0) : DASH}</td><td class="txt">${l ? E(setS(l.set)) : ""}</td></tr>`;
    }).join("");
    const combos = segs.filter((s) => (s.by_settings || []).length > 1).map((s) =>
      `<div class="combo"><span class="lbl" style="margin-right:10px">${E(s.name)} · by settings</span>`
      + s.by_settings.map((c) => `<span>${E(setS(c))}: <b>${secT(c.best)}</b> best · ${secT(c.avg)} avg · ${c.n} tr${c.n === 1 ? "y" : "ies"}</span>`).join("") + `</div>`).join("");
    const ld = d.last_done;
    const last = ld ? `<div class="lastd">Last finished: ${E(ld.name)} <b>${secT(ld.t)}</b> <span class="x">· ${E(ld.at.slice(11))} · ${E(setS(ld.set))}${ld.off ? " · had an off" : ""}</span></div>` : "";
    $("segBody").innerHTML = last + `<table><thead><tr><th>SEGMENT</th><th>LAST</th><th>BEST</th><th>LAST vs BEST</th><th>TRIES</th><th>MIN km/h</th><th>EXIT km/h</th><th style="text-align:left">SETTINGS (LAST TRY)</th></tr></thead><tbody>${rows}</tbody></table>`
      + (combos ? `<div style="margin-top:10px">${combos}</div>` : "");
    $("segSrc").textContent = `${d.track || ""} · your own list: ${d.file}`;
  }
  async function segLoop() {
    const d = await segApi();
    paintSeg(d);
    clearTimeout(G.timer);
    G.timer = setTimeout(segLoop, d && (d.segments || []).some((s) => s.running) ? 1000 : 3000);
  }
  segLoop();

  async function loop() {
    const d = await api();
    paint(d);
    clearTimeout(S.timer);
    S.timer = setTimeout(loop, d && d.live ? 5000 : 15000);
  }
  $("review").addEventListener("click", () => location.href = "review.html?" + new URLSearchParams({ k: KEY }).toString());
  $("back").addEventListener("click", () => {
    try { sessionStorage.setItem("re_stay_dash", "1"); } catch (e) {}
    location.href = "./" + (KEY ? "?k=" + encodeURIComponent(KEY) : "");
  });
  paintViz();
  loop();
})();
