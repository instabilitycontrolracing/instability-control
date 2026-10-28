/* Timing screen + session screen. Data comes from the engineer's timing.py over the same live link the iPad uses.
   ?embed=ipad  -> inside the iPad page (DASHBOARD button goes back)
   ?embed=pc    -> inside the PC app's Timing tab (POP OUT opens its own window)
   no embed     -> its own window / browser tab (the screen above the triples): full screen button */
(() => {
  const Q = new URLSearchParams(location.search);
  const KEY = Q.get("k") || "";
  const EMBED = Q.get("embed") || "";
  // ?view=timing / ?view=session: a window that only ever shows that page (so both can be open side by side)
  const LOCK = ["timing", "session", "both"].includes(Q.get("view")) ? Q.get("view") : "";
  const $ = (s) => document.querySelector(s);
  const store = {
    get(k, d) { try { const v = localStorage.getItem("tm." + k); return v == null ? d : v; } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem("tm." + k, v); } catch (e) {} },
  };
  let D = null, view = store.get("view", "both"), cls = store.get("cls", "mine"), unitF = store.get("unit", "F") === "F";
  const rowEls = new Map(), hist = new Map(), lastPos = new Map(), lastBest = new Map(), seenRc = new Set();
  let firstRc = true;

  // ---------------------------------------------------------------- formatting
  const lapT = (t) => { if (t == null || !(t > 0)) return "–"; const m = Math.floor(t / 60), s = t - m * 60; return m ? `${m}:${s.toFixed(3).padStart(6, "0")}` : s.toFixed(3); };
  const secT = (t) => (t == null ? "" : t >= 60 ? lapT(t) : t.toFixed(3));
  const gapT = (g) => {
    if (g == null) return "";
    if (typeof g === "string") return g;
    if (g >= 60) { const m = Math.floor(g / 60); return `+${m}:${(g - m * 60).toFixed(1).padStart(4, "0")}`; }
    return "+" + (g < 10 ? g.toFixed(3) : g.toFixed(1));
  };
  const clock = (s) => { if (s == null) return "–"; s = Math.max(0, Math.floor(s)); const h = Math.floor(s / 3600), m = Math.floor(s / 60) % 60, x = s % 60;
    return h ? `${h}:${String(m).padStart(2, "0")}:${String(x).padStart(2, "0")}` : `${m}:${String(x).padStart(2, "0")}`; };
  const temp = (c) => (c == null ? "–" : unitF ? `${Math.round(c * 9 / 5 + 32)}<small>°F</small>` : `${c.toFixed(1)}<small>°C</small>`);
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  // ---------------------------------------------------------------- layout
  function setView(v) {
    if (LOCK) v = LOCK;
    view = v; if (!LOCK) store.set("view", v);
    document.body.classList.remove("v-timing", "v-both", "v-session");
    const wide = innerWidth >= 1400;
    document.body.classList.add("v-" + (v === "both" && !wide ? "timing" : v));
    document.querySelectorAll("#viewSeg button").forEach((b) => b.classList.toggle("on", b.dataset.v === v));
    $("#vBoth").style.display = wide ? "" : "none";
    fit();
  }
  function fit() {
    const W = innerWidth, H = innerHeight;
    document.body.classList.toggle("narrow", W < 1500 && !document.body.classList.contains("v-timing") || W < 1180);
    document.body.classList.toggle("strip", H < 560 && W / H > 2.6);
    // the watch sits dead centre on the bar; it steps aside only if it would cover the header text or buttons
    const wt = $("#tmWatch");
    if (wt) {
      wt.classList.remove("clash");
      const r = wt.getBoundingClientRect();
      const hit = [...document.querySelectorAll("header .blk, header .ctrl")].some((e) => {
        if (e.offsetParent === null || getComputedStyle(e).display === "none") return false;
        const b = e.getBoundingClientRect(); return b.width > 0 && b.right > r.left + 4 && b.left < r.right - 4;
      });
      wt.classList.toggle("clash", hit);
    }
    document.documentElement.style.setProperty("--side", W >= 1900 ? "420px" : W >= 1500 ? "380px" : "330px");
    // rows grow to fill the screen (the screen above the triples shows the whole field without scrolling)
    const box = $("#rows"); if (!box || !D) return;
    const n = box.querySelectorAll(".row").length, heads = box.querySelectorAll(".chead").length;
    const avail = box.clientHeight - 16 - heads * 44;
    const h = Math.max(22, Math.min(46, Math.floor(avail / Math.max(1, n))));
    document.documentElement.style.setProperty("--rowh", h + "px");
    document.documentElement.style.setProperty("--fs", Math.max(13, Math.min(20, Math.round(h * 0.5))) + "px");
  }
  addEventListener("resize", () => setView(view));

  // ---------------------------------------------------------------- class picker
  function renderClassSeg() {
    const seg = $("#clsSeg"); const cl = (D && D.classes) || [];
    seg.parentElement.style.display = cl.length > 1 ? "" : "none";
    const want = ["mine", ...cl.filter((c) => !c.mine).map((c) => String(c.cid)), "all"];
    const sig = want.join("|");
    if (seg.dataset.sig !== sig) {
      seg.dataset.sig = sig;
      seg.innerHTML = want.map((k) => {
        if (k === "mine") { const c = cl.find((c) => c.mine); return `<button data-c="mine"><span class="dot" style="background:${c ? c.col : "var(--gold)"}"></span>${esc(c ? c.name : "Class")}</button>`; }
        if (k === "all") return `<button data-c="all">All</button>`;
        const c = cl.find((c) => String(c.cid) === k); return `<button data-c="${k}"><span class="dot" style="background:${c.col}"></span>${esc(c.name)}</button>`;
      }).join("");
      seg.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => { cls = b.dataset.c; store.set("cls", cls); render(); }));
    }
    if (!want.includes(cls)) cls = "mine";
    seg.querySelectorAll("button").forEach((b) => b.classList.toggle("on", b.dataset.c === cls));
  }
  const shownClasses = () => {
    const cl = (D && D.classes) || [];
    if (cls === "all") return cl;
    if (cls === "mine") return cl.filter((c) => c.mine).concat(cl.length && !cl.some((c) => c.mine) ? [cl[0]] : []);
    return cl.filter((c) => String(c.cid) === cls);
  };

  // ---------------------------------------------------------------- tower
  function trend(r, now) {
    // is he catching the car ahead? compare the interval now with ~25 s ago
    if (typeof r.int !== "number") return "";
    let h = hist.get(r.i); if (!h) hist.set(r.i, (h = []));
    if (!h.length || now - h[h.length - 1][0] > 2) h.push([now, r.int]);
    while (h.length && now - h[0][0] > 40) h.shift();
    const old = h.find((x) => now - x[0] >= 20);
    if (!old) return "";
    const d = r.int - old[1];
    return d < -0.15 ? "closing" : d > 0.15 ? "losing" : "";
  }
  function rowHtml(r, c, nb, now) {
    const chg = r.gain == null ? "" : r.gain > 0 ? `▲${r.gain}` : r.gain < 0 ? `▼${-r.gain}` : "–";
    const chgC = r.gain == null ? "" : r.gain > 0 ? "up" : r.gain < 0 ? "dn" : "eq";
    const isLead = r.cp === 1;
    const gap = isLead ? (D.race ? "LEADER" : r.best ? "" : "") : gapT(r.gap);
    const tr = trend(r, now);
    const int = isLead ? "" : r.int == null ? "" : gapT(r.int) + (tr === "closing" ? "<i>▼</i>" : tr === "losing" ? "<i>▲</i>" : "");
    const secs = [0, 1, 2].map((k) => {
      const live = r.cur[k] != null, t = live ? r.cur[k] : r.prev[k], col = live ? r.sc[k] : r.psc[k];
      const isNow = r.sec === k + 1 && !r.pit;
      const cls_ = ["sec", "r", col || "", live ? "" : "ghost", isNow && !live ? "live" : ""].join(" ");
      return `<div class="${cls_}">${t == null ? "" : secT(t)}</div>`;
    }).join("");
    let st = "";
    if (r.pen === "black" || r.pen === "dq") st = `<span class="badge pen">${r.pen === "dq" ? "DQ" : "PEN"}</span>`;
    else if (r.pen === "repair") st = `<span class="badge rep">REP</span>`;
    else if (r.out) st = `<span class="badge out">OUT</span>`;
    else if (r.pit) st = `<span class="badge pit">PIT</span>`;
    else if (r.off) st = `<span class="badge off">OFF</span>`;
    return `<div class="pos">${r.cp}</div><div class="chg ${chgC}">${chg}</div>` +
      `<div class="num"><span>${esc(r.num)}</span></div>` +
      `<div class="drv" title="${esc(r.car)}">${esc(r.name)}${r.ir ? `<span class="ir">${(r.ir / 1000).toFixed(1)}k</span>` : ""}</div>` +
      `<div class="int r ${tr}">${int}</div><div class="gap r${isLead ? " lead" : ""}">${gap}</div>` +
      `<div class="last r ${r.lcol}">${lapT(r.last)}</div><div class="best r${r.fast ? " p" : ""}">${lapT(r.best)}</div>` + secs +
      `<div class="stops">${r.stops || (D.race ? "0" : "")}</div><div class="c-tyre">${r.lc >= 0 ? r.tyre : ""}</div><div class="st">${st}</div>`;
  }
  function renderTower() {
    const box = $("#rows"), now = Date.now() / 1000;
    const groups = shownClasses();
    const before = new Map();
    rowEls.forEach((el, i) => { if (el.isConnected) before.set(i, el.getBoundingClientRect().top); });
    const keep = new Set(), order = [];
    const multi = groups.length > 1 || (D.classes || []).length > 1;
    let meIdx = -1;
    for (const c of groups) {
      const mi = c.rows.findIndex((r) => r.me); if (mi >= 0) meIdx = mi;
      if (multi) {
        const id = "h" + c.cid; let h = rowEls.get(id);
        if (!h) { h = document.createElement("div"); h.className = "chead"; rowEls.set(id, h); }
        h.style.setProperty("--cc", c.col);
        h.innerHTML = `<i></i>${esc(c.name)} <em>${c.n} cars</em>` + (c.fast ? `<span class="fl">FASTEST ${lapT(c.fast.t)} · #${esc(c.fast.num)}</span>` : "");
        order.push(h); keep.add(id);
      }
      c.rows.forEach((r, n) => {
        let el = rowEls.get(r.i);
        if (!el) { el = document.createElement("div"); el.className = "row"; rowEls.set(r.i, el); }
        const nb = mi >= 0 && Math.abs(n - mi) === 1;
        el.className = "row" + (r.me ? " me" : "") + (nb ? " nb" : "") + (r.pit || r.out ? " inpit" : "");
        el.style.setProperty("--cc", r.col);
        el.innerHTML = rowHtml(r, c, nb, now);
        const lp = lastPos.get(r.i);
        if (lp != null && lp !== r.cp) { el.classList.remove("flash-up", "flash-dn"); void el.offsetWidth; el.classList.add(r.cp < lp ? "flash-up" : "flash-dn"); }
        lastPos.set(r.i, r.cp);
        const lb = lastBest.get(r.i);
        if (r.fast && lb != null && r.best && lb !== r.best) { el.classList.remove("fastflash"); void el.offsetWidth; el.classList.add("fastflash"); }
        lastBest.set(r.i, r.best);
        order.push(el); keep.add(r.i);
      });
    }
    // put them in order (only move what moved, so nothing flickers)
    let prev = null;
    for (const el of order) {
      const want = prev ? prev.nextSibling : box.firstChild;
      if (want !== el) box.insertBefore(el, want);
      prev = el;
    }
    rowEls.forEach((el, k) => { if (!keep.has(k)) { el.remove(); rowEls.delete(k); } });
    // slide rows that changed place (FLIP)
    rowEls.forEach((el, i) => {
      if (!before.has(i)) return;
      const dy = before.get(i) - el.getBoundingClientRect().top;
      if (Math.abs(dy) > 2) {
        el.style.transition = "none"; el.style.transform = `translateY(${dy}px)`;
        requestAnimationFrame(() => requestAnimationFrame(() => { el.style.transition = ""; el.style.transform = ""; }));
      }
    });
  }

  // ---------------------------------------------------------------- session side
  function renderSide() {
    const s = D.session || {};
    $("#trkName").innerHTML = `${esc(s.track)}${s.cfg ? " · " + esc(s.cfg) : ""}<small>${esc([s.city, s.len, s.series].filter(Boolean).join(" · "))}</small>`;
    const wdeg = s.wdir == null ? 0 : s.wdir;
    const windTxt = s.wind == null ? "–" : `${Math.round(s.wind * (unitF ? 2.23694 : 3.6))}<small>${unitF ? "mph" : "km/h"}</small>` +
      `<svg class="wind" viewBox="0 0 16 16" style="transform:rotate(${wdeg + 180}deg)"><path d="M8 1l4 10-4-2.5L4 11z" fill="#9CA3AF"/></svg>`;
    const wet = ["", "Dry", "Mostly dry", "Very lightly wet", "Lightly wet", "Moderately wet", "Very wet", "Extremely wet"][s.wet] || "–";
    const tod = s.tod == null ? "–" : (() => { const h = Math.floor(s.tod / 3600) % 24, m = Math.floor(s.tod / 60) % 60; return `${((h + 11) % 12) + 1}:${String(m).padStart(2, "0")}<small>${h < 12 ? "am" : "pm"}</small>`; })();
    $("#wxKv").innerHTML = [
      ["Air", temp(s.air)], ["Track", temp(s.track_t)], ["Wind", windTxt],
      ["Sky", esc(s.sky || "–")], ["Surface", esc(wet)], ["Humidity", s.hum == null ? "–" : Math.round(s.hum * 100) + "<small>%</small>"],
      ["Rain", s.rain == null ? "–" : Math.round(s.rain * 100) + "<small>%</small>"], ["Time of day", tod], ["Session", esc(s.name || s.type || "–")],
    ].map(([k, v]) => `<div><span>${k}</span><b>${v}</b></div>`).join("");
    $("#unitBtn").textContent = unitF ? "°F" : "°C";
    // me
    let me = null, mc = null;
    for (const c of D.classes || []) { const r = c.rows.find((r) => r.me); if (r) { me = r; mc = c; } }
    if (me) {
      const g = me.gain;
      $("#meKv").innerHTML = [
        ["Class pos", `<b class="gold">P${me.cp}<small> / ${mc.n}</small></b>`],
        ["Started", me.start ? `<b>P${me.start}</b>` : "<b>–</b>"],
        ["Gained", g == null ? "<b>–</b>" : `<b class="${g > 0 ? "grn" : g < 0 ? "red" : ""}">${g > 0 ? "+" + g : g}</b>`],
        ["Last", `<b class="${me.lcol === "p" ? "pur" : me.lcol === "g" ? "grn" : ""}">${lapT(me.last)}</b>`],
        ["Best", `<b class="${me.fast ? "pur" : ""}">${lapT(me.best)}</b>`],
        ["Incidents", `<b class="${s.inc_lim && s.inc >= s.inc_lim * 0.75 ? "red" : ""}">${s.inc ?? "–"}${s.inc_lim ? `<small> / ${s.inc_lim}</small>` : ""}</b>`],
        ["Interval", `<b>${me.cp === 1 ? "–" : gapT(me.int) || "–"}</b>`],
        ["Pit stops", `<b>${me.stops}</b>`], ["Tyre laps", `<b>${me.lc >= 0 ? me.tyre : "–"}</b>`],
      ].map(([k, v]) => `<div><span>${k}</span>${v}</div>`).join("");
    }
    // fastest laps and best sectors per class
    $("#fastBox").innerHTML = (D.classes || []).map((c) => {
      const bs = c.best_sec || [], ideal = bs.every((x) => x) ? bs.reduce((a, b) => a + b, 0) : null;
      return `<div class="fcls" style="--cc:${c.col}"><i></i><div class="n">${esc(c.name)}</div><div class="t">${lapT(c.fast && c.fast.t)}</div>` +
        `<div class="who"><span>${c.fast ? `#${esc(c.fast.num)} ${esc(c.fast.name)}` : "No laps yet"}</span><span>${c.fast && c.fast.lap ? "Lap " + c.fast.lap : ""}</span></div>` +
        `<div class="secs">${[0, 1, 2].map((k) => `<span>S${k + 1} ${bs[k] ? bs[k].toFixed(3) : "–"}</span>`).join("")}<span class="ideal">IDEAL ${lapT(ideal)}</span></div></div>`;
    }).join("") || `<div class="empty">No laps yet</div>`;
    // race control
    const rc = (D.rc || []).slice().reverse();
    $("#rcN").textContent = rc.length ? rc.length + " messages" : "";
    const box = $("#rc");
    const K = { fast: "FASTEST", pit: "PIT", flag: "FLAG", lead: "LEAD", pen: "PENALTY", off: "OFF" };
    box.innerHTML = rc.map((m) => {
      const id = m.t + m.x, isNew = !firstRc && !seenRc.has(id); seenRc.add(id);
      return `<div class="rcl${isNew ? " new" : ""}"><time>${clock(m.t)}</time><span class="k ${m.k}">${K[m.k] || m.k}</span><span>${esc(m.x)}${m.c ? ` <span style="color:var(--t4)">· ${esc(m.c)}</span>` : ""}</span></div>`;
    }).join("") || `<div class="empty">Pit stops, fastest laps, flags and penalties show up here</div>`;
    firstRc = false;
  }

  // ---------------------------------------------------------------- header
  function renderHead() {
    const s = D.session || {};
    $("#hType").textContent = [s.name || s.type, s.series].filter(Boolean).join(" · ") || "Session";
    $("#hTrk").textContent = s.track || "–";
    const timed = s.time_left != null && (s.laps_total == null || s.laps_left == null);
    if (D.race && s.laps_total && s.lead_lap) {
      $("#hClockL").textContent = timed ? "Time left" : "Lap";
      $("#hClockV").innerHTML = timed ? clock(s.time_left) : `${Math.min(s.lead_lap, s.laps_total)}<small>/ ${s.laps_total}</small>`;
    } else if (s.time_left != null) {
      $("#hClockL").textContent = D.race && s.lead_lap ? `Time left · lap ${s.lead_lap}` : "Time left";
      $("#hClockV").textContent = clock(s.time_left);
    } else { $("#hClockL").textContent = "Lap"; $("#hClockV").textContent = s.lead_lap || "–"; }
    $("#hFlag").className = "blk " + (s.fcol || "");
    $("#hFlagV").textContent = s.flag || "–";
    $("#hAir").innerHTML = temp(s.air); $("#hTt").innerHTML = temp(s.track_t);
  }

  function render() {
    if (!D) return;
    renderClassSeg();
    renderHead();
    if (!document.body.classList.contains("v-session")) renderTower();
    if (!document.body.classList.contains("v-timing")) renderSide();
    fit();
  }


  // ---------------------------------------------------------------- the watch (same one as the iPad / PC app)
  function watchSVG(id) {
    const P = id + "_";
    let flutes = "";
    for (let i = 0; i < 128; i++) {
      const a = i * Math.PI * 2 / 128, s = Math.sin(a), c = Math.cos(a);
      const x1 = (50 + 42 * s).toFixed(3), y1 = (50 - 42 * c).toFixed(3), x2 = (50 + 50 * s).toFixed(3), y2 = (50 - 50 * c).toFixed(3);
      flutes += i % 2 === 0
        ? `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="rgba(255,252,240,.55)" stroke-width=".32"/>`
        : `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="rgba(0,0,0,.55)" stroke-width=".34"/>`;
    }
    const sub = (x, y, deg) => `<line x1="${x}" y1="${y}" x2="${x}" y2="${(y - 6.5).toFixed(2)}" stroke="#2A2418" stroke-width="1.1" stroke-linecap="round" transform="rotate(${deg} ${x} ${y})"/>
      <circle cx="${x}" cy="${y}" r=".9" fill="#C5A572"/>`;
    const hand = (cls, inner) => `<svg class="hand ${cls}" viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">${inner}</svg>`;
    return `<div class="wbox"><svg class="watch" viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">
    <defs>
      <clipPath id="${P}clip"><circle cx="50" cy="50" r="44"/></clipPath>
      <linearGradient id="${P}bez" gradientUnits="userSpaceOnUse" x1="50" y1="4" x2="50" y2="96">
        <stop offset="0" stop-color="#FCF7E8"/><stop offset=".22" stop-color="#EDE3CA"/><stop offset=".48" stop-color="#C7BB9C"/>
        <stop offset=".72" stop-color="#8E8267"/><stop offset="1" stop-color="#534A38"/></linearGradient>
      <radialGradient id="${P}dark" gradientUnits="userSpaceOnUse" cx="50" cy="96" r="59.8">
        <stop offset="0" stop-color="rgb(20,16,8)" stop-opacity=".55"/><stop offset=".6" stop-color="rgb(20,16,8)" stop-opacity=".1"/>
        <stop offset="1" stop-color="rgb(20,16,8)" stop-opacity="0"/></radialGradient>
      <radialGradient id="${P}gloss" gradientUnits="userSpaceOnUse" cx="33.4" cy="22.4" r="50.6">
        <stop offset="0" stop-color="rgb(255,255,250)" stop-opacity=".7"/><stop offset=".55" stop-color="rgb(255,255,250)" stop-opacity=".12"/>
        <stop offset="1" stop-color="rgb(255,255,250)" stop-opacity="0"/></radialGradient>
    </defs>
    <g clip-path="url(#${P}clip)">
      <circle cx="50" cy="50" r="44" fill="#F4F0E6"/>
      <image href="/assets/dial.png" x="-4.56" y="-4.56" width="109.12" height="109.12" preserveAspectRatio="xMidYMid slice"/>
    </g>
    ${sub(28.8, 47.65, -25)}${sub(70.75, 47.65, 15)}${sub(49.95, 71.35, 40)}
    <circle cx="50" cy="50" r="46" fill="none" stroke="url(#${P}bez)" stroke-width="8"/>
    <circle cx="50" cy="50" r="46" fill="none" stroke="url(#${P}dark)" stroke-width="8"/>
    ${flutes}
    <circle cx="50" cy="50" r="42" fill="none" stroke="rgba(0,0,0,.7)" stroke-width=".55"/>
    <circle cx="50" cy="50" r="49.9" fill="none" stroke="rgba(0,0,0,.45)" stroke-width=".4"/>
    <circle cx="50" cy="50" r="46" fill="none" stroke="url(#${P}gloss)" stroke-width="8"/>
  </svg>${hand("h-hour", `<line x1="50" y1="55" x2="50" y2="28" stroke="#9C7C45" stroke-width="3.6" stroke-linecap="round"/>
      <line x1="50" y1="55" x2="50" y2="28" stroke="#F2E8D0" stroke-width="2.8" stroke-linecap="round"/>`)}${hand("h-min", `<line x1="50" y1="55" x2="50" y2="16" stroke="#9C7C45" stroke-width="2.6" stroke-linecap="round"/>
      <line x1="50" y1="55" x2="50" y2="16" stroke="#F2E8D0" stroke-width="1.9" stroke-linecap="round"/>`)}${hand("h-sec", `<line x1="50" y1="60" x2="50" y2="13" stroke="#C5A572" stroke-width=".7" stroke-linecap="round"/>
      <circle cx="50" cy="19" r="1.2" fill="#C5A572"/><circle cx="50" cy="50" r="2.3" fill="#E4C887"/><circle cx="50" cy="50" r="1.2" fill="#7A6240"/>`)}</div>`;
  }
  const W = (() => {
    const box = $("#tmWatch"); if (!box) return null;
    box.innerHTML = watchSVG("tm");
    return { h: box.querySelector(".h-hour"), m: box.querySelector(".h-min"), s: box.querySelector(".h-sec"), last: ["", "", ""] };
  })();
  function tickWatch() {
    if (!W || document.hidden) return;
    const d = new Date(), sod = d.getHours() * 3600 + d.getMinutes() * 60 + d.getSeconds() + d.getMilliseconds() / 1000;
    const a = [(sod / 3600 % 12) * 30, (sod / 60 % 60) * 6, Math.floor(sod * 8) / 8 % 60 * 6];
    [W.h, W.m, W.s].forEach((h, i) => { const v = `rotate(${a[i].toFixed(1)}deg)`; if (W.last[i] !== v) { W.last[i] = v; h.style.transform = v; } });
  }
  tickWatch(); setInterval(tickWatch, 125);

  // ---------------------------------------------------------------- live link
  let es = null, lastMsg = 0;
  function connect() {
    if (es) try { es.close(); } catch (e) {}
    es = new EventSource(`/events?k=${encodeURIComponent(KEY)}&only=timing,off,hb`);
    es.addEventListener("timing", (e) => {
      lastMsg = Date.now();
      try { D = JSON.parse(e.data); } catch (x) { return; }
      document.body.classList.remove("waiting", "lost");
      render();
    });
    es.addEventListener("off", () => { document.body.classList.add("waiting"); });
    es.onerror = () => { document.body.classList.add("lost"); };
  }
  setInterval(() => { if (lastMsg && Date.now() - lastMsg > 6000) { document.body.classList.add("waiting"); } if (lastMsg && Date.now() - lastMsg > 15000) { lastMsg = Date.now(); connect(); } }, 2000);

  // ---------------------------------------------------------------- buttons
  document.querySelectorAll("#viewSeg button").forEach((b) => b.addEventListener("click", () => { setView(b.dataset.v); render(); }));
  $("#unitBtn").addEventListener("click", () => { unitF = !unitF; store.set("unit", unitF ? "F" : "C"); render(); });
  const back = $("#backBtn"), fs = $("#fsBtn"), pops = document.querySelectorAll(".ibtn.pop");
  const pyApi = () => window.pywebview && window.pywebview.api;
  back.style.display = EMBED === "ipad" ? "" : "none";
  fs.style.display = EMBED ? "none" : "";
  // pop-out buttons: in the PC app's tab, and in a pop-out window (to open the other page too). Not on the iPad.
  pops.forEach((b) => {
    b.style.display = EMBED === "ipad" || (LOCK && b.dataset.pop === LOCK) ? "none" : "";
    b.addEventListener("click", () => {
      const v = b.dataset.pop;
      if (EMBED === "pc") return parent.postMessage({ timing: "popout", view: v }, "*");
      if (pyApi() && pyApi().popout) return pyApi().popout(v);
      window.open(`/timing/?k=${encodeURIComponent(KEY)}&view=${v}`, "tm_" + v, "width=1500,height=860");
    });
  });
  if (LOCK) document.body.classList.add("locked");
  back.addEventListener("click", () => parent.postMessage({ timing: "close" }, "*"));
  fs.addEventListener("click", () => {
    if (window.pywebview && window.pywebview.api && window.pywebview.api.timing_fullscreen) return window.pywebview.api.timing_fullscreen();
    const d = document;
    if (d.fullscreenElement || d.webkitFullscreenElement) (d.exitFullscreen || d.webkitExitFullscreen).call(d);
    else { const el = d.documentElement; (el.requestFullscreen || el.webkitRequestFullscreen || (() => {})).call(el); }
  });
  if (!KEY) { document.querySelector("#wait b").textContent = "NO KEY IN THE LINK"; document.querySelector("#wait span").textContent = "Open this from the Race Engineer (Timing tab) or the iPad page"; }
  setView(view);
  connect();
  window.TIMING_DEBUG = { set(d) { D = d; document.body.classList.remove("waiting"); render(); } };
})();
