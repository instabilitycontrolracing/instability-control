/* Driving coach (Analysis tab > Coach): your lap vs a fast reference, corner by corner, ranked by time lost.
   Every judgement text comes from the fixed coaching bank in engineer/coach.py. coach (2026-10-24) */
"use strict";

const CO = { on: false, res: null, key: "", busy: false, open: null, msg: "", msgBad: false, g61: null, g61Ask: false, token: false };

function coKey() { return `${anEl("anLap").value}|${anEl("anRef").value}`; }
function coEsc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }
const coSec = (x) => (x == null || !isFinite(x) ? "-" : (x > 0 ? "+" : x < 0 ? "−" : "") + Math.abs(x).toFixed(2) + " s");
const coN = (x) => (x == null || !isFinite(x) ? 0 : x);           // #344: untrusted gaps arrive as null

function coToggle() {
  CO.on = !CO.on;
  anEl("anCoach").classList.toggle("on", CO.on);
  if (!AN.cmp) return;
  if (CO.on) { AN.sel = null; anDraw(); }
  anSide();
}

/* called first thing by anSide(): returns true when the coach owns the side panel */
function coSide(sec) {
  if (!CO.on) return false;
  if (sec && CO.res) {   // a drag / click on the map: open the corner under it
    const hit = CO.res.corners.find((c) => c.span[1] >= sec.from && c.span[0] <= sec.to);
    if (hit) CO.open = hit.key;
  }
  anEl("anClear").style.visibility = AN.sel ? "visible" : "hidden";
  if (CO.key !== coKey() && !CO.busy) { coRun(); return true; }
  coRender();
  return true;
}

async function coRun() {
  if (!AN.cur) return;
  CO.busy = true; CO.key = coKey();
  coRender();
  let r = null;
  try { r = await api.coach_run(+anEl("anLap").value, anEl("anRef").value); } catch (e) { r = { error: String(e) }; }
  CO.busy = false;
  if (!r || r.error) { CO.res = null; coMsg((r && r.error) || "Can't coach this lap", true); }
  else { CO.res = r; CO.open = r.corners.length ? r.corners[0].key : null; }
  if (CO.key !== coKey()) return coRun();     // lap / reference changed while we were busy
  if (CO.on) coRender();
}

function coMsg(t, bad) { CO.msg = t || ""; CO.msgBad = !!bad; }

/* ---------------- loading a reference ---------------- */
async function coLoad(kind, arg) {
  coMsg(kind === "best" ? "Finding your fastest lap here in your recordings…" : kind === "g61" ? "Downloading the lap from Garage 61…" : "Reading the lap…"); coRender();
  let r = null;
  try { r = await api.coach_load(kind, arg || null); } catch (e) { r = { ok: false, error: String(e) }; }
  if (!r || !r.ok) { coMsg(r && r.cancel ? "" : (r && r.error) || "Couldn't load that lap", !(r && r.cancel)); coRender(); return; }
  CO.g61 = null; CO.g61Ask = false;
  const ref = anEl("anRef");
  let o = [...ref.options].find((x) => x.value === "coach");
  if (!o) { o = document.createElement("option"); o.value = "coach"; ref.prepend(o); }
  o.textContent = r.label; ref.value = "coach";
  coMsg(r.ref && r.ref.position === false ? "Loaded. This lap has no position data: the line is estimated." : "Loaded.");
  await anCompare();          // map, traces and the coach all follow the new reference
}

/* ---------------- Garage 61 (2026-10-28, web API only; the token stays in a local file, never in the page) ----------------
   One click = one lap list (the app caches it 15 minutes). No polling, no timers. */
async function coG61() {
  try { const st = await api.coach_state(); CO.token = !!(st && st.token); } catch (e) {}
  if (!CO.token) { CO.g61 = null; CO.g61Ask = true; coMsg(""); coRender(); return; }
  CO.g61Ask = false; coMsg("Asking Garage 61…"); coRender();
  let r = null;
  try { r = await api.coach_g61_laps(); } catch (e) { r = { ok: false, error: String(e) }; }
  if (!r || !r.ok) {
    CO.g61 = null;
    if (r && (r.kind === "no_token" || r.kind === "bad_token")) { CO.token = false; CO.g61Ask = true; }
    coMsg((r && r.error) || "Couldn't list Garage 61 laps", true); coRender(); return;
  }
  CO.g61 = r; coMsg(""); coRender();
}

