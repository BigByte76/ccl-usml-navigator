#!/usr/bin/env python3
"""
Build the data files for the EAR CCL / ITAR USML browser.

Sources (eCFR Versioner API):
  structure  https://www.ecfr.gov/api/versioner/v1/structure/<date>/title-15.json
             https://www.ecfr.gov/api/versioner/v1/structure/<date>/title-22.json
  full text  https://www.ecfr.gov/api/versioner/v1/full/<date>/title-15.xml?part=774
             https://www.ecfr.gov/api/versioner/v1/full/<date>/title-22.xml?part=121

The structure JSON only goes down to "Supplement No. 1 to Part 774" and
"§ 121.1", so it supplies the regulatory hierarchy (breadcrumbs, part/section
labels). The full-text XML for those two nodes is parsed into a drill-down
tree: Category > Product Group > ECCN > paragraph > sub-paragraph ... for the
CCL, and Category > (a) > (1) > (i) > (A) for the USML.

Usage:
  python3 scripts/build_data.py                 # date 2026-11-19, use cache
  python3 scripts/build_data.py --date 2026-12-01 --refresh
"""
import argparse
import gzip
import html
import json
import os
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw")
OUT = os.path.join(ROOT, "site", "data")
API = "https://www.ecfr.gov/api/versioner/v1"


# --------------------------------------------------------------------------- fetch
def fetch(url, dest, refresh):
    if os.path.exists(dest) and not refresh:
        return
    print("GET", url, file=sys.stderr)
    req = urllib.request.Request(url, headers={
        "Accept-Encoding": "gzip",          # the /full endpoint requires compression
        "User-Agent": "ccl-usml-browser-build/1.0",
    })
    with urllib.request.urlopen(req, timeout=180) as r:
        body = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            body = gzip.decompress(body)
    if body.lstrip()[:6] == b"<error":
        raise SystemExit(f"eCFR error for {url}:\n{body.decode()[:500]}")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "wb") as f:
        f.write(body)


# --------------------------------------------------------------------------- helpers
def norm_ws(s):
    return re.sub(r"\s+", " ", s or "").strip()


def text_of(el):
    return norm_ws("".join(el.itertext()))


INLINE = {"I": "i", "B": "b", "SU": "sup", "BR": "br"}
E_MAP = {"01": "i", "02": "b", "03": "i", "04": "b", "05": "b", "51": "sub", "52": "sub", "54": "sub"}
BLOCK_P = {"P", "FP", "FP-1", "FP-2", "FP1", "FP2", "FP-DASH", "PSPACE"}
DROP = {"XREF"}


def render(el, top=True):
    """Convert an eCFR XML element to safe HTML (all text escaped)."""
    tag = el.tag
    if tag in DROP:
        return html.escape(el.tail or "") if not top else ""
    inner = html.escape(el.text or "")
    for c in el:
        inner += render(c, top=False)
    if tag in BLOCK_P:
        out = f'<p class="{tag.lower()}">{inner.strip()}</p>'
    elif tag in INLINE:
        t = INLINE[tag]
        out = "<br>" if t == "br" else f"<{t}>{inner}</{t}>"
    elif tag == "br":
        out = "<br>"
    elif tag == "E":
        t = E_MAP.get(el.get("T", ""), "i")
        out = f"<{t}>{inner}</{t}>"
    elif tag == "NOTE":
        out = f'<div class="note">{inner}</div>'
    elif tag == "HED":
        out = f'<div class="note-h">{inner.strip()}</div>'
    elif tag in ("HD1", "HD2", "HD3", "HEAD"):
        out = f'<h4 class="{tag.lower()}">{inner.strip()}</h4>'
    elif tag in ("TABLE", "THEAD", "TBODY", "TFOOT", "TR"):
        out = f"<{tag.lower()}>{inner}</{tag.lower()}>"
    elif tag in ("TH", "TD"):
        attrs = ""
        for a in ("colspan", "rowspan"):
            if el.get(a):
                attrs += f' {a}="{int(el.get(a))}"'
        out = f"<{tag.lower()}{attrs}>{inner.strip()}</{tag.lower()}>"
    elif tag == "DIV" and el.get("class") == "gpotbl_div":
        out = f'<div class="tbl">{inner}</div>'
    elif tag == "CITA":
        out = f'<p class="cita">{inner.strip()}</p>'
    elif tag in ("AUTH", "SOURCE", "EDNOTE", "EFFDNOT", "EXTRACT"):
        out = f'<div class="{tag.lower()}">{inner}</div>'
    else:
        out = inner
    if not top:
        out += html.escape(el.tail or "")
    return out


