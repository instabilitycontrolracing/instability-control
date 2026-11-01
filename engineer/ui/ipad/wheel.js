/* The Car panel as the car's own steering-wheel screen (2026-10-26, #197).
   Requested: "take the format of how the stuff shows up on the steering wheel display and make it mirror that in that section
   of the iPad display" - whatever car he's in. Layout traced from:
     * BMW M4 GT3 Evo: his Spa guide video (Desktop\Sim Racing\Guides\BMW M4 GT3 Evo) - the Bosch screen in the car
     (the M Hybrid V8's screen is different from iRacing's manual - request: leave the GTP on the plain grid for now)
   Positions are the real screen's, in its own pixels (each layout's `box`), drawn as percentages so the panel scales.
   A value iRacing doesn't send shows "–" in its box - never a made-up number. Any other car keeps the plain settings grid. */
(() => {
  const isNum = (x) => typeof x === "number" && isFinite(x);
  const lapT = (t) => { if (!isNum(t) || t <= 0) return "–"; const m = Math.floor(t / 60), s = t - m * 60; return `${m}:${s.toFixed(3).padStart(6, "0")}`; };

  // [key, label, x0, y0, x1, y1, kind, extra]   kinds: box (outlined: label on top, value under), tile (coloured setting),
  // tp (tyre-pressure square), gear, num (big bare number), lbl (bare label), shift (shift-light row), psl
  const L = {
    evo: {
      name: "BMW M4 GT3 EVO", box: [144, 42, 874, 574], tp: "#4BD34B",
      items: [
        ["shift", "", 300, 48, 720, 80, "shift", { n: 10 }],
        ["tp", "TYRE PRESSURE", 152, 141, 376, 326, "tp"],
        ["lfuel", "LAP FUEL [kg]", 150, 335, 310, 405, "box"],
        ["frem", "FUEL REMAIN [kg]", 150, 413, 310, 485, "box"],
        ["tmot", "TMOT", 150, 492, 218, 566, "box", { sm: 1 }],
        ["toil", "TOIL", 222, 492, 293, 566, "box", { sm: 1 }],
        ["tgear", "TGEAR", 297, 492, 367, 566, "box", { sm: 1 }],
        ["gl", "GEAR", 455, 148, 565, 175, "lbl"],
        ["gear", "", 440, 178, 580, 292, "gear", { col: "#4BD34B" }],
        ["spd", "", 395, 296, 625, 392, "num"],
        ["psl", "PSL", 335, 186, 425, 236, "psl"],
        ["tyre", "TYRE", 406, 488, 588, 570, "box", { ctr: 1 }],
        ["als", "ALS", 562, 141, 636, 220, "tile", { hd: "#41C3CC", bg: "#E9ECEF", fg: "#20242A" }],
        ["map", "MAP", 640, 141, 710, 220, "tile", { hd: "#D7262B", bg: "#D7262B" }],
        ["tc", "TC", 714, 141, 786, 220, "tile", { hd: "#2B3BD8", bg: "#2B3BD8" }],
        ["abs", "ABS", 790, 141, 866, 220, "tile", { hd: "#3BA43F", bg: "#3BA43F" }],
        ["gain", "GAIN\\LOSS", 667, 228, 867, 310, "box", { big: 1 }],
        ["last", "LAST LAP", 667, 316, 867, 398, "box", { big: 1 }],
        ["best", "BEST LAP", 667, 404, 867, 486, "box", { big: 1 }],
        ["brkb", "BRKB", 595, 490, 711, 570, "box"],
        ["lap", "LAP", 715, 490, 790, 570, "box"],
        ["min", "MIN", 794, 490, 870, 570, "box"],
      ],
    },
    // #719 (2026-10-31, Angelo sent the wheel shot from his 10-31 race: "that is so you can put that design in the ipad app"):
    // the BMW M Hybrid V8 EVO's screen, traced box for box from that frame (his recording, 1:29 left, lap 20).
    // Boxes iRacing sends no number for (BBT, ENT, MID, R LAPS, the brake-temperature rows, MODE, MED) show a dash.
    gtp: {
      name: "BMW M HYBRID V8 EVO", box: [445, 66, 975, 448], tp: "#FFFFFF",
      items: [
        ["shift", "", 470, 74, 950, 100, "shift", { n: 16 }],
        ["bbt", "BBT", 455, 138, 497, 190, "cbox", { c: "#D9C51E" }],
        ["tclon", "TCLON", 503, 138, 547, 190, "cbox", { c: "#D7262B" }],
        ["ent", "ENT", 551, 138, 595, 190, "cbox", { c: "#2B6BE8" }],
        ["lapl", "LAP", 606, 140, 662, 162, "lbl", { sm: 1 }],
        ["rlaps", "R LAPS", 736, 140, 820, 192, "bare"],
        ["mid", "MID", 825, 138, 867, 190, "cbox", { c: "#3BA43F" }],
        ["tclat", "TCLAT", 873, 138, 917, 190, "cbox", { c: "#D7262B" }],
        ["mig", "MIG", 921, 138, 965, 190, "cbox", { c: "#2B6BE8" }],
        ["ttf", "", 455, 196, 595, 219, "band", { bg: "#1E2FB8" }],
        ["tp", "", 455, 221, 595, 296, "tp2"],
        ["ttr", "", 455, 298, 595, 320, "band", { bg: "#1E2FB8" }],
        ["brk", "", 455, 332, 595, 396, "band4", { bg: "#C21F26" }],
        ["soc", "SOC", 455, 398, 525, 446, "bare"],
        ["toil", "TOIL", 527, 398, 595, 446, "bare"],
        ["gear", "", 670, 198, 748, 280, "gearbox", { bg: "#2F9E35" }],
        ["spd", "", 636, 282, 784, 326, "num"],
        ["brkb", "BRKBIAS", 610, 330, 702, 392, "bare"],
        ["mode", "MODE", 706, 330, 818, 392, "bare"],
        ["med", "", 668, 398, 752, 440, "box", { ctr: 1 }],
        ["dlt", "DLT", 820, 272, 966, 318, "dlt"],
        ["last", "LAST LAP", 820, 320, 966, 358, "bare"],
        ["best", "BEST LAP", 820, 358, 966, 398, "bare"],
        ["rarb", "RE", 820, 400, 890, 442, "cbox", { c: "#E6E8EB", side: 1 }],
        ["farb", "FR", 895, 400, 965, 442, "cbox", { c: "#2B6BE8", side: 1 }],
      ],
    },
  };

  function pick(full) {
    const q = (location.search.match(/[?&]wheel=(\w+)/) || [])[1];
    if (q) return L[q] ? q : null;
    const s = `${(full && full.car_path) || ""} ${(full && full.car) || ""}`.toLowerCase();
    if (/bmwm4gt3|m4 gt3/.test(s)) return "evo";
    if (/bmwlmdh|m hybrid v8/.test(s)) return "gtp";        // #719
    return null;
  }

  function build(box, id) {
    const lay = L[id], [X0, Y0, X1, Y1] = lay.box, W = X1 - X0, H = Y1 - Y0;
    const pc = (v, o, s) => `${(((v - o) / s) * 100).toFixed(3)}%`;
    let h = `<div class="whl ${id}">`;
    for (const [k, lbl, x0, y0, x1, y1, kind, ex = {}] of lay.items) {
      const pos = `left:${pc(x0, X0, W)};top:${pc(y0, Y0, H)};width:${(((x1 - x0) / W) * 100).toFixed(3)}%;height:${(((y1 - y0) / H) * 100).toFixed(3)}%`;
      const cls = `w-${kind}${ex.sm ? " sm" : ""}${ex.big ? " big" : ""}${ex.ctr ? " ctr" : ""}`;
      if (kind === "tp") h += `<div class="${cls}" data-k="${k}" style="${pos};--tp:${lay.tp}"><b>${lbl}</b><div class="g"><i>–</i><i>–</i><i>–</i><i>–</i></div></div>`;
      else if (kind === "cbox") h += `<div class="${cls}${ex.side ? " side" : ""}" data-k="${k}" style="${pos};--c:${ex.c}"><b>${lbl}</b><span>–</span></div>`;
      else if (kind === "band") h += `<div class="${cls}" data-k="${k}" style="${pos};--bg:${ex.bg}"><div class="g"><i>–</i><i>–</i></div></div>`;
      else if (kind === "band4") h += `<div class="${cls}" data-k="${k}" style="${pos};--bg:${ex.bg}"><div class="g"><i>–</i><i>–</i><i>–</i><i>–</i></div></div>`;
      else if (kind === "tp2") h += `<div class="w-tp2" data-k="${k}" style="${pos}"><div class="g"><i>–</i><i>–</i><i>–</i><i>–</i></div></div>`;
      else if (kind === "gearbox") h += `<div class="${cls}" data-k="${k}" style="${pos};--bg:${ex.bg}"><span>–</span></div>`;
      else if (kind === "tile") h += `<div class="${cls}" data-k="${k}" style="${pos};--hd:${ex.hd};--bg:${ex.bg};--fg:${ex.fg || "#fff"}"><b>${lbl}</b><span>–</span></div>`;
      else if (kind === "shift") h += `<div class="${cls}" data-k="${k}" style="${pos}">${"<i></i>".repeat(ex.n)}</div>`;
      else if (kind === "lbl") h += `<div class="${cls}" style="${pos}">${lbl}</div>`;
      else if (kind === "psl") h += `<div class="${cls}" data-k="${k}" style="${pos}">PSL</div>`;
      else if (kind === "gear") h += `<div class="${cls}" data-k="${k}" style="${pos};color:${ex.col}"><span>–</span></div>`;
      else if (kind === "num") h += `<div class="${cls}" data-k="${k}" style="${pos}"><span>–</span></div>`;
      else h += `<div class="${cls}" data-k="${k}" style="${pos}"><b>${lbl}</b><span>–</span></div>`;
    }
    h += `</div>`;
    box.innerHTML = h;
    // fit the screen inside the panel at the real screen's shape (as big as the panel allows)
    const scr = box.firstElementChild, fit = () => {
      const r = box.getBoundingClientRect(), cw = r.width - 8, ch = r.height - 8;
      if (cw <= 0 || ch <= 0) return;
      const k = Math.min(cw / W, ch / H);
      scr.style.width = `${Math.floor(W * k)}px`; scr.style.height = `${Math.floor(H * k)}px`;
    };
    if (box._ro) box._ro.disconnect();
    if (window.ResizeObserver) { box._ro = new ResizeObserver(fit); box._ro.observe(box); }
    fit();
    for (const b of scr.querySelectorAll("b")) fitText(b, b);
    box._w = {};
    for (const n of box.querySelectorAll("[data-k]")) box._w[n.dataset.k] = n;
  }

  const S = { base: null, lastFuel: null };
  function put(box, k, txt, opt = {}) {
    const n = box._w[k];
    if (!n) return;
    const v = n.querySelector("span") || n;
    if (v._t !== txt) {
      if (opt.pop && v._t && v._t !== "–" && txt !== "–") { n.classList.remove("pop"); void n.offsetWidth; n.classList.add("pop"); clearTimeout(n._pt); n._pt = setTimeout(() => n.classList.remove("pop"), 1600); }
      v._t = txt; v.textContent = txt;
      fitText(v, n);
    }
    if ("cls" in opt) { n.classList.toggle("gain", opt.cls === "gain"); n.classList.toggle("loss", opt.cls === "loss"); }
  }
  // a value wider than its box shrinks to fit (the real screen never overflows)
  function fitText(v, n) {
    v.style.fontSize = "";
    const rg = document.createRange(); rg.selectNodeContents(v);
    const room = (v === n ? n.clientWidth : v.clientWidth) - 3, need = rg.getBoundingClientRect().width;
    if (room > 0 && need > room) v.style.fontSize = `${(parseFloat(getComputedStyle(v).fontSize) * room / need).toFixed(1)}px`;
  }
  const num = (x, d) => (isNum(x) ? x.toFixed(d) : "–");
  const setv = (x) => (isNum(x) ? String(Math.round(x * 10) / 10) : "–");

  function draw(t, full) {
    const box = document.getElementById("dash");
    if (!box) return false;
    const id = pick(full);
    if (!id) { if (box._wid) { box._wid = null; if (box._ro) box._ro.disconnect(); box.dataset.sig = ""; box.classList.remove("wheel"); box.innerHTML = ""; } return false; }
    if (box._wid !== id) { box._wid = id; box.dataset.sig = "wheel:" + id; box.classList.add("wheel"); build(box, id); }
    const w = t.wh || {}, met = t.met !== false;
    // tyre pressures: iRacing sends kPa -> bar (metric) or psi
    const tpN = box._w.tp && box._w.tp.querySelectorAll("i");
    const many = (k, vals) => { const n = box._w[k] && box._w[k].querySelectorAll("i"); if (n) n.forEach((e, i) => { const s = vals[i] ?? "–"; if (e._t !== s) { e._t = s; e.textContent = s; fitText(e, e); } }); };
    if (tpN) (w.tp || []).slice(0, 4).forEach((p, i) => {
      let s = "–";
      if (isNum(p) && p > 0) { const kpa = p < 10 ? p * 100 : p; s = met ? (kpa / 100).toFixed(2) : (kpa * 0.145038).toFixed(1); }
      if (tpN[i]._t !== s) { tpN[i]._t = s; tpN[i].textContent = s; fitText(tpN[i], tpN[i]); }
    });
    const temp = (c) => (isNum(c) && c > 0 ? String(Math.round(met ? c : c * 9 / 5 + 32)) : "–");
    put(box, "tmot", temp(w.tmot)); put(box, "toil", temp(w.toil));
    put(box, "tgear", "–"); put(box, "tgbx", "–"); put(box, "pwat", "–");
    put(box, "poil", isNum(w.poil) && w.poil > 0 ? (met ? w.poil.toFixed(1) : (w.poil * 14.5038).toFixed(0)) : "–");
    const g = t.gear;
    put(box, "gear", g === -1 ? "R" : g === 0 ? "N" : isNum(g) ? String(g) : "–");
    put(box, "spd", isNum(t.spd) ? String(t.spd) : "–");
    put(box, "rpm", isNum(t.rpm) ? String(t.rpm) : "–");
    put(box, "tyre", isNum(w.tyre) && w.tyre >= 0 ? `TYRE ${w.tyre + 1}` : "–");
    put(box, "brkb", num(t.bb, id === "gtp" ? 2 : 1), { pop: 1 });
    put(box, "lap", isNum(t.lap) ? String(Math.max(0, t.lap - 1)) : "–");
    put(box, "min", isNum(w.st) ? String(Math.floor(w.st / 60)) : "–");
    put(box, "last", lapT(t.last)); put(box, "best", lapT(t.best));
    const psl = box._w.psl; if (psl) psl.classList.toggle("on", !!w.lim);
    // fuel: the Evo's screen is in kg (the car's own density from iRacing), the GTP's in litres / gallons
    const fuel = t.fuel, fl = t.fuel_lap;
    if (id === "evo") {
      const kg = isNum(w.kgl) && w.kgl > 0 ? w.kgl : null;
      const cv = (x) => (kg ? x * kg : met ? x : x / 3.785);
      const u = kg ? "kg" : met ? "L" : "gal";
      for (const k of ["lfuel", "frem"]) { const b = box._w[k] && box._w[k].querySelector("b"), want = (k === "lfuel" ? "LAP FUEL " : "FUEL REMAIN ") + `[${u}]`; if (b && b.textContent !== want) { b.textContent = want; fitText(b, b); } }
      put(box, "lfuel", isNum(fl) && fl > 0 ? cv(fl).toFixed(2) : "–");
      put(box, "frem", isNum(fuel) ? cv(fuel).toFixed(2) : "–");
      put(box, "als", "–");
      put(box, "map", setv(w.map), { pop: 1 }); put(box, "tc", setv(t.tc), { pop: 1 }); put(box, "abs", setv(t.abs), { pop: 1 });
      const d = t.delta;
      put(box, "gain", isNum(d) ? (d > 0 ? "+" : d < 0 ? "−" : "") + Math.abs(d).toFixed(2) : "–", { cls: isNum(d) ? (d > 0.005 ? "loss" : d < -0.005 ? "gain" : "") : "" });
      shift(box, t, full, w);
    } else if (id === "gtp") {
      // #719: the EVO screen. Tyre pressures above are psi with one decimal (bar with two in metric) like the car.
      const tt = (w.tt || []).map((c) => temp(c));
      many("ttf", [tt[0], tt[1]]); many("ttr", [tt[2], tt[3]]);
      many("brk", ["–", "–", "–", "–"]);                       // brake temperatures: iRacing doesn't send them
      put(box, "bbt", "–"); put(box, "ent", "–"); put(box, "mid", "–"); put(box, "rlaps", "–");
      put(box, "tclon", setv(t.tc2), { pop: 1 }); put(box, "tclat", setv(t.tc), { pop: 1 }); put(box, "mig", setv(t.mig), { pop: 1 });
      put(box, "rarb", setv(t.rarb), { pop: 1 }); put(box, "farb", setv(t.farb), { pop: 1 });
      put(box, "soc", isNum(w.soc) ? String(Math.round(w.soc <= 1.0001 ? w.soc * 100 : w.soc)) : "–");
      put(box, "mode", "–"); put(box, "med", "–");
      const d = t.delta;
      put(box, "dlt", isNum(d) ? (d > 0 ? "+" : d < 0 ? "−" : "") + Math.abs(d).toFixed(2).padStart(5, "0") : "–", { cls: isNum(d) ? (d > 0.005 ? "loss" : d < -0.005 ? "gain" : "") : "" });
      const lt = (x) => (isNum(x) && x > 0 ? (() => { const m = Math.floor(x / 60), s2 = x - m * 60; return `${String(m).padStart(2, "0")}:${s2.toFixed(2).padStart(5, "0")}`; })() : "–");
      put(box, "last", lt(t.last)); put(box, "best", lt(t.best));
      shift(box, t, full, w);
    } else {
      const cv = (x) => (met ? x : x / 3.785);
      // fuel used since fuel was last added: from the moment we see fuel go in (or the stint start in the pits)
      if (isNum(fuel)) {
        if (S.base === null && (t.pit || (isNum(t.lap) && t.lap <= 1))) S.base = fuel;
        if (isNum(S.lastFuel) && fuel > S.lastFuel + 0.3) S.base = fuel;
        if (isNum(S.base) && fuel > S.base) S.base = fuel;
        S.lastFuel = fuel;
      }
      put(box, "lfuel", isNum(fl) && fl > 0 ? cv(fl).toFixed(2) : "–");
      put(box, "fused", isNum(S.base) && isNum(fuel) ? cv(S.base - fuel).toFixed(1) : "–");
      put(box, "soc", isNum(w.soc) ? (w.soc <= 1.0001 ? w.soc * 100 : w.soc).toFixed(1) : "–");
      put(box, "tc1", setv(t.tc), { pop: 1 }); put(box, "tc2", setv(t.tc2), { pop: 1 });
      put(box, "farb", setv(t.farb), { pop: 1 }); put(box, "rarb", setv(t.rarb), { pop: 1 });
      put(box, "pred", isNum(t.best) && t.best > 0 && isNum(t.delta) ? lapT(t.best + t.delta) : "–");
    }
    return true;
  }

  // the Evo's shift lights: they fill from both ends toward the middle - green, yellow, red; all red flashing = shift now;
  // magenta flashing on the pit limiter
  const COLS = ["#3BD33B", "#3BD33B", "#F2DA22", "#F2DA22", "#F04030"];
  function shift(box, t, full, w) {
    const n = box._w.shift; if (!n) return;
    const L = n.children, half = L.length / 2;
    const red = (full && full.redline) || 7000, sh = (full && full.shift) || red * 0.97, lo = sh * 0.72;
    const f = isNum(t.rpm) ? (t.rpm - lo) / (sh - lo) : 0;
    const lit = Math.max(0, Math.min(half, Math.ceil(f * half)));
    const mode = w.lim ? "lim" : f >= 1 ? "go" : "";
    if (n._m !== mode) { n._m = mode; n.className = "w-shift" + (mode ? " " + mode : ""); }
    const cols = half > 5 ? ["#3BD33B", "#3BD33B", "#3BD33B", "#F2B322", "#F2B322", "#F2B322", "#F04030", "#F04030"] : COLS;
    for (let i = 0; i < half; i++) {
      const on = mode ? true : i < lit, c = mode === "lim" ? "#E040E0" : mode === "go" ? "#F04030" : cols[Math.min(i, cols.length - 1)];
      for (const e of [L[i], L[L.length - 1 - i]]) { const bg = on ? c : ""; if (e._c !== bg) { e._c = bg; e.style.background = bg; e.classList.toggle("on", on); } }
    }
  }

  window.WHEEL = { draw, pick, L };
})();