async function g61SaveToken(v, status) {
  v = String(v || "").trim(); if (!v) return false;
  let r = null; try { r = await api.g61_save_token(v); } catch (e) {}
  CO.token = !!(r && r.token);
  if (!(r && r.ok)) { status("Couldn't save the token.", false); return false; }
  status("Saved. Testing…");
  let t = null; try { t = await api.g61_test(); } catch (e) {}
  const good = !!(t && t.ok && t.driving_data);
  status((t && t.status) || "No answer from Garage 61.", good);
  return good;
}

function coG61Html() {
  let h = "";
  if (CO.g61Ask) {
    h += `<div class="co-g61tok"><div class="co-msg">Garage 61 needs your personal token once. On garage61.net, make a personal access token
      with <b>driving data</b> ticked, copy it and paste it here. It is saved only on this PC and never shown again.</div>
      <div class="row"><input class="ask g61" id="coG61Token" type="password" autocomplete="off" spellcheck="false" placeholder="Paste your Garage 61 token">
      <button class="btn gold sm" id="coG61Save">Save</button></div><div class="st-line" id="coG61Status"></div></div>`;
  }
  const G = CO.g61;
  if (G && G.laps) {
    const mb = G.my_best;
    h += `<div class="co-g61">` + (G.laps.length ? G.laps.map((L) => {
      const gap = mb && L.time ? L.time - mb : null;
      const who = coEsc(L.driver) + (L.mine ? " (you)" : "");
      return `<div class="co-lap ${L.telemetry ? "" : "off"}" data-id="${coEsc(L.id)}">
        <span>${who}</span><span>${gap == null ? coEsc(L.date || "") : coSec(gap)}</span><b>${fmtLap(L.time)}</b><span>${L.telemetry ? "Load" : "no telemetry"}</span></div>`;
    }).join("") : `<div class="co-msg">No laps.</div>`) + `</div>`;
    if (G.note) h += `<div class="co-msg">${coEsc(G.note)}</div>`;
  }
  return h;
}

