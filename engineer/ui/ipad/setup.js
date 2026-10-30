/* #602 (2026-10-30): the iPad SETUP sheet. Data from /api/setupsheet (the PC's setup_sheet.py): iRacing's garage
   layout for this car filled with his real values; changed fields show current -> suggested, how many clicks and the
   reason; the checklist ticks itself when the live setup shows the change, and he can tick by hand.
   Nothing is computed here - every number on the page comes from the PC (iRacing's own values or the rulebook). */
"use strict";
(function () {
  const qs = new URLSearchParams(location.search);
  let KEY = qs.get("k") || "";
  try { if (KEY) localStorage.setItem("re_key", KEY); else KEY = localStorage.getItem("re_key") || ""; } catch (e) {}
  const AUTO = qs.get("auto") === "1";                 // opened by the dashboard because there's no session (#582)
  const $ = (id) => document.getElementById(id);
  const E = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const S = { d: null, tab: null, mode: "changes", id: qs.get("id") || null, timer: 0 };
  try { S.mode = localStorage.getItem("re_setup_mode") || "changes"; } catch (e) {}
  const LABEL = { todo: "TO DO · TAP WHEN DONE", done: "DONE", check: "CHECK · MOVED THE OTHER WAY", manual: "TAP WHEN DONE" };
  const AR = { arrows: ["‹", "›"], list: ["⌄", ""], read: ["", ""], unknown: ["", ""] };

  async function api(method, body) {
    const u = `/api/setupsheet?k=${encodeURIComponent(KEY)}${S.id && method === "GET" ? "&id=" + encodeURIComponent(S.id) : ""}`;
    try {
      const r = await fetch(u, method === "GET" ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      return r.ok ? await r.json() : null;
    } catch (e) { return null; }
  }
  function toast(t) { const el = $("toast"); el.textContent = t; el.classList.add("on"); clearTimeout(el._t); el._t = setTimeout(() => el.classList.remove("on"), 2600); }

  function countByTab(d) {
    const n = {};
    for (const t of d.tabs || []) n[t.name] = t.rows.flat().reduce((a, s) => a + s.fields.filter((f) => f.changed).length, 0);
    return n;
  }
  function field(f) {
    const a = AR[f.adj] || AR.unknown;
    const ro = f.adj === "read";
    if (!f.changed) {
      const dim = S.d.has && S.mode === "full";
      return `<div class="f${ro ? " ro" : ""}${dim ? " dim" : ""}${f.extra ? " extra" : ""}"><span class="l">${E(f.label)}</span><span class="ar">${a[0]}</span>`
        + `<span class="v">${f.value === "—" ? '<span class="x">—</span>' : E(f.value)}${f.live ? "" : ""}</span><span class="ar">${a[1]}</span></div>`;
    }
    const done = f.state === "done";
    const val = f.sug ? `<s>${E(f.was)}</s>${E(f.sug)}` : `${E(f.was)}`;
    return `<div class="f ch${done ? " done" : ""}" data-i="${f.i}"><span class="l">${E(f.label)}</span><span class="ar">${a[0]}</span>`
      + `<span class="v">${val}${done ? '<span class="tag">✓ DONE</span>' : ""}</span><span class="ar">${a[1]}</span>`
      + `<div class="why"><em>${E(f.how)}</em><span>${E(f.reason)}</span></div></div>`;
  }
  function paintSheet() {
    const d = S.d, g = $("garage");
    if (!d.tabs || !d.tabs.length) {
      g.innerHTML = `<div class="empty"><h2>No setup to show yet</h2><p>${E(d.why || "When the team meeting or My style suggests a setup it lands here, laid out like the garage. Open it again when iRacing is running to see your current setup.")}</p>`
        + `<button class="pill" id="build2">BUILD FROM MY LAPS</button></div>`;
      const b = $("build2"); if (b) b.addEventListener("click", build);
      return;
    }
    const cnt = countByTab(d);
    if (!S.tab || !d.tabs.some((t) => t.name === S.tab)) S.tab = (d.tabs.find((t) => cnt[t.name]) || d.tabs[0]).name;
    const lay = d.layout || {};
    const changesOnly = d.has && S.mode === "changes";
    function rowsHtml(tab) {
      let out = "";
      for (const row of tab.rows) {
        const secs = row.map((s) => {
          const fl = changesOnly ? s.fields.filter((f) => f.changed) : s.fields;
          if (changesOnly && !fl.length) return null;
          return `<div class="sec"><h3>${E(s.name)}:</h3>${fl.length ? fl.map(field).join("") : '<div class="none">Nothing shown here in the garage.</div>'}</div>`;
        }).filter(Boolean);
        if (secs.length) out += `<div class="row${secs.length === 1 ? " one" : ""}">${secs.join("")}</div>`;
      }
      return out;
    }
    let body = "";
    if (changesOnly) {                                   // every change on one screen, grouped by garage tab
      for (const t of d.tabs) if (cnt[t.name]) body += `<div class="tabh">${E(t.name)}</div>${rowsHtml(t)}`;
      if (!body) body = `<div class="notes">No changes on this suggestion.</div>`;
    } else {
      const tab = d.tabs.find((t) => t.name === S.tab);
      body = tab.empty ? `<div class="notes">Setup notes stay in iRacing - they aren't in the data iRacing shares.</div>` : rowsHtml(tab);
    }
    g.innerHTML = `<div class="gtop"><span class="gt">Garage</span><span class="gn">${E(lay.car || d.car || "")}${lay.generic ? " · iRacing's own sections (no garage layout for this car yet)" : ""}</span>`
      + `<span class="gu">${E(lay.generic ? "imperial · converted from iRacing" : "imperial · as in the garage")}</span></div>`
      + `<div class="tabs">${d.tabs.map((t) => `<button class="tab${t.name === S.tab && !changesOnly ? " on" : ""}" data-t="${E(t.name)}">${E(t.name)}${cnt[t.name] ? `<b>${cnt[t.name]}</b>` : ""}</button>`).join("")}</div>`
      + `<div class="sheet">${body}</div>`;
    g.querySelectorAll(".tab").forEach((b) => b.addEventListener("click", () => {
      S.tab = b.dataset.t;
      if (S.d.has && S.mode === "changes") { S.mode = "full"; try { localStorage.setItem("re_setup_mode", S.mode); } catch (e) {} paintHead(); }
      paintSheet();
    }));
    g.querySelectorAll(".f.ch").forEach((r) => r.addEventListener("click", () => tick(+r.dataset.i)));
  }
  function paintSide() {
    const d = S.d, s = $("side");
    $("wrap").classList.toggle("solo", !d.has);
    if (!d.has) { s.innerHTML = ""; return; }
    const pct = d.total ? Math.round(100 * d.done / d.total) : 0;
    const items = (d.items || []).map((it) => {
      const fv = it.fields.map((f) => `<span><u>${E(f.label)}</u>${E(f.before)}${f.sug ? ` → <b>${E(f.sug)}</b>` : ""}</span>`).join("");
      return `<button class="item ${it.state}" data-i="${it.i}"><span class="k">${it.state === "done" ? "✓" : it.i + 1}</span><span>`
        + `<div class="t">${E(it.t)}</div><div class="h">${E(it.how)}</div>${fv ? `<div class="fv">${fv}</div>` : ""}`
        + `<div class="r">${E(it.reason)}${it.note ? " " + E(it.note) : ""}</div>`
        + `<div class="st">${it.state === "done" && it.auto && it.hand == null ? "DONE · SEEN IN IRACING" : (LABEL[it.state] || "")}</div></span></button>`;
    }).join("");
    s.innerHTML = `<div class="panel card"><span class="lbl">Changes</span>`
      + `<div class="prog"><span class="n">${d.done}<small> / ${d.total}</small></span><span class="s">${d.done === d.total && d.total ? "All in - run 3 laps and compare" : "One change at a time, 3 laps, compare"}</span></div>`
      + `<div class="bar"><i style="width:${pct}%"></i></div>${items}`
      + `<p class="small">Ticks itself when iRacing shows the change (garage values update when you click Apply). Tap to tick or untick by hand.</p></div>`
      + `<div class="panel card"><span class="lbl">Values</span><div class="src${d.live_values ? " live" : ""}" style="margin-top:8px"><i></i>${d.live_values ? "Live from iRacing now" : "From your recording when this was suggested"}</div>`
      + `<p class="small">Every value is iRacing's own (converted to imperial like the garage, so the last digit can differ by one). "—" = iRacing didn't report it. A suggested number is only shown when the rule gives an exact step.</p>`
      + `${(d.notes || []).length ? `<p class="small">${d.notes.map(E).join("<br>")}</p>` : ""}</div>`;
    s.querySelectorAll(".item").forEach((b) => b.addEventListener("click", () => tick(+b.dataset.i)));
  }
  function paintHead() {
    const d = S.d;
    if (d.has) {
      $("whereA").textContent = [d.car, d.track, d.session].filter(Boolean).join(" · ");
      $("whereB").innerHTML = `Suggested ${E(d.date || "")} by <i>${E(d.source || "")}</i>${d.sessions && d.sessions.length ? ` · from ${d.sessions.map((x) => `${E(x.track)} (${x.laps} laps)`).join(", ")}` : ""}`;
    } else {
      $("whereA").textContent = d.tabs && d.tabs.length ? "Your setup now (live from iRacing)" : (d.error || "No suggested setup yet");
      $("whereB").textContent = d.tabs && d.tabs.length ? "No suggestion from the team yet" : "";
    }
    const h = $("hist");
    h.innerHTML = (d.history || []).map((x) => `<option value="${E(x.id)}"${x.id === d.id ? " selected" : ""}>${E(x.date || "")} · ${E(x.track || x.car || "")} · ${x.n} change${x.n === 1 ? "" : "s"}${x.current ? " (latest)" : ""}</option>`).join("");
    h.style.display = (d.history || []).length > 1 ? "" : "none";
    $("mode").style.display = d.has ? "" : "none";
    $("mode").querySelectorAll("button").forEach((b) => b.classList.toggle("on", b.dataset.m === S.mode));
  }
  function paint(d) {
    if (!d) { $("whereA").textContent = "Can't reach the Race Engineer on the PC."; return; }
    S.d = d;
    paintHead(); paintSheet(); paintSide();
    if (AUTO && d.on_track) location.href = "./" + (KEY ? "?k=" + encodeURIComponent(KEY) : "");   // #582: back to the dashboard on track
  }
  async function tick(i) {
    const it = (S.d.items || []).find((x) => x.i === i);
    if (!it) return;
    paint(await api("POST", { action: "tick", id: S.d.id, i, on: it.state !== "done" }));
  }
  async function build() {
    toast("Reading your laps…");
    const d = await api("POST", { action: "build" });
    if (d) { S.id = null; paint(d); toast(d.why || "New suggestion on the sheet."); }
  }
  async function loop() {
    paint(await api("GET"));
    clearTimeout(S.timer);
    S.timer = setTimeout(loop, S.d && S.d.session_live ? 2000 : 10000);
  }
  $("mode").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
    S.mode = b.dataset.m; try { localStorage.setItem("re_setup_mode", S.mode); } catch (e) {}
    paintHead(); paintSheet();
  }));
  $("hist").addEventListener("change", (e) => { S.id = e.target.value; loop(); });
  $("build").addEventListener("click", build);
  $("back").addEventListener("click", () => {
    try { sessionStorage.setItem("re_stay_dash", "1"); } catch (e) {}
    location.href = "./" + (KEY ? "?k=" + encodeURIComponent(KEY) : "");
  });
  if (qs.get("fixture")) { const f = document.createElement("div"); f.className = "fixture"; f.textContent = qs.get("fixture"); document.body.appendChild(f); }
  loop();
})();
