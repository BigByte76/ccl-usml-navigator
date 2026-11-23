# CCL / USML Navigator

A fast, static website for navigating the **EAR Commerce Control List** (15 CFR Part 774, Supp. No. 1) and the
**ITAR U.S. Munitions List** (22 CFR § 121.1). You can drill down to the final paragraph-level classification, or search
keywords across both lists.

## Run it

Open `site/index.html` in a browser. It needs no server and no internet connection.

To host it, copy the `site/` folder to any static web host (GitHub Pages, S3, an intranet share). You can also serve it locally:

```sh
cd site && python3 -m http.server 8000   # then open http://localhost:8000
```

## Features

- **Drill down** for the CCL goes Category → Product Group (A–E) → ECCN → `a.` → `a.1.` → `a.1.a.` …, down to the last
  sub-paragraph. For the USML it goes Category → `(a)` → `(1)` → `(i)` → `(A)`.
- **Classification path.** Every paragraph page shows the chain of parent paragraphs (for example
  3A001 → .b → .b.2 → .b.2.a), so the leaf is read in context. Leaf pages are marked *Final classification level*
  and have a copy button.
- **ECCN details:** reasons for control (shown as chips), the license requirements table, list-based license
  exceptions, related controls, notes, and the full text of every sub-paragraph.
- **Badges** mark USML SME (`*`) paragraphs, 600-series and 515-series ECCNs, "subject to the ITAR" cross-reference
  entries, and reserved paragraphs.
- **Search** runs instantly as you type (a few ms). It matches all words (AND), and it also supports
  `"exact phrase"`, `-exclude`, and the CCL / USML / All scope buttons. Search terms are highlighted on the page you
  open from a result.
- **Jump to a code:** typing `3A001.a.1`, `XI(a)(3)` or `Category XV` gives a *Go to* result. Press Enter to open it.
- **Cross-references:** ECCN mentions (`0A501.c`) and USML references (`Category XII(c)`) in the text are links.
- Related provisions are included: § 774.1, CCL Supplements 2–7 and § 121.0.
- A side tree, keyboard shortcuts (`/` to search, ↑ ↓ Enter), dark mode, mobile layout and print styles.

## Data and refreshing it

`scripts/build_data.py` downloads and parses the regulations from the eCFR Versioner API:

| Source | Used for |
|---|---|
| `structure/<date>/title-15.json`, `title-22.json` | Regulatory hierarchy and breadcrumbs (Title › Chapter › Subchapter › Part › Supplement/Section) |
| `full/<date>/title-15.xml?part=774` | Full text of the CCL, parsed into the drill-down tree |
| `full/<date>/title-22.xml?part=121` | Full text of the USML, parsed into the drill-down tree |

The structure JSON stops at "Supplement No. 1 to Part 774" and "§ 121.1". It has no ECCNs or USML paragraphs, so
the full-text XML for those two nodes supplies everything below that level.

```sh
python3 scripts/build_data.py                        # default date 2026-11-19 (uses cached downloads)
python3 scripts/build_data.py --date 2026-12-15 --refresh
```

Raw downloads are cached in `data/raw/`. The build writes `site/data/{ccl,usml}.json`, plus `.js` copies so the page
works from `file://`. It then prints counts (as of 2026-11-19: 637 ECCNs / 4,479 CCL paragraphs; 21 USML
categories / 1,203 paragraphs).

### Parsing notes

- The CCL source is inconsistent in a few places, and the parser handles each case:
  - Some ECCNs have no `Items:` line.
  - Some put the first item inline (`Items: a. …`).
  - Some labels have a stray dot (`b.2.a..`).
  - Lettered lists inside "Related Controls", and table footnotes, reuse item letters. These are kept as text, not
    treated as items.
- About 10 sub-paragraphs (for example `4A004.z.1`) have no parent paragraph in the source. They are attached
  directly to their ECCN.
- USML roman numerals are told apart from letters (`(i)`, `(v)`, `(x)`) by context.
- ECCNs that are only cross-references to the ITAR (for example 9A005–9A011) have no item paragraphs by design.

## Disclaimer

This is a navigation aid, not legal advice. Confirm classifications against the official eCFR text and, where needed,
through a BIS commodity classification (CCATS) or a DDTC commodity jurisdiction (CJ) request.
