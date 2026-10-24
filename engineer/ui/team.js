/* Team tab: chat with the engineer and the mechanic (local AI). */
"use strict";
const TM = { open: false, busy: false, answer: null, text: "", meet: null, kick: null };   // meet/kick: memory (2026-10-24)
const tmEl = (id) => document.getElementById(id);

/* ---- talking with the team (open mic + spoken answers) ---- */
const MT = { live: false, voice: true, want: false, state: "off", talking: null };
function mtPaint() {
  const mic = tmEl("mtMic"); if (!mic) return;
  mic.classList.toggle("on", MT.live);
  mic.classList.toggle("hearing", MT.live && MT.state === "hearing");
  mic.classList.toggle("thinking", MT.state === "thinking");
  tmEl("mtVoice").classList.toggle("on", MT.voice);
  tmEl("mtStop").classList.toggle("show", !!MT.talking);
  const st = tmEl("mtState");
  const label = MT.talking ? (MT.talking === "MECHANIC" ? "Mechanic" : "Engineer") : MT.state === "thinking" ? "Thinking" : MT.state === "hearing" ? "Hearing you" : MT.live ? "Listening" : "";
  st.textContent = label;
  st.className = "mt-state " + (MT.talking ? "talking" : MT.state);
}
function mtEvent(e) {
  if (e.t === "meet_state") { MT.state = e.state; if (e.state === "off") MT.live = false; }
  else if (e.t === "meet_level") tmEl("mtMic").style.setProperty("--lv", e.v.toFixed(2));
  else if (e.t === "meet_talk") MT.talking = e.on ? e.role || "ENGINEER" : null;
  mtPaint();
}

function tmSetState(state, reason) {
  const chip = tmEl("tmChip"); chip.className = "chip";
  const map = { ready: ["ok", "Ready"], loading: ["load", "Loading"], blocked: ["blocked", "Driving"],
                off: ["", "Off"], missing: ["blocked", "Not installed"], error: ["blocked", "Problem"] };
  const [c, t] = map[state] || ["", state];
  if (c) chip.classList.add(c);
  tmEl("tmState").textContent = t;
  TM.state = state;
  if (reason && state !== "ready" && state !== "loading") tmEl("tmCtx").textContent = reason;
  else tmCtx();
  // open mic comes back by itself once the team is ready (if you left it on)
  if (state === "ready" && MT.want && !MT.live && api.meet_live) api.meet_live(true).then((on) => { MT.live = on; mtPaint(); });
  if (state === "ready" && TM.kick && !TM.busy) { const k = TM.kick; TM.kick = null; tmAskModel(k, true); }   // memory (2026-10-24)
}

function tmCtx() {
  if (TM.meet) { tmEl("tmCtx").textContent = TM.meet.label; return; }                 // memory (2026-10-24)
  const s = (typeof AN !== "undefined" && AN.cur) ? `${AN.cur.track}  ·  ${AN.cur.car}  ·  lap ${document.getElementById("anLap").value}` +
    (AN.sel ? `  ·  ${Math.round(AN.sel[0])}–${Math.round(AN.sel[1])} m` : "") : "Newest session";
  tmEl("tmCtx").textContent = s;
}

async function tmOpen() {
  if (!TM.open) {
    TM.open = true;
    tmEl("tmSend").addEventListener("click", () => tmAsk(tmEl("tmAsk").value));
    tmEl("tmAsk").addEventListener("keydown", (e) => { if (e.key === "Enter") tmAsk(tmEl("tmAsk").value); });
    document.querySelectorAll(".chip-q").forEach((b) => b.addEventListener("click", () => tmAsk(b.dataset.q || b.textContent)));
    tmEl("tmNew").addEventListener("click", async () => { await api.team_reset(); tmEl("tmFeed").innerHTML = ""; tmLeaveMeeting(); });
    tmEl("mmMeet").addEventListener("click", () => tmMeeting("prerace"));                // memory (2026-10-24)
    tmEl("mmDebrief").addEventListener("click", () => tmMeeting("debrief"));
    tmEl("mtMic").addEventListener("click", async () => { const on = !MT.live; MT.live = on; MT.want = on; mtPaint(); try { MT.live = await api.meet_live(on); } catch (e) {} mtPaint(); });
    tmEl("mtVoice").addEventListener("click", async () => { MT.voice = !MT.voice; mtPaint(); try { await api.meet_voice(MT.voice); } catch (e) {} });
    tmEl("mtStop").addEventListener("click", () => api.meet_stop && api.meet_stop());
    try { const m = await api.meet_state(); MT.voice = m.voice; MT.live = m.live; MT.want = m.want_live; } catch (e) {}
    mtPaint();
  }
  tmCtx();
  mmLoad();
  try { const r = await api.team_open(); tmSetState(r.state, r.reason); } catch (e) {}
}

