#!/usr/bin/env python3
"""
Build site/data/dsgl.js — the Australian Defence and Strategic Goods List 2024.

Source: Federal Register of Legislation, F2024L01024 (as made, 16 Aug 2024; commenced 1 Sep 2024)
  page      https://www.legislation.gov.au/F2024L01024/asmade/text
  full text https://www.legislation.gov.au/F2024L01024/asmade/2024-08-16/text/original/epub/OEBPS/document_1/document_1.html

The Word-exported HTML marks depth with paragraph classes, but not reliably (notes use item
classes and vice versa), so the tree is rebuilt from the labels themselves:
  * absolute codes ("3. A. 001. a. 2. a.", "ML1. b.") set the position exactly;
  * relative labels ("a.", "1.") alternate letter/number by level, so each one is either the
    first child of the current paragraph or the next sibling of one of its ancestors.

Usage:  python3 scripts/build_dsgl.py [--refresh]
"""
import argparse
import gzip
import html
import json
import os
import re
import sys
import urllib.request
from html.parser import HTMLParser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_data import Node, Ids, short_title, def_keys, slug  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw", "dsgl")
OUT = os.path.join(ROOT, "site", "data")
PAGE = "https://www.legislation.gov.au/F2024L01024/asmade/text"
DOC = ("https://www.legislation.gov.au/F2024L01024/asmade/2024-08-16/text/original/"
       "epub/OEBPS/document_1/document_1.html")


def fetch(url, dest, refresh):
    if os.path.exists(dest) and not refresh:
        return
    print("GET", url, file=sys.stderr)
    req = urllib.request.Request(url, headers={"Accept-Encoding": "gzip", "User-Agent": "Mozilla/5.0 (dsgl-browser-build)"})
    with urllib.request.urlopen(req, timeout=180) as r:
        body = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            body = gzip.decompress(body)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "wb") as f:
        f.write(body)


# --------------------------------------------------------------------------- mini DOM
VOID = {"br", "img", "meta", "link", "hr", "input", "col"}


class El:
    __slots__ = ("tag", "attrs", "kids", "parent")

    def __init__(self, tag, attrs, parent):
        self.tag, self.attrs, self.kids, self.parent = tag, dict(attrs), [], parent


