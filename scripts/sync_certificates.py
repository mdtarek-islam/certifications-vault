#!/usr/bin/env python3
"""Index the certificates in this repository.

Outputs:
  docs/certificates-index.json   machine-readable index
  assets/architecture.svg        animated taxonomy (domains, issuers, counts)
  README.md                      tables between the CERTS and CERTS-COUNT markers

Manual fixes go in docs/certificates-overrides.json, keyed by file sha256.
The script reads that file and never writes it.

Usage: python scripts/sync_certificates.py [--check] [--dry-run] [--root PATH]
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import quote
from xml.sax.saxutils import escape

SCHEMA_VERSION = 1
SKIP_DIRS = {".git", ".github", "docs", "assets", "scripts", "tests"}
EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp"}
OVERRIDE_FIELDS = ("title", "issuer", "domain", "completed", "verify_url")

# Colour tokens. The repo has no DESIGN.md, so these mirror the original diagram.
TOKENS = {
    "bg": "#0d1117",
    "surface": "#161b22",
    "border": "#30363d",
    "text": "#e6edf3",
    "muted": "#8b949e",
    "accent": "#58a6ff",
    "ok": "#3fb950",
}

ISSUER_PATTERNS = [
    ("Claude Academy", r"claude\s+academy"),
    ("AWS", r"(?-i:\bAWS\b)|amazon\s+web\s+services"),
    ("DeepLearning.AI", r"deeplearning\.ai"),
    ("Coursera", r"\bcoursera\b"),
    ("Udemy", r"\budemy\b"),
    ("Google", r"\bgoogle\b"),
    ("Microsoft", r"\bmicrosoft\b"),
    ("IBM", r"\bIBM\b"),
    ("HackerRank", r"\bhackerrank\b"),
]

# Order matters: the first domain with a matching keyword wins.
DOMAIN_KEYWORDS = [
    ("Machine learning", ["machine learning", "deep learning", "neural", "tensorflow",
                          "pytorch", "scikit", "reinforcement"]),
    ("Generative AI", ["generative", "prompt", "llm", "ai fluency", "ai capabilities",
                       "chatgpt", "gpt"]),
    ("AI tooling", ["claude", "copilot", "mcp", "langchain"]),
    ("Data", ["data", "sql", "analytics", "pandas", "statistics", "power bi", "tableau"]),
    ("Cloud", ["cloud", "aws", "azure", "gcp", "kubernetes", "docker", "devops",
               "billing", "serverless"]),
    ("Web", ["web", "html", "css", "javascript", "react", "frontend", "front-end", "node"]),
    ("Programming", ["python", "java", "c++", "programming", "algorithm", "software",
                     "coding"]),
    ("Security", ["security", "cyber", "ethical hacking", "penetration", "cissp"]),
]

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
MON = r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?"
DATE_RES = [
    ("iso", re.compile(r"(?<!\d)((?:19|20)\d\d)[-/._](\d{2})[-/._](\d{2})(?!\d)")),
    ("mdy", re.compile(r"\b" + MON + r"\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", re.I)),
    ("dmy", re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+" + MON + r",?\s+(\d{4})\b", re.I)),
]
DATE_STRIP_RE = re.compile(r"[\s._-]*(?:19|20)\d\d[-._]\d{2}[-._]\d{2}[\s._-]*$")
VERIFY_RE = re.compile(r"https?://[^\s)>\"']*verify[^\s)>\"']*", re.I)
DATE_HINT_RE = re.compile(r"complet|issued|awarded|date", re.I)


def _make_date(y, m, d):
    try:
        return dt.date(int(y), int(m), int(d))
    except ValueError:
        return None


def find_dates(text):
    """Return (position, ISO date) pairs found in text."""
    found = []
    for kind, rx in DATE_RES:
        for m in rx.finditer(text):
            g = m.groups()
            if kind == "iso":
                d = _make_date(g[0], g[1], g[2])
            elif kind == "mdy":
                d = _make_date(g[2], MONTHS[g[0][:3].lower()], g[1])
            else:
                d = _make_date(g[2], MONTHS[g[1][:3].lower()], g[0])
            if d:
                found.append((m.start(), d.isoformat()))
    return sorted(found)


def find_date(text):
    """Prefer a date on a line that mentions completion, else the first date."""
    if not text:
        return None
    for line in text.splitlines():
        if DATE_HINT_RE.search(line):
            hits = find_dates(line)
            if hits:
                return hits[0][1]
    hits = find_dates(text)
    return hits[0][1] if hits else None


def detect_issuer(text):
    """Return the canonical issuer whose name appears earliest in text."""
    best = None
    for name, pat in ISSUER_PATTERNS:
        m = re.search(pat, text or "", re.I)
        if m and (best is None or m.start() < best[0]):
            best = (m.start(), name)
    return best[1] if best else None


def classify_domain(title):
    low = (title or "").lower()
    for domain, words in DOMAIN_KEYWORDS:
        for w in words:
            if re.search(r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z0-9])", low):
                return domain
    return "Other"


def _clean_title(title):
    title = re.sub(r"\s+", " ", title or "").strip()
    title = re.sub(r"\s*[:\-]\s*[^:]*\bcompletion badge\s*$", "", title, flags=re.I)
    return title.replace(" - ", ": ").strip()


def _title_from_filename(stem):
    if " - " in stem:
        stem = stem.split(" - ", 1)[1]
    stem = DATE_STRIP_RE.sub("", stem.replace("_", " "))
    return _clean_title(stem)


def _issuer_from_name(path: Path, root: Path):
    stem = path.stem
    if " - " in stem:
        prefix = stem.split(" - ", 1)[0].strip()
        return detect_issuer(prefix) or (prefix.title() if prefix.isupper() else prefix)
    parent = path.parent
    if parent != root:
        return detect_issuer(parent.name) or parent.name
    return detect_issuer(stem)


def _pdf_date(raw):
    m = re.search(r"D:(\d{4})(\d{2})(\d{2})", str(raw or ""))
    d = _make_date(*m.groups()) if m else None
    return d.isoformat() if d else None


def _title_from_text(text, issuer_hit):
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    stop = next((i for i, ln in enumerate(lines)
                 if re.match(r"(completed|completion date|issued|date)\b", ln, re.I)), None)
    if stop is None:
        return None
    start = 1 if lines and detect_issuer(lines[0]) else 0
    block = lines[start:stop]
    if issuer_hit and not block:
        return None
    if not 1 <= len(block) <= 4 or sum(map(len, block)) > 120:
        return None
    return _clean_title(" ".join(block))


def _read_pdf(path):
    from pypdf import PdfReader
    try:
        reader = PdfReader(str(path))
        meta = reader.metadata or {}
        meta = {str(k): str(v) for k, v in dict(meta).items() if v}
        text = reader.pages[0].extract_text() if reader.pages else ""
    except Exception:  # damaged file: fall back to name conventions
        return {}, ""
    return meta, text or ""


def _exif_date(path):
    try:
        from PIL import Image
        with Image.open(path) as im:
            exif = im.getexif()
            raw = None
            try:
                raw = exif.get_ifd(0x8769).get(0x9003)
            except Exception:
                pass
            raw = raw or exif.get(0x9003) or exif.get(0x0132)
            return find_date(str(raw)) if raw else None
    except Exception:
        return None


def describe(path: Path, root: Path):
    rel = path.relative_to(root).as_posix()
    data = path.read_bytes()
    rec = {
        "path": rel,
        "sha256": hashlib.sha256(data).hexdigest(),
        "size": len(data),
    }
    title = issuer = completed = verify = None
    if path.suffix.lower() == ".pdf":
        meta, text = _read_pdf(path)
        meta_text = " ".join(meta.get(k, "") for k in ("/Producer", "/Creator", "/Author",
                                                         "/Subject", "/Title"))
        issuer = detect_issuer(meta_text) or detect_issuer(text)
        title = _clean_title(meta.get("/Title", ""))
        if not title or title.lower() == "untitled":
            title = _title_from_text(text, issuer)
        completed = find_date(text) or _pdf_date(meta.get("/CreationDate"))
        m = VERIFY_RE.search(text)
        verify = m.group(0).rstrip(".,") if m else None
    else:
        completed = _exif_date(path)
    issuer = issuer or _issuer_from_name(path, root) or "Unknown"
    title = title or _title_from_filename(path.stem) or path.stem
    completed = completed or find_date(path.stem)
    rec.update(title=title, issuer=issuer, domain=classify_domain(title), completed=completed)
    if verify:
        rec["verify_url"] = verify
    return rec


def scan(root):
    root = Path(root)
    out = []
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if rel.parts[0] in SKIP_DIRS or not p.is_file():
            continue
        if p.suffix.lower() in EXTENSIONS:
            out.append(describe(p, root))
    return sort_records(out)


def sort_records(records):
    return sorted(records, key=lambda r: (r["issuer"].lower(), r["completed"] or "9999-99-99",
                                          r["title"].lower(), r["path"]))


def load_overrides(root):
    p = Path(root) / "docs" / "certificates-overrides.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def apply_overrides(records, overrides):
    merged = []
    for r in records:
        r = dict(r)
        for k, v in (overrides.get(r["sha256"]) or {}).items():
            if k in OVERRIDE_FIELDS:
                r[k] = v
        merged.append(r)
    return sort_records(merged)


def build_index(records, overrides, previous=None, today=None):
    records = apply_overrides(records, overrides)
    idx = {
        "schema_version": SCHEMA_VERSION,
        "summary": {
            "total": len(records),
            "by_issuer": dict(sorted(Counter(r["issuer"] for r in records).items())),
            "by_domain": dict(sorted(Counter(r["domain"] for r in records).items())),
        },
        "certificates": records,
    }
    if previous and {k: v for k, v in previous.items() if k != "generated"} == idx:
        idx["generated"] = previous["generated"]
    else:
        idx["generated"] = today or dt.date.today().isoformat()
    return idx


def dump_index(idx):
    return json.dumps(idx, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


# ---------- formatting helpers ----------

def _fmt(iso, with_year=True):
    d = dt.date.fromisoformat(iso)
    s = "%d %s" % (d.day, d.strftime("%b"))
    return s + (" %d" % d.year if with_year else "")


def short_range(dates):
    dates = sorted(set(d for d in dates if d))
    if not dates:
        return "Undated"
    a, b = dt.date.fromisoformat(dates[0]), dt.date.fromisoformat(dates[-1])
    if a == b:
        return _fmt(dates[0])
    if (a.year, a.month) == (b.year, b.month):
        return "%d to %s" % (a.day, _fmt(dates[-1]))
    if a.year == b.year:
        return "%s to %s" % (_fmt(dates[0], False), _fmt(dates[-1]))
    return "%s to %s" % (_fmt(dates[0]), _fmt(dates[-1]))


def long_range(dates):
    dates = sorted(set(d for d in dates if d))
    if not dates:
        return ""
    a, b = dt.date.fromisoformat(dates[0]), dt.date.fromisoformat(dates[-1])
    full = lambda d: "%d %s %d" % (d.day, d.strftime("%B"), d.year)
    if a == b:
        return ", completed on " + full(a)
    if (a.year, a.month) == (b.year, b.month):
        return ", completed between %d and %s" % (a.day, full(b))
    return ", completed between %s and %s" % (full(a), full(b))


def plural(n, word):
    return "%d %s" % (n, word if n == 1 else word + "s")


# ---------- README ----------

def render_count_block(records):
    n = len(records)
    issuers = sorted({r["issuer"] for r in records}, key=str.lower)
    dates = [r["completed"] for r in records]
    lines = ["It holds %s from %s%s." % (plural(n, "document"), plural(len(issuers), "issuer"),
                                         long_range(dates)), ""]
    lines += ["| Issuer | Documents | Completed |", "|---|---|---|"]
    for iss in issuers:
        rs = [r for r in records if r["issuer"] == iss]
        lines.append("| %s | %d | %s |" % (iss, len(rs), short_range([r["completed"] for r in rs])))
    return "\n".join(lines)


def render_cert_block(records):
    lines = ["| # | Title | Issuer | Domain | Completed | Document | Verify |",
             "|---|---|---|---|---|---|---|"]
    for i, r in enumerate(records, 1):
        verify = "[Verify](%s)" % r["verify_url"] if r.get("verify_url") else "See document"
        when = _fmt(r["completed"]) if r["completed"] else "Undated"
        label = Path(r["path"]).suffix.lstrip(".").upper()
        lines.append("| %d | %s | %s | %s | %s | [%s](./%s) | %s |" % (
            i, r["title"].replace("|", "/"), r["issuer"], r["domain"], when, label,
            quote(r["path"]), verify))
    return "\n".join(lines)


def _replace_block(text, tag, body, anchors):
    start, end = "<!-- %s:START -->" % tag, "<!-- %s:END -->" % tag
    block = "%s\n%s\n%s" % (start, body, end)
    rx = re.compile(re.escape(start) + r".*?" + re.escape(end), re.S)
    if rx.search(text):
        return rx.sub(lambda m: block, text, count=1)
    for heading in anchors:
        m = re.search(r"^" + re.escape(heading) + r"[ \t]*\n", text, re.M)
        if m:
            return text[:m.end()] + "\n" + block + "\n" + text[m.end():]
    return text.rstrip("\n") + "\n\n" + block + "\n"


def render_readme(text, records):
    eol_crlf = "\r\n" in text
    text = text.replace("\r\n", "\n")
    text = _replace_block(text, "CERTS-COUNT", render_count_block(records), ["## Overview"])
    text = _replace_block(text, "CERTS", render_cert_block(records),
                          ["### Certificate index", "## Features"])
    return text.replace("\n", "\r\n") if eol_crlf else text


# ---------- SVG ----------

def render_svg(records):
    t = TOKENS
    domains = Counter(r["domain"] for r in records)
    issuers = Counter(r["issuer"] for r in records)
    dom_order = sorted(domains, key=lambda d: (-domains[d], d))
    iss_order = sorted(issuers, key=lambda i: (-issuers[i], i))
    links = Counter((r["domain"], r["issuer"]) for r in records)

    top, dom_h, dom_gap, iss_gap = 96, 48, 22, 26
    incoming = {i: [d for d in dom_order if (d, i) in links] for i in iss_order}
    iss_h = {i: max(52, 22 * (len(incoming[i]) + 1)) for i in iss_order}
    dom_y = {d: top + k * (dom_h + dom_gap) for k, d in enumerate(dom_order)}
    iss_y, y = {}, top
    for i in iss_order:
        iss_y[i] = y
        y += iss_h[i] + iss_gap
    dom_end = top + len(dom_order) * (dom_h + dom_gap)
    height = max(dom_end, y, top + 80) + 24
    DX, DW, IX, IW, CX, CW = 24, 220, 380, 220, 730, 206

    n = len(records)
    desc = "%s from %s, grouped into %s." % (
        plural(n, "certificate"), plural(len(issuers), "issuer"), plural(len(domains), "domain"))
    out = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 %d" width="960" height="%d" '
        'role="img" aria-labelledby="t d">' % (height, height),
        "  <title id=\"t\">Certificate taxonomy</title>",
        "  <desc id=\"d\">%s</desc>" % escape(desc),
        "  <style>",
        '    text { font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif; fill: %s; }' % t["text"],
        "    .sec { fill: %s; font-size: 12px; }" % t["muted"],
        "    .name { font-size: 14px; font-weight: 600; }",
        "    .num { font-size: 12px; font-weight: 600; }",
        "    .node { fill: %s; stroke: %s; stroke-width: 1; }" % (t["surface"], t["border"]),
        "    .issuer { stroke: %s; }" % t["accent"],
        "    .count { stroke: %s; }" % t["ok"],
        "    .rail { fill: none; stroke: %s; stroke-width: 1.5; }" % t["border"],
        "    .pulse { fill: none; stroke-width: 2.5; stroke-linecap: square; "
        "stroke-dasharray: 12 300; animation: flow 3.6s linear infinite; }",
        "    .blue { stroke: %s; }" % t["accent"],
        "    .green { stroke: %s; }" % t["ok"],
        "    @keyframes flow { from { stroke-dashoffset: 12; } to { stroke-dashoffset: -100; } }",
        "    @media (prefers-reduced-motion: reduce) {",
        "      .pulse { animation: none; stroke-dasharray: none; opacity: 0.45; }",
        "    }",
        "  </style>",
        '  <rect width="960" height="%d" fill="%s"/>' % (height, t["bg"]),
        '  <text x="24" y="30" font-size="16" font-weight="600">Certificate taxonomy</text>',
        '  <text x="%d" y="72" class="sec">Domain</text>' % DX,
        '  <text x="%d" y="72" class="sec">Issuer</text>' % IX,
        '  <text x="%d" y="72" class="sec">Certificates</text>' % CX,
    ]
    if not records:
        out.append('  <text x="24" y="120" class="sec">No certificates found.</text>')
        out.append("</svg>")
        return "\n".join(out) + "\n"

    rails, pulses, nodes = [], [], []
    delay = 0.0
    for i in iss_order:
        for k, d in enumerate(incoming[i]):
            y1 = dom_y[d] + dom_h // 2
            y2 = iss_y[i] + int(iss_h[i] * (k + 1) / (len(incoming[i]) + 1))
            xm = DX + DW + 22 + (dom_order.index(d) % 8) * 9
            path = "M%d %d H%d V%d H%d" % (DX + DW, y1, xm, y2, IX)
            rails.append('  <path class="rail" d="%s"/>' % path)
            pulses.append('  <path class="pulse blue" pathLength="100" '
                          'style="animation-delay:%.1fs" d="%s"/>' % (delay, path))
            nodes.append('  <text x="%d" y="%d" text-anchor="end" class="num">%d</text>'
                         % (IX - 8, y2 - 5, links[(d, i)]))
            delay += 0.3
        yc = iss_y[i] + iss_h[i] // 2
        path = "M%d %d H%d" % (IX + IW, yc, CX)
        rails.append('  <path class="rail" d="%s"/>' % path)
        pulses.append('  <path class="pulse green" pathLength="100" '
                      'style="animation-delay:%.1fs" d="%s"/>' % (delay, path))
        delay += 0.3
    out += rails + pulses
    for d in dom_order:
        y1 = dom_y[d]
        out.append('  <g><title>%s: %s</title>' % (escape(d), plural(domains[d], "certificate")))
        out.append('    <rect class="node" x="%d" y="%d" width="%d" height="%d" rx="6"/>' % (DX, y1, DW, dom_h))
        out.append('    <text x="%d" y="%d" class="name">%s</text>' % (DX + 14, y1 + 29, escape(d)))
        out.append('    <text x="%d" y="%d" text-anchor="end" class="num">%d</text></g>' % (DX + DW - 14, y1 + 29, domains[d]))
    for i in iss_order:
        y1, h = iss_y[i], iss_h[i]
        out.append('  <g><title>%s: %s</title>' % (escape(i), plural(issuers[i], "certificate")))
        out.append('    <rect class="node issuer" x="%d" y="%d" width="%d" height="%d" rx="6"/>' % (IX, y1, IW, h))
        out.append('    <text x="%d" y="%d" text-anchor="middle" class="name">%s</text></g>'
                   % (IX + IW // 2 + 6, y1 + h // 2 + 5, escape(i)))
        out.append('  <rect class="node count" x="%d" y="%d" width="%d" height="%d" rx="6"/>'
                   % (CX, y1 + h // 2 - 20, CW, 40))
        out.append('  <text x="%d" y="%d" text-anchor="middle" class="name">%s</text>'
                   % (CX + CW // 2, y1 + h // 2 + 5, escape(plural(issuers[i], "certificate"))))
    out += nodes
    out.append("</svg>")
    return "\n".join(out) + "\n"


# ---------- driver ----------

def _read(path):
    return path.read_bytes().decode("utf-8") if path.exists() else None


def _same(a, b):
    return a is not None and a.replace("\r\n", "\n") == b.replace("\r\n", "\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    ap.add_argument("--check", action="store_true", help="exit 1 if outputs would change")
    ap.add_argument("--dry-run", action="store_true", help="report changes, write nothing")
    args = ap.parse_args(argv)
    root = Path(args.root)

    records = scan(root)
    overrides = load_overrides(root)
    index_path = root / "docs" / "certificates-index.json"
    prev_text = _read(index_path)
    previous = json.loads(prev_text) if prev_text else None
    idx = build_index(records, overrides, previous)
    final = idx["certificates"]

    outputs = {
        index_path: dump_index(idx),
        root / "assets" / "architecture.svg": render_svg(final),
    }
    readme = root / "README.md"
    if readme.exists():
        outputs[readme] = render_readme(_read(readme), final)

    changed = [p for p, text in outputs.items() if not _same(_read(p), text)]
    for p in changed:
        print("%s %s" % ("would change" if args.check or args.dry_run else "update",
                         p.relative_to(root).as_posix()))
    print("certificates found: %d" % len(final))
    if args.check:
        return 1 if changed else 0
    if args.dry_run:
        return 0
    for p in changed:
        p.parent.mkdir(parents=True, exist_ok=True)
        text = outputs[p]
        if p == readme and "\r\n" in (_read(p) or ""):
            text = text.replace("\r\n", "\n").replace("\n", "\r\n")
        with open(p, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