function tmAdd(cls, who, text) {
  const e = tmEl("tmEmpty"); if (e) e.remove();
  const el = document.createElement("div"); el.className = "tm-msg " + cls;
  el.innerHTML = `<span class="who">${who}</span><span class="x"></span>`;
  el.querySelector(".x").textContent = text;
  tmEl("tmFeed").appendChild(el);
  tmEl("tmFeed").scrollTo({ top: tmEl("tmFeed").scrollHeight, behavior: "smooth" });
  return el;
}

async function tmAsk(q) {
  q = (q || "").trim(); if (!q || TM.busy) return;
  tmEl("tmAsk").value = "";
  tmAdd("you", "YOU", q);
  if (TM.meet && TM.meet.kind === "prerace") {                // memory (2026-10-24): "what if" -> the strategy code answers first
    let wi = null; try { wi = await api.team_whatif(q); } catch (e) {}
    if (wi && wi.lines) tmAdd("strat", "STRATEGY", wi.lines.join("\n"));
    if (TM.state !== "ready") {
      if (!wi || !wi.lines) tmAdd("note", "", "Without the team AI the strategy code answers: what if it rains, one stop / two stops / no stop, a caution, no tyres, hotter or cooler, a longer race.");
      return;
    }
  } else if (TM.meet && TM.state !== "ready") { tmAdd("note", "", tmOffline()); return; }
  if (TM.state !== "ready") { tmAdd("err", "", TM.state === "blocked" ? "Not while driving." : "Still loading."); return; }
  tmAskModel(q, false);
}

async function tmAskModel(q, silent) {
  if (TM.busy) return;
  TM.busy = true; TM.text = ""; TM.answer = document.createElement("div"); TM.answer.className = "tm-answer";
  tmEl("tmFeed").appendChild(TM.answer);
  tmRender(true);
  try { await api.team_ask(q); } catch (e) { tmEvent({ t: "team_done", err: String(e) }); }
}

function tmRender(typing) {
  // split the answer into ENGINEER / MECHANIC bubbles as it streams in
  const box = TM.answer; if (!box) return;
  const parts = []; const re = /(ENGINEER:|MECHANIC:)/g; let last = 0, who = "ENGINEER", m;
  while ((m = re.exec(TM.text))) { const chunk = TM.text.slice(last, m.index).trim(); if (chunk) parts.push([who, chunk]); who = m[1].slice(0, -1); last = re.lastIndex; }
  const tail = TM.text.slice(last).trim(); if (tail || !parts.length) parts.push([who, tail]);
  box.innerHTML = "";
  parts.forEach(([w, t], i) => {
    const el = document.createElement("div"); el.className = "tm-msg " + (w === "MECHANIC" ? "mech" : "eng");
    el.innerHTML = `<span class="who">${w}</span><span class="x"></span>`;
    const x = el.querySelector(".x"); x.textContent = t.replace(/\*\*/g, "");
    if (typing && i === parts.length - 1) x.classList.add("tm-typing");
    el.style.animation = "none"; el.style.marginBottom = "10px"; el.style.display = "block";
    box.appendChild(el);
  });
  tmEl("tmFeed").scrollTop = tmEl("tmFeed").scrollHeight;
}

