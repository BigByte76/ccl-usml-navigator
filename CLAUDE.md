# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A static, dependency-free website for navigating three export-control lists: the EAR Commerce Control List
(CCL, 15 CFR 774 Supp. 1), the ITAR U.S. Munitions List (USML, 22 CFR 121.1) and the Australian Defence and
Strategic Goods List 2024 (DSGL, F2024L01024). Python scripts download and parse the regulations into JSON trees;
a single vanilla-JS page (`site/`) renders them. README.md documents features and parser quirks in detail.

## Commands

There is no package manager, build tool, linter or test suite. Python scripts use only the standard library.

```sh
python3 scripts/build_data.py                         # CCL + USML (default eCFR date 2026-11-19, cached downloads)
python3 scripts/build_data.py --date YYYY-MM-DD --refresh
python3 scripts/build_dsgl.py [--refresh]             # DSGL
cd site && python3 -m http.server 8000                # or just open site/index.html (works from file://)
```

Each build prints a counts summary (ECCNs, paragraphs, definitions). Compare it with the previous run, and the
figures in README.md, to catch parser regressions; there are no automated checks beyond that.

Raw downloads cache to `data/raw/` (gitignored); a missing file is fetched automatically. `data/raw/excluded/`
holds sources that were looked at but are not used.

## Architecture

**Pipeline:** source (eCFR XML/JSON, legislation.gov.au HTML) → `scripts/*.py` → `site/data/{ccl,usml,dsgl}.json`
plus identical `.js` copies (`window.__DATA__.<src> = {...}`). The page loads only the `.js` files via `<script>`
tags so it works without a server; the `.json` copies are committed for diffs but excluded from the Pages deploy.
Never hand-edit `site/data/`: change the parser and rebuild.

**Shared node schema** (defined by `Node` in `scripts/build_data.py`, reused by `build_dsgl.py` via import):
compact keys `i` id, `c` display code, `t` title, `y` type (`root`/`part`/`category`/`group`/`subgroup`/`eccn`/
`item`/`info`/`def`/`defs`/`ref`), `h` HTML before children, `p` HTML after children, `k` children, `s` USML SME
flag; `def` nodes also carry `keys` (lookup keys) and USML defs `a` (aliases to link in text). The root also has
`refs` (first entry is always the definitions node, then related provisions), `crumbs` and `meta`. IDs are made
unique per list by `Ids`, which appends `~2`, `~3`… to duplicates; the app strips that suffix when indexing codes.
`meta.json` is written only by `build_data.py`; DSGL metadata (including SL/VSL code lists scraped from its
tables) lives in `dsgl.js` under `meta`.

**Parsers:**
- `build_data.py` uses the eCFR structure JSON for breadcrumbs only (it stops at Supp. 1 / § 121.1) and parses the
  full-text XML below that. CCL items come from `a.1.b`-style labels; USML from `(a)(1)(i)(A)` labels, with roman
  numerals vs letters resolved by context.
- `build_dsgl.py` parses a Word-exported HTML file whose styles don't reliably encode depth, so it rebuilds the tree
  from the labels: absolute codes fix the position, relative labels alternate letter/number by level, and lettered
  lists inside Notes are kept inside the note.

**Front end** (`site/app.js`, one IIFE, sections marked `/* ---- name */`): on load it walks every tree to build
`byId`/`parentOf` maps per source, a `codeMap` (normalised code → nodes, used for "Go to" jumps and CCL↔DSGL
*Compare*), a flat `entries` array for search, and definition indexes. Text is rendered as stored HTML, then
post-processed to link cross-references (ECCNs, USML categories) and defined terms (quoted terms in CCL/DSGL; a
curated alias list for USML). Routing is hash-based: `#/<src>/<id>[?hl=terms]`, `#/search?q=…&s=<src>`, `#/` home.
The app needs `ccl` and `usml` data; `dsgl` is optional and adds itself to `SOURCES` when present.

**Deploy:** `.github/workflows/pages.yml` publishes `site/` (minus `data/*.json`) to GitHub Pages on pushes to
`main` that touch `site/`.
