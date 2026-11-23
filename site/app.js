/* CCL / USML / DSGL Navigator — static, no dependencies. */
(() => {
  "use strict";

  const DATA = window.__DATA__ || {};
  const SRC = {
    ccl: { key: "ccl", short: "CCL", reg: "EAR", long: "Commerce Control List", cfr: "15 CFR Part 774, Supp. No. 1",
           ecfr: d => `https://www.ecfr.gov/on/${d}/title-15/part-774/appendix-Supplement%20No.%201%20to%20Part%20774` },
    usml: { key: "usml", short: "USML", reg: "ITAR", long: "U.S. Munitions List", cfr: "22 CFR § 121.1",
            ecfr: d => `https://www.ecfr.gov/on/${d}/title-22/chapter-I/subchapter-M/part-121/section-121.1` },
    dsgl: { key: "dsgl", short: "DSGL", reg: "AU", long: "Defence and Strategic Goods List 2024", cfr: "F2024L01024",
            ecfr: () => "https://www.legislation.gov.au/F2024L01024/asmade/text" },
  };
  const TYPE_LABEL = {
    ccl: { defs: "Definitions", def: "Definition", category: "CCL Category", part: "Category part", group: "Product group", subgroup: "Sub-group",
           eccn: "ECCN", item: "ECCN paragraph", info: "Category note", ref: "Related provision" },
    usml: { defs: "Definitions", def: "Definition", category: "USML Category", item: "USML paragraph", ref: "Related provision" },
    dsgl: { defs: "Definitions", def: "Definition", part: "DSGL list", category: "Dual-use category", group: "Product group", eccn: "Control entry",
            item: "DSGL paragraph", ref: "Related provision" },
  };
  const LINK_LABEL = { ccl: "eCFR ↗", usml: "eCFR ↗", dsgl: "Legislation ↗" };

  const $ = (s, el = document) => el.querySelector(s);
  const main = $("#main");
  const qInput = $("#q");
  const enc = encodeURIComponent;
  const esc = s => String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  if (!DATA.ccl || !DATA.usml) {
    main.innerHTML = `<div class="wrap empty">Data files are missing. Run <code>python3 scripts/build_data.py</code>.</div>`;
    return;
  }
  const META = DATA.ccl.meta;
  const SOURCES = ["ccl", "usml", "dsgl"].filter(k => DATA[k]);
  const DM = DATA.dsgl ? DATA.dsgl.meta : null;
  const SL = new Set(DM && DM.sl || []), VSL = new Set(DM && DM.vsl || []);

  /* ------------------------------------------------------------------ index */
  const byId = { ccl: new Map(), usml: new Map(), dsgl: new Map() };
  const parentOf = { ccl: new Map(), usml: new Map(), dsgl: new Map() };
  const codeMap = new Map();          // normalized code -> [[src, node], ...]
  const entries = [];                 // search entries

  const decodeEnt = s => s.replace(/&(amp|lt|gt|quot|#39|#x27);/g, (m, e) =>
    ({ amp: "&", lt: "<", gt: ">", quot: '"', "#39": "'", "#x27": "'" }[e]));
  const plain = h => decodeEnt((h || "").replace(/<br>/g, " ").replace(/<\/(p|div|h4|td|th|tr)>/g, " ").replace(/<[^>]+>/g, "")).replace(/\s+/g, " ").trim();
  const norm = s => s.toLowerCase().replace(/[“”"‘’'`]/g, "").replace(/[‐‑–—]/g, "-");
  const normCode = s => s.toLowerCase().replace(/^(usml|ccl|dsgl|eccn|category|cat\.?)\s+/g, "").replace(/\s+/g, "");

  function addCode(key, src, n) {
    const k = normCode(key);
    if (!k) return;
    const list = codeMap.get(k) || [];
    if (!list.some(([s2]) => s2 === src)) list.push([src, n]);
    codeMap.set(k, list);
  }

  for (const src of SOURCES) {
    const root = DATA[src];
    byId[src].set(root.i, root);
    const visit = (n, par, depth) => {
      byId[src].set(n.i, n);
      parentOf[src].set(n.i, par);
      n._d = depth;
      if (n.y !== "root") {
        const txt = plain((n.h || "") + " " + (n.p || ""));
        entries.push({ src, n, code: n.c, codeN: norm(n.c), title: norm(n.t || ""), text: norm(n.c + " " + (n.t || "") + " " + txt), raw: txt });
        addCode(n.i.replace(/~\d+$/, ""), src, n);
        addCode(n.c, src, n);
        if (src === "usml" && n.y === "category") addCode("usml " + n.i, src, n);
        if (src === "dsgl" && n.y === "category") addCode(n.i, src, n);
      }
      for (const k of n.k || []) visit(k, n, depth + 1);
    };
    for (const k of root.k || []) visit(k, root, 1);
    for (const r of root.refs || []) visit(r, root, 1);
  }

  /* ------------------------------------------------------------------ definitions */
  const defIndex = { ccl: new Map(), usml: new Map(), dsgl: new Map() };
  const defsNode = {};
  const defKey = s => s.replace(/[“”"‘’']/g, "").replace(/\s+/g, " ").trim().replace(/[.,:;]+$/, "").toLowerCase();
  for (const src of SOURCES) {
    for (const r of DATA[src].refs || []) {
      if (r.y !== "defs") continue;
      defsNode[src] = r;
      for (const d of r.k || []) for (const k of d.keys || []) if (!defIndex[src].has(k)) defIndex[src].set(k, d);
    }
  }
  function lookupDef(src, phrase) {
    const M = defIndex[src], k = defKey(phrase);
    if (!k || k.length > 80) return null;
    const tries = [k, k.replace(/ies$/, "y"), k.replace(/es$/, ""), k.replace(/s$/, ""), k.replace(/-/g, " "), k.replace(/ /g, "-")];
    for (const t of tries) if (M.has(t)) return M.get(t);
    return null;
  }
  // USML text does not quote defined terms: link a curated set of key ITAR phrases instead.
  const usmlPhrases = [];
  for (const d of (defsNode.usml && defsNode.usml.k) || []) for (const a of d.a || []) usmlPhrases.push([a.toLowerCase(), d]);
  usmlPhrases.sort((x, y) => y[0].length - x[0].length);
  const USML_TERM_RE = usmlPhrases.length
    ? new RegExp(`\\b(${usmlPhrases.map(([a]) => a.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})\\b`, "gi") : null;
  const usmlPhraseMap = new Map(usmlPhrases);
  const defTip = d => esc(trimWordsRaw(plain(d.h || d.t || ""), 320));
  function trimWordsRaw(s, k) { return s.length <= k ? s : s.slice(0, k).replace(/\s+\S*$/, "") + "…"; }

  /* Untruncated paragraph text (titles in the data are capped for list views). */
  function fullTitle(n) {
    if (n.y !== "item" || !n.h) return n.t || "";
    const m = n.h.match(/^<p[^>]*>([\s\S]*?)<\/p>/);
    if (!m) return n.t || "";
    return plain(m[1]).replace(/^\*?\s*(\([a-zA-Z0-9]+\)\s*)/, "").replace(/^[a-z](\.[0-9a-z]+)*\.*\s+/, "") || n.t || "";
  }
  const refLabel = n => n.y === "def" ? "" : n.y === "defs" ? "Definitions" : n.y === "ref" ? n.c.replace(/^Supplement No\. (\d+) to Part \d+$/, "Supp. $1") : n.c.replace(/^Category /, "");
  const refTitle = n => n.y === "def" ? n.c : n.y === "defs" ? `${(n.k || []).length} terms` : n.y === "ref" ? (n.t || "").replace(/^(§+\s*[\d.\-]+|Supplement No\. \d+ to Part \d+|Division \d+)\s*[—-]?\s*/, "") : (n.t || "");
  const trimWords = (s, k) => s.length <= k ? s : s.slice(0, k).replace(/\s+\S*$/, "") + "…";
  const ancestors = (src, n) => {
    const out = [];
    for (let p = parentOf[src].get(n.i); p && p.y !== "root"; p = parentOf[src].get(p.i)) out.unshift(p);
    return out;
  };
  const href = (src, n, hl) => `#/${src}/${enc(n.i)}${hl ? "?hl=" + enc(hl) : ""}`;
  const countDesc = n => (n.k || []).reduce((a, k) => a + 1 + countDesc(k), 0);
  const reasons = n => {
    const m = (n.h || "").match(/<i>Reason for Control:<\/i>\s*([^<]+)/);
    return m ? m[1].split(/[,;]\s*/).map(s => s.trim()).filter(s => /^[A-Z][A-Z0-9 :]{0,10}$/.test(s)) : [];
  };
  function chips(src, n) {
    const c = [];
    if (n.s) c.push(`<span class="pill sme" title="Significant Military Equipment">SME</span>`);
    if (n.r) c.push(`<span class="pill">Reserved</span>`);
    if (src === "ccl" && n.y === "eccn") {
      if (/subject to the ITAR/i.test(n.t)) c.push(`<span class="pill usml" title="Cross-reference only — the item is controlled under the ITAR">→ ITAR</span>`);
      if (/^\d[A-E]6\d\d$/.test(n.c)) c.push(`<span class="pill warn">600 series</span>`);
      else if (/^\d[A-E]5[12]\d$/.test(n.c)) c.push(`<span class="pill warn">${n.c.slice(2, 5)} series</span>`);
      for (const r of reasons(n)) c.push(`<span class="pill rfc" title="Reason for control">${esc(r)}</span>`);
    }
    if (src === "dsgl" && (n.y === "eccn" || n.y === "item")) {
      const lists = sensitivity(n.c);
      if (lists.vsl) c.push(`<span class="pill usml" title="On the Very Sensitive List of dual-use goods and technologies">VSL${lists.vsl === "part" ? " (part)" : ""}</span>`);
      else if (lists.sl) c.push(`<span class="pill warn" title="On the Sensitive List of dual-use goods and technologies">SL${lists.sl === "part" ? " (part)" : ""}</span>`);
    }
    return c.join("");
  }

  /* SL / VSL membership: "full" if the code or a parent paragraph is listed, "part" if only sub-paragraphs are. */
  function sensitivity(code) {
    const look = set => {
      let c = code;
      while (c) {
        if (set.has(c)) return "full";
        const cut = c.lastIndexOf(".");
        if (cut < 0) break;
        c = c.slice(0, cut);
      }
      for (const x of set) if (x.startsWith(code + ".")) return "part";
      return null;
    };
    const vsl = (DM && DM.vsl_cat0 && /^0[A-E]/.test(code)) ? "full" : look(VSL);
    return { vsl, sl: vsl || look(SL) };
  }

  /* ------------------------------------------------------------------ cross-reference links */
  const ROMAN_RE = "(?:XXI|XX|XIX|XVIII|XVII|XVI|XV|XIV|XIII|XII|XI|X|IX|VIII|VII|VI|V|IV|III|II|I)";
  const ECCN_REF = /\b(\d[A-E]\d{3})((?:\.[a-z0-9]{1,3})*)\b/g;
  const ML_REF = /\bML\s?(\d{1,3})((?:\.[a-z0-9]{1,3})*)\b/g;
  const USML_REF = new RegExp(`\\b(USML )?Category (${ROMAN_RE})(?![A-Za-z])((?:\\([a-zA-Z0-9]{1,5}\\))*)`, "g");
  function resolve(src, code) {
    const M = byId[src];
    let c = code;
    while (c) {
      if (M.has(c)) return M.get(c);
      const cut = src === "usml" ? c.lastIndexOf("(") : c.lastIndexOf(".");
      if (cut <= 0) break;
      c = c.slice(0, cut);
    }
    return null;
  }
  /* apply fn only to text outside our \u0001..\u0002 placeholder tags */
  const outside = (s2, fn) => s2.split(/(\u0001[^\u0002]*\u0002)/).map((p, i) => (i % 2 ? p : fn(p))).join("");
  function linkify(html, src, hlTerms) {
    return html.split(/(<[^>]+>)/).map((seg, i) => {
      if (i % 2 || !seg) return seg;
      const eSrc = src === "dsgl" ? "dsgl" : "ccl";     // DSGL text refers to DSGL entries
      const a = (s2, n, m) => `\u0001a class="xref" href="${href(s2, n)}"\u0002${m}\u0001/a\u0002`;
      const dl = (d, m) => `\u0001a class="defref" href="${href(src, d)}" title="${defTip(d)}"\u0002${m}\u0001/a\u0002`;
      let out = seg;
      if (src === "usml") {
        if (USML_TERM_RE) out = out.replace(USML_TERM_RE, m => { const d = usmlPhraseMap.get(m.toLowerCase()); return d ? dl(d, m) : m; });
      } else {
        // “Quoted” terms are defined terms (EAR Part 772 / DSGL Division 4)
        out = out.replace(/“([^“”]{1,80})”/g, (m, term) => { const d = lookupDef(src, term); return d ? `“${dl(d, term)}”` : m; });
      }
      out = outside(out, t => t.replace(ECCN_REF, (m, e, rest) => {
        const n = resolve(eSrc, e + rest);
        return n ? a(eSrc, n, m) : m;
      }));
      if (src === "dsgl") {
        out = outside(out, t => t.replace(ML_REF, (m, num, rest) => {
          const n = resolve("dsgl", "ML" + num + rest);
          return n ? a("dsgl", n, m) : m;
        }));
      } else {
        // In the CCL, "Category XII" (roman) always refers to the USML; in the USML, to itself.
        out = outside(out, t => t.replace(USML_REF, (m, pre, rn, rest) => {
          const n = resolve("usml", rn + rest);
          return n ? a("usml", n, m) : m;
        }));
      }
      if (hlTerms && hlTerms.length) out = highlightText(out, hlTerms, true);
      return out.replace(/\u0001/g, "<").replace(/\u0002/g, ">");
    }).join("");
  }

  /* highlight in already-escaped text (skips our \u0001..\u0002 placeholder tags) */
  function highlightText(s, terms, escapedAlready) {
    if (!terms.length) return escapedAlready ? s : esc(s);
    const pats = terms.map(t => t.split("").map(ch => {
      const e = ch.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      return /["']/.test(ch) ? "" : e + "[“”\"‘’']?";
    }).join("")).filter(Boolean);
    if (!pats.length) return escapedAlready ? s : esc(s);
    const re = new RegExp(`(${pats.join("|")})`, "gi");
    const parts = s.split(/(\u0001[^\u0002]*\u0002)/);
    return parts.map((p, i) => (i % 2 ? p : (escapedAlready ? p : esc(p)).replace(re, "<mark>$1</mark>"))).join("");
  }

  /* ------------------------------------------------------------------ search */
  function parseQuery(q) {
    const terms = [], neg = [];
    q.replace(/(-?)"([^"]+)"|(-?)(\S+)/g, (m, n1, phrase, n2, word) => {
      const t = norm(phrase || word).trim();
      if (!t) return;
      ((n1 || n2) ? neg : terms).push(t);
    });
    return { terms, neg };
  }
  function search(q, scope) {
    const { terms, neg } = parseQuery(q);
    if (!terms.length) return { terms, hits: [] };
    const hits = [];
    for (const e of entries) {
      if (scope !== "all" && e.src !== scope) continue;
      let ok = true, score = 0;
      for (const t of terms) {
        const at = e.text.indexOf(t);
        if (at < 0) { ok = false; break; }
        if (e.codeN === t) score += 1000;
        else if (e.codeN.startsWith(t)) score += 60;
        if (e.title.includes(t)) score += 12;
        // frequency, capped
        let c = 0, p = at;
        while (p >= 0 && c < 6) { c++; p = e.text.indexOf(t, p + t.length); }
        score += c;
      }
      if (!ok) continue;
      for (const t of neg) if (e.text.includes(t)) { ok = false; break; }
      if (!ok) continue;
      if (e.n.y === "eccn" || e.n.y === "category") score += 4;
      if (e.n.r) score -= 8;
      score -= e.n._d * 0.3;
      hits.push({ e, score });
    }
    hits.sort((a, b) => b.score - a.score);
    return { terms, hits };
  }
  function snippet(raw, terms) {
    const low = norm(raw);
    let at = -1;
    for (const t of terms) { at = low.indexOf(t); if (at >= 0) break; }
    if (at < 0) at = 0;
    // norm() strips quote chars, so map position approximately back to raw by re-scanning
    let ri = 0, li = 0;
    while (ri < raw.length && li < at) { if (!/[“”"‘’'`]/.test(raw[ri])) li++; ri++; }
    const start = Math.max(0, ri - 80), end = Math.min(raw.length, ri + 180);
    const s = (start ? "…" : "") + raw.slice(start, end) + (end < raw.length ? "…" : "");
    return highlightText(s, terms, false);
  }

  /* ------------------------------------------------------------------ views */
  let scope = "all";
  const APP = "CCL / USML / DSGL Navigator";
  const setTitle = t => { document.title = t ? `${t} · ${APP}` : APP; };

  function cfrCrumbs(src) {
    return (DATA[src].crumbs || []).map(c =>
      `<span class="cfr" title="${esc(c.desc || "")}">${esc(c.label)}</span>`).join("");
  }
  function foot() {
    const dsgl = DM ? `<br>DSGL: ${esc(DM.instrument)}, ${esc(DM.version)} —
      <a href="${esc(DM.sources[0])}" target="_blank" rel="noopener">legislation.gov.au</a>. Later amendments to the instrument are not included.` : "";
    return `<div class="foot">CCL / USML: eCFR Versioner API, point-in-time ${esc(META.date)} —
      ${META.sources.map(u => `<a href="${esc(u)}" target="_blank" rel="noopener">${esc(u.replace("https://www.ecfr.gov/api/versioner/v1/", ""))}</a>`).join(" · ")}.${dsgl}
      <br>This tool is a navigation aid, not legal advice. Confirm classifications against the official text and, where needed,
      with BIS (CCATS), DDTC (CJ) or Defence Export Controls.</div>`;
  }

  function viewHome() {
    setTitle("");
    const ccl = DATA.ccl, usml = DATA.usml;
    const G = ["A", "B", "C", "D", "E"];
    const matrix = (src, cats) => {
    const rows = [];
    for (const cat of cats) {
      const subs = cat.k.filter(k => k.y === "part");
      const lines = subs.length ? subs.map(p => ({ label: p.c.replace("Category ", ""), node: p, title: p.t })) : [{ label: cat.c.replace("Category ", ""), node: cat, title: cat.t }];
      for (const L of lines) {
        const cells = G.map(g => {
          const grp = (L.node.k || []).find(k => k.y === "group" && k.c.endsWith(g));
          if (!grp) return `<td><span class="none">·</span></td>`;
          const nE = (function cnt(n) { return (n.k || []).reduce((a, k) => a + (k.y === "eccn" ? 1 : cnt(k)), 0); })(grp);
          return `<td><a class="cell" href="${href(src, grp)}" title="${esc(grp.c + " — " + grp.t)}">${nE || "–"}</a></td>`;
        }).join("");
        rows.push(`<tr><td class="cat"><a href="${href(src, L.node)}"><b>${esc(L.label)}</b>${esc(L.title)}</a></td>${cells}</tr>`);
      }
    }
    return `<table class="matrix ${src}"><thead><tr><th></th>${G.map(g => `<th title="${g}">${g}</th>`).join("")}</tr></thead><tbody>${rows.join("")}</tbody></table>`;
    };
    const dsgl = DATA.dsgl;
    const ml = dsgl ? dsgl.k.find(k => k.i === "ML") : null, du = dsgl ? dsgl.k.find(k => k.i === "DU") : null;
    const dsglCard = dsgl ? `<section class="card homecard wide">
          <h3><span class="pill dsgl">AU</span> Defence and Strategic Goods List 2024</h3>
          <div class="sub">F2024L01024 · ${esc(DM.version)} · ${DM.ml} munitions entries, ${DM.du_entries} dual-use entries, ${DM.items.toLocaleString()} paragraphs</div>
          <div class="split">
            <div><div class="minihead">Part 1 — Munitions list</div>
              <ul class="catlist">${ml.k.map(c => `<li><a href="${href("dsgl", c)}"><span class="rn dsgl">${esc(c.c)}</span><span>${esc(trimWords(c.t, 90))}</span></a></li>`).join("")}</ul></div>
            <div><div class="minihead">Part 2 — Dual-use list · entries per product group</div>${matrix("dsgl", du.k)}</div>
          </div>
          <div class="refs">${refs("dsgl")}</div>
        </section>` : "";
    function refs(src) { return (DATA[src].refs || []).filter(r => !/\[Reserved\]/.test(r.t)).map(r => r.y === "defs"
      ? `<a class="defs-link" href="${href(src, r)}" title="${esc(r.t)}"><b>Definitions</b> · ${(r.k || []).length} terms</a>`
      : `<a href="${href(src, r)}" title="${esc(r.t)}">${esc(refLabel(r).replace(/^(\d)/, "§ $1"))} ${esc(trimWords(refTitle(r), 40))}</a>`).join(""); }
    main.innerHTML = `<div class="wrap">
      <div class="hero">
        <h1>Export classification navigator</h1>
        <p>Drill down through the EAR Commerce Control List, the ITAR U.S. Munitions List and the Australian Defence and
        Strategic Goods List to the paragraph-level classification, or search keywords across all three. US text as of
        <b>${esc(META.date)}</b> (${META.ccl.eccns} ECCNs / ${META.ccl.items.toLocaleString()} CCL paragraphs; ${META.usml.categories} USML categories /
        ${META.usml.items.toLocaleString()} paragraphs)${DM ? `; DSGL 2024 as made (${(DM.ml + DM.du_entries).toLocaleString()} entries / ${DM.items.toLocaleString()} paragraphs)` : ""}.</p>
      </div>
      <div class="homegrid">
        <section class="card homecard">
          <h3><span class="pill ccl">EAR</span> Commerce Control List</h3>
          <div class="sub">15 CFR Part 774, Supplement No. 1 · ECCNs per product group</div>
          ${matrix("ccl", ccl.k)}
          <div class="refs">${refs("ccl")}</div>
        </section>
        <section class="card homecard">
          <h3><span class="pill usml">ITAR</span> U.S. Munitions List</h3>
          <div class="sub">22 CFR § 121.1 · 21 categories</div>
          <ul class="catlist">${usml.k.map(c => `<li><a href="${href("usml", c)}"><span class="rn">${esc(c.i)}</span><span>${esc(c.t)}</span></a></li>`).join("")}</ul>
          <div class="refs">${refs("usml")}</div>
        </section>
        ${dsglCard}
      </div>
      <div class="card tips">
        <b>Search tips.</b> Words are combined with AND: <code>infrared camera</code>. Use quotes for a phrase:
        <code>"focal plane array"</code>. Exclude with a minus: <code>radar -weather</code>. Type a classification to jump to it:
        <code>3A001.a.1</code>, <code>XI(a)(3)</code>, <code>Category XV</code>, <code>ML10.b</code>. Use the scope buttons to limit a
        search to one list. An ECCN that exists in both the CCL and the DSGL has a <i>Compare</i> button.
        Defined terms are underlined in the text: hover for the definition, click to open it. Type a term such as
        <code>specially designed</code> to jump to its definitions. Press <kbd>/</kbd> to search, <kbd>↑</kbd><kbd>↓</kbd> and
        <kbd>Enter</kbd> to pick a result. Linked ECCN and USML references in the text are clickable.
      </div>
      ${foot()}
    </div>`;
  }

  function viewNode(src, id, hl) {
    const n = byId[src].get(id);
    if (!n) { main.innerHTML = `<div class="wrap empty">Not found: ${esc(id)}. <a href="#/">Home</a></div>`; return; }
    const S = SRC[src];
    const anc = ancestors(src, n);
    const hlTerms = hl ? parseQuery(hl).terms : [];
    setTitle(`${n.c}${n.t ? " " + n.t.slice(0, 60) : ""}`);
    const kids = n.k || [];
    const isLeaf = !kids.length && !n.r && (n.y === "item" || n.y === "eccn");

    const crumbs = `<div class="crumbs">${cfrCrumbs(src)}<a href="#/">${S.short}</a>${anc.map(a => `<a href="${href(src, a)}">${esc(a.c)}</a>`).join("")}<span>${esc(n.c)}</span></div>`;

    const head = `<div class="head">
      <div class="titles">
        <div class="kicker"><span class="pill ${src}">${S.reg} · ${S.short}</span><span class="pill">${TYPE_LABEL[src][n.y] || n.y}</span>${chips(src, n)}</div>
        <div><span class="bigcode">${esc(n.c)}</span></div>
        <h1>${n.y === "def" ? (n.cats ? `<span class="muted">Applies to: ${esc(n.cats)}</span>` : "") : linkify(esc(n.y === "ref" || n.y === "defs" ? n.t : fullTitle(n)), src, hlTerms)}</h1>
      </div>
      <div class="actions">
        ${compareBtn(src, n)}
        ${n.y === "def" ? `<a class="btn" href="#/search?q=${enc('"' + n.c.replace(/\s*\(.*\)$/, "") + '"')}&s=${src}" title="Search this list for the term">Find uses</a>` : ""}
        <button class="btn" data-copy="${esc(n.c)}" title="Copy classification">Copy</button>
        <a class="btn" href="${n.y === "ref" ? refUrl(src, n) : S.ecfr(META.date)}" target="_blank" rel="noopener">${LINK_LABEL[src]}</a>
      </div></div>`;

    // classification path: from the ECCN / USML category down to here
    let pathHtml = "";
    if (n.y === "item") {
      const startAt = anc.findIndex(a => a.y === (src === "usml" ? "category" : "eccn"));
      const chain = anc.slice(Math.max(0, startAt)).concat([n]);
      pathHtml = `<h2>Classification path</h2><div class="card path"><ol>${chain.map(c =>
        `<li class="${c === n ? "me" : ""}"><a class="pc" href="${href(src, c)}">${esc(c.c)}</a><span class="pt">${linkify(esc(fullTitle(c)), src, hlTerms)}</span></li>`).join("")}</ol></div>`;
    }

    const finalBox = isLeaf ? `<div class="final"><span class="lbl">Final classification level</span><span class="val">${esc(n.c)}</span>
      <button class="btn" data-copy="${esc(n.c)}">Copy</button>${n.s ? `<span class="pill sme">SME</span>` : ""}</div>` : "";

    const defsHtml = n.y === "def" ? alsoDefined(src, n) : "";
    const filterBox = n.y === "defs" ? `<input id="deffilter" class="deffilter" type="search" placeholder="Filter ${kids.length} terms…" autocomplete="off">` : "";
    const kidsHtml = kids.length ? `${filterBox}<h2>${n.y === "defs" ? "Terms" : n.y === "eccn" || n.y === "item" || src === "usml" ? "Drill down — paragraphs" : "Drill down"} <span class="muted">(${kids.length})</span></h2>
      <div class="card"><ul class="kids">${kids.map(k => {
        const d = countDesc(k);
        return `<li class="${k.r ? "reserved" : ""}"><a href="${href(src, k, hl)}"><span class="kc">${esc(k.c)}</span>
          <span class="kt">${esc(k.t || "")}<span class="chips">${chips(src, k)}</span></span>
          <span class="kn">${d ? d + " ›" : ""}</span></a></li>`;
      }).join("")}</ul></div>` : "";

    let textHtml = "";
    const body = n.h ? linkify(n.h, src, hlTerms) : "";
    if (n.y === "eccn") {
      const heading = src === "ccl" ? "License requirements, exceptions &amp; list of items controlled" : "Entry text &amp; notes";
      textHtml = body ? `<details class="sect" open><summary><h2>${heading}</h2></summary><div class="card text">${body}</div></details>` : "";
    } else if (body) {
      textHtml = `<h2>${n.y === "ref" ? "Text" : n.y === "def" ? "Definition" : n.y === "defs" ? "Introduction" : "Regulatory text"}</h2><div class="card text">${body}</div>`;
    }
    if (n.p) textHtml += `<h2>Notes to ${esc(n.c)}</h2><div class="card text">${linkify(n.p, src, hlTerms)}</div>`;

    let fullHtml = "";
    if (kids.length && (n.y === "eccn" || n.y === "item" || (src === "usml" && n.y === "category"))) {
      fullHtml = `<details class="sect" id="fullsec"><summary><h2>Full text of all sub-paragraphs</h2></summary><div class="card text subtree" id="fulltext"></div></details>`;
    }

    // siblings
    const par = parentOf[src].get(n.i);
    const list = !par ? [] : n.y === "ref" ? par.refs || [] : par.k || [];
    const ix = list.indexOf(n);
    const prev = ix > 0 ? list[ix - 1] : null, next = ix >= 0 && ix < list.length - 1 ? list[ix + 1] : null;
    const pager = `<div class="pager">${prev ? `<a class="card prev" href="${href(src, prev, hl)}">← <span class="code">${esc(prev.c)}</span> ${esc((prev.t || "").slice(0, 60))}</a>` : "<span></span>"}
      ${next ? `<a class="card next" href="${href(src, next, hl)}"><span class="code">${esc(next.c)}</span> ${esc((next.t || "").slice(0, 60))} →</a>` : ""}</div>`;

    main.innerHTML = n.y === "defs"
      ? `<div class="wrap">${crumbs}${head}${textHtml}${kidsHtml}${foot()}</div>`
      : `<div class="wrap">${crumbs}${head}${finalBox}${pathHtml}${kidsHtml}${textHtml}${defsHtml}${fullHtml}${pager}${foot()}</div>`;
    const ff = $("#deffilter");
    if (ff) ff.addEventListener("input", () => {
      const q = defKey(ff.value);
      main.querySelectorAll(".kids li").forEach(li => { li.hidden = q && !defKey(li.textContent).includes(q); });
    });

    const fs = $("#fullsec");
    if (fs) fs.addEventListener("toggle", () => {
      const box = $("#fulltext");
      if (fs.open && !box.dataset.done) {
        const parts = [];
        const walk = (k, d) => {
          parts.push(`<div class="st" style="margin-left:${d * 14}px"><a class="st-code" href="${href(src, k)}">${esc(k.c)}</a>${linkify(k.h || "", src, hlTerms)}${k.p ? linkify(k.p, src, hlTerms) : ""}</div>`);
          for (const c of k.k || []) walk(c, d + 1);
        };
        for (const k of kids) walk(k, 0);
        box.innerHTML = parts.join("");
        box.dataset.done = 1;
      }
    });
    const mk = main.querySelector(".text mark");
    if (mk && hlTerms.length) setTimeout(() => mk.scrollIntoView({ block: "center" }), 0);
    syncTree(src, n);
  }

  /* The same term defined in the other lists. */
  function alsoDefined(src, n) {
    const links = [];
    for (const s2 of SOURCES) {
      if (s2 === src) continue;
      let d = null;
      for (const k of n.keys || []) { d = lookupDef(s2, k); if (d) break; }
      if (d) links.push(`<a class="btn" href="${href(s2, d)}"><span class="pill ${s2}">${SRC[s2].short}</span> ${esc(d.c)}</a>`);
    }
    return links.length ? `<h2>Also defined in</h2><div class="also">${links.join("")}</div>` : "";
  }

  /* Same code in the other Wassenaar-based list (CCL <-> DSGL). */
  function compareBtn(src, n) {
    const other = src === "ccl" ? "dsgl" : src === "dsgl" ? "ccl" : null;
    if (!other || !DATA[other] || !(n.y === "eccn" || n.y === "item")) return "";
    const m = byId[other].get(n.c);
    return m ? `<a class="btn" href="${href(other, m)}" title="Open the same code in the ${SRC[other].long}">Compare: ${SRC[other].short} ${esc(m.c)}</a>` : "";
  }

  function refUrl(src, n) {
    const d = META.date;
    if (src === "dsgl") return SRC.dsgl.ecfr();
    if (src === "ccl") return /^\d/.test(n.c) ? `https://www.ecfr.gov/on/${d}/title-15/section-${n.c}` : `https://www.ecfr.gov/on/${d}/title-15/part-774/appendix-${enc(n.c)}`;
    return `https://www.ecfr.gov/on/${d}/title-22/section-${n.c}`;
  }

  let lastResults = [], sel = -1, shown = 0;
  function viewSearch(q, sc, keepFocus) {
    if (sc && sc !== scope) setScope(sc, false);
    const t0 = performance.now();
    const { terms, hits } = search(q, scope);
    const ms = performance.now() - t0;
    setTitle(`Search: ${q}`);
    // direct jump
    const direct = (codeMap.get(normCode(q)) || []).filter(([s2]) => scope === "all" || s2 === scope);
    lastResults = hits;
    shown = 0; sel = -1;
    main.innerHTML = `<div class="wrap">
      <div class="sr-head"><h1>${hits.length.toLocaleString()} result${hits.length === 1 ? "" : "s"}</h1>
        <span class="muted">for “${esc(q)}” in ${scope === "all" ? SOURCES.map(k => SRC[k].short).join(" + ") : SRC[scope].short} · ${ms.toFixed(0)} ms</span></div>
      ${direct.map(([s2, n2], i) => `<a class="card jump" href="${href(s2, n2)}"><span class="pill ${s2}">${SRC[s2].short}</span>
        Go to <b class="code">${esc(n2.c)}</b> <span class="muted">${esc((n2.t || "").slice(0, 90))}</span>${i === 0 ? " <kbd>Enter</kbd>" : ""}</a>`).join("")}
      ${hits.length ? `<div class="card"><ul class="results" id="results"></ul></div><button class="btn more" id="more" hidden>Show more</button>`
                    : (terms.length ? `<div class="card empty">No matches. Try fewer words, or check the scope filter.</div>` : "")}
      ${foot()}</div>`;
    window.__direct = direct[0] || null;
    renderMore(terms, q);
    const more = $("#more");
    if (more) more.onclick = () => renderMore(terms, q);
    if (!keepFocus) main.focus();
  }
  function renderMore(terms, q) {
    const ul = $("#results");
    if (!ul) return;
    const batch = lastResults.slice(shown, shown + 60);
    ul.insertAdjacentHTML("beforeend", batch.map(({ e }) => {
      const anc = ancestors(e.src, e.n);
      const ctx = anc.slice(-3).map(a => a.c + (a.y === "eccn" || a.y === "category" ? " " + trimWords(a.t || "", 60) : "")).join(" › ");
      return `<li><a href="${href(e.src, e.n, q)}"><div class="r1"><span class="pill ${e.src}">${SRC[e.src].short}</span>
        <span class="rc">${esc(e.n.c)}</span>${chips(e.src, e.n)}<span class="rt">${highlightText((e.n.t || "").slice(0, 160), terms, false)}</span></div>
        ${ctx ? `<div class="rp">${esc(ctx)}</div>` : ""}
        <div class="rs">${snippet(e.raw, terms)}</div></a></li>`;
    }).join(""));
    shown += batch.length;
    const more = $("#more");
    if (more) { more.hidden = shown >= lastResults.length; more.textContent = `Show more (${(lastResults.length - shown).toLocaleString()} left)`; }
  }
  function moveSel(d) {
    const lis = [...document.querySelectorAll("#results li")];
    if (!lis.length) return;
    if (lis[sel]) lis[sel].classList.remove("sel");
    sel = Math.max(0, Math.min(lis.length - 1, sel + d));
    lis[sel].classList.add("sel");
    lis[sel].scrollIntoView({ block: "nearest" });
  }

  /* ------------------------------------------------------------------ tree */
  let treeSrc = "ccl";
  const tree = $("#tree");
  function treeLi(src, n) {
    const has = (n.k || []).length > 0;
    const tw = has ? `<button class="tw" aria-expanded="false" aria-label="${esc(n.c)} sub-entries">▶</button>` : `<span class="tw leaf"></span>`;
    return `<li data-id="${esc(n.i)}"><div class="row">${tw}
      <a href="${href(src, n)}" title="${esc(n.c + " " + (n.t || ""))}"><span class="tc">${esc(refLabel(n))}</span>${esc(refTitle(n))}</a></div></li>`;
  }
  function renderTree(src) {
    treeSrc = src;
    document.querySelectorAll(".side-tabs button").forEach(b => {
      b.classList.toggle("on", b.dataset.tab === src);
      b.setAttribute("aria-pressed", b.dataset.tab === src);
    });
    const root = DATA[src];
    tree.innerHTML = `<ul>${root.k.map(k => treeLi(src, k)).join("")}</ul><div class="tref">Related provisions</div><ul>${(root.refs || []).map(k => treeLi(src, k)).join("")}</ul>`;
  }
  function expand(li, open) {
    const src = treeSrc;
    const n = byId[src].get(li.dataset.id);
    const tw = li.querySelector(".tw");
    let ul = li.querySelector(":scope > ul");
    if (open === undefined) open = !ul || ul.hidden;
    if (open) {
      if (!ul && n.k) { li.insertAdjacentHTML("beforeend", `<ul>${n.k.map(k => treeLi(src, k)).join("")}</ul>`); ul = li.querySelector(":scope > ul"); }
      if (ul) ul.hidden = false;
      tw.textContent = "▼";
      tw.setAttribute("aria-expanded", "true");
    } else if (ul) { ul.hidden = true; tw.textContent = "▶"; tw.setAttribute("aria-expanded", "false"); }
  }
  function syncTree(src, n) {
    if (treeSrc !== src) renderTree(src);
    tree.querySelectorAll(".row.cur").forEach(r => r.classList.remove("cur"));
    const chain = ancestors(src, n).concat([n]);
    let li = null;
    for (const a of chain) {
      li = [...tree.querySelectorAll("li")].find(x => x.dataset.id === a.i);   // small lists; fine
      if (!li) return;
      if (a !== n) expand(li, true);
    }
    if (li) { li.firstElementChild.classList.add("cur"); li.firstElementChild.scrollIntoView({ block: "nearest" }); }
  }
  tree.addEventListener("click", e => {
    const tw = e.target.closest(".tw");
    if (tw) { e.preventDefault(); expand(tw.closest("li")); return; }
    if (e.target.closest("a")) setNav(false);
  });
  document.querySelectorAll(".side-tabs button").forEach(b => b.onclick = () => renderTree(b.dataset.tab));

  /* ------------------------------------------------------------------ mobile navigation drawer */
  // Below 900px the sidebar is an off-canvas drawer. Closed, it is inert so its links are not
  // tab stops; open, the rest of the page is inert, Escape or a click outside closes it, and
  // focus returns to the menu button.
  const side = $("#side"), menuBtn = $("#menuBtn");
  const mobile = matchMedia("(max-width: 900px)");
  const behindDrawer = [main, $(".search-wrap"), $(".brand")];
  const navOpen = () => document.body.classList.contains("nav-open");
  function setNav(open, returnFocus = false) {
    open = open && mobile.matches;
    document.body.classList.toggle("nav-open", open);
    menuBtn.setAttribute("aria-expanded", open);
    side.inert = mobile.matches && !open;
    for (const el of behindDrawer) el.inert = open;
    if (open) (tree.querySelector(".row.cur a") || side.querySelector(".side-tabs .on")).focus({ preventScroll: true });
    else if (returnFocus) menuBtn.focus();
  }
  menuBtn.onclick = () => setNav(!navOpen(), true);
  document.addEventListener("keydown", e => { if (e.key === "Escape" && navOpen()) setNav(false, true); });
  document.addEventListener("click", e => { if (navOpen() && !e.target.closest("#side, #menuBtn")) setNav(false, true); });
  mobile.addEventListener("change", () => setNav(false));
  setNav(false);

  /* ------------------------------------------------------------------ routing */
  function route() {
    const h = location.hash.slice(1) || "/";
    const [path, qs] = h.split("?");
    const params = new URLSearchParams(qs || "");
    const parts = path.split("/").filter(Boolean);
    if (parts[0] === "search") {
      const q = params.get("q") || "";
      if (qInput.value !== q && document.activeElement !== qInput) qInput.value = q;
      viewSearch(q, params.get("s"), document.activeElement === qInput);
      return;
    }
    if (document.activeElement !== qInput) qInput.value = "";
    if (SRC[parts[0]] && DATA[parts[0]] && parts[1]) {
      viewNode(parts[0], decodeURIComponent(parts[1]), params.get("hl"));
      main.scrollTop = 0;
      if (!params.get("hl")) main.focus({ preventScroll: true });
      return;
    }
    if (SRC[parts[0]] && DATA[parts[0]]) renderTree(parts[0]);
    viewHome();
    main.scrollTop = 0;
  }
  window.addEventListener("hashchange", route);

  /* ------------------------------------------------------------------ search input */
  let tmr = 0;
  function setScope(s, rerun = true) {
    scope = s;
    document.querySelectorAll(".scope button").forEach(b => {
      b.classList.toggle("on", b.dataset.scope === s);
      b.setAttribute("aria-pressed", b.dataset.scope === s);
    });
    if (rerun && qInput.value.trim()) go(true);
  }
  function go(replace) {
    const q = qInput.value.trim();
    if (!q) { if (location.hash.startsWith("#/search")) location.hash = "#/"; return; }
    const target = `#/search?q=${enc(q)}${scope !== "all" ? "&s=" + scope : ""}`;
    if (location.hash === target) return;
    if (replace && location.hash.startsWith("#/search")) { history.replaceState(null, "", target); route(); }
    else location.hash = target;
  }
  qInput.addEventListener("input", () => { clearTimeout(tmr); tmr = setTimeout(() => go(true), 90); });
  qInput.addEventListener("keydown", e => {
    if (e.key === "ArrowDown") { e.preventDefault(); moveSel(1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); moveSel(-1); }
    else if (e.key === "Enter") {
      e.preventDefault(); clearTimeout(tmr);
      const lis = document.querySelectorAll("#results li a");
      if (sel >= 0 && lis[sel]) { location.hash = lis[sel].getAttribute("href"); qInput.blur(); return; }
      if (window.__direct && location.hash.startsWith("#/search")) { location.hash = href(window.__direct[0], window.__direct[1]); qInput.blur(); return; }
      go(false);
    } else if (e.key === "Escape") { qInput.value = ""; qInput.blur(); }
  });
  document.querySelectorAll(".scope button").forEach(b => b.onclick = () => setScope(b.dataset.scope));
  document.addEventListener("keydown", e => {
    if (e.key === "/" && document.activeElement !== qInput && !/input|textarea/i.test(document.activeElement.tagName)) {
      e.preventDefault(); qInput.focus(); qInput.select();
    }
  });
  document.addEventListener("click", e => {
    const b = e.target.closest("[data-copy]");
    if (!b) return;
    const t = b.dataset.copy;
    // The page is served over HTTPS (or file://), so the async Clipboard API is the only path.
    // A denied or missing clipboard shows "Copy failed" on the button instead of a prompt().
    const report = ok => {
      const msg = ok ? "Copied" : "Copy failed";
      if (!b.dataset.label) b.dataset.label = b.textContent;
      b.textContent = msg;
      announce.textContent = ok ? `Copied ${t}` : msg;
      clearTimeout(b._t);
      b._t = setTimeout(() => { b.textContent = b.dataset.label; announce.textContent = ""; }, 1500);
    };
    Promise.resolve().then(() => navigator.clipboard.writeText(t)).then(() => report(true), () => report(false));
  });
  const announce = $("#announce");

  renderTree("ccl");
  route();
})();
