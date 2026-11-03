"""Tests for scripts/sync_certificates.py."""
import hashlib
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import sync_certificates as sc  # noqa: E402

EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)


def make_pdf(path, lines, info=None):
    """Write a one-page PDF with the given text lines and optional info dict."""
    stream = "BT /F1 12 Tf 14 TL 40 700 Td " + " ".join(
        "(%s) Tj T*" % ln.replace("(", "[").replace(")", "]") for ln in lines
    ) + " ET"
    info_body = "<< " + " ".join("/%s (%s)" % kv for kv in (info or {}).items()) + " >>"
    objs = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        "/Resources << /Font << /F1 5 0 R >> >> >>",
        "<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream),
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        info_body,
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += ("%d 0 obj\n%s\nendobj\n" % (i, body)).encode("latin-1")
    xref = len(out)
    out += ("xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)).encode()
    for off in offsets:
        out += ("%010d 00000 n \n" % off).encode()
    out += (
        "trailer\n<< /Size %d /Root 1 0 R /Info 6 0 R >>\nstartxref\n%d\n%%%%EOF\n"
        % (len(objs) + 1, xref)
    ).encode()
    Path(path).write_bytes(out)


def make_png(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (4, 4), (10, 20, 30)).save(path)


@pytest.fixture
def vault(tmp_path):
    make_pdf(
        tmp_path / "AWS - Intro to Cloud.pdf",
        ["AWS Training & Certification", "Intro to Cloud", "Completed: October 17, 2026"],
    )
    make_pdf(
        tmp_path / "CLAUDE ACADEMY - Claude 101.pdf",
        ["Verify this badge at https://academy.claude.com/verify/abc123"],
        {
            "Title": "Claude 101: Claude Academy completion badge",
            "Creator": "Claude Academy",
            "CreationDate": "D:20261015120245Z",
        },
    )
    make_png(tmp_path / "Udemy" / "Python Basics 2024-03-05.png")
    return tmp_path


def by_name(records):
    return {Path(r["path"]).name: r for r in records}


def test_pdf_text_extraction(vault):
    rec = by_name(sc.scan(vault))["AWS - Intro to Cloud.pdf"]
    data = (vault / "AWS - Intro to Cloud.pdf").read_bytes()
    assert rec["issuer"] == "AWS"
    assert rec["title"] == "Intro to Cloud"
    assert rec["completed"] == "2026-10-17"
    assert rec["domain"] == "Cloud"
    assert rec["sha256"] == hashlib.sha256(data).hexdigest()
    assert rec["size"] == len(data)
    assert rec["path"] == "AWS - Intro to Cloud.pdf"


def test_pdf_metadata_and_verify_url(vault):
    rec = by_name(sc.scan(vault))["CLAUDE ACADEMY - Claude 101.pdf"]
    assert rec["issuer"] == "Claude Academy"
    assert rec["title"] == "Claude 101"
    assert rec["completed"] == "2026-10-15"
    assert rec["verify_url"] == "https://academy.claude.com/verify/abc123"


def test_image_uses_folder_and_filename(vault):
    rec = by_name(sc.scan(vault))["Python Basics 2024-03-05.png"]
    assert rec["issuer"] == "Udemy"
    assert rec["title"] == "Python Basics"
    assert rec["completed"] == "2024-03-05"
    assert rec["domain"] == "Programming"
    assert rec["path"] == "Udemy/Python Basics 2024-03-05.png"


def test_skipped_directories(vault):
    for d in ("docs", "assets", "scripts", "tests", ".github", ".git"):
        make_png(vault / d / "ignored.png")
    names = [Path(r["path"]).name for r in sc.scan(vault)]
    assert "ignored.png" not in names
    assert len(names) == 3


@pytest.mark.parametrize(
    "title,domain",
    [
        ("Fundamentals of Machine Learning", "Machine learning"),
        ("Introduction to Generative AI", "Generative AI"),
        ("Claude Code 101", "AI tooling"),
        ("SQL for Data Analysis", "Data"),
        ("Job Roles in the Cloud", "Cloud"),
        ("Responsive Web Design", "Web"),
        ("Python Programming", "Programming"),
        ("Network Security Basics", "Security"),
        ("Pottery", "Other"),
    ],
)
def test_domain_map(title, domain):
    assert sc.classify_domain(title) == domain


def test_date_formats():
    assert sc.find_date("Completed: October 17, 2026") == "2026-10-17"
    assert sc.find_date("Issued 5 Mar 2024") == "2024-03-05"
    assert sc.find_date("2023-01-09") == "2023-01-09"
    assert sc.find_date("no date here") is None


def test_overrides_merge_and_keep_orphans(vault):
    target = by_name(sc.scan(vault))["AWS - Intro to Cloud.pdf"]
    docs = vault / "docs"
    docs.mkdir()
    ov = {
        target["sha256"]: {"title": "Fixed title", "domain": "Security"},
        "f" * 64: {"title": "Orphan"},
    }
    ov_path = docs / "certificates-overrides.json"
    ov_path.write_text(json.dumps(ov), encoding="utf-8")
    before = ov_path.read_bytes()
    assert sc.main(["--root", str(vault)]) == 0
    index = json.loads((docs / "certificates-index.json").read_text(encoding="utf-8"))
    rec = {c["path"]: c for c in index["certificates"]}["AWS - Intro to Cloud.pdf"]
    assert rec["title"] == "Fixed title"
    assert rec["domain"] == "Security"
    assert ov_path.read_bytes() == before


def test_index_is_stable_and_dated_on_change(vault):
    idx = sc.build_index(sc.scan(vault), {}, previous=None, today="2026-11-02")
    assert idx["schema_version"] == 1
    assert idx["generated"] == "2026-11-02"
    assert idx["summary"]["total"] == 3
    again = sc.build_index(sc.scan(vault), {}, previous=idx, today="2030-01-01")
    assert again == idx
    make_png(vault / "Udemy" / "Extra 2025-01-01.png")
    changed = sc.build_index(sc.scan(vault), {}, previous=idx, today="2030-01-01")
    assert changed["generated"] == "2030-01-01"
    assert changed["summary"]["total"] == 4


def test_svg_valid_animated_and_counts(vault):
    svg = sc.render_svg(sc.scan(vault))
    root = ET.fromstring(svg)
    assert root.tag.endswith("svg")
    assert "prefers-reduced-motion" in svg
    assert EM_DASH not in svg and EN_DASH not in svg
    assert "AWS" in svg and "Claude Academy" in svg
    assert "Cloud" in svg


def test_svg_empty_vault_is_valid():
    ET.fromstring(sc.render_svg([]))


README = (
    "# Title\n\n## Overview\n\nIntro text.\n\n## Features\n\nKeep me.\n\n"
    "## Usage\n\nTail text.\n"
)


def test_readme_adds_markers_and_keeps_rest(vault):
    recs = sc.scan(vault)
    out = sc.render_readme(README, recs)
    for m in ("CERTS:START", "CERTS:END", "CERTS-COUNT:START", "CERTS-COUNT:END"):
        assert "<!-- %s -->" % m in out
    assert "Intro text." in out and "Keep me." in out and "Tail text." in out
    assert "It holds 3 documents from 3 issuers" in out
    assert "| 1 |" in out and "[PDF](./AWS%20-%20Intro%20to%20Cloud.pdf)" in out
    assert sc.render_readme(out, recs) == out


def test_readme_replaces_only_marked_blocks(vault):
    recs = sc.scan(vault)
    first = sc.render_readme(README, recs)
    make_png(vault / "Udemy" / "Extra 2025-01-01.png")
    second = sc.render_readme(first, sc.scan(vault))
    assert "It holds 4 documents" in second
    assert second.count("<!-- CERTS:START -->") == 1
    assert "Keep me." in second


def test_check_and_dry_run(vault):
    (vault / "README.md").write_text(README, encoding="utf-8")
    assert sc.main(["--root", str(vault), "--check"]) == 1
    assert not (vault / "docs" / "certificates-index.json").exists()
    assert sc.main(["--root", str(vault), "--dry-run"]) == 0
    assert not (vault / "docs" / "certificates-index.json").exists()
    assert (vault / "README.md").read_text(encoding="utf-8") == README
    assert sc.main(["--root", str(vault)]) == 0
    assert (vault / "docs" / "certificates-index.json").exists()
    assert (vault / "assets" / "architecture.svg").exists()
    assert "<!-- CERTS:START -->" in (vault / "README.md").read_text(encoding="utf-8")
    assert sc.main(["--root", str(vault), "--check"]) == 0