def short_title(s, n=220):
    s = norm_ws(s)
    return s if len(s) <= n else s[: n - 1].rsplit(" ", 1)[0] + "…"


class Node(dict):
    """i=id, c=code, t=title, h=html, k=children, p=post-children html, y=type, s=SME flag"""

    def __init__(self, id, code, title, typ, html_=""):
        super().__init__(i=id, c=code, t=title, y=typ)
        if html_:
            self["h"] = html_

    def add(self, child):
        self.setdefault("k", []).append(child)
        return child

    def append_html(self, h, post=False):
        key = "p" if post else "h"
        self[key] = self.get(key, "") + h


class Ids:
    def __init__(self):
        self.seen = set()

    def make(self, base):
        i, n = base, 2
        while i in self.seen:
            i = f"{base}~{n}"
            n += 1
        self.seen.add(i)
        return i


# --------------------------------------------------------------------------- structure JSON
def find_path(node, pred, path=()):
    path = path + (node,)
    if pred(node):
        return path
    for c in node.get("children") or []:
        r = find_path(c, pred, path)
        if r:
            return r
    return None


def crumbs(path):
    return [{"label": n.get("label_level") or n.get("label"), "desc": n.get("label_description", ""),
             "type": n.get("type"), "id": n.get("identifier")} for n in path]


# --------------------------------------------------------------------------- CCL
ECCN_RE = re.compile(r"^(\d[A-E]\d{3}|EAR99)\b\s*(.*)$", re.S)
CAT_RE = re.compile(r"^Category (\d+)\s*[—-]\s*(.*)$")
PART_RE = re.compile(r"^Part (\d)\s*[—-]\s*(.*)$")
GROUP_RE = re.compile(r"^([A-E])\.\s*(.*)$")
SUBGRP_RE = re.compile(r"^(I{1,3})\.\s*(.*)$")
ITEM_RE = re.compile(r"^([a-z](?:\.[0-9a-z]+)*)\.*(?:\s|$)")
GROUP_NAMES = {"A": "Systems, Equipment and Components", "B": "Test, Inspection and Production Equipment",
               "C": "Materials", "D": "Software", "E": "Technology"}


def valid_ccl_label(lab):
    parts = lab.split(".")
    for n, p in enumerate(parts):
        if n % 2 == 0 and not re.fullmatch(r"[a-z]", p):
            return False
        if n % 2 == 1 and not re.fullmatch(r"\d+", p):
            return False
    return True


def note_target(hed_text, eccn_code):
    """Return ('eccn', None) | ('item', label) | (None, None) from a note heading."""
    t = hed_text.replace("“", "").replace("”", "")
    m = re.search(r"\bto (?:paragraphs? |ECCN |entry )?(?:(\d[A-E]\d{3}))?((?:\.|\b)[a-z](?:\.[0-9a-z]+)*)?", t)
    if not m:
        return (None, None)
    code, lab = m.group(1), m.group(2)
    if code and code != eccn_code:
        return (None, None)
    if lab:
        lab = lab.lstrip(".")
        if valid_ccl_label(lab):
            return ("item", lab)
    if code:
        return ("eccn", None)
    if re.search(r"\bto this (entry|ECCN)\b", t):
        return ("eccn", None)
    return (None, None)


