/* Setup helper: Project CARS 2-style click-through race engineer. No AI: a fixed bank of fixes. */
"use strict";
const SU = { data: null, kind: null, cond: "dry", area: null, prob: null, step: 0, inited: false };
const suEl = (id) => document.getElementById(id);
const suEsc = (s) => String(s ?? "").replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));

async function suOpen() {
  if (!SU.inited) {
    SU.inited = true;
    suEl("suRestart").addEventListener("click", () => suArea());
    document.querySelectorAll("#suCar button").forEach((b) => b.addEventListener("click", () => suLoad(b.dataset.k)));
    document.querySelectorAll("#suCond button").forEach((b) => b.addEventListener("click", () => { SU.cond = b.dataset.k; suSeg("suCond", SU.cond); if (SU.prob) suResult(); }));
    await suLoad(null);
  }
}

function suSeg(id, key) {
  const seg = suEl(id), btns = [...seg.querySelectorAll("button")];
  btns.forEach((b) => b.classList.toggle("active", b.dataset.k === key));
  const a = btns.find((b) => b.dataset.k === key) || btns[0], ink = seg.querySelector(".ink");
  ink.style.left = a.offsetLeft + "px"; ink.style.width = a.offsetWidth + "px";
}

async function suLoad(kind) {
  let d = null;
  try { d = await api.setup_bank(kind); } catch (e) {}
  if (!d) return;
  SU.data = d; SU.kind = d.kind;
  requestAnimationFrame(() => { suSeg("suCar", d.kind); suSeg("suCond", SU.cond); });
  suEl("suSrc").textContent = d.car ? (d.kind === d.auto ? `${d.car} · ${d.track}` : "No current values") : "No telemetry";
  const det = d.detected || [];
  const box = suEl("suDetect");
  box.innerHTML = det.length ? `<span class="lbl">Detected</span>` + det.map((x) => {
    const p = d.bank.problems.find((q) => q.id === x.id);
    return p ? `<button class="su-pill" data-id="${x.id}">${suEsc(p.label)}  ·  ${suEsc(x.corners.slice(0, 3).join(", "))}</button>` : "";
  }).join("") : "";
  box.querySelectorAll(".su-pill").forEach((b) => b.addEventListener("click", () => { const p = d.bank.problems.find((q) => q.id === b.dataset.id); SU.area = p.area; suPick(p.id); }));
  if (SU.prob && d.bank.problems.find((q) => q.id === SU.prob.id)) suPick(SU.prob.id); else suArea();
}

function suShow(html) {
  const st = suEl("suStage");
  st.innerHTML = `<div class="su-step">${html}</div>`;
  return st.firstChild;
}

function suArea() {
  SU.area = null; SU.prob = null;
  const det = new Set((SU.data.detected || []).map((x) => SU.data.bank.problems.find((p) => p.id === x.id)?.area));
  const el = suShow(`<div class="su-q">Where?</div>
    <div class="su-grid">${SU.data.bank.areas.map((a, i) => `<button class="su-opt ${det.has(a.id) ? "hot" : ""}" style="animation-delay:${i * 40}ms" data-a="${a.id}"><b>${suEsc(a.label)}</b><span>${suEsc(a.sub)}${det.has(a.id) ? " · detected" : ""}</span></button>`).join("")}</div>`);
  el.querySelectorAll(".su-opt").forEach((b) => b.addEventListener("click", () => suProblems(b.dataset.a)));
}

function suProblems(area) {
  SU.area = area;
  const a = SU.data.bank.areas.find((x) => x.id === area);
  const det = new Set((SU.data.detected || []).map((x) => x.id));
  const list = SU.data.bank.problems.filter((p) => p.area === area);
  const el = suShow(`<button class="su-back">‹ Back</button><div class="su-q">${suEsc(a.label)}</div>
    <div class="su-grid">${list.map((p, i) => `<button class="su-opt ${det.has(p.id) ? "hot" : ""}" style="animation-delay:${i * 40}ms" data-p="${p.id}"><b>${suEsc(p.label)}</b>${det.has(p.id) ? "<span>Detected</span>" : ""}</button>`).join("")}</div>`);
  el.querySelector(".su-back").addEventListener("click", suArea);
  el.querySelectorAll(".su-opt").forEach((b) => b.addEventListener("click", () => suPick(b.dataset.p)));
}

