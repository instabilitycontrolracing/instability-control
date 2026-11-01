/* #582 (2026-10-30): the iPad REVIEW page. Data from /api/review (the PC's review_page.py): the last recordings, the
   chosen one's summary and laps (sectors, gap to the best lap, flags), one lap's traces against the best lap (asked for
   when tapped), the debrief's problem corners and practice plan, and the setup suggestion.
   Nothing is computed here but the drawing - every number comes from the PC (#419). Missing data shows "—". */
"use strict";
(function () {
  const qs = new URLSearchParams(location.search);
  let KEY = qs.get("k") || "";
  try { if (KEY) localStorage.setItem("re_key", KEY); else KEY = localStorage.getItem("re_key") || ""; } catch (e) {}
  const AUTO = qs.get("auto") === "1";                 // opened by the dashboard because there's no session (#582)
  const $ = (id) => document.getElementById(id);
  const E = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const DASH = '<span class="x">—</span>';
  const S = { d: null, sid: qs.get("sid") || null, lap: qs.get("lap") ? +qs.get("lap") : null, tr: {}, sig: "", timer: 0, scrub: null };
  const FLAG = { pit: "PIT", incident: "INC", off: "OFF", invalid: "INVALID", partial: "PARTIAL" };

  async function api(extra) {
    try {
      const r = await fetch(`/api/review?k=${encodeURIComponent(KEY)}${S.sid ? "&sid=" + encodeURIComponent(S.sid) : ""}${extra || ""}`);
      return r.ok ? await r.json() : null;
    } catch (e) { return null; }
  }
  const lapT = (t) => t == null ? DASH : `${Math.floor(t / 60)}:${(t % 60).toFixed(3).padStart(6, "0")}`;
  const secT = (t) => t == null ? DASH : (t >= 60 ? lapT(t) : t.toFixed(3));
  const gapT = (g) => g == null ? DASH : (g >= 0 ? "+" : "−") + Math.abs(g).toFixed(3);
  const nav = (page) => location.href = page + "?" + new URLSearchParams(Object.assign({ k: KEY }, AUTO ? { auto: "1" } : {})).toString();

  // ------------------------------------------------------------------ header + summary
  function paintHead(d) {
    const s = d.session;
    $("whereA").textContent = s ? [s.track, s.car].filter(Boolean).join(" · ") || "—" : (d.why || "No session to show");
    $("whereB").innerHTML = s ? [s.type, s.date].filter(Boolean).map(E).join(" · ") + (s.file ? ` · from <i>${E(s.file)}</i>` : "") : "";
    const p = $("pick");
    p.innerHTML = (d.sessions || []).map((x, i) => `<option value="${E(x.id)}"${x.id === d.sid ? " selected" : ""}>`
      + `${E(x.date || "")} · ${E(x.track || "?")}${x.type ? " · " + E(x.type) : ""}${i === 0 ? " (latest)" : ""}</option>`).join("");
    p.style.display = (d.sessions || []).length > 1 ? "" : "none";
  }
  function stat(lbl, v, s2, cls) {
    return `<div class="panel stat"><span class="lbl">${lbl}</span><div class="v ${cls || ""}">${v}</div><div class="s">${s2}</div></div>`;
  }
  function paintStats(s) {
    const bestLap = s.laps.find((L) => L.best);
    const inc = s.incidents;
    return `<div class="stats">`
      + stat("Session", E(s.type || "—"), E(s.date || "—"), "word")
      + stat("Best lap", lapT(s.best), bestLap ? `lap ${bestLap.n}${s.best_clean ? "" : " · <b>not a clean lap</b>"}` : "no full lap in this recording", s.best != null && s.best_clean ? "purple" : "")
      + stat("Clean-lap average", lapT(s.avg), s.avg != null ? `over ${s.avg_n} clean lap${s.avg_n === 1 ? "" : "s"}${s.spread != null ? ` · ±${s.spread.toFixed(2)} s` : ""}` : "needs a clean lap (no incident, pit or off)")
      + stat("Laps", `${s.laps_n}`, `${s.clean_n} clean · full laps only`)
      + stat("Incidents", inc == null ? DASH : `${inc}<small>x</small>`, inc == null ? "not in this recording" : inc === 0 ? "a clean session" : "incident points in the session")
      + `<div class="panel stat"><span class="lbl">Best sectors</span><div class="secs">${[0, 1, 2].map((k) => `<span><u>S${k + 1}</u>${secT(s.best_sec[k])}</span>`).join("")}</div>`
      + `<div class="s">${s.best_sec.some((x) => x != null) ? "from the clean laps" : "needs a clean lap"}</div></div>`
      + `</div>`;
  }

  // ------------------------------------------------------------------ lap list
  function paintLaps(s) {
    const rows = s.laps.slice().reverse().map((L) => {
      const fl = (L.best ? `<span class="fl best">BEST</span>` : "") + L.flags.map((f) => `<span class="fl ${f}">${f === "incident" ? `${L.incidents}x INC` : FLAG[f] || f.toUpperCase()}</span>`).join("")
        + (!L.flags.length && L.clean && !L.best ? `<span class="fl clean">CLEAN</span>` : "");
      const sec = [0, 1, 2].map((k) => {
        const v = L.sec[k], b = s.best_sec[k];
        return `<td>${v != null && b != null && Math.abs(v - b) < 0.0005 && L.clean ? `<span class="p">${secT(v)}</span>` : secT(v)}</td>`;
      }).join("");
      const fx = (L.fx || []).length ? `<tr class="fxr"><td colspan="7"><span class="fxl">${L.fx.map(E).join(" · ")}</span></td></tr>` : "";
      return `<tr class="lap${L.n === S.lap ? " sel" : ""}${L.time == null ? " part" : ""}" data-n="${L.n}"><td class="n">${L.n}</td>`
        + `<td class="t">${L.best && s.best_clean ? `<span class="p">${lapT(L.time)}</span>` : lapT(L.time)}</td>${sec}`
        + `<td class="g${L.delta > 0 ? " up" : ""}">${L.best ? "" : gapT(L.delta)}</td><td>${fl}</td></tr>${fx}`;
    }).join("");
    return `<section class="panel laps"><div class="hd"><span class="lbl">Laps</span><span class="k">newest first · tap a lap for its traces</span></div>`
      + `<table><thead><tr><th>LAP</th><th>TIME</th><th>S1</th><th>S2</th><th>S3</th><th>TO BEST</th><th></th></tr></thead><tbody>${rows}</tbody></table>`
      + `<div class="foot">Sectors are thirds of the lap. Purple = your best. "—" = not in the recording (a lap that started or ended part-way round has no time).</div></section>`;
  }

  // ------------------------------------------------------------------ traces
  function defaultLap(s) {
    const full = s.laps.filter((L) => L.time != null);
    if (!full.length) return null;
    const other = full.filter((L) => !L.best);
    return (other.length ? other[other.length - 1] : full[full.length - 1]).n;
  }
  function paintTraceBox() {
    return `<section class="panel tr" id="trBox"><div class="hd"><span class="ttl" id="trT"></span><span class="key" id="trK"></span></div>`
      + `<div class="read" id="trR"></div><div id="trC"></div><div class="note" id="trN"></div></section>`;
  }
  function drawTrace() {
    const s = S.d && S.d.session, box = $("trC");
    if (!box || !s) return;
    const tr = S.tr[S.d.sid + ":" + S.lap];
    if (S.lap == null) { $("trT").textContent = "Traces"; box.innerHTML = `<div class="emp">No full lap in this recording, so there's nothing to draw.</div>`; return; }
    if (!tr) { $("trT").innerHTML = `Lap <i>${S.lap}</i>`; box.innerHTML = `<div class="emp">Loading the traces…</div>`; return; }
    if (tr.error) { $("trT").innerHTML = `Lap <i>${S.lap}</i>`; box.innerHTML = `<div class="emp">${E(tr.error)}</div>`; $("trK").innerHTML = ""; $("trN").textContent = ""; return; }
    const me = tr.me, rf = tr.best, D = tr.d, L = tr.track_len || D[D.length - 1] || 1;
    $("trT").innerHTML = rf ? `Lap <i>${tr.lap}</i> vs your best (lap ${tr.ref})` : `Lap <i>${tr.lap}</i> · your best lap`;
    $("trK").innerHTML = `<span><i style="background:var(--gold2)"></i>lap ${tr.lap}</span>` + (rf ? `<span><i style="background:rgba(245,243,238,.55)"></i>best · lap ${tr.ref}</span>` : "");
    const W = Math.max(300, box.clientWidth), PADL = 46, PADR = 8, w = W - PADL - PADR;
    const unit = tr.units === "kmh" ? "km/h" : "mph";
    const lanes = [{ k: "v", name: "SPEED", unit, h: 190 }, { k: "thr", name: "THROTTLE", h: 62 }, { k: "brk", name: "BRAKE", h: 62 }];
    if (tr.gap) lanes.push({ k: "gap", name: "GAP", unit: "s", h: 92 });
    let y = 34, out = "";
    const X = (d) => PADL + (d / L) * w;
    // corner names along the top (the same corners as Analysis)
    for (const c of tr.corners || []) {
      const cx = X((c.start + c.end) / 2);
      if (cx > PADL + 10 && cx < W - PADR - 10) out += `<line x1="${cx.toFixed(1)}" y1="14" x2="${cx.toFixed(1)}" y2="9999" stroke="rgba(255,255,255,.05)"/><text x="${cx.toFixed(1)}" y="10" text-anchor="middle">${E(c.name.replace(/^Turn /, "T"))}</text>`;
    }
    const geo = [];
    for (const ln of lanes) {
      let lo, hi;
      if (ln.k === "thr" || ln.k === "brk") { lo = 0; hi = 1; }
      else if (ln.k === "gap") { lo = Math.min(0, ...tr.gap); hi = Math.max(0, ...tr.gap); const pad = Math.max(0.05, (hi - lo) * 0.08); lo -= pad; hi += pad; }
      else { const all = [...(me.v || []), ...((rf && rf.v) || [])].filter((x) => x != null); lo = Math.floor(Math.min(...all) / 10) * 10; hi = Math.ceil(Math.max(...all) / 10) * 10; }
      const Y = (v) => y + ln.h - ((v - lo) / (hi - lo || 1)) * ln.h;
      out += `<rect x="${PADL}" y="${y}" width="${w}" height="${ln.h}" fill="rgba(0,0,0,.28)" rx="4"/>`;
      out += `<text class="ln" x="${PADL + 2}" y="${y - 5}">${ln.name}${ln.unit ? " · " + ln.unit : ""}</text>`;
      if (ln.k === "gap") {
        out += `<line x1="${PADL}" x2="${PADL + w}" y1="${Y(0)}" y2="${Y(0)}" stroke="rgba(255,255,255,.18)" stroke-dasharray="3 4"/>`;
        out += `<text x="${PADL - 6}" y="${y + 9}" text-anchor="end">${gapT(hi).replace(/(\.\d\d)\d$/, "$1")}</text><text x="${PADL - 6}" y="${y + ln.h}" text-anchor="end">${gapT(lo).replace(/(\.\d\d)\d$/, "$1")}</text>`;
      } else if (ln.k === "v") {
        out += `<text x="${PADL - 6}" y="${y + 9}" text-anchor="end">${hi}</text><text x="${PADL - 6}" y="${y + ln.h}" text-anchor="end">${lo}</text>`;
      } else {
        out += `<text x="${PADL - 6}" y="${y + 9}" text-anchor="end">100%</text><text x="${PADL - 6}" y="${y + ln.h}" text-anchor="end">0</text>`;
      }
      const path = (arr, n) => { let p = ""; for (let i = 0; i < n; i++) { if (arr[i] == null) continue; p += (p ? "L" : "M") + X(D[i]).toFixed(1) + " " + Y(arr[i]).toFixed(1); } return p; };
      if (ln.k === "gap") {
        out += `<path d="${path(tr.gap, tr.gap.length)}" fill="none" stroke="var(--gold2)" stroke-width="1.8"/>`;
      } else {
        if (rf && rf[ln.k]) out += `<path d="${path(rf[ln.k], Math.min(rf[ln.k].length, D.length))}" fill="none" stroke="rgba(245,243,238,.5)" stroke-width="1.4"/>`;
        if (me[ln.k]) out += `<path d="${path(me[ln.k], Math.min(me[ln.k].length, D.length))}" fill="none" stroke="var(--gold2)" stroke-width="1.8"/>`;
        else out += `<text x="${PADL + w / 2}" y="${y + ln.h / 2}" text-anchor="middle">not in this recording</text>`;
      }
      geo.push({ y, h: ln.h });
      y += ln.h + 26;
    }
    const H = y + 14;
    let ticks = "";
    const step = L > 8000 ? 2000 : L > 3000 ? 1000 : 500;
    for (let m = step; m < L; m += step) ticks += `<text x="${X(m).toFixed(1)}" y="${H - 2}" text-anchor="middle">${(m / 1000).toFixed(m % 1000 ? 1 : 0)} km</text>`;
    box.innerHTML = `<svg class="cv" id="trSvg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">${out}${ticks}<line id="trCur" x1="-10" x2="-10" y1="14" y2="${H - 14}" stroke="var(--gold)" stroke-width="1" opacity=".8"/></svg>`;
    $("trN").textContent = tr.gap ? "GAP above the line = this lap is behind the best lap at that point of the track." : rf ? "The time gap isn't shown: the two laps don't line up in the recording." : "This is your best lap of the session.";
    const svg = $("trSvg");
    const at = (ev) => {
      const r = svg.getBoundingClientRect(), x = (ev.touches ? ev.touches[0].clientX : ev.clientX) - r.left;
      const dd = Math.max(0, Math.min(L, ((x - PADL) / w) * L));
      let i = 0; while (i < D.length - 1 && D[i] < dd) i++;
      S.scrub = i; readout();
      $("trCur").setAttribute("x1", X(D[i])); $("trCur").setAttribute("x2", X(D[i]));
    };
    svg.addEventListener("pointerdown", at); svg.addEventListener("pointermove", (e) => { if (e.buttons || e.pointerType === "touch") at(e); });
    if (S.scrub != null && S.scrub < D.length) { $("trCur").setAttribute("x1", X(D[S.scrub])); $("trCur").setAttribute("x2", X(D[S.scrub])); }
    readout();
  }
  function readout() {
    const tr = S.tr[S.d.sid + ":" + S.lap], el = $("trR");
    if (!el || !tr || tr.error) { if (el) el.innerHTML = ""; return; }
    if (S.scrub == null || S.scrub >= tr.d.length) { el.innerHTML = `<u>Touch the traces to read the numbers at any point.</u>`; return; }
    const i = S.scrub, me = tr.me, rf = tr.best, unit = tr.units === "kmh" ? "km/h" : "mph";
    const v = (a, f) => a && a[i] != null ? f(a[i]) : "—";
    const pc = (x) => Math.round(x * 100) + "%";
    el.innerHTML = `<u>${(tr.d[i] / 1000).toFixed(2)} km</u> · speed <b>${v(me.v, (x) => x.toFixed(0))}</b>${rf ? ` / ${v(rf.v, (x) => x.toFixed(0))}` : ""} ${unit}`
      + ` · throttle <b>${v(me.thr, pc)}</b>${rf ? ` / ${v(rf.thr, pc)}` : ""} · brake <b>${v(me.brk, pc)}</b>${rf ? ` / ${v(rf.brk, pc)}` : ""}`
      + (tr.gap && tr.gap[i] != null ? ` · gap <b>${gapT(tr.gap[i])} s</b>` : "");
  }
  async function loadTrace() {
    const s = S.d && S.d.session;
    if (!s || S.lap == null) { drawTrace(); return; }
    const key = S.d.sid + ":" + S.lap;
    drawTrace();
    if (!S.tr[key]) {
      const d = await api(`&lap=${S.lap}`);
      if (d && d.trace) S.tr[key] = d.trace;
      else S.tr[key] = { error: "Can't reach the Race Engineer on the PC." };
      if (S.d.sid + ":" + S.lap === key) drawTrace();
    }
  }

  // ------------------------------------------------------------------ debrief + setup
  function paintDebrief(db) {
    const src = db && db.source ? `<span class="src">${db.source === "night review" ? "from the night review" : "from this session's debrief"}</span>` : "";
    if (!db || db.state !== "ready") {
      return `<div class="panel card"><div class="hd"><span class="lbl">Problem corners</span></div><div class="emp">${E((db && db.why) || "No debrief for this session.")}</div></div>`
        + `<div class="panel card"><div class="hd"><span class="lbl">Practice plan</span></div><div class="emp">The practice plan comes with the debrief.</div></div>`;
    }
    const corners = db.corners.map((c) => `<div class="it"><div class="t">${E(c.name)}</div><div class="w">${E(c.text)}</div></div>`).join("")
      + db.time_corners.map((c) => `<div class="it"><span class="num">${c.lost.toFixed(2)} s</span><div class="t">${E(c.name)}</div><div class="d">usually lost here between your usual lap and your best</div></div>`).join("");
    const top = db.top.map((t) => `<div class="it"><div class="t">${E(t.title)}</div><div class="w">${E(t.why)}</div><div class="d">${E(t.drill)}</div></div>`).join("");
    const plan = db.plan.map((p) => `<div class="it"><div class="t">${E(p.title)}</div><div class="w">${E(p.text)}</div></div>`).join("");
    return `<div class="panel card"><div class="hd"><span class="lbl">Problem corners</span>${src}</div>`
      + (corners || `<div class="emp">No corner stands out: no incidents, big slides or repeated lock-ups${db.incidents ? "" : " in this session"}.</div>`) + `</div>`
      + `<div class="panel card"><div class="hd"><span class="lbl">Practice plan</span>${src}</div>`
      + (plan || top || `<div class="emp">Nothing to practise from this session's mistakes. Keep stacking clean laps.</div>`)
      + (plan && top ? `<p class="small">Top things to work on: ${db.top.map((t) => E(t.title)).join(" · ")}</p>` : "") + `</div>`;
  }
  function paintSetup(st) {
    const btn = `<button class="pill solid go" id="goSetup">OPEN SETUP</button>`;
    if (!st || !st.has) {
      return `<div class="panel card"><div class="hd"><span class="lbl">Setup suggestion</span></div><div class="emp">No setup suggestion yet. When the team meeting or My style suggests one, it shows here and on SETUP.</div>${btn}</div>`;
    }
    const items = st.items.map((it) => {
      const fv = it.fields.map((f) => `<div><u>${E(f.label)}</u>${st.same_car ? `<em>in this session</em> ${f.here != null ? E(f.here) : "—"} · ` : ""}`
        + `<em>suggestion</em> ${E(f.before)}${f.sug ? ` → <b>${E(f.sug)}</b>` : ` (${E(it.how)})`}</div>`).join("");
      return `<div class="it sug${it.state === "done" ? " done" : ""}"><div class="t">${E(it.t)}</div><div class="d">${E(it.how)} · ${E(it.reason)}</div>${fv ? `<div class="fv">${fv}</div>` : ""}</div>`;
    }).join("");
    return `<div class="panel card"><div class="hd"><span class="lbl">Setup suggestion</span><span class="src">${E(st.date || "")} · ${E(st.source || "")}</span></div>`
      + `<p class="small">${E([st.car, st.track].filter(Boolean).join(" at "))} · ${st.done} of ${st.total} done${st.same_car ? "" : " · made for a different car than this session"}</p>`
      + (items || `<div class="emp">No changes on this suggestion.</div>`) + btn + `</div>`;
  }

  // ------------------------------------------------------------------ the page
  function paint(d) {
    if (!d) { $("whereA").textContent = "Can't reach the Race Engineer on the PC."; return; }
    if (AUTO && d.on_track) { location.href = "./" + (KEY ? "?k=" + encodeURIComponent(KEY) : ""); return; }   // #582: back on track
    const sig = JSON.stringify([d.sid, d.sessions, d.session, d.debrief, d.setup]);
    if (sig === S.sig) return;                          // nothing new (the iPad polls): keep the page as it is
    S.sig = sig; S.d = d;
    if (S.sid && d.sid !== S.sid) S.sid = d.sid;
    paintHead(d);
    const s = d.session;
    if (!s) {
      $("page").innerHTML = `<div class="panel empty"><h2>Nothing to review yet</h2><p>${E(d.why || "Drive a session and it shows up here.")}</p></div>`
        + `<div class="cards">${paintSetup(d.setup)}</div>`;
      wire(); return;
    }
    if (S.lap == null || !s.laps.some((L) => L.n === S.lap)) S.lap = defaultLap(s);
    $("page").innerHTML = paintStats(s) + `<div class="main">${paintLaps(s)}${paintTraceBox()}</div>`
      + `<div class="cards">${paintDebrief(d.debrief)}${paintSetup(d.setup)}</div>`;
    wire();
    loadTrace();
  }
  function wire() {
    document.querySelectorAll("tr.lap").forEach((r) => r.addEventListener("click", () => {
      S.lap = +r.dataset.n; S.scrub = null;
      document.querySelectorAll("tr.lap").forEach((x) => x.classList.toggle("sel", x === r));
      loadTrace();
    }));
    const g = $("goSetup"); if (g) g.addEventListener("click", () => nav("setup.html"));
  }
  async function loop() {
    const d = await api("");
    paint(d);
    clearTimeout(S.timer);
    S.timer = setTimeout(loop, d && d.session_live ? 2000 : 10000);
  }
  $("pick").addEventListener("change", (e) => { S.sid = e.target.value; S.lap = null; S.scrub = null; S.sig = ""; loop(); });
  $("setup").addEventListener("click", () => nav("setup.html"));
  $("debrief").addEventListener("click", () => nav("debrief.html"));
  $("track").addEventListener("click", () => nav("learn.html"));          // ic186 (#729): track learning
  $("back").addEventListener("click", () => {
    try { sessionStorage.setItem("re_stay_dash", "1"); } catch (e) {}
    location.href = "./" + (KEY ? "?k=" + encodeURIComponent(KEY) : "");
  });
  let rz = 0;
  addEventListener("resize", () => { clearTimeout(rz); rz = setTimeout(drawTrace, 150); });
  if (qs.get("fixture")) { const f = document.createElement("div"); f.className = "fixture"; f.textContent = qs.get("fixture"); document.body.appendChild(f); }
  loop();
})();
