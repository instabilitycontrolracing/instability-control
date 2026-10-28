/* Incident forensics view (2026-10-27): one incident's story and its trace. Shared by the window (Team tab,
   Analysis) and the iPad debrief page.
   FX.detail(e)          -> HTML: why, what to do, drill, also, evidence
   FX.draw(canvas, tr)   -> speed / pedals / steering / slip around the moment, with your clean laps dashed
   The data comes from engineer/forensics.py (real telemetry; nothing here makes numbers up). */
"use strict";
(function () {
  const esc = (t) => String(t == null ? "" : t).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const KIND = { spin: "Spin", crash: "Crash", contact: "Contact", off: "Off", moment: "Slide", incident: "Incident" };
  const KCOL = { spin: "#FF7A45", crash: "#FF4D5E", contact: "#FF4D5E", off: "#FFC93C", moment: "#B794FF", incident: "#9CA3AF" };

  function badge(e) {
    return `<span class="fx-kind" style="--k:${KCOL[e.kind] || "#9CA3AF"}">${KIND[e.kind] || esc(e.kind)}</span>`;
  }
  function meta(e) {
    const m = [`Lap ${e.lap}`];
    if (e.pts) m.push(`${e.pts}x`);
    if (e.loss != null && e.loss >= 1) m.push(`${Math.round(e.loss)} s lost`);
    if (e.pos_before && e.pos_after && e.pos_before !== e.pos_after) m.push(`P${e.pos_before} → P${e.pos_after}`);
    return m.join("  ·  ");
  }
  function detail(e) {
    let h = `<div class="fx-cause"><span class="lbl">Why</span><b>${esc(e.cause_title)}</b>${e.confidence === "unsure" ? `<em>not certain</em>` : ""}</div>`;
    h += `<ul class="fx-why">${(e.why || []).map((w) => `<li>${esc(w)}</li>`).join("")}</ul>`;
    if ((e.factors || []).length) h += `<div class="fx-also"><span class="lbl">Also</span>${e.factors.map(esc).join(" ")}</div>`;
    h += `<div class="fx-fix"><span class="lbl">What to do</span>${esc(e.what)}</div>`;
    h += `<div class="fx-drill"><span class="lbl">Drill</span>${esc(e.drill)}</div>`;
    h += `<details class="fx-ev"><summary>Evidence</summary>${(e.evidence || []).map((x) => `<p>${esc(x)}</p>`).join("")}${
      e.base_src ? `<p class="d">Compared with ${e.base_n} clean laps (${esc(e.base_src)}).</p>` : ""}</details>`;
    return h;
  }

  /* ---- the trace ---- */
  function draw(cv, tr) {
    if (!cv || !tr || !tr.t || !tr.t.length) return;
    const dpr = window.devicePixelRatio || 1, W = cv.clientWidth || 600, H = cv.clientHeight || 260;
    cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr);
    const g = cv.getContext("2d"); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, W, H);
    const L = 46, R = 10, T = 8, B = 18;
    const t0 = tr.t[0], t1 = tr.t[tr.t.length - 1];
    const X = (t) => L + (t - t0) / (t1 - t0 || 1) * (W - L - R);
    const lanes = [
      { k: "kmh", lbl: "km/h", h: 0.34 },
      { k: "ped", lbl: "pedals", h: 0.22 },
      { k: "steer", lbl: "steer °", h: 0.24 },
      { k: "slip", lbl: "slip °", h: 0.20 },
    ];
    const ih = H - T - B - 6 * (lanes.length - 1);
    let y = T;
    const u = tr.usual || {};
    g.font = "600 9.5px Inter, sans-serif"; g.textBaseline = "middle";
    // off-track shading
    const offs = tr.off || [];
    for (const ln of lanes) {
      const h = ln.h * ih, y0 = y, y1 = y + h;
      g.fillStyle = "rgba(0,0,0,.28)"; g.fillRect(L, y0, W - L - R, h);
      for (let i = 0; i < offs.length; i++) if (offs[i]) { g.fillStyle = "rgba(255,201,60,.10)"; g.fillRect(X(tr.t[i]) - 1, y0, (W - L - R) / tr.t.length + 2, h); }
      g.fillStyle = "#8E98AC"; g.textAlign = "right"; g.fillText(ln.lbl, L - 6, y0 + h / 2);
      const line = (arr, lo, hi, col, dash, width) => {
        if (!arr) return;
        g.save(); g.strokeStyle = col; g.lineWidth = width || 1.6; if (dash) g.setLineDash(dash);
        g.beginPath(); let pen = false;
        for (let i = 0; i < arr.length; i++) {
          const v = arr[i]; if (v == null) { pen = false; continue; }
          const yy = y1 - (Math.max(lo, Math.min(hi, v)) - lo) / (hi - lo || 1) * h;
          if (!pen) { g.moveTo(X(tr.t[i]), yy); pen = true; } else g.lineTo(X(tr.t[i]), yy);
        }
        g.stroke(); g.restore();
      };
      if (ln.k === "kmh") {
        const all = tr.kmh.concat((u.kmh || []).filter((v) => v != null));
        const lo = Math.max(0, Math.floor(Math.min(...all) / 20) * 20), hi = Math.ceil(Math.max(...all) / 20) * 20 + 10;
        g.fillStyle = "#5E6880"; g.textAlign = "right"; g.fillText(String(hi), W - R - 3, y0 + 7); g.fillText(String(lo), W - R - 3, y1 - 6);
        line(u.kmh, lo, hi, "rgba(229,231,235,.55)", [4, 3], 1.3);
        line(tr.kmh, lo, hi, "#F0CD7E", null, 2);
      } else if (ln.k === "ped") {
        line(u.thr, 0, 1, "rgba(52,210,123,.45)", [4, 3], 1.2); line(u.brk, 0, 1, "rgba(255,77,94,.45)", [4, 3], 1.2);
        line(tr.thr, 0, 1, "#34D27B", null, 1.8); line(tr.brk, 0, 1, "#FF4D5E", null, 1.8);
      } else if (ln.k === "steer") {
        // scale on the run-up (after a spin the wheel goes to full lock and would squash the part that matters)
        const pre = tr.steer.filter((v, i) => tr.t[i] <= 0.5).map(Math.abs).concat((u.steer || []).filter((v) => v != null).map(Math.abs));
        const m = Math.max(30, Math.min(450, Math.max(...pre) * 1.25));
        g.strokeStyle = "rgba(255,255,255,.08)"; g.beginPath(); g.moveTo(L, (y0 + y1) / 2); g.lineTo(W - R, (y0 + y1) / 2); g.stroke();
        line(u.steer, -m, m, "rgba(96,165,250,.5)", [4, 3], 1.2); line(tr.steer, -m, m, "#60A5FA", null, 1.8);
      } else {
        const m = Math.max(15, Math.min(180, Math.max(...tr.slip.map(Math.abs))));
        g.strokeStyle = "rgba(255,255,255,.08)"; g.beginPath(); g.moveTo(L, (y0 + y1) / 2); g.lineTo(W - R, (y0 + y1) / 2); g.stroke();
        line(tr.slip, -m, m, "#B794FF", null, 1.8);
      }
      // gear numbers along the speed lane
      if (ln.k === "kmh" && tr.gear) {
        g.fillStyle = "rgba(245,243,238,.55)"; g.textAlign = "center"; g.font = "700 9px Inter, sans-serif";
        let last = null;
        for (let i = 0; i < tr.gear.length; i++) if (tr.gear[i] !== last && tr.gear[i] > 0) { last = tr.gear[i]; g.fillText(String(last), X(tr.t[i]), y1 - 7); }
        g.font = "600 9.5px Inter, sans-serif";
      }
      y = y1 + 6;
    }
    // the moment it started
    const x0 = X(0);
    g.strokeStyle = "rgba(255,77,94,.9)"; g.lineWidth = 1.2; g.setLineDash([3, 3]);
    g.beginPath(); g.moveTo(x0, T); g.lineTo(x0, H - B); g.stroke(); g.setLineDash([]);
    g.fillStyle = "#8E98AC"; g.textAlign = "center";
    for (let s = Math.ceil(t0); s <= t1; s++) g.fillText((s > 0 ? "+" : "") + s + " s", X(s), H - 7);
  }

  /* ---- your line through it (GPS) against your usual line ---- */
  function drawMap(cv, m) {
    if (!cv || !m || !m.me || !m.me.x.length) return false;
    const dpr = window.devicePixelRatio || 1, W = cv.clientWidth || 240, H = cv.clientHeight || 240;
    cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr);
    const g = cv.getContext("2d"); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, W, H);
    const me = m.me, us = m.usual;
    // zoom on the last 3 s before it and what happened after
    const xs = [], ys = [];
    me.t.forEach((t, i) => { if (t >= -3) { xs.push(me.x[i]); ys.push(me.y[i]); } });
    if (!xs.length) return false;
    let x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
    const span = Math.max(60, x1 - x0, y1 - y0) * 1.25, cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
    const S = Math.min(W, H) / span;
    const X = (x) => W / 2 + (x - cx) * S, Y = (y) => H / 2 - (y - cy) * S;
    g.fillStyle = "rgba(0,0,0,.28)"; g.fillRect(0, 0, W, H);
    const path = (px, py, col, w, dash, from = 0, to = px.length) => {
      g.save(); g.strokeStyle = col; g.lineWidth = w; g.lineCap = "round"; g.lineJoin = "round"; if (dash) g.setLineDash(dash);
      g.beginPath(); for (let i = from; i < to; i++) (i === from ? g.moveTo : g.lineTo).call(g, X(px[i]), Y(py[i])); g.stroke(); g.restore();
    };
    if (us && us.x.length) { path(us.x, us.y, "rgba(229,231,235,.16)", 14); path(us.x, us.y, "rgba(229,231,235,.6)", 1.4, [5, 4]); }
    path(me.x, me.y, "#F0CD7E", 2.4);
    for (let i = 1; i < me.x.length; i++) if (me.off[i]) path(me.x, me.y, "#FFC93C", 4, null, i - 1, i + 1);
    const k = me.t.findIndex((t) => t >= 0);
    if (k >= 0) { g.strokeStyle = "#FF4D5E"; g.lineWidth = 2; g.beginPath(); g.arc(X(me.x[k]), Y(me.y[k]), 6, 0, 7); g.stroke(); }
    g.fillStyle = "#8E98AC"; g.font = "600 9.5px Inter, sans-serif"; g.textAlign = "left";
    const m10 = Math.max(10, Math.round(span / 4 / 10) * 10);
    g.fillRect(8, H - 10, m10 * S, 2); g.fillText(`${m10} m`, 8, H - 18);
    return true;
  }

  const css = `
.fx-kind{display:inline-flex;align-items:center;height:20px;padding:0 9px;border-radius:10px;font:700 9.5px/1 Inter;letter-spacing:.16em;text-transform:uppercase;color:var(--k);background:color-mix(in srgb,var(--k) 12%,transparent);box-shadow:inset 0 0 0 1px color-mix(in srgb,var(--k) 45%,transparent);white-space:nowrap}
.fx-cause{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;margin:2px 0 6px}.fx-cause b{font:700 15px Inter;color:#F5F3EE}.fx-cause em{font:600 11px Inter;color:#FFC93C;font-style:normal}
.fx-why{margin:0 0 8px;padding:0;list-style:none;display:flex;flex-direction:column;gap:4px}.fx-why li{position:relative;padding-left:12px;font:500 13px/1.5 Inter;color:#E5E7EB}
.fx-why li::before{content:"";position:absolute;left:0;top:.62em;width:4px;height:4px;border-radius:50%;background:#F0CD7E}
.fx-also,.fx-fix,.fx-drill{font:500 13px/1.5 Inter;color:#D5DAE3;margin:6px 0}.fx-fix{color:#C9F7D7}.fx-drill{color:#F2E2BC}
.fx-also .lbl,.fx-fix .lbl,.fx-drill .lbl{display:block;margin-bottom:2px;font:700 9.5px Inter;letter-spacing:.18em;text-transform:uppercase;color:#8E98AC}
.fx-cause .lbl{font:700 9.5px Inter;letter-spacing:.18em;text-transform:uppercase;color:#8E98AC}
.fx-ev{margin-top:8px}.fx-ev summary{cursor:pointer;font:700 9.5px Inter;letter-spacing:.18em;text-transform:uppercase;color:#8E98AC}.fx-ev p{margin:4px 0;font:500 12px/1.45 Inter;color:#9CA3AF}.fx-ev p.d{color:#6B7280}
.fx-viz{display:flex;gap:10px;align-items:stretch;margin-top:10px}.fx-viz .fx-cv{flex:1;min-width:0;margin-top:0}.fx-viz .fx-map{flex:none;width:250px;height:250px;border-radius:8px;background:rgba(0,0,0,.25)}
@media (max-width:760px){.fx-viz{flex-direction:column}.fx-viz .fx-map{width:100%;height:240px}}
.fx-legend{display:flex;gap:14px;flex-wrap:wrap;font:600 10.5px Inter;color:#8E98AC;margin:6px 0 0}.fx-legend i{display:inline-block;width:14px;height:2px;margin-right:5px;vertical-align:middle}
`;
  function legend() {
    return `<div class="fx-legend"><span><i style="background:#F0CD7E"></i>speed</span><span><i style="background:#34D27B"></i>throttle</span><span><i style="background:#FF4D5E"></i>brake</span><span><i style="background:#60A5FA"></i>steering</span><span><i style="background:#B794FF"></i>slip angle</span><span><i style="background:repeating-linear-gradient(90deg,#E5E7EB 0 4px,transparent 4px 7px)"></i>your clean laps (map: usual line)</span><span><i style="background:#FFC93C;height:4px"></i>off track</span><span><i style="background:#FF4D5E;width:2px;height:10px"></i>it started</span></div>`;
  }
  if (!document.getElementById("fx-css")) { const st = document.createElement("style"); st.id = "fx-css"; st.textContent = css; document.head.appendChild(st); }
  // the trace and the map together, into a container element
  function viz(box, tr) {
    box.innerHTML = `<div class="fx-viz"><canvas class="fx-cv"></canvas><canvas class="fx-map"></canvas></div>${legend()}`;
    requestAnimationFrame(() => { draw(box.querySelector(".fx-cv"), tr); if (!drawMap(box.querySelector(".fx-map"), tr.map)) box.querySelector(".fx-map").remove(); });
  }
  window.FX = { detail, draw, drawMap, viz, badge, meta, legend, esc, KIND, KCOL };
})();