/* ---------------- drawing ---------------- */
function coRender() {
  const el = anEl("anSide"); if (!el || !CO.on) return;
  const R = CO.res, refLbl = anEl("anRef").selectedOptions[0]?.textContent || "";
  let h = `<div class="an-head co-head"><div><div class="lbl">Driving coach</div><div class="co-vs">vs ${coEsc(refLbl)}</div></div>
    <div class="an-vs"><div class="lbl">to find</div><div class="an-big ${R && R.total != null ? (R.total > 0 ? "lose" : "gain") : ""}">${R ? coSec(R.total) : "–"}</div></div></div>`;
  h += `<div class="co-src"><span class="lbl">Reference lap</span><div class="co-btns">
      <button class="btn sm" data-co="best">My best here</button><button class="btn sm" data-co="g61">Garage 61</button><button class="btn sm" data-co="csv">CSV file</button><button class="btn sm" data-co="ibt">.ibt file</button></div></div>`;
  if (CO.msg) h += `<div class="co-msg ${CO.msgBad ? "bad" : ""}">${coEsc(CO.msg)}</div>`;
  h += coG61Html();
  if (CO.busy) { h += `<div class="co-busy">Coaching…</div>`; coPut(el, h); return; }
  if (!R) { coPut(el, h); return; }
  const key = anEl("anRef").value;
  if (key !== "coach" && !CO.msg) h += `<div class="co-msg">Coaching against this reference. For more to learn, load a faster lap (your best here, Garage 61, a CSV or an .ibt).</div>`;
  if (R.focus.length) {
    h += `<div class="an-sub">Work on these first</div>`;
    R.focus.forEach((f, i) => {
      h += `<div class="co-focus" data-key="${coEsc((R.corners.find((c) => c.name === f.corner) || {}).key)}"><div class="co-n">${i + 1}</div><div class="co-fb">
        <div class="co-fh"><span>${coEsc(f.corner)} · ${coEsc(f.title)}</span><b class="lose">${coSec(f.lost)}</b></div>
        <div class="co-det">${coEsc(f.detail)}</div><div class="co-drill"><span class="lbl">Drill</span>${coEsc(f.drill)}</div></div></div>`;
    });
  } else if (R.total == null) h += `<div class="co-msg">${coEsc(R.delta_note || "Time gap not shown.")}</div>`;
  else h += `<div class="co-msg">Nothing to work on against this reference: you're as quick or quicker everywhere.</div>`;
  h += `<div class="an-sub">Corner by corner</div>`;
  const mx = Math.max(0.1, ...R.corners.map((c) => Math.abs(coN(c.lost))));
  for (const c of R.corners) {
    const open = CO.open === c.key;
    h += `<div class="co-corner ${open ? "open" : ""}" data-key="${coEsc(c.key)}"><div class="an-row co-row">
      <span class="n">${coEsc(c.name)}</span><span class="bar"><i class="${c.lost == null ? "" : c.lost > 0 ? "lose" : "gain"}" style="width:${Math.abs(coN(c.lost)) / mx * 100}%"></i></span>
      <span class="v ${c.lost == null ? "" : c.lost > 0 ? "lose" : "gain"}">${c.lost == null ? "-" : `${c.lost > 0 ? "+" : ""}${c.lost.toFixed(2)}`}</span></div>`;
    if (open) {
      h += `<div class="co-body"><div class="co-phase"><span>Entry ${coSec(c.phase.entry)}</span><span>Exit + straight ${coSec(c.phase.exit)}</span></div>`;
      if (!c.findings.length) h += `<div class="co-det">${coN(c.lost) > 0.03 ? "Small loss, no single cause." : "Nothing to fix here."}</div>`;
      for (const f of c.findings) {
        h += `<div class="co-find ${f.consequence ? "csq" : ""}"><div class="co-ft">${coEsc(f.title)}${f.consequence ? `<small>result</small>` : ""}</div>
          <div class="co-det">${coEsc(f.detail)}</div><div class="co-why">${coEsc(f.why)}</div>
          <div class="co-drill"><span class="lbl">Drill</span>${coEsc(f.drill)}</div></div>`;
      }
      const M = c.me, F = c.ref, v = (x, u = "") => (x == null ? "–" : `${Math.round(x)}${u}`), s2 = (x) => (x == null ? "–" : `${x.toFixed(2)} s`);
      h += `<table class="an-t"><tr><th></th><th>You</th><th>Ref</th></tr>
        <tr><td>Brake at</td><td>${v(M.brake_d, " m")}</td><td>${v(F.brake_d, " m")}</td></tr>
        <tr><td>Peak brake</td><td>${v(M.peak_brake, "%")}</td><td>${v(F.peak_brake, "%")}</td></tr>
        <tr><td>Release</td><td>${s2(M.release_s)}</td><td>${s2(F.release_s)}</td></tr>
        <tr><td>Turn-in</td><td>${v(M.turnin_d, " m")}</td><td>${v(F.turnin_d, " m")}</td></tr>
        <tr><td>Minimum</td><td>${v(M.min_kmh, " km/h")}</td><td>${v(F.min_kmh, " km/h")}</td></tr>
        <tr><td>Apex at</td><td>${v(M.apex_d, " m")}</td><td>${v(F.apex_d, " m")}</td></tr>
        <tr><td>Throttle on</td><td>${v(M.throttle_on_d, " m")}</td><td>${v(F.throttle_on_d, " m")}</td></tr>
        <tr><td>Full throttle</td><td>${v(M.full_throttle_d, " m")}</td><td>${v(F.full_throttle_d, " m")}</td></tr>
        <tr><td>Gear</td><td>${v(M.gear_apex)}</td><td>${v(F.gear_apex)}</td></tr>
        <tr><td>Exit</td><td>${v(M.exit_kmh, " km/h")}</td><td>${v(F.exit_kmh, " km/h")}</td></tr></table>`;
      if (c.consistency) h += `<div class="co-cons">Over ${c.consistency.laps} laps: brake point ±${c.consistency.brake_sd_m ?? "–"} m · minimum ±${c.consistency.min_sd_kmh} km/h · time ±${c.consistency.time_sd.toFixed(2)} s</div>`;
      h += `</div>`;
    }
    h += `</div>`;
  }
  for (const n of R.notes || []) h += `<div class="an-hint">${coEsc(n)}</div>`;
  h += `<div class="an-hint">Time per corner runs from its braking zone to the next one, so a slow exit counts where it starts.</div>`;
  const top = el.scrollTop;
  coPut(el, h);
  el.scrollTop = top;
}

function coPut(el, h) {
  const tok = document.getElementById("coG61Token"), keep = tok ? tok.value : "";   // a half-pasted token survives a redraw
  el.innerHTML = h; coBind(el);
  const t2 = document.getElementById("coG61Token"); if (t2 && keep) t2.value = keep;
}