function tmEvent(e) {
  if (e.t === "team_state") tmSetState(e.state, e.reason);
  else if (e.t === "team_meeting") tmOpen().then(() => tmMeeting(e.kind));   // memory (2026-10-24): after a race / "debrief" on the radio
  else if (e.t === "team_tok") { TM.text += e.text; tmRender(true); }
  else if (e.t === "team_done") {
    TM.busy = false;
    if (e.err && !TM.text) { if (TM.answer) TM.answer.remove(); tmAdd("err", "", e.err); }
    else tmRender(false);
    TM.answer = null;
  }
}
async function tmHeard(text) {
  await tmOpen();
  if (/\bdebrief\b(?!.*\blap\b)/i.test(text)) return tmMeeting("debrief");                     // memory (2026-10-24)
  if (/\b(strategy|pre-?race|race) meeting\b|^\s*meeting\b/i.test(text)) return tmMeeting("prerace");
  // the team may still be loading: wait up to ~40 s for it, then ask
  for (let i = 0; i < 80 && TM.state === "loading"; i++) await new Promise((r) => setTimeout(r, 500));
  tmAsk(text);
}
/* ---- race memory, pre-race meeting, debrief (memory, 2026-10-24) ----
   The facts come from fixed code (strategy maths + memory + mechanic). With the team AI loaded they are folded
   into a card and the team talks them through; without it the card is the meeting. */
const mmLap = (t) => t ? `${Math.floor(t / 60)}:${(t % 60).toFixed(3).padStart(6, "0")}` : "-";
const mmEsc = (t) => String(t == null ? "" : t).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
function tmOffline() {
  return TM.state === "blocked" ? "The team joins you once you're out of the car. Until then, these are the facts from the strategy code and your history."
    : TM.state === "loading" ? "The team is loading. They'll talk you through it in a moment."
    : "The team AI isn't loaded, so here are the facts from the strategy code and your history.";
}
function tmLeaveMeeting() { TM.meet = null; TM.kick = null; tmEl("tmFeed").closest(".tm-wrap").classList.remove("meeting", "debrief"); tmCtx(); }

function tmFacts(pack, open) {
  const e = tmEl("tmEmpty"); if (e) e.remove();
  const el = document.createElement("div"); el.className = "tm-facts" + (open ? "" : " collapsed");
  const tag = pack.source === "similar car (rough guide)" ? "Rough guide" : pack.kind === "debrief" ? (pack.date || "") : "Facts";
  el.innerHTML = `<div class="fh"><span class="t">${mmEsc(pack.title)}</span><span class="w">${mmEsc(pack.car || "")}  ·  ${mmEsc(pack.track || "")}</span><span class="tg">${mmEsc(tag)}  ${open ? "▴" : "▾"}</span></div><div class="fb"></div>`;
  const fb = el.querySelector(".fb");
  for (const sec of pack.sections || []) {
    const d = document.createElement("div"); d.className = "fs" + (sec.h === "Strategy" ? " wide" : "");
    d.innerHTML = `<span class="lbl">${mmEsc(sec.h)}</span><ul>${sec.lines.map((l) =>
      `<li class="${/^ROUGH GUIDE/.test(l) ? "rough" : /^(- |MECHANIC|Mechanic)/.test(l) ? "mech" : ""}">${mmEsc(l.replace(/^- /, ""))}</li>`).join("")}</ul>`;
    fb.appendChild(d);
  }
  el.querySelector(".fh").addEventListener("click", () => {
    el.classList.toggle("collapsed");
    el.querySelector(".tg").textContent = `${tag}  ${el.classList.contains("collapsed") ? "▾" : "▴"}`;
  });
  tmEl("tmFeed").appendChild(el);
  tmEl("tmFeed").scrollTo({ top: tmEl("tmFeed").scrollHeight, behavior: "smooth" });
}

async function tmMeeting(kind) {
  if (TM.busy) return;
  let r; try { r = await api.team_meeting(kind); } catch (e) { r = { error: String(e) }; }
  if (!r || r.error) { tmAdd("err", "", "Couldn't put the meeting together" + (r && r.error ? `: ${r.error}` : ".")); return; }
  const p = r.pack;
  TM.meet = { kind, label: `${p.title}  ·  ${p.car || ""}  ·  ${p.track || ""}` };
  tmEl("tmFeed").closest(".tm-wrap").classList.toggle("meeting", kind === "prerace");
  tmEl("tmFeed").closest(".tm-wrap").classList.toggle("debrief", kind === "debrief");
  tmCtx();
  const ai = r.team === "ready" || r.team === "loading";
  tmFacts(p, !ai);
  tmSetState(r.team, r.reason);
  const kick = kind === "debrief" ? "Debrief me on that session." : "Run the pre-race meeting.";
  if (r.team === "ready") tmAskModel(kick, true);
  else { TM.kick = kick; tmAdd("note", "", tmOffline()); }
  mmLoad();
}

