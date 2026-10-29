/* #514 (2026-10-29): the guided garage. Your "My style" changes, one by one; each turns green by itself when iRacing
   reports it (the live setup values), amber if the number moved the other way, and the ones iRacing doesn't report
   (pads, dampers ...) you tick with a tap. Nothing guessed: before -> now are iRacing's own values. */
"use strict";
(function () {
  const G = { open: false, timer: 0, idle: 0 };
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const LABEL = { todo: "TO DO", done: "DONE", check: "CHECK", manual: "TAP WHEN DONE" };

  async function get() {
    try { const r = await fetch(`/api/setupguide?k=${encodeURIComponent(KEY)}`); return await r.json(); } catch (e) { return null; }
  }
  function paint(d) {
    const sheet = $("guide");
    if (!d || !d.active) { sheet.classList.remove("on"); G.open = false; return; }
    sheet.classList.add("on"); G.open = true;
    $("guideSub").textContent = `${d.car || "Your car"} · ${d.done}/${d.total} done${d.live ? "" : " · waiting for iRacing"}`;
    $("guideList").innerHTML = d.steps.map((s, i) => {
      const vals = s.key ? `<span class="gv">${esc(s.before ?? "–")}${s.now != null && s.now !== s.before ? ` → <b>${esc(s.now)}</b>` : ""}</span>` : "";
      return `<button class="gstep ${s.state}" data-i="${i}" data-state="${s.state}">
        <span class="gn">${s.state === "done" ? "✓" : i + 1}</span>
        <span class="gt">${esc(s.t)}${s.where ? `<small>${esc(s.where)}</small>` : ""}</span>${vals}
        <span class="gs">${LABEL[s.state] || ""}</span></button>`;
    }).join("");
    $("guideList").querySelectorAll(".gstep").forEach((b) => b.addEventListener("click", async () => {
      const st = b.dataset.state;
      if (st === "manual" || st === "check" || st === "done") paint(await post("/api/setupguide", { action: "tick", i: +b.dataset.i, on: st !== "done" }));
    }));
    if (d.total && d.done === d.total) $("guideSub").textContent += " · all in - run 3 laps and compare";
  }
  async function loop() {
    const d = await get();
    paint(d);
    clearTimeout(G.timer);
    G.timer = setTimeout(loop, G.open ? 1000 : 5000);     // fast while the checklist is up, slow to notice a start
  }
  function wire() {
    $("guideBtn").addEventListener("click", async () => {
      $("guideSub").textContent = "Reading your style sheet…";
      $("guide").classList.add("on");
      const d = await post("/api/setupguide", { action: "start" });
      if (d && d.active) paint(d);
      else { $("guideList").innerHTML = `<p class="gwhy">${esc((d && d.why) || "Couldn't start the guide.")}</p>`; setTimeout(() => $("guide").classList.remove("on"), 4000); }
    });
    $("guideClose").addEventListener("click", async () => { paint(await post("/api/setupguide", { action: "stop" })); });
    loop();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", wire); else wire();
})();