def parse_ccl(supp_el, ids):
    root = Node("ccl", "CCL", "Commerce Control List", "root")
    cat = part = group = subgrp = eccn = None
    holder = None            # node receiving loose content
    items = {}               # label -> node, within current ECCN
    last_item = None
    in_items = False
    seen_list = False

    def container():
        return subgrp or group or part or cat or root

    def is_eccn_head(e):
        return (e.tag in ("FP-2", "FP-1", "FP") and len(e) and e[0].tag == "B"
                and not (e.text or "").strip() and ECCN_RE.match(text_of(e)))

    # Look ahead: does each ECCN have an explicit "Items:" line?
    kids = list(supp_el)
    has_marker, cur = {}, None
    for n, e in enumerate(kids):
        if is_eccn_head(e):
            cur = n
            has_marker[cur] = False
        elif cur is not None and re.match(r"^Items:", text_of(e)):
            has_marker[cur] = True
    marker_expected = False

    for n, el in enumerate(kids):
        tag = el.tag
        if tag in ("HEAD", "XREF", "CITA"):
            continue
        txt = text_of(el)

        if tag == "HD1":
            m = CAT_RE.match(txt)
            if m:
                cat = root.add(Node(ids.make(f"C{m.group(1)}"), f"Category {m.group(1)}", m.group(2), "category"))
                part = group = subgrp = eccn = None
                holder = cat
                continue
            m = PART_RE.match(txt)
            if m and cat:
                part = cat.add(Node(ids.make(f"{cat['i']}P{m.group(1)}"),
                                    f"{cat['c']} Part {m.group(1)}", m.group(2), "part"))
                group = subgrp = eccn = None
                holder = part
                continue
            m = GROUP_RE.match(txt)
            if m and cat:
                catnum = cat["i"][1:]
                gcode = f"{catnum}{m.group(1)}"
                gid = gcode + (f"-P{part['i'][-1]}" if part else "")
                title = re.sub(r"[“”]", "", m.group(2))
                group = (part or cat).add(Node(ids.make(gid), gcode, title, "group"))
                subgrp = eccn = None
                holder = group
                continue
            m = SUBGRP_RE.match(txt)
            if m and group:
                subgrp = group.add(Node(ids.make(f"{group['i']}-{m.group(1)}"),
                                        f"{group['c']} {m.group(1)}", m.group(2).title()
                                        if m.group(2).isupper() else m.group(2), "subgroup"))
                eccn = None
                holder = subgrp
                continue
            # Other headings (Annex to Category 1, Special Conditions for STA, ...)
            if eccn is not None:
                eccn.append_html(render(el))   # heading inside an entry: keep as entry content
                continue
            base = (cat["i"] if cat else "ccl") + "-" + re.sub(r"[^A-Za-z0-9]+", "-", txt)[:40].strip("-")
            info = (cat or root).add(Node(ids.make(base), txt, "", "info"))
            group = subgrp = eccn = None
            holder = info
            continue

        if tag in ("FP-2", "FP-1", "FP") and len(el) and el[0].tag == "B" and not (el.text or "").strip():
            m = ECCN_RE.match(txt)
            if m and cat:
                code, title = m.group(1), m.group(2)
                if code == "EAR99":
                    eccn = None
                    holder = cat.add(Node(ids.make(f"{cat['i']}-EAR99"), "EAR99", title, "info"))
                    subgrp = group = None
                    continue
                eccn = container().add(Node(ids.make(code), code, short_title(title, 400), "eccn"))
                if "[Reserved]" in title:
                    eccn["r"] = 1
                holder = eccn
                items, last_item, in_items, seen_list = {}, None, False, False
                marker_expected = has_marker.get(n, False)
                continue

        h = render(el)
        if eccn is not None:
            if re.match(r"^List of Items Controlled", txt):
                seen_list = True
            if not in_items and re.match(r"^Items:", txt):
                in_items = True
                rest = re.sub(r"^Items:\s*", "", txt)
                m = ITEM_RE.match(rest)
                if rest and m and valid_ccl_label(m.group(1)):
                    # "Items: a. Filament winding machines ..." -> first item inline
                    eccn.append_html('<p class="fp"><i>Items:</i></p>')
                    txt = rest
                    h = re.sub(r"^(<p[^>]*>)\s*<i>Items:</i>\s*", r"\1", h)
                    tag = "P"
                else:
                    eccn.append_html(h)
                    continue
            if tag == "P" and seen_list and not marker_expected and not in_items and ITEM_RE.match(txt) and valid_ccl_label(ITEM_RE.match(txt).group(1)):
                in_items = True   # some entries omit the "Items:" line
            if in_items and tag in ("P", "FP", "FP-1"):
                m = ITEM_RE.match(txt)
                if m and valid_ccl_label(m.group(1)) and m.group(1) not in items:
                    lab = m.group(1)
                    parent = eccn
                    pl = lab.split(".")[:-1]
                    while pl:
                        if ".".join(pl) in items:
                            parent = items[".".join(pl)]
                            break
                        pl = pl[:-1]
                    node = parent.add(Node(ids.make(f"{eccn['c']}.{lab}"), f"{eccn['c']}.{lab}",
                                           short_title(txt[m.end():]) or txt, "item", h))
                    if "[Reserved]" in txt:
                        node["r"] = 1
                    items[lab] = node
                    last_item = node
                    continue
            if in_items and tag == "NOTE":
                hed = el.find("HED")
                kind, lab = note_target(text_of(hed) if hed is not None else "", eccn["c"])
                if kind == "eccn":
                    eccn.append_html(h, post=True)
                    continue
                if kind == "item" and lab in items:
                    items[lab].append_html(h)
                    continue
            if in_items and last_item is not None:
                last_item.append_html(h)
            else:
                eccn.append_html(h)
            continue

        (holder or root).append_html(h)
    return root