function mmPaint(m) {
  if (!m) return;
  const src = tmEl("mmSrc"), ag = m.ag || {};
  const rough = m.source === "similar car (rough guide)";
  src.className = "mm-src" + (rough ? " rough" : m.source === "none" ? " none" : "");
  src.textContent = rough ? "Rough guide" : m.source === "none" ? "No history" : "This car";
  tmEl("mmWhere").innerHTML = `${mmEsc(m.track)}<small>${mmEsc(m.car)}${m.live ? "  ·  live" : ""}</small>`;
  const rg = tmEl("mmRough");
  rg.hidden = !rough;
  if (rough) rg.textContent = `Nothing stored for this car here yet. Borrowed from ${(m.from_cars || []).join(", ")} at this track.`;
  const st = (k, v, g) => `<div>${k}<b class="${g ? "g" : ""}">${v}</b></div>`;
  tmEl("mmStats").innerHTML = ag.sessions ? [
    st("Sessions", `${ag.sessions}${ag.races ? ` <span style="font:600 11px Inter;color:var(--t3)">${ag.races} race${ag.races > 1 ? "s" : ""}</span>` : ""}`),
    st("Best lap", mmLap(ag.best), true), st("Typical", mmLap(ag.typical)),
    st("Fuel/lap", ag.fuel_lap ? `${ag.fuel_lap.toFixed(2)} L` : "-"),
    st("Pit loss", ag.pit_loss ? `${ag.pit_loss.toFixed(0)} s` : "-"),
    st("Tyre fade", ag.tyre_deg != null ? `${ag.tyre_deg.toFixed(2)} s` : "-")].join("") : "";
  const tr = ag.trouble || [];
  tmEl("mmTrouble").innerHTML = tr.length ? tr.slice(0, 3).map((t) => `<div class="mm-row">${mmEsc(t.name)}<b>+${t.lost.toFixed(2)}</b></div>`).join("")
    : `<div class="mm-empty">${ag.sessions ? "Needs 3 clean laps in a session." : "Drive a session here and it shows up."}</div>`;
  tmEl("mmSpots").innerHTML = ag.sessions ? `<div class="mm-row"><span>${ag.spins} spins · ${ag.offs} offs <span class="d">a session</span></span><b class="${(ag.spins + ag.offs) ? "" : "ok"}">${(ag.spins + ag.offs) ? "" : "clean"}</b></div>`
    + ((ag.hotspots || []).length ? `<div class="mm-row"><span>Most at ${(ag.hotspots || []).slice(0, 2).map(mmEsc).join(", ")}</span></div>` : "") : `<div class="mm-empty">-</div>`;
  tmEl("mmSess").innerHTML = (m.sessions || []).length ? m.sessions.slice(0, 4).map((x) =>
    `<div class="mm-row"><span>${mmEsc(x.session || "")}${x.pos ? ` · P${x.pos}` : ""} <span class="d">${mmEsc((x.date || "").slice(5, 10))}</span></span><b class="n">${mmLap(x.best)}</b></div>`).join("")
    : `<div class="mm-empty">No sessions yet.</div>`;
  tmEl("mmDebrief").disabled = !(m.sessions || []).length || rough;
}
async function mmLoad() { try { mmPaint(await api.mem_state()); } catch (e) {} }
function mmEvent(e) {
  if (e.t === "mem") mmPaint(e.s);
  else if (e.t === "mem_review") { if (TM.open) tmAdd("strat", "DATA REVIEW", e.text); }
}
window.tmOpen = tmOpen; window.tmEvent = tmEvent; window.tmHeard = tmHeard; window.mtEvent = mtEvent;
window.mmEvent = mmEvent; window.tmMeeting = tmMeeting;