function coBind(el) {
  el.querySelectorAll("[data-co]").forEach((b) => b.addEventListener("click", () => (b.dataset.co === "g61" ? coG61() : coLoad(b.dataset.co))));
  el.querySelectorAll(".co-lap:not(.off)").forEach((r) => r.addEventListener("click", () => coLoad("g61", r.dataset.id)));
  const tok = el.querySelector("#coG61Token");
  if (tok) {
    const st = (t, ok) => { const s = document.getElementById("coG61Status"); if (s) { s.textContent = t; s.className = "st-line" + (ok === true ? " ok" : ok === false ? " bad" : ""); } };
    const save = async () => {
      const v = tok.value; tok.value = "";                     // never keep the token in the page
      if (await g61SaveToken(v, st)) { g61Paint(); coG61(); }
    };
    el.querySelector("#coG61Save").addEventListener("click", save);
    tok.addEventListener("keydown", (e) => { if (e.key === "Enter") save(); });
  }
  const pick = (key) => {
    const c = CO.res && CO.res.corners.find((x) => x.key === key); if (!c) return;
    CO.open = CO.open === key ? null : key;
    AN.sel = CO.open ? [c.span[0], c.span[1]] : null;
    anDraw(); coRender();
  };
  el.querySelectorAll(".co-row").forEach((r) => r.addEventListener("click", () => pick(r.parentElement.dataset.key)));
  el.querySelectorAll(".co-focus").forEach((r) => r.addEventListener("click", () => { CO.open = null; pick(r.dataset.key); }));
}

/* ---------------- Settings > General > Garage 61 ---------------- */
function g61Status(t, ok) { const s = document.getElementById("g61Status"); if (s) { s.textContent = t; s.className = "st-line" + (ok === true ? " ok" : ok === false ? " bad" : ""); } }
function g61Paint() {
  const i = document.getElementById("g61Token");
  if (i) i.placeholder = CO.token ? "Saved on this PC (hidden)" : "Paste your Garage 61 token";
  const c = document.getElementById("g61Clear"); if (c) c.disabled = !CO.token;
}
async function g61Init() {
  const box = document.getElementById("g61Token"); if (!box) return;
  try { const st = await api.coach_state(); CO.token = !!(st && st.token); } catch (e) {}
  g61Paint();
  g61Status(CO.token ? "Token saved. Press Test to check it." : "No token yet. The coach also works without one: My best here, a CSV or an .ibt lap.");
  const save = async () => {
    const v = box.value; box.value = "";                      // never keep the token in the page
    await g61SaveToken(v, g61Status); g61Paint();
  };
  document.getElementById("g61Save").addEventListener("click", save);
  box.addEventListener("keydown", (e) => { if (e.key === "Enter") save(); });
  document.getElementById("g61Test").addEventListener("click", async () => {
    g61Status("Testing…");
    let r = null; try { r = await api.g61_test(); } catch (e) {}
    g61Status((r && r.status) || "No answer from Garage 61.", !!(r && r.ok && r.driving_data));
  });
  document.getElementById("g61Clear").addEventListener("click", async () => {
    try { await api.g61_clear_token(); } catch (e) {}
    CO.token = false; CO.g61 = null; g61Paint(); g61Status("Token removed from this PC.");
  });
}

/* ---------------- wiring ---------------- */
(function coBoot() {
  const btn = document.getElementById("anCoach");
  if (btn) btn.addEventListener("click", coToggle);
  const wait = () => { if (typeof api !== "undefined" && api) g61Init(); else setTimeout(wait, 200); };
  wait();
})();

/* browser preview only: sample data for the Analysis tab and the coach (see coach_mock.js) */
window.coachMock = function () {
  const D = window.COACH_SAMPLE; if (!D) return {};
  let token = false, loaded = false;
  const cmp = () => JSON.parse(JSON.stringify(D.compare));
  return {
    an_sessions: async () => D.sessions,
    an_open: async () => JSON.parse(JSON.stringify(D.open)),
    an_compare: async () => cmp(),
    an_section: async (a, b) => ({ from: a, to: b, lost: 0, corners: [], notes: ["Preview: no Python behind this page."] }),
    coach_state: async () => ({ token, ref: loaded ? { label: "sample" } : null }),
    g61_save_token: async (t) => { token = !!t; return { ok: true, token }; },
    g61_clear_token: async () => { token = false; return { ok: true, token }; },
    g61_test: async () => (token ? { ok: true, driving_data: true, plan: "free", status: "Connected as Preview Driver (free plan). Driving data: yes. The API shows your own and your teammates' laps." }
      : { ok: false, kind: "no_token", status: "No Garage 61 token yet." }),
    coach_g61_laps: async () => D.g61,
    coach_load: async () => { loaded = true; return { ok: true, key: "coach", label: D.ref_label, ref: { position: true } }; },
    coach_run: async () => JSON.parse(JSON.stringify(D.coach)),
    coach_last: async () => D.coach,
  };
};
window.coSide = coSide;