class Dom(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = El("root", {}, None)
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        el = El(tag, attrs, self.cur)
        self.cur.kids.append(el)
        if tag not in VOID:
            self.cur = el

    def handle_startendtag(self, tag, attrs):
        self.cur.kids.append(El(tag, attrs, self.cur))

    def handle_endtag(self, tag):
        c = self.cur
        while c is not self.root and c.tag != tag:
            c = c.parent
        if c is not self.root:
            self.cur = c.parent

    def handle_data(self, data):
        self.cur.kids.append(data)


def text(el):
    if isinstance(el, str):
        return el
    if el.tag == "br":
        return " "
    return "".join(text(k) for k in el.kids)


def norm(s):
    return re.sub(r"\s+", " ", s.replace("\xa0", " ").replace("‑", "-")).strip()


def inline(el):
    """Escaped HTML keeping sup/sub/bold/italic."""
    if isinstance(el, str):
        return html.escape(el.replace("\xa0", " ").replace("‑", "-"))
    if el.tag == "br":
        return "<br>"
    if el.tag == "img":
        return '<span class="fig">[figure — see official text]</span>'
    inner = "".join(inline(k) for k in el.kids)
    st = el.attrs.get("style", "") or ""
    if el.tag in ("sup",) or "vertical-align:super" in st:
        inner = f"<sup>{inner}</sup>"
    elif el.tag in ("sub",) or "vertical-align:sub" in st:
        inner = f"<sub>{inner}</sub>"
    if el.tag in ("b", "strong") or "font-weight:bold" in st:
        inner = f"<b>{inner}</b>"
    if el.tag in ("i", "em") or "font-style:italic" in st:
        inner = f"<i>{inner}</i>"
    return inner


def blocks(el):
    """Flatten the body into p / heading / table / li blocks in document order."""
    for k in el.kids:
        if isinstance(k, str):
            continue
        if k.tag in ("p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "table"):
            yield k
        else:
            yield from blocks(k)


def render_table(t):
    rows = []
    for tr in iter_tag(t, "tr"):
        cells = []
        for td in [c for c in tr.kids if not isinstance(c, str) and c.tag in ("td", "th")]:
            ps = [inline(p).strip() for p in blocks(td)] or [inline(td).strip()]
            span = f' colspan="{int(td.attrs["colspan"])}"' if td.attrs.get("colspan", "").isdigit() else ""
            cells.append(f"<td{span}>{'<br>'.join(x for x in ps if x)}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return f'<div class="tbl"><table>{"".join(rows)}</table></div>'


def iter_tag(el, tag):
    for k in el.kids:
        if isinstance(k, str):
            continue
        if k.tag == tag:
            yield k
        else:
            yield from iter_tag(k, tag)


# --------------------------------------------------------------------------- labels
DU_ABS = re.compile(r"^(\d)(?:\.\s*|\s+)([A-E])(?:\.\s*|\s+)(\d{3})(?:\.|(?=\s))((?:\s*(?:[a-z]|\d{1,2})\.(?!\d))*)\s*")
ML_ABS = re.compile(r"^ML\s?(\d{1,3})\.((?:\s*(?:[a-z]|\d{1,2})\.(?!\d))*)\s*")
GROUP = re.compile(r"^(\d)\.\s*([A-E])(?:\.\s*|\s+)(?:(\d)\.?\s+)?([A-Z][a-z“\"].*)$")
GROUP_NAMES = {"A": "Systems, Equipment and Components", "B": "Test, Inspection and Production Equipment",
               "C": "Materials", "D": "Software", "E": "Technology"}
CAT5_PARTS = {"1": "Telecommunications", "2": "\u201cInformation security\u201d"}
REL = re.compile(r"^([a-z]|\d{1,2})\.(?!\d)\s*((?:(?:[a-z]|\d{1,2})\.(?!\d)\s*)*)")
NOTEISH = re.compile(r"^(Note|N\.\s?B\.|NB|Technical Note|Technical Notes|Technical note|Nota|Notes)\b", re.I)


def labs(s):
    return re.findall(r"([a-z]|\d{1,2})\.", s or "")


def is_letter(l):
    return l.isalpha()


def succ(l):
    return chr(ord(l) + 1) if is_letter(l) else str(int(l) + 1)


def first_of(depth, num_first=False):
    return "a" if (depth % 2 == 0) != num_first else "1"


# --------------------------------------------------------------------------- parse
def parse(dom, ids):
    body = next(iter_tag(dom.root, "body"))
    bl = list(blocks(body))

    root = Node("dsgl", "DSGL", "Defence and Strategic Goods List 2024", "root")
    refs = []
    part1 = Node(ids.make("ML"), "Part 1", "Munitions list", "part")
    part2 = Node(ids.make("DU"), "Part 2", "Dual-use list", "part")
    root.add(part1)
    root.add(part2)

    section = None            # current top-level region
    ref = None                # current reference node (preliminary parts, sensitive lists)
    cat = grp = entry = None
    path, nodes = [], {}      # within entry: label path -> node
    last = None               # node receiving loose content
    note_open = False         # inside a note's own a./b./1. list
    note_stack = []           # label paths of open note lists (innermost last)

    def note_fit(lab, more):
        """Place a label in the innermost open note list it fits; True if it fits one."""
        for k in range(len(note_stack) - 1, -1, -1):
            np_ = place(note_stack[k], lab, False, True)
            if np_ is not None:
                del note_stack[k + 1:]
                note_stack[k] = np_ + labs(more)
                return True
        return False

    def place(cur, lab, nf, is_note):
        """Where does relative label `lab` go, given current label path `cur`? None if nowhere."""
        if not cur:
            if is_note:
                return [lab] if lab in ("a", "1") else None
            return [lab] if lab == first_of(0, nf) or lab == "a" else None
        if lab == first_of(len(cur), nf if not is_note else not is_letter(cur[0])):
            return cur + [lab]
        for d in range(len(cur) - 1, -1, -1):
            if succ(cur[d]) == lab:
                return cur[:d] + [lab]
        return None

    cur_part = [None]

    def make_group(catnum, letter, partnum, title):
        holder = cat
        if partnum and catnum == "5":
            pid = f"C5P{partnum}"
            holder = next((k for k in cat.get("k", []) if k["i"] == pid), None)
            if holder is None:
                holder = cat.add(Node(ids.make(pid), f"Category 5 Part {partnum}", CAT5_PARTS.get(partnum, ""), "part"))
            cur_part[0] = partnum
        elif catnum == "5" and cur_part[0]:
            holder = next(k for k in cat["k"] if k["i"] == f"C5P{cur_part[0]}")
        code = f"{catnum}{letter}"
        existing = next((k for k in holder.get("k", []) if k["y"] == "group" and k["c"] == code), None)
        if existing is not None:
            return existing
        gid = code + (f"-P{partnum or cur_part[0]}" if catnum == "5" and (partnum or cur_part[0]) else "")
        return holder.add(Node(ids.make(gid), code, title, "group"))

    def entry_code():
        return entry["c"]

    def add_item(lpath, body_html, title_txt):
        nonlocal last, path
        parent = entry
        for d in range(len(lpath) - 1, 0, -1):
            key = ".".join(lpath[:d])
            if key in nodes:
                parent = nodes[key]
                break
        code = entry_code() + "." + ".".join(lpath)
        n = parent.add(Node(ids.make(code), code, short_title(title_txt) or "", "item", body_html))
        if re.match(r"^(Not used|\[Reserved\])", title_txt):
            n["r"] = 1
        nodes[".".join(lpath)] = n
        path = list(lpath)
        last = n
        return n

    for b in bl:
        cls = b.attrs.get("class", "") or ""
        if b.tag == "table":
            h = render_table(b)
            (last or ref or entry or grp or cat or root).append_html(h)
            continue
        raw = norm(text(b))
        if not raw:
            continue
        h_inline = inline(b).strip()
        auto = li_label(b)
        if auto:
            # Word auto-numbered list: the label exists only as list numbering
            raw = f"{auto}. {raw}"
            h_inline = f"{auto}. {h_inline}"

        # ---- big headings
        if cls.startswith("TOC") or cls in ("Header",):
            continue
        if cls.startswith("ActHead"):
            if raw.startswith("Part 1A"):
                section = "pre"; ref = None; continue
            if raw.startswith("Part 1—") or raw.startswith("Part 1 —"):
                section = "ml"; ref = None; entry = None; last = part1; continue
            if raw.startswith("Part 2"):
                section = "du"; ref = None; entry = None; last = part2; continue
            m = re.match(r"^Category (\d)\s*[—-]\s*(.*)$", raw)
            if m and section == "du":
                cat = part2.add(Node(ids.make(f"C{m.group(1)}"), f"Category {m.group(1)}", m.group(2), "category"))
                grp = entry = None; last = cat; continue
            if raw.startswith("Sensitive list") or raw.startswith("Very sensitive list"):
                section = "ref"
                ref = Node(ids.make("R-" + ("VSL" if raw.startswith("Very") else "SL")),
                           "VSL" if raw.startswith("Very") else "SL", raw, "ref")
                refs.append(ref); entry = None; last = ref; continue
            if raw.startswith("Schedule 1"):
                section = "end"; ref = None; continue
            if section == "pre" and cls in ("ActHead3",):
                ref = Node(ids.make("R-" + re.sub(r"[^A-Za-z0-9]+", "-", raw.split("—")[0]).strip("-")),
                           raw.split("—")[0].strip(), raw, "ref")
                if raw.startswith("Division 4"):
                    ref.update(y="defs", c="Definitions", t="Division 4 — Definitions (DSGL 2024)")
                refs.append(ref); last = ref; continue
            if ref is not None:
                ref.append_html(f'<h4>{html.escape(raw)}</h4>'); continue
            continue
        if section in (None, "end"):
            continue
        if section == "pre" and ref is not None and ref["y"] == "defs":
            # Definitions: one "Definition" paragraph per term: “Term” (categories) means ...
            dm = re.match(r'^[“"](.+?)[”"]\s*(\(([^)]*)\))?\s*', raw)
            if cls == "Definition" and dm:
                term = dm.group(1).strip()
                d = ref.add(Node(ids.make("D-" + slug(term)), term, short_title(raw[dm.end():].lstrip(",;: "), 300), "def",
                                 f'<p class="p">{h_inline}</p>'))
                d["keys"] = def_keys(term)
                if dm.group(3):
                    d["cats"] = dm.group(3)
                continue
            target = (ref.get("k") or [None])[-1] or ref
            target.append_html(f'<p class="{"note" if "note" in cls.lower() else "p"}">{h_inline}</p>')
            continue
        if section in ("pre", "ref"):
            if ref is not None:
                ref.append_html(f'<p class="{ "note" if "Note" in cls else "p"}">{h_inline}</p>')
            continue

        noteish = bool(NOTEISH.match(raw)) or any(k in cls for k in ("Note", "NB", "Tech", "Table", "Definition"))

        # ---- dual-use group heading "3. A. Systems, Equipment and Components"
        if section == "du":
            m = GROUP.match(raw)
            if m and not DU_ABS.match(raw) and cat is not None and len(raw) < 90 and cat["i"] == f"C{m.group(1)}":
                grp = make_group(m.group(1), m.group(2), m.group(3), m.group(4).strip())
                entry = None; last = grp; note_open = False; continue
            m = DU_ABS.match(raw)
            if m and not noteish:
                code = f"{m.group(1)}{m.group(2)}{m.group(3)}"
                ls = labs(m.group(4))
                rest = raw[m.end():]
                if entry is None or entry["c"] != code:
                    if cat is None or cat["i"] != f"C{code[0]}":
                        continue
                    if grp is None or grp["c"] != code[:2]:
                        # heading missing or not recognisable in the source: create the group
                        grp = make_group(code[0], code[1], cur_part[0], GROUP_NAMES[code[1]])
                    entry = grp.add(Node(ids.make(code), code, short_title(rest, 400), "eccn",
                                         f'<p class="head">{html.escape(rest)}</p>' if not ls else ""))
                    nodes, path, last, note_open = {}, [], entry, False
                    note_stack.clear()
                    if not ls:
                        if re.match(r"^(Not used|\[Reserved\])", rest):
                            entry["r"] = 1
                        continue
                if ls:
                    add_item(ls, f'<p class="item">{strip_label(h_inline, raw[:m.end()])}</p>', rest)
                    note_open = False; note_stack.clear()
                else:
                    note_open = False; note_stack.clear()
                continue
        else:  # munitions list
            m = ML_ABS.match(raw)
            if m and not noteish:
                code = f"ML{int(m.group(1))}"
                ls = labs(m.group(2))
                rest = raw[m.end():]
                if (note_open and entry is not None and len(ls) == 1 and note_stack and note_stack[-1]
                        and succ(note_stack[-1][-1]) == ls[0] and note_fit(ls[0], "")):
                    # source typo: a note's list item printed with a full code, e.g. "ML910. e. tranquilliser guns"
                    last.append_html(f'<p class="note-li">{ls[0]}. {strip_label(h_inline, raw[:m.end()])}</p>')
                    continue
                if entry is None or entry["c"] != code:
                    entry = part1.add(Node(ids.make(code), code, short_title(rest, 400), "eccn",
                                           f'<p class="head">{html.escape(rest)}</p>' if not ls else ""))
                    if re.match(r"^(Not used|\[Reserved\])", rest):
                        entry["r"] = 1
                    nodes, path, last, note_open = {}, [], entry, False
                    note_stack.clear()
                    if not ls:
                        continue
                if ls:
                    add_item(ls, f'<p class="item">{strip_label(h_inline, raw[:m.end()])}</p>', rest)
                    note_open = False; note_stack.clear()
                continue

        if entry is None:
            (last or grp or cat or root).append_html(f'<p class="{"note" if noteish else "p"}">{h_inline}</p>')
            continue

        # ---- relative label inside an entry
        m = REL.match(raw)
        if m and noteish and note_open:
            # labelled paragraph styled as a note: part of an open note's list
            note_fit(m.group(1), m.group(2))
            last.append_html(f'<p class="note-li">{h_inline}</p>')
            continue
        if m and not noteish:
            lab = m.group(1)
            if note_open:
                if note_fit(lab, m.group(2)):
                    last.append_html(f'<p class="note-li">{h_inline}</p>')
                    continue
                note_open = False                  # label does not fit any open note list: back to items
                note_stack.clear()
            nf = entry.get("_nf", False)
            if not path and not nodes and lab == "1":
                entry["_nf"] = nf = True          # e.g. 1C350.1, 1C350.2 ...
            target = place(path, lab, nf, False)
            if target is not None:
                extra = labs(m.group(2))            # stacked labels, e.g. "2. a. Voltage rating ..."
                add_item(target + extra, f'<p class="item">{strip_label(h_inline, m.group(0))}</p>', raw[m.end():])
                continue
            # unplaceable label: keep as text
            last.append_html(f'<p class="p">{h_inline}</p>')
            continue

        # ---- notes and other text
        if NOTEISH.match(raw):
            # a note that introduces a list ("... does not apply to the following:") opens note mode
            opens = raw.rstrip().endswith(":") or bool(re.search(r"following\W*$|as follows\W*$", raw))
            if re.match(r"^Notes?\b", raw) or not note_open:
                note_stack.clear()                 # a new numbered note replaces any open ones
            if opens:
                note_stack.append([])              # technical notes / N.B.s nest inside an open note
            note_open = bool(note_stack)
            last.append_html(f'<p class="note">{h_inline}</p>')
        elif noteish:
            last.append_html(f'<p class="note">{h_inline}</p>')
        else:
            last.append_html(f'<p class="{"note" if note_open else "p"}">{h_inline}</p>')

    # wrap consecutive note paragraphs into note boxes for display
    def tidy(n):
        for key in ("h", "p"):
            if key in n:
                n[key] = re.sub(r'((?:<p class="note(?:-li)?">.*?</p>)+)', r'<div class="note">\1</div>', n[key])
        for k in n.get("k", []):
            tidy(k)
    def clean(n):
        n.pop("_nf", None)
        for k in n.get("k", []):
            clean(k)
    clean(root)
    tidy(root)
    for r in refs:
        tidy(r)
    return root, refs


def li_label(b):
    """Label implied by an <li> in an auto-numbered <ol> ('a', '1', ...), or None."""
    par = b.parent
    if b.tag != "li" or par is None or par.tag != "ol":
        return None
    sibs = [k for k in par.kids if not isinstance(k, str) and k.tag == "li"]
    n = sibs.index(b) + int(par.attrs.get("start", "1") or 1)
    style = (par.attrs.get("style", "") or "") + " " + (par.attrs.get("type", "") or "")
    if "lower-latin" in style or "lower-alpha" in style or " a" == style[-2:]:
        return chr(96 + n) if n <= 26 else None
    if "roman" in style or "upper" in style or "disc" in style or "bullet" in style:
        return None
    return str(n)


def strip_label(h_inline, label_text):
    """Remove the leading label (e.g. '3. A. 001. a.' or 'b.') from inline HTML."""
    want = re.sub(r"\s+", "", label_text)
    out, i, got = h_inline, 0, ""
    # walk characters of the html, skipping tags, until the label's non-space chars are consumed
    while i < len(out) and len(got) < len(want):
        if out[i] == "<":
            j = out.find(">", i)
            i = j + 1 if j >= 0 else len(out)
            continue
        if not out[i].isspace():
            got += out[i]
        i += 1
    rest = out[i:]
    return rest.lstrip()


def count(node, typ):
    return (1 if node.get("y") == typ else 0) + sum(count(c, typ) for c in node.get("k", []))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    a = ap.parse_args()
    dest = os.path.join(RAW, "document_1.html")
    fetch(DOC, dest, a.refresh)
    dom = Dom()
    dom.feed(open(dest, encoding="utf-8").read())
    ids = Ids()
    root, refs = parse(dom, ids)
    root["refs"] = refs
    root["crumbs"] = [{"label": "Defence and Strategic Goods List 2024", "desc": "F2024L01024 (as made)", "type": "instrument"}]
    meta = {
        "instrument": "Defence and Strategic Goods List 2024 (F2024L01024)",
        "version": "As made 2024-08-16; commenced 2024-09-01",
        "sources": [PAGE, DOC],
        "ml": count(root["k"][0], "eccn"),
        "du_categories": count(root["k"][1], "category"),
        "du_entries": count(root["k"][1], "eccn"),
        "items": count(root, "item"),
        "defs": sum(count(r, "def") for r in refs),
    }
    # Codes on the Sensitive / Very Sensitive Lists (first cell of each table row)
    for r in refs:
        if r["c"] in ("SL", "VSL"):
            codes = re.findall(r"<tr><td[^>]*>\s*(?:<[^>]+>)*\s*(\d[A-E]\d{3}(?:\.[a-z0-9]{1,2})*)", r.get("h", ""))
            meta[r["c"].lower()] = sorted(set(c.rstrip(".") for c in codes))
    if "All of Category 0" in next((r.get("h", "") for r in refs if r["c"] == "VSL"), ""):
        meta["vsl_cat0"] = True
    root["meta"] = meta
    blob = json.dumps(root, ensure_ascii=False, separators=(",", ":"))
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "dsgl.json"), "w") as f:
        f.write(blob)
    with open(os.path.join(OUT, "dsgl.js"), "w") as f:
        f.write(f"window.__DATA__=window.__DATA__||{{}};window.__DATA__.dsgl={blob};\n")
    print(json.dumps(meta, indent=1))


if __name__ == "__main__":
    main()
