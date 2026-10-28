/* Tutorial: a short guided tour. Opened from the "?" button. */
"use strict";
const TOUR = [
  { el: "#go", h: "Start", p: "Turns the engineer on. Leave it on and drive." },
  { el: '.tab[data-p="radio"]', panel: "radio", h: "Radio", p: "Every call he makes. Type a question, or hold your radio button and talk." },
  { el: '.tab[data-p="series"]', panel: "series", h: "Series", p: "Pick the series, car and track you're practising for. What to watch for, your numbers, fuel and stops." },
  { el: '.tab[data-p="analysis"]', panel: "analysis", h: "Analysis", p: "Pick a lap. Compare it to your best, your theoretical best, or any lap. Red is time lost. Drag on the map to pick a section." },
  { el: '.tab[data-p="setup"]', panel: "setup", h: "Setup", p: "Pick what the car does. Get one fix at a time." },
  { el: '.tab[data-p="team"]', panel: "team", h: "Team", p: "Talk to the engineer and mechanic. Mic button: just speak, they answer out loud. Not while driving." },
  { el: "#pcCard", panel: "radio", h: "Pit", p: "Say \"box this lap\" or tap Plan. The engineer plans fuel, tyres and fixes for what you told him, then fills in the pit menu when you say yes." },
  { el: "#setBtn", h: "Settings", p: "Sound, calls, buttons, startup. The iPad link is in General." },
  { el: "#helpBtn", h: "Tutorial", p: "Opens this again." },
];
let tourI = 0, tourFrom = "radio";

function tourStart() {
  tourFrom = typeof curPanel !== "undefined" && curPanel !== "settings" ? curPanel : "radio";
  if (typeof curPanel !== "undefined" && curPanel === "settings") showPanel(tourFrom);
  tourI = 0;
  document.getElementById("tour").classList.add("on");
  tourShow();
}

function tourEnd() {
  document.getElementById("tour").classList.remove("on");
  if (typeof showPanel === "function") showPanel(tourFrom);
}

function tourShow() {
  const s = TOUR[tourI];
  if (s.panel && typeof showPanel === "function") showPanel(s.panel);
  const t = document.querySelector(s.el); if (!t) return;
  const r = t.getBoundingClientRect(), pad = 6;
  const hole = document.getElementById("tourHole"), card = document.getElementById("tourCard");
  Object.assign(hole.style, { left: r.left - pad + "px", top: r.top - pad + "px", width: r.width + pad * 2 + "px", height: r.height + pad * 2 + "px" });
  document.getElementById("tourN").textContent = `${tourI + 1} / ${TOUR.length}`;
  document.getElementById("tourH").textContent = s.h;
  document.getElementById("tourP").textContent = s.p;
  document.getElementById("tourBack").style.visibility = tourI ? "visible" : "hidden";
  document.getElementById("tourNext").textContent = tourI === TOUR.length - 1 ? "Done" : "Next";
  const W = window.innerWidth, H = window.innerHeight, cw = 340, ch = card.offsetHeight || 170;
  let x = r.left + r.width / 2 - cw / 2, y = r.bottom + 18;
  if (y + ch > H - 12) y = r.top - ch - 18;
  x = Math.max(12, Math.min(W - cw - 12, x));
  card.style.left = x + "px"; card.style.top = Math.max(12, y) + "px";
}

(function () {
  const on = (id, fn) => document.getElementById(id).addEventListener("click", fn);
  on("tourNext", () => { if (tourI < TOUR.length - 1) { tourI++; tourShow(); } else tourEnd(); });
  on("tourBack", () => { if (tourI > 0) { tourI--; tourShow(); } });
  on("tourSkip", tourEnd);
  document.addEventListener("keydown", (e) => {
    if (!document.getElementById("tour").classList.contains("on")) return;
    if (e.key === "Escape") tourEnd();
    else if (e.key === "ArrowRight" || e.key === "Enter") document.getElementById("tourNext").click();
    else if (e.key === "ArrowLeft") document.getElementById("tourBack").click();
  });
  window.addEventListener("resize", () => { if (document.getElementById("tour").classList.contains("on")) tourShow(); });
})();
window.tourStart = tourStart;