# --------------------------------------------------------------------------- USML
def _roman(n):
    out = ""
    for v, r in ((50, "l"), (40, "xl"), (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i")):
        while n >= v:
            out, n = out + r, n - v
    return out


ROMAN = [_roman(n) for n in range(1, 80)]
USML_CAT_RE = re.compile(r"^Category ([IVXL]+)\s*[—-]\s*(.*)$")
USML_LAB_RE = re.compile(r"^(\*\s*)?\(([a-zA-Z]+|\d+)\)(?:\s*[-–]\s*\(([a-zA-Z]+|\d+)\))?\s*")


def nxt_letter(c):
    return chr(ord(c) + 1) if c else "a"


def parse_usml(extract_el, ids):
    root = Node("usml", "USML", "United States Munitions List", "root")
    cat = None
    stack = []        # list of (level, label, node)
    last_txt = ""
    last_node = None

    def classify(lab):
        cur = {lvl: l for lvl, l, _ in stack}
        if lab.isdigit():
            return 2
        if lab.isupper():
            return 4
        is_letter = len(lab) == 1
        is_roman = lab in ROMAN
        if is_roman and not is_letter:
            return 3
        if is_letter and not is_roman:
            return 1
        # ambiguous: i, v, x
        if lab == "i":
            # first roman item follows an introductory "...as follows:" paragraph
            return 3 if stack and last_txt.rstrip().endswith((":", "—")) else 1
        r = cur.get(3)
        exp_roman = ROMAN[ROMAN.index(r) + 1] if r in ROMAN else None
        return 3 if lab == exp_roman else 1

    def code_of(node_labels):
        return "".join(f"({l})" for l in node_labels)

    for el in extract_el:
        tag = el.tag
        txt = text_of(el)
        if tag == "HD1":
            m = USML_CAT_RE.match(txt)
            if m:
                cat = root.add(Node(ids.make(m.group(1)), f"Category {m.group(1)}", m.group(2).strip(), "category"))
                stack, last_node, last_txt = [], None, ""
                continue
        h = render(el)
        if cat is None:
            root.append_html(h)
            continue
        if tag == "P":
            m = USML_LAB_RE.match(txt)
            if m:
                lab = m.group(2)
                lvl = classify(lab)
                while stack and stack[-1][0] >= lvl:
                    stack.pop()
                parent = stack[-1][2] if stack else cat
                labels = [l for _, l, _ in stack] + [lab]
                code = f"{cat['i']}{code_of(labels)}"
                node = parent.add(Node(ids.make(code), code, short_title(txt[m.end():]), "item", h))
                if m.group(1):
                    node["s"] = 1
                if "[Reserved]" in txt:
                    node["r"] = 1
                stack.append((lvl, lab, node))
                last_node, last_txt = node, txt
                continue
        if tag == "NOTE":
            hed = el.find("HED")
            ht = text_of(hed) if hed is not None else ""
            if re.search(r"\bto Category [IVXL]+\b", ht) or re.search(r"\bto this category\b", ht, re.I):
                cat.append_html(h, post=True)
                continue
            m = re.search(r"to paragraphs? ((?:\([a-zA-Z0-9]+\))+)", ht)
            if m:
                target = f"{cat['i']}{m.group(1)}"
                for _, _, n in reversed(stack):
                    if n["c"] == target:
                        n.append_html(h)
                        break
                else:
                    (last_node or cat).append_html(h)
                continue
        (last_node or cat).append_html(h)
    return root


# --------------------------------------------------------------------------- reference docs
def ref_node(el, ids, label, prefix):
    head = el.find("HEAD")
    title = text_of(head) if head is not None else label
    body = "".join(render(c) for c in el if c.tag not in ("HEAD", "XREF"))
    rid = ids.make(prefix + re.sub(r"[^A-Za-z0-9.]+", "-", el.get("N", label)))
    return Node(rid, el.get("N", label), title, "ref", body)


# --------------------------------------------------------------------------- definitions
def def_key(term):
    return re.sub(r"\s+", " ", re.sub(r"[“”\"‘’']", "", term)).strip().rstrip(".,:;").strip().lower()


def def_keys(term):
    """Lookup keys for a term: the term, and for 'Long Name (ABBR)' both parts."""
    keys = [def_key(term)]
    m = re.match(r"^(.*?)\s*\(([^)]+)\)\s*$", term)
    if m:
        keys += [def_key(m.group(1)), def_key(m.group(2))]
    return [k for i, k in enumerate(keys) if k and k not in keys[:i]]


def slug(s):
    return re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-")[:60] or "term"


def parse_ear_defs(x772, ids):
    """15 CFR 772.1: one paragraph per term, the term in italics at the start."""
    sec = next(e for e in x772.iter("DIV8") if e.get("N") == "772.1")
    root = Node(ids.make("DEFS"), "Definitions", "Part 772 — Definitions of Terms (15 CFR 772.1)", "defs")
    cur = None
    for el in sec:
        if el.tag in ("HEAD", "XREF", "CITA"):
            continue
        first = el[0] if len(el) else None
        is_term = (el.tag == "P" and first is not None and first.tag == "I" and not (el.text or "").strip()
                   and not re.match(r"^\s*(Note|N\.B|Technical)", text_of(first)))
        if is_term:
            term = norm_ws(text_of(first)).rstrip(".").strip().strip("“”\" ")
            rest = norm_ws(text_of(el))[len(norm_ws(text_of(first))):].strip()
            cur = root.add(Node(ids.make("D-" + slug(term)), term, short_title(rest, 300), "def", render(el)))
            cur["keys"] = def_keys(term)
            continue
        if cur is not None:
            cur.append_html(render(el))
        else:
            root.append_html(render(el))
    return root


# Section of 22 CFR Part 120 Subpart C -> extra phrases to link in USML text
ITAR_ALIASES = {
    "120.31": ["defense article", "defense articles"],
    "120.32": ["defense service", "defense services"],
    "120.33": ["technical data"],
    "120.34": ["public domain"],
    "120.36": ["significant military equipment"],
    "120.37": ["major defense equipment"],
    "120.39": ["foreign defense article", "foreign defense articles"],
    "120.41": ["specially designed"],
    "120.42": ["form, fit, function", "catch-all control", "enumerated"],
    "120.43": ["basic research", "applied research"],
    "120.50": ["export"],
    "120.51": ["reexport"],
    "120.52": ["retransfer"],
    "120.56": ["release"],
    "120.62": ["U.S. person", "U.S. persons"],
    "120.63": ["foreign person", "foreign persons"],
}
ITAR_LINKED = {"120.31", "120.32", "120.33", "120.34", "120.36", "120.37", "120.39", "120.41", "120.43", "120.62", "120.63"}


def parse_itar_defs(x120, ids):
    """22 CFR Part 120 Subpart C (§§ 120.30-120.69): one section per term or group of terms."""
    sub = next(e for e in x120.iter() if e.get("TYPE") == "SUBPART" and e.get("N") == "C")
    root = Node(ids.make("DEFS"), "Definitions", "Part 120 Subpart C — Definitions (22 CFR 120.30–120.69)", "defs")
    for sec in sub.iter("DIV8"):
        head = text_of(sec.find("HEAD"))
        m = re.match(r"^§\s*([\d.]+)\s+(.*?)\.?$", head)
        if not m or "[Reserved]" in head:
            continue
        num, term = m.group(1), m.group(2)
        body = "".join(render(c) for c in sec if c.tag not in ("HEAD", "XREF"))
        first = next((text_of(c) for c in sec if c.tag == "P"), "")
        n = root.add(Node(ids.make("D-" + num), term, short_title(f"§ {num}. " + re.sub(r"^\(a\)\s*", "", first), 300), "def", body))
        n["keys"] = def_keys(term)
        n["sec"] = num
        if num in ITAR_LINKED:
            n["a"] = ITAR_ALIASES.get(num, [])
    return root


def count(node, typ):
    return (1 if node.get("y") == typ else 0) + sum(count(c, typ) for c in node.get("k", []))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="2026-11-19")
    ap.add_argument("--refresh", action="store_true", help="re-download even if cached")
    a = ap.parse_args()
    d = a.date
    files = {
        "t15": (f"{API}/structure/{d}/title-15.json", f"title-15-{d}.json"),
        "t22": (f"{API}/structure/{d}/title-22.json", f"title-22-{d}.json"),
        "p774": (f"{API}/full/{d}/title-15.xml?part=774", f"part774-{d}.xml"),
        "p121": (f"{API}/full/{d}/title-22.xml?part=121", f"part121-{d}.xml"),
        "p772": (f"{API}/full/{d}/title-15.xml?part=772", f"part772-{d}.xml"),
        "p120": (f"{API}/full/{d}/title-22.xml?part=120", f"part120-{d}.xml"),
    }
    paths = {}
    for k, (url, fn) in files.items():
        paths[k] = os.path.join(RAW, fn)
        fetch(url, paths[k], a.refresh)

    t15 = json.load(open(paths["t15"]))
    t22 = json.load(open(paths["t22"]))
    p774 = find_path(t15, lambda n: n.get("type") == "part" and n.get("identifier") == "774")
    p121 = find_path(t22, lambda n: n.get("type") == "part" and n.get("identifier") == "121")
    if not p774 or not p121:
        raise SystemExit("Part 774 or Part 121 not found in structure JSON")
    ccl_path = find_path(p774[-1], lambda n: n.get("identifier") == "Supplement No. 1 to Part 774")
    usml_path = find_path(p121[-1], lambda n: n.get("identifier") == "121.1")

    # ---- CCL
    ids = Ids()
    x774 = ET.parse(paths["p774"]).getroot()
    supp1 = next(e for e in x774.iter("DIV9") if e.get("N") == "Supplement No. 1 to Part 774")
    ccl = parse_ccl(supp1, ids)
    refs = []
    for e in x774:
        if e.tag in ("DIV8", "DIV9") and e.get("N") != "Supplement No. 1 to Part 774":
            refs.append(ref_node(e, ids, e.get("N"), "R-"))
    ccl["refs"] = [parse_ear_defs(ET.parse(paths["p772"]).getroot(), ids)] + refs
    ccl["crumbs"] = crumbs(p774[:-1]) + crumbs(ccl_path)

    # ---- USML
    ids = Ids()
    x121 = ET.parse(paths["p121"]).getroot()
    s1211 = next(e for e in x121.iter("DIV8") if e.get("N") == "121.1")
    usml = parse_usml(s1211.find("EXTRACT"), ids)
    refs = []
    for e in x121.iter("DIV8"):
        if e.get("N") != "121.1":
            refs.append(ref_node(e, ids, e.get("N"), "R-"))
    usml["refs"] = [parse_itar_defs(ET.parse(paths["p120"]).getroot(), ids)] + refs
    usml["crumbs"] = crumbs(p121[:-1]) + crumbs(usml_path)

    meta = {
        "date": d,
        "sources": [u for u, _ in files.values()],
        "ccl": {"categories": count(ccl, "category"), "eccns": count(ccl, "eccn"), "items": count(ccl, "item")},
        "usml": {"categories": count(usml, "category"), "items": count(usml, "item")},
        "defs": {"ccl": count(ccl["refs"][0], "def"), "usml": count(usml["refs"][0], "def")},
    }
    ccl["meta"] = usml["meta"] = meta

    os.makedirs(OUT, exist_ok=True)
    for name, obj in (("ccl", ccl), ("usml", usml)):
        blob = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
        with open(os.path.join(OUT, f"{name}.json"), "w") as f:
            f.write(blob)
        # .js copy so index.html also works when opened directly from disk (file://)
        with open(os.path.join(OUT, f"{name}.js"), "w") as f:
            f.write(f"window.__DATA__=window.__DATA__||{{}};window.__DATA__.{name}={blob};\n")
    with open(os.path.join(OUT, "meta.json"), "w") as f:
        json.dump(meta, f, indent=1)
    print(json.dumps(meta, indent=1))


if __name__ == "__main__":
    main()
