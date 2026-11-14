"""Parser regressions found on the real vault."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import sync_certificates as sc  # noqa: E402
from test_sync_certificates import README, make_pdf, make_png, vault  # noqa: E402,F401


def test_wrapped_verify_url_is_rejoined():
    text = "Verify this certificate at:\nhttps://coursera.org/verify/professio\nnal-cert/KYDGIRH2F93K"
    assert sc.find_verify_url(text) == "https://coursera.org/verify/professional-cert/KYDGIRH2F93K"


def test_verify_url_does_not_swallow_following_prose():
    text = "Verify at:\nhttps://coursera.org/verify/3BRU6TFH81Y8\nCoursera has confirmed the identity"
    assert sc.find_verify_url(text) == "https://coursera.org/verify/3BRU6TFH81Y8"
    assert sc.find_verify_url("https://x.org/verify/abc\nParticipant") == "https://x.org/verify/abc"
    assert sc.find_verify_url("https://x.org/verify/abc and more\n/tail") == "https://x.org/verify/abc"
    assert sc.find_verify_url("no link") is None
    assert sc.find_verify_url("") is None


def test_filename_prefix_wins_over_pdf_text(tmp_path):
    make_pdf(
        tmp_path / "COURSERA - GOOGLE AI Fundamentals.pdf",
        ["12-Nov-2026", "AI Fundamentals",
         "an online course authorized by Google and offered through Coursera"],
    )
    rec = sc.scan(tmp_path)[0]
    assert rec["issuer"] == "Coursera"
    assert rec["title"] == "Google AI Fundamentals"
    assert rec["domain"] == "Artificial intelligence"
    assert rec["completed"] == "2026-11-12"


@pytest.mark.parametrize(
    "title,domain",
    [
        ("UNESCO Global MOOC on the Ethics of AI", "AI governance"),
        ("Google AI for Data Analysis", "Artificial intelligence"),
        ("AI capabilities and limitations", "Generative AI"),
        ("Fundamentals of Machine Learning and Artificial Intelligence", "Machine learning"),
        ("Maintaining a fair mindset", "Other"),
    ],
)
def test_domain_map_ai_titles(title, domain):
    assert sc.classify_domain(title) == domain


def test_hyphenated_day_month_year():
    assert sc.find_date("13-Nov-2026") == "2026-11-13"
    assert sc.find_date("31-Feb-2026") is None


def test_hidden_and_tooling_directories_are_skipped(vault):  # noqa: F811
    for d in (".venv", ".pytest_cache", "node_modules", "nested/.cache"):
        make_png(vault / d / "ignored.png")
    make_png(vault / "Udemy" / "docs" / "kept 2025-01-01.png")
    names = [Path(r["path"]).name for r in sc.scan(vault)]
    assert "ignored.png" not in names
    assert "kept 2025-01-01.png" in names


def test_status_block_tracks_latest_date(vault):  # noqa: F811
    text = (README + "\n## Maintenance status\n\n<!-- CERTS-STATUS:START -->\nold\n"
            "<!-- CERTS-STATUS:END -->\n")
    out = sc.render_readme(text, sc.scan(vault))
    assert "latest entry is dated 17 October 2026." in out
    assert "\nold\n" not in out
    assert "CERTS-STATUS" not in sc.render_readme(README, sc.scan(vault))
    assert sc.render_status_block([]) == "Active. The vault grows as courses complete."


def test_damaged_pdf_falls_back_to_filename(tmp_path):
    (tmp_path / "AWS - Broken File.pdf").write_bytes(b"%PDF-1.4 not a real pdf")
    rec = sc.scan(tmp_path)[0]
    assert rec["issuer"] == "AWS"
    assert rec["title"] == "Broken File"
    assert rec["completed"] is None