function suPick(id) {
  SU.prob = SU.data.bank.problems.find((p) => p.id === id); SU.step = 0; SU.tech = SU.prob.check.length ? "ask" : "car";
  suResult();
}

function suResult() {
  const p = SU.prob, vals = SU.data.values || {};
  let h = `<button class="su-back">‹ Back</button><div class="su-q">${suEsc(p.label)}</div>`;
  if (SU.tech === "ask") {
    h += `<div class="su-card tech"><div class="lbl">Check first</div>${p.check.map((c) => `<p>${suEsc(c)}</p>`).join("")}
      <div class="su-btns"><button class="btn gold" id="suCarIt">It's the car</button><button class="btn" id="suMeIt">It's me</button></div></div>`;
  } else if (SU.tech === "me") {
    h += `<div class="su-card tech"><div class="lbl">Engineer</div><p>Work on it for 3 laps, then compare in Analysis.</p>
      <div class="su-btns"><button class="btn" id="suCarIt">Show fixes anyway</button></div></div>`;
  } else {
    const steps = p.steps, s = steps[Math.min(SU.step, steps.length - 1)];
    if (SU.step >= steps.length) {
      h += `<div class="su-card fix"><div class="lbl">Mechanic</div><p>No more fixes. Go back to the last change that helped.</p>
        <div class="su-btns"><button class="btn" id="suAgain">Restart</button></div></div>`;
    } else {
      const now = s.key && vals[s.key] ? `<span class="su-tag"><b>Now</b>${suEsc(vals[s.key])}</span>` : "";
      h += `<div class="su-dots">${steps.map((_, i) => `<i class="${i < SU.step ? "done" : i === SU.step ? "on" : ""}"></i>`).join("")}</div>
        <div class="su-card fix"><div class="lbl">Mechanic · fix ${SU.step + 1} of ${steps.length}</div>
        <div class="su-change">${suEsc(s.t)}</div>
        <div class="su-meta">${s.where ? `<span class="su-tag"><b>Where</b>${suEsc(s.where)}</span>` : ""}${now}</div>
        ${s.why ? `<p class="su-why">${suEsc(s.why)}</p>` : ""}
        ${SU.cond === "wet" && p.wet ? `<div class="su-wet">Wet: ${suEsc(p.wet)}</div>` : ""}
        <p class="su-why">One change. 3 laps. Then:</p>
        <div class="su-btns"><button class="btn good" id="suBetter">Better</button><button class="btn" id="suSame">No change</button><button class="btn bad" id="suWorse">Worse</button></div></div>`;
    }
  }
  const el = suShow(h);
  el.querySelector(".su-back").addEventListener("click", () => suProblems(p.area));
  const on = (id, fn) => { const b = el.querySelector("#" + id); if (b) b.addEventListener("click", fn); };
  on("suCarIt", () => { SU.tech = "car"; suResult(); });
  on("suMeIt", () => { SU.tech = "me"; suResult(); });
  on("suAgain", () => { SU.step = 0; suResult(); });
  on("suBetter", () => { suShow(`<div class="su-card fix"><div class="lbl">Mechanic</div><div class="su-change">Keep it.</div><div class="su-btns"><button class="btn" id="x1">New problem</button><button class="btn" id="x2">One more step</button></div></div>`);
      suEl("x1").addEventListener("click", suArea); suEl("x2").addEventListener("click", () => suResult()); });
  on("suSame", () => { SU.step++; suResult(); toast("Put it back"); });
  on("suWorse", () => { SU.step++; suResult(); toast("Put it back"); });
}
window.suOpen = suOpen;
