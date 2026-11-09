/* TickerChatter front end.
   Plain DOM + SVG, no build step.
   A search runs the real Python pipeline in the browser through Pyodide. */
(() => {
  "use strict";

  const CONFIG = window.TICKERCHATTER_CONFIG || {};
  const PYODIDE = "https://cdn.jsdelivr.net/pyodide/v0.26.4/full/";
  const PY_FILES = ["__init__.py", "tickers.py", "extract.py", "stats.py", "live.py"];
  const REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;

  const $ = (id) => document.getElementById(id);
  const SVG = "http://www.w3.org/2000/svg";
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const sleep = (ms) => new Promise((r) => setTimeout(r, REDUCED ? 0 : ms));
  const plural = (n, w) => `${n.toLocaleString()} ${w}${n === 1 ? "" : "s"}`;
  const day = (iso) => new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
  const fmtZ = (z) => { const s = Math.abs(z).toFixed(1); return s === "0.0" ? s : (z > 0 ? "+" : "−") + s; };
  const fmtRatio = (r) => (r >= 10 ? Math.round(r) : r.toFixed(1)).toString();
  const LABEL = { spike: "Spike", elevated: "Elevated", normal: "Normal", building: "Too new to score" };
  const ICON = {
    spike: '<svg viewBox="0 0 12 12" aria-hidden="true"><path d="M6 1.5 11 10H1z"/></svg>',
    elevated: '<svg viewBox="0 0 12 12" aria-hidden="true"><path d="M6 2 10 7H7.5v3h-3V7H2z"/></svg>',
    normal: '<svg viewBox="0 0 12 12" aria-hidden="true"><rect x="1.5" y="5" width="9" height="2" rx="1"/></svg>',
    building: '<svg viewBox="0 0 12 12" aria-hidden="true"><path d="M6 1a5 5 0 1 0 0 10A5 5 0 0 0 6 1zm.75 5.2 2 1.2-.6 1-2.65-1.6V3h1.25z"/></svg>',
  };
  function ago(iso) {
    const m = Math.max(0, Math.round((Date.now() - new Date(iso)) / 60000));
    if (m < 60) return m <= 1 ? "just now" : `${m} min ago`;
    const h = Math.round(m / 60);
    return h < 24 ? `${h} h ago` : day(iso);
  }
  function el(tag, attrs = {}, html) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
    if (html != null) n.innerHTML = html;
    return n;
  }
  function svg(tag, attrs = {}) {
    const n = document.createElementNS(SVG, tag);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
    return n;
  }
  const rank = (t) => (t.z == null ? -1e9 + t.current : t.z);

  let DATA = null;

  /* ---------- scroll reveals: things unmask as they come into view ---------- */
  // A fully masked card has no visible area, so the browser never reports it as
  // on screen. Masked cards are revealed by watching their container instead.
  const io = "IntersectionObserver" in window && !REDUCED
    ? new IntersectionObserver((entries) => entries.forEach((e) => {
        if (!e.isIntersecting) return;
        const t = e.target;
        if (t.dataset.revealKids) t.querySelectorAll(":scope > .mask").forEach((k) => k.classList.add("in"));
        else t.classList.add("in");
        io.unobserve(t);
      }), { threshold: 0.12, rootMargin: "0px 0px -6% 0px" })
    : null;
  function watch(root = document) {
    root.querySelectorAll(".reveal, .lines, .strip, .chips").forEach((n) => (io ? io.observe(n) : n.classList.add("in")));
    new Set([...root.querySelectorAll(".mask")].map((m) => m.parentElement)).forEach((p) => {
      if (io) { p.dataset.revealKids = "1"; io.observe(p); }
      else p.querySelectorAll(":scope > .mask").forEach((k) => k.classList.add("in"));
    });
  }

  /* ---------- scroll focus: blurry near the bottom, sharp as it rises ---------- */
  const focusEls = [];
  function trackFocus(root = document) {
    if (REDUCED) return;
    root.querySelectorAll(".focus").forEach((n) => { if (!focusEls.includes(n)) focusEls.push(n); });
    updateFocus();
  }
  let focusQueued = false;
  function updateFocus() {
    focusQueued = false;
    const vh = innerHeight;
    for (const n of focusEls) {
      const top = n.getBoundingClientRect().top;
      // 0 when the top edge is at the bottom of the screen, 1 once it's 30% of the way up.
      const p = Math.min(1, Math.max(0, (vh - top) / (vh * 0.3)));
      n.style.filter = p >= 1 ? "none" : `blur(${((1 - p) * 14).toFixed(1)}px)`;
    }
  }
  addEventListener("scroll", () => { if (!focusQueued) { focusQueued = true; requestAnimationFrame(updateFocus); } }, { passive: true });
  addEventListener("resize", () => requestAnimationFrame(updateFocus));

  /* ---------- bubble hover: the sheen follows the cursor ---------- */
  document.addEventListener("pointermove", (e) => {
    const b = e.target.closest?.(".bubble");
    if (!b) return;
    const r = b.getBoundingClientRect();
    b.style.setProperty("--mx", `${((e.clientX - r.left) / r.width) * 100}%`);
    b.style.setProperty("--my", `${((e.clientY - r.top) / r.height) * 100}%`);
  }, { passive: true });

  /* ---------- tooltip ---------- */
  const tip = $("tip");
  function showTip(html, x, y) {
    tip.innerHTML = html; tip.hidden = false;
    const r = tip.getBoundingClientRect();
    let left = x + 14, top = y - r.height - 12;
    if (left + r.width > innerWidth - 8) left = x - r.width - 14;
    if (top < 8) top = y + 16;
    tip.style.left = `${left}px`; tip.style.top = `${top}px`;
  }
  const hideTip = () => (tip.hidden = true);

  /* ---------- sparkline + chart ---------- */
  function sparkline(t, w = 104, h = 26) {
    const s = svg("svg", { class: "spark", viewBox: `0 0 ${w} ${h}`, preserveAspectRatio: "none", "aria-hidden": "true" });
    const max = Math.max(1, ...t.series.map((p) => p.count));
    const step = w / t.series.length;
    t.series.forEach((p, i) => {
      const last = i === t.series.length - 1;
      const bh = p.covered ? Math.max(1.5, (p.count / max) * (h - 2)) : 0;
      s.append(svg("rect", { x: (i * step + 0.5).toFixed(2), y: (h - bh).toFixed(2), width: Math.max(1, step - 1.5).toFixed(2), height: bh.toFixed(2), rx: 1, class: last ? `now ${t.status}` : "" }));
    });
    return s;
  }
  function niceStep(raw) {
    const p = Math.pow(10, Math.floor(Math.log10(Math.max(raw, 1))));
    const f = raw / p;
    return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * p;
  }
  function chart(t, width) {
    const W = Math.round(Math.min(620, Math.max(280, width || 520)));
    const H = W < 420 ? 190 : 220, m = { l: 30, r: 10, t: 22, b: 26 };
    const series = t.series.slice(-Math.min(t.series.length, t.mode === "live" ? 15 : 30));
    const n = series.length, iw = W - m.l - m.r, ih = H - m.t - m.b;
    const step = iw / n, bw = Math.max(3, step - 3);
    const has = t.mean != null, swing = Math.max(t.std || 0, 1);
    const hi = has ? t.mean + 2 * swing : 0, lo = has ? Math.max(0, t.mean - 2 * swing) : 0;
    const raw = Math.max(4, hi, ...series.map((p) => p.count));
    const tick = niceStep(raw / 3), yMax = Math.ceil(raw / tick) * tick;
    const y = (v) => m.t + ih - (v / yMax) * ih;
    const x = (i) => m.l + i * step + (step - bw) / 2;
    const s = svg("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": `${t.name} headlines per day` });
    const g = svg("g", { class: "grid" });
    for (let v = 0; v <= yMax; v += tick) {
      g.append(svg("line", { x1: m.l, x2: W - m.r, y1: y(v), y2: y(v) }));
      const tx = svg("text", { x: m.l - 8, y: y(v) + 4, "text-anchor": "end" }); tx.textContent = v; g.append(tx);
    }
    s.append(g);
    if (has) {
      const first = series.findIndex((p) => p.baseline);
      const x0 = first >= 0 ? x(first) - 2 : x(n - 1), x1 = x(n - 1) + bw + 2;
      s.append(svg("rect", { class: "band", x: x0, width: x1 - x0, y: y(hi), height: y(lo) - y(hi), rx: 5 }));
      s.append(svg("line", { class: "mean", x1: x0, x2: x1, y1: y(t.mean), y2: y(t.mean) }));
    }
    const bars = series.map((p, i) => {
      const last = i === n - 1;
      const bh = p.covered ? Math.max(p.count ? 2 : 0, y(0) - y(p.count)) : 3;
      const r = svg("rect", { class: last ? `bar now ${t.status}` : !p.covered ? "bar gap" : p.baseline ? "bar base" : "bar", x: x(i), y: y(0) - bh, width: bw, height: bh, rx: Math.min(3, bw / 2), style: `--i:${i}` });
      s.append(r); return r;
    });
    const now = series[n - 1];
    const ann = svg("text", { class: "ann", x: x(n - 1) + bw, y: y(now.count) - 8, "text-anchor": "end" });
    ann.textContent = `${now.count} today`; s.append(ann);
    [[0, "start"], [Math.floor(n / 2), "middle"], [n - 1, "end"]].forEach(([i, a]) => {
      const tx = svg("text", { x: a === "start" ? x(i) : a === "end" ? x(i) + bw : x(i) + bw / 2, y: H - 6, "text-anchor": a });
      tx.textContent = i === n - 1 ? "Last 24h" : day(series[i].end); s.append(tx);
    });
    series.forEach((p, i) => {
      const hit = svg("rect", { class: "hit", x: m.l + i * step, y: m.t, width: step, height: ih });
      const label = i === n - 1 ? "Last 24 hours" : `24h ending ${day(p.end)}`;
      const note = !p.covered ? "Before tracking started" : p.baseline ? "Used for the usual level" : "";
      hit.addEventListener("mousemove", (e) => { bars[i].classList.add("hl"); showTip(`<b>${label}</b><br>${p.covered ? plural(p.count, "headline") : "No data"}${note ? `<br>${note}` : ""}`, e.clientX, e.clientY); });
      hit.addEventListener("mouseleave", () => { bars[i].classList.remove("hl"); hideTip(); });
      s.append(hit);
    });
    return s;
  }

  /* ---------- detail view (run result and sheet) ---------- */
  function headline(t) {
    if (t.z == null) return `Not enough history for ${esc(t.name)} yet.`;
    if ((t.status === "spike" || t.status === "elevated") && t.ratio) return `${esc(t.name)} is in the news ${fmtRatio(t.ratio)}× more than usual.`;
    if (t.status === "spike" || t.status === "elevated") return `${esc(t.name)} went from near silence to ${plural(t.current, "headline")}.`;
    return `${esc(t.name)} is getting its usual amount of coverage.`;
  }
  function renderDetail(t, host) {
    const need = (DATA?.thresholds?.min_baseline_days || 3) - (t.baseline_days || 0);
    const summary = t.z == null
      ? `<b>${plural(t.current, "headline")}</b> in the last 24 hours. It needs ${plural(Math.max(need, 1), "more day")} of history before today can be compared with normal.`
      : `<b>${plural(t.current, "headline")}</b> in the last 24 hours. Over the ${t.baseline_days} days before, it averaged <b>${t.mean.toFixed(1)}</b> a day, give or take ${t.std.toFixed(1)}.`;
    const swing = Math.max(t.std || 0, 1);
    const math = t.z == null ? "" :
      `<div class="math"><span>z =</span><span class="frac"><span>${t.current} − ${t.mean.toFixed(1)}</span><span>${swing.toFixed(1)}</span></span><span>= <b>${fmtZ(t.z)}</b></span><span>${t.z >= 2 ? "Above 2, so it counts as a spike." : t.z >= 1 ? "Between 1 and 2: busier than usual, not a spike." : "Inside the usual range."}</span></div>`;
    const news = t.headlines.length
      ? `<ul>${t.headlines.slice(0, 8).map((h) => `<li><a href="${esc(h.link)}" target="_blank" rel="noopener"><span class="t">${esc(h.title)}</span><span class="m">${esc(h.source)}, ${esc(ago(h.published))}</span></a></li>`).join("")}</ul>`
      : `<p class="none">No headlines name ${esc(t.name)} in this period.</p>`;
    const sector = t.sector && t.sector !== "Other" ? esc(t.sector) : "";
    const sym = t.symbol && t.symbol !== t.name ? `${esc(t.symbol)}${sector ? ", " : ""}` : "";
    const badge = (t.mode === "live" ? `<span class="badge">Live search</span>` : `<span class="badge">Hourly collection</span>`) +
      (t.z != null && t.early ? `<span class="badge" title="Based on fewer than 7 days, so treat it as a first look">Early read, ${t.baseline_days} days</span>` : "");
    host.innerHTML =
      `<article class="detail">` +
        `<div class="d-head"><div><h3 id="${host.id === "sheet-body" ? "sheet-title" : "detail-title"}">${headline(t)}</h3><p>${sym}${sector}${badge}</p></div><span class="pill ${t.status}">${ICON[t.status]}${LABEL[t.status]}</span></div>` +
        `<div><p class="d-summary">${summary}</p><div class="chart grow"></div>` +
          `<div class="legend"><span><i class="lg-base"></i>Days used for the usual level</span>${t.mean != null ? `<span><i class="lg-mean"></i>Usual level</span><span><i class="lg-band"></i>Normal range</span>` : ""}</div>${math}</div>` +
        `<div class="news"><h4>Latest headlines</h4>${news}</div>` +
      `</article>`;
    const c = host.querySelector(".chart");
    c.append(chart(t, c.clientWidth));
  }

  /* ---------- sheet ---------- */
  const sheet = $("sheet");
  let lastFocus = null;
  function openSheet(t) {
    lastFocus = document.activeElement;
    sheet.hidden = false;
    renderDetail({ ...t, mode: "hourly" }, $("sheet-body"));
    requestAnimationFrame(() => requestAnimationFrame(() => sheet.classList.add("open")));
    document.body.style.overflow = "hidden";
    sheet.querySelector(".close").focus();
  }
  function closeSheet() {
    sheet.classList.remove("open");
    document.body.style.overflow = "";
    setTimeout(() => (sheet.hidden = true), REDUCED ? 0 : 450);
    if (lastFocus) lastFocus.focus();
  }
  sheet.addEventListener("click", (e) => { if (e.target.closest("[data-close]")) closeSheet(); });
  addEventListener("keydown", (e) => { if (e.key === "Escape" && !sheet.hidden) closeSheet(); });

  /* ---------- hero ---------- */
  function renderHero() {
    const list = $("tickers");
    (DATA?.watchlist || []).forEach((t) => list.append(el("option", { value: t.name, label: t.symbol })));
    const movers = DATA ? [...DATA.tickers].sort((a, b) => rank(b) - rank(a)) : [];
    const picks = movers.slice(0, 3).map((t) => t.name);
    const fallback = ["Micron", "Nvidia", "Tesla"];
    const tries = (picks.length ? picks : fallback);
    $("hint").innerHTML = `Try ${tries.map((n) => `<button type="button" data-q="${esc(n)}">${esc(n)}</button>`).join(", ")}.`;
    $("hint").addEventListener("click", (e) => { const b = e.target.closest("[data-q]"); if (b) run(b.dataset.q); });

    const chips = $("chips");
    const spots = [[8, 6], [52, 0], [30, 30], [70, 34], [4, 60], [46, 66], [76, 74]];
    movers.slice(0, spots.length).forEach((t, i) => {
      const wrap = el("div", { class: "chip-float", style: `--x:${spots[i][0]}%;--y:${spots[i][1]}%;--t:${5.5 + (i % 3) * 1.3}s;--d:${(0.4 + i * 0.09).toFixed(2)}s` });
      const zt = t.z == null ? "Too new" : `${t.status === "spike" ? "▲ " : ""}z ${fmtZ(t.z)}`;
      const b = el("button", { type: "button", class: "chip bubble", style: `--d:${(0.4 + i * 0.09).toFixed(2)}s`, "aria-label": `Run ${t.name}` },
        `<b>${esc(t.symbol)}</b><small class="${t.status}">${esc(zt)}</small>`);
      b.addEventListener("click", () => run(t.name));
      wrap.append(b); chips.append(wrap);
    });
  }

  /* ---------- today ---------- */
  function renderToday() {
    if (!DATA) {
      $("updated").textContent = "No headlines collected yet. Double-click Run TickerChatter.command to fill this in.";
      $("today").querySelectorAll(".strip, .all").forEach((n) => (n.hidden = true));
      return;
    }
    $("updated").textContent = `Updated ${ago(DATA.generated_at)} from ${DATA.totals.sources} publishers`;

    const ZMIN = -2, ZMAX = 4, ZERO = ZMAX / (ZMAX - ZMIN);
    const plot = $("strip");
    DATA.tickers.forEach((t, i) => {
      const b = el("button", { type: "button", class: `sbar ${t.status}`, style: `--i:${i}`, "aria-label": `${t.symbol}: ${LABEL[t.status]}` });
      const bar = el("i");
      let top, h, o = "bottom";
      if (t.z == null) { h = 0.07; top = ZERO - h; }
      else {
        const z = Math.max(ZMIN, Math.min(ZMAX, t.z));
        if (z >= 0) { h = Math.max(z / (ZMAX - ZMIN), 0.014); top = ZERO - h; } else { h = -z / (ZMAX - ZMIN); top = ZERO; o = "top"; }
      }
      bar.style.cssText = `top:${top * 100}%;height:${h * 100}%;--o:${o}`;
      b.append(bar);
      b.addEventListener("click", () => openSheet(t));
      b.addEventListener("mousemove", (e) => showTip(`<b>${esc(t.symbol)}</b> ${esc(t.name)}<br>${plural(t.current, "headline")} today${t.mean != null ? `, usually ${t.mean.toFixed(1)}` : ""}`, e.clientX, e.clientY));
      b.addEventListener("mouseleave", hideTip);
      plot.append(b);
    });

    const sorted = [...DATA.tickers].sort((a, b) => rank(b) - rank(a) || b.current - a.current);
    sorted.slice(0, 3).forEach((t, i) => {
      const card = el("button", { type: "button", class: "mover mask bubble", style: `--d:${0.08 * i}s` });
      const line = t.z == null ? `${plural(t.current, "headline")} so far. Still building history.`
        : t.ratio && t.status !== "normal" ? `<strong>${fmtRatio(t.ratio)}×</strong> its usual coverage, ${plural(t.current, "headline")} today.`
        : `${plural(t.current, "headline")} today, about usual.`;
      card.innerHTML = `<div class="top"><div><b>${esc(t.symbol)}</b> <span class="name">${esc(t.name)}</span></div><span class="pill ${t.status}">${ICON[t.status]}${LABEL[t.status]}</span></div><p class="big">${line}</p>`;
      card.append(sparkline(t, 300, 44));
      card.append(el("span", { class: "go" }, "Open details"));
      card.addEventListener("click", () => openSheet(t));
      $("movers").append(card);
    });

    const ul = $("list");
    sorted.forEach((t) => {
      const li = el("li");
      const b = el("button", { type: "button", class: "bubble bubble-sm" }, `<b>${esc(t.symbol)}</b><span class="nm">${esc(t.name)}</span><span class="z ${t.status}">${t.z == null ? "Too new" : `z ${fmtZ(t.z)}`}</span>`);
      b.append(sparkline(t, 72, 22));
      b.addEventListener("click", () => openSheet(t));
      li.append(b); ul.append(li);
    });
    $("more").addEventListener("click", () => {
      const open = $("list-wrap").classList.toggle("open");
      $("more").setAttribute("aria-expanded", String(open));
      $("more").textContent = open ? "Show fewer" : "Show all 40 stocks";
    });
  }

  /* ---------- how it works: open a step to read the real code ---------- */
  const STEPS = [
    { title: "Collect headlines", text: "Every hour, and whenever someone runs a search, it pulls recent stories from Google News and Yahoo Finance.", file: "fetch.py", fn: "fetch_feed" },
    { title: "Remove repeats", text: "One story syndicated to ten sites should count once, so titles are reduced to a simple key and duplicates are dropped.", file: "extract.py", fn: "headline_key" },
    { title: "Spot the company", text: "Each headline is checked for the symbol and the names papers actually use, so “Nvidia” and “(NVDA)” count, but words like AI or CEO don't.", file: "extract.py", fn: "pattern_for" },
    { title: "Score the surprise", text: "Mentions are counted per 24 hours. The last day is compared with the 14 before it to get a z-score.", file: "stats.py", fn: "score" },
  ];
  const codeCache = {};
  async function pySource(file) {
    if (!codeCache[file]) codeCache[file] = fetch(`py/pipeline/${file}`).then((r) => (r.ok ? r.text() : Promise.reject(r.status)));
    return codeCache[file];
  }
  function sliceFunction(src, fn) {
    const start = src.indexOf(`def ${fn}(`);
    if (start < 0) return "";
    const rest = src.slice(start);
    const end = rest.search(/\n(?=\S)/);
    return (end < 0 ? rest : rest.slice(0, end)).trimEnd();
  }
  function highlight(code) {
    const KW = /^(def|return|for|in|if|elif|else|not|and|or|import|from|as|try|except|continue|with|None|True|False|lambda|is)$/;
    return code.split("\n").map((line) => {
      let out = "", i = 0;
      const re = /(#.*$)|("""[^]*?"""|f?r?"(?:[^"\\]|\\.)*"|f?r?'(?:[^'\\]|\\.)*')|\b([A-Za-z_]\w*)\b/g;
      let m;
      while ((m = re.exec(line))) {
        out += esc(line.slice(i, m.index));
        if (m[1]) out += `<span class="c">${esc(m[1])}</span>`;
        else if (m[2]) out += `<span class="s">${esc(m[2])}</span>`;
        else if (KW.test(m[3])) out += `<span class="k">${m[3]}</span>`;
        else if (line.slice(re.lastIndex).startsWith("(")) out += `<span class="f">${m[3]}</span>`;
        else out += esc(m[3]);
        i = re.lastIndex;
      }
      return out + esc(line.slice(i));
    }).join("\n");
  }
  function renderSteps() {
    const ol = $("steps");
    STEPS.forEach((s, i) => {
      const li = el("li", { class: "step mask bubble", style: `--d:${0.08 * (i % 2)}s` });
      li.innerHTML =
        `<button type="button" aria-expanded="false"><span class="num">${i + 1}</span><span><h3>${s.title}</h3><p>${s.text}</p></span><span class="plus"><svg viewBox="0 0 14 14" aria-hidden="true"><path d="M7 2v10M2 7h10"/></svg></span></button>` +
        `<div class="body"><div><p class="file">${s.file}</p><pre class="code"><code>Loading…</code></pre></div></div>`;
      const btn = li.querySelector("button");
      btn.addEventListener("click", async () => {
        const open = li.classList.toggle("open");
        btn.setAttribute("aria-expanded", String(open));
        const code = li.querySelector("code");
        if (open && code.dataset.loaded !== "1") {
          try { code.innerHTML = highlight(sliceFunction(await pySource(s.file), s.fn)); code.dataset.loaded = "1"; }
          catch { code.textContent = "Open the site through a web server (or GitHub Pages) to see the code here."; }
        }
      });
      ol.append(li);
    });
  }

  /* ---------- running the pipeline ---------- */
  let pyReady = null;
  function getPython() {
    if (pyReady) return pyReady;
    pyReady = (async () => {
      if (!window.loadPyodide) {
        await new Promise((ok, fail) => { const s = el("script", { src: `${PYODIDE}pyodide.js` }); s.onload = ok; s.onerror = fail; document.head.append(s); });
      }
      const py = await window.loadPyodide({ indexURL: PYODIDE });
      py.FS.mkdirTree("/home/pyodide/pipeline");
      for (const f of PY_FILES) py.FS.writeFile(`/home/pyodide/pipeline/${f}`, await (await fetch(`py/pipeline/${f}`)).text());
      py.runPython("import sys; sys.path.insert(0, '/home/pyodide')");
      return py.pyimport("pipeline.live");
    })();
    pyReady.catch(() => (pyReady = null));
    return pyReady;
  }

  function matchWatchlist(q) {
    const s = q.trim().toLowerCase();
    return (DATA?.watchlist || []).find((t) => [t.symbol, t.name, ...t.aliases].some((n) => n.toLowerCase() === s));
  }

  const PIPE = ["Collect headlines", "Remove repeats", "Spot the company", "Score the surprise"];
  function pipeUI() {
    const ol = $("pipe");
    ol.innerHTML = "";
    const steps = PIPE.map((name, i) => {
      const li = el("li", { class: "pstep bubble" });
      li.innerHTML = `<button type="button" aria-expanded="false" disabled><span class="n">${i + 1}. ${name}</span><span class="v">Waiting</span><span class="more-i"></span></button>`;
      ol.append(li);
      return li;
    });
    const detail = el("li", { class: "pdetail" }, `<div><div class="inner"></div></div>`);
    ol.append(detail);
    let openIdx = -1;
    const notes = [];
    steps.forEach((li, i) => li.querySelector("button").addEventListener("click", () => {
      steps.forEach((s) => { s.classList.remove("open"); s.querySelector("button").setAttribute("aria-expanded", "false"); });
      if (openIdx === i) { openIdx = -1; detail.classList.remove("open"); return; }
      openIdx = i; li.classList.add("open"); li.querySelector("button").setAttribute("aria-expanded", "true");
      detail.querySelector(".inner").innerHTML = notes[i] || "";
      detail.classList.add("open");
    }));
    return {
      async set(i, state, value, note, extraClass = "") {
        const li = steps[i];
        li.className = `pstep bubble on ${state} ${extraClass}`;
        li.querySelector(".v").textContent = value;
        const btn = li.querySelector("button");
        if (note) { notes[i] = note; btn.disabled = false; li.querySelector(".more-i").textContent = "See how"; }
        await sleep(state === "done" ? 320 : 120);
      },
    };
  }

  async function run(query) {
    query = String(query || "").trim();
    if (!query) return;
    $("q").value = query;
    const btn = document.querySelector(".search button");
    btn.disabled = true;
    const runner = $("runner");
    runner.hidden = false;
    $("result").innerHTML = "";
    const ui = pipeUI();
    requestAnimationFrame(() => runner.scrollIntoView({ behavior: REDUCED ? "auto" : "smooth", block: "start" }));
    const known = matchWatchlist(query);

    try {
      if (CONFIG.newsApi) await runLive(query, known, ui);
      else if (known && DATA) await runHourly(known, ui);
      else showNoLive(query);
    } catch (err) {
      console.error(err);
      $("result").innerHTML = `<div class="notice"><b>That search didn't finish.</b> ${esc(err.userMessage || "The news server or Python didn't respond. Wait a moment and run it again.")}</div>`;
    } finally {
      btn.disabled = false;
    }
  }

  async function runLive(query, known, ui) {
    await ui.set(0, "busy", "Reading the news…");
    const py = getPython();
    const params = new URLSearchParams({ q: known ? known.name : query });
    if (known) params.set("symbol", known.symbol);
    else if (/^[A-Z.]{1,5}$/.test(query)) params.set("symbol", query);
    const res = await fetch(`${CONFIG.newsApi.replace(/\/$/, "")}/?${params}`).catch(() => null);
    if (!res || !res.ok) { const e = new Error("news"); e.userMessage = "Couldn't reach the news server. Try again in a minute."; throw e; }
    const news = await res.json();
    const sources = {};
    news.items.forEach((it) => (sources[it.source] = (sources[it.source] || 0) + 1));
    const topSources = Object.entries(sources).sort((a, b) => b[1] - a[1]).slice(0, 5);
    await ui.set(0, "done", plural(news.items.length, "headline"),
      `<p>Ran <b>${news.feeds} searches</b>: one Google News search for each of the last ${news.days} days (each returns at most 100 stories), plus Yahoo Finance.${news.failed ? ` ${news.failed} didn't respond.` : ""}</p>` +
      (topSources.length ? `<p>Most stories came from ${topSources.map(([s, n]) => `${esc(s)} (${n})`).join(", ")}.</p>` : ""));

    await ui.set(1, "busy", "Starting Python…");
    const live = await py.catch(() => { const e = new Error("py"); e.userMessage = "Python couldn't load in this browser. Try a recent Chrome, Safari or Firefox."; throw e; });
    const company = known ? JSON.stringify(known) : live.resolve_json(query);
    const t = JSON.parse(live.analyze(JSON.stringify(news.items), company, new Date().toISOString().replace(/\.\d{3}Z$/, "+00:00"), news.days));
    t.mode = "live";
    await ui.set(1, "done", `${t.unique.toLocaleString()} unique`,
      `<p><b>${(t.fetched - t.unique).toLocaleString()} repeats removed.</b> Each title is lowercased and stripped of punctuation, so the same story from two sites becomes the same key.</p><p>This ran in your browser: the same <b>extract.py</b> the hourly job uses, loaded with Pyodide.</p>`);

    const match = t.headlines[0]?.title;
    await ui.set(2, "done", `${t.matched.toLocaleString()} name ${t.name}`,
      `<p>A search for a company also returns stories that only mention it in passing or not at all. Only headlines that actually name ${esc(t.name)} count.</p>` +
      (match ? `<span class="ex">${esc(match)}</span>` : "") +
      (t.rejected_example ? `<span class="ex no">${esc(t.rejected_example)}</span>` : ""));

    await ui.set(3, "done", t.z == null ? "Too new to score" : `z = ${fmtZ(t.z)}`,
      t.z == null ? `<p>There are fewer than 5 days with coverage, so there's no reliable "usual" to compare against.</p>`
        : `<p>Last 24 hours: <b>${t.current}</b>. Usual: <b>${t.mean.toFixed(1)}</b> a day, give or take <b>${t.std.toFixed(1)}</b>.</p><p>z = (${t.current} − ${t.mean.toFixed(1)}) ÷ ${Math.max(t.std, 1).toFixed(1)} = <b>${fmtZ(t.z)}</b>. ${t.z >= 2 ? "Above 2, so it's a spike." : "Below 2, so not a spike."}</p>`,
      t.status === "spike" ? "spike" : "");
    showResult(t);
  }

  async function runHourly(t0, ui) {
    const t = { ...DATA.tickers.find((x) => x.symbol === t0.symbol), mode: "hourly" };
    const total = t.series.reduce((a, p) => a + p.count, 0);
    const note = `<p>Live search isn't switched on for this site yet, so this uses the headlines collected every hour.</p>`;
    await ui.set(0, "done", plural(DATA.totals.headlines, "headline"), `${note}<p>Collected from ${DATA.totals.sources} publishers over the past few weeks.</p>`);
    await ui.set(1, "done", "Already unique", `${note}<p>Duplicates are dropped as the headlines are stored.</p>`);
    await ui.set(2, "done", `${total.toLocaleString()} name ${t.name}`, `<p>Headlines in the last 30 days that name ${esc(t.name)} or its symbol.</p>`);
    await ui.set(3, "done", t.z == null ? "Too new to score" : `z = ${fmtZ(t.z)}`, t.z == null ? "" : `<p>z = (${t.current} − ${t.mean.toFixed(1)}) ÷ ${Math.max(t.std, 1).toFixed(1)} = <b>${fmtZ(t.z)}</b>.</p>`, t.status === "spike" ? "spike" : "");
    showResult(t);
  }

  function showNoLive(query) {
    $("pipe").innerHTML = "";
    if (!DATA) {
      $("result").innerHTML = `<div class="notice"><b>No headlines collected yet.</b> Run the pipeline once (double-click Run TickerChatter.command) to fill in the 40 tracked stocks, or switch on live search to look up any company.</div>`;
      return;
    }
    const tracked = DATA.watchlist.slice(0, 8);
    $("result").innerHTML = `<div class="notice"><b>Live search isn't switched on yet,</b> so only the 40 stocks collected every hour work for now. ${esc(query)} isn't one of them.<div class="row">${tracked.map((t) => `<button class="more bubble" type="button" data-q="${esc(t.name)}">${esc(t.name)}</button>`).join("")}</div></div>`;
    $("result").querySelectorAll("[data-q]").forEach((b) => b.addEventListener("click", () => run(b.dataset.q)));
  }

  function showResult(t) {
    const host = el("div", { class: "mask", id: "result-card" });
    $("result").innerHTML = "";
    $("result").append(host);
    renderDetail(t, host);
    requestAnimationFrame(() => host.classList.add("in"));
    trackFocus($("runner"));
  }

  $("run").addEventListener("submit", (e) => { e.preventDefault(); run($("q").value); });

  /* ---------- theme ---------- */
  (() => {
    const root = document.documentElement;
    try { const s = localStorage.getItem("tc-theme"); if (s) root.dataset.theme = s; } catch { /* blocked */ }
    $("theme").addEventListener("click", () => {
      const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
      root.dataset.theme = dark ? "light" : "dark";
      try { localStorage.setItem("tc-theme", root.dataset.theme); } catch { /* blocked */ }
    });
  })();

  /* ---------- boot ---------- */
  async function load() {
    if (window.TICKERCHATTER_DATA) return window.TICKERCHATTER_DATA;
    try { const r = await fetch("data/latest.json", { cache: "no-store" }); return r.ok ? r.json() : null; } catch { return null; }
  }
  load().then((d) => {
    // A data file with no headlines (pipeline never fetched) is the same as no data.
    DATA = d && d.totals && d.totals.headlines > 0 ? d : null;
    renderHero(); renderToday(); renderSteps();
    watch();
    trackFocus();
    // Warm up Python in the background once the page is idle, so the first search is quick.
    const warm = () => getPython().catch(() => {});
    if (CONFIG.newsApi) window.requestIdleCallback ? requestIdleCallback(warm, { timeout: 4000 }) : setTimeout(warm, 2500);
  });
})();
