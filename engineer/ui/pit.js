/* Pit card on the Radio tab: stint, the plan, what's in iRacing's pit menu. Same plan as the radio and the iPad. */
"use strict";
const PC = { s: null, draft: null };
const pcEl = (id) => document.getElementById(id);
const pcLap = (t) => { if (t == null || t <= 0) return "–"; const m = Math.floor(t / 60); return `${m}:${(t - m * 60).toFixed(3).padStart(6, "0")}`; };
function pcState(s) {
  PC.s = s;
  if (!s || !s.live) { pcEl("pcMenu").textContent = "Not in a session"; return; }
  const met = s.metric, u = met ? "L" : "gal", cv = (x) => (met ? x : x / 3.785);
  pcEl("pcLaps").textContent = s.laps ?? "–";
  pcEl("pcDeg").textContent = s.deg != null ? (s.deg > 0 ? "+" : "") + s.deg.toFixed(2) : "–";
  pcEl("pcFl").textContent = s.fuel_lap ? cv(s.fuel_lap).toFixed(2) : "–";
  const m = s.menu || {}, ty = m.lf || m.rf || m.lr || m.rr, parts = [];
  if (m.fuel) parts.push(`${cv(m.fuel).toFixed(0)} ${u}`); if (ty) parts.push("tyres"); if (m.ws) parts.push("tear-off"); if (m.fr) parts.push("repair");
  pcEl("pcMenu").textContent = "In the car: " + (parts.join(" · ") || "nothing");
  pcEl("pcCard").classList.toggle("ask", !!s.awaiting);
  if (s.plan && (!PC.draft || PC.draft._k !== JSON.stringify(s.plan))) PC.draft = Object.assign({}, s.plan, { _k: JSON.stringify(s.plan) });
  pcEl("pcCmp").innerHTML = (s.complaints || []).slice(-3).map((c) => `<div>L${c.lap ?? "?"}${c.corner ? " · " + c.corner : ""}: ${String(c.text).replace(/</g, "&lt;")}</div>`).join("");
  pcPaint();
}
function pcPaint() {
  const d = PC.draft, s = PC.s, box = pcEl("pcPlan");
  if (!d || !s) { box.innerHTML = ""; return; }
  const met = s.metric, f = d.fuel == null ? "–" : d.fuel >= 900 ? "Full" : `${(met ? d.fuel : d.fuel / 3.785).toFixed(0)} ${met ? "L" : "gal"}`;
  box.innerHTML = `<div class="r"><span>Fuel</span><b>${f}</b></div>
    <div class="r tog ${d.tyres ? "on" : ""}" data-k="tyres"><span>Tyres</span><b>${d.tyres ? "4 new" : "Stay out"}</b></div>
    <div class="r tog ${d.pressure ? "on" : ""}" data-k="pressure"><span>Pressure</span><b>${d.pressure ? (d.pressure.end === "front" ? "Fronts" : "Rears") + " −0.5" : "As is"}</b></div>
    ${d.in_car ? `<div class="r"><span>Wheel</span><b style="font:600 12px Inter">${d.in_car.say}</b></div>` : ""}`;
  box.querySelectorAll(".tog").forEach((el) => el.addEventListener("click", () => {
    if (el.dataset.k === "tyres") { d.tyres = !d.tyres; if (!d.tyres) d.pressure = null; }
    else { const p = d.pressure; d.pressure = !p ? { end: "front", psi: -0.5 } : p.end === "front" ? { end: "rear", psi: -0.5 } : null; if (d.pressure) d.tyres = true; }
    pcPaint();
  }));
}
(function () {
  pcEl("pcPropose").addEventListener("click", async () => { try { await api.pit_propose(); pcState(await api.pit_state()); } catch (e) {} });
  pcEl("pcSend").addEventListener("click", async () => {
    const d = PC.draft; if (!d) return;
    try { const ok = await api.pit_apply({ fuel: d.fuel, tyres: d.tyres, ws: d.ws, fr: d.fr, pressure: d.pressure }); toast(ok ? "In the pit menu" : "Not in a session"); } catch (e) {}
  });
  pcEl("pcClear").addEventListener("click", async () => { try { await api.pit_clear(); PC.draft = null; pcState(await api.pit_state()); } catch (e) {} });
})();
function pcRuns(r) {
  if (!r || !r.plan || !r.plan.length) return "";
  return `<div class="pc-runs">${r.plan.map((x, i) => {
    const cls = x.done ? "done" : i === r.cur ? "cur" : "";
    const lap = i === r.cur && r.active ? ` · lap ${Math.min(r.laps, x.laps)}/${x.laps}` : ` · ${x.laps} laps`;
    return `<div class="${cls}"><i></i>${String(x.name).replace(/</g, "&lt;")}<span>${lap}</span></div>`;
  }).join("")}</div>`;
}
function pcStrat(s) {
  const box = pcEl("pcStrat"); if (!box) return;
  box.innerHTML = pcRuns(s && s.runplan) + (s && s.plans ? s.plans : []).map((p, i) => {
    const beat = (p.outlook || []).filter((x) => x.beat).map((x) => "#" + x.num);
    return `<div class="${i === s.rec ? "rec" : ""}"><b>${p.name}</b>${String(p.text).replace(/</g, "&lt;")}${beat.length ? ` · beats ${beat.join(", ")}` : ""}</div>`;
  }).join("");
}
window.pcState = pcState; window.pcStrat = pcStrat;
