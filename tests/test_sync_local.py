"""Tests for scripts/sync_local.py against a throwaway repository and bare remote."""
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import sync_local as sl  # noqa: E402
from test_sync_certificates import make_pdf  # noqa: E402


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                          text=True).stdout


@pytest.fixture
def repo(tmp_path):
    remote = tmp_path / "remote.git"
    work = tmp_path / "work"
    git(tmp_path, "init", "--bare", "--initial-branch=main", str(remote))
    git(tmp_path, "init", "--initial-branch=main", str(work))
    for key, value in (("user.name", "Test"), ("user.email", "test@example.invalid"),
                       ("commit.gpgsign", "false"), ("core.autocrlf", "false")):
        git(work, "config", key, value)
    git(work, "remote", "add", "origin", str(remote))
    (work / "README.md").write_text("# Vault\n\n## Overview\n\n## Features\n", encoding="utf-8")
    make_pdf(work / "AWS - Intro to Cloud.pdf", ["Intro to Cloud", "Completed: October 17, 2026"])
    git(work, "add", "--", "README.md", "AWS - Intro to Cloud.pdf")
    git(work, "commit", "-m", "init")
    git(work, "push", "origin", "HEAD:refs/heads/main")
    assert sl.main(["--root", str(work), "--yes"]) == 0  # commit the first generated outputs
    return work


def last_message(work):
    return git(work, "log", "-1", "--format=%B")


def test_detects_add_modify_and_rename(repo):
    make_pdf(repo / "AWS - New One.pdf", ["New One", "Completed: October 18, 2026"])
    make_pdf(repo / "COURSERA - Second.pdf", ["Second", "Completed: October 19, 2026"])
    changes = sl.detect(repo)
    assert changes.added == ["AWS - New One.pdf", "COURSERA - Second.pdf"]
    assert not (changes.modified or changes.renamed or changes.deleted)
    assert sl.main(["--root", str(repo), "--yes"]) == 0

    make_pdf(repo / "AWS - New One.pdf", ["New One", "Completed: October 20, 2026"])
    (repo / "COURSERA - Second.pdf").rename(repo / "COURSERA - Second Course.pdf")
    (repo / "notes.txt").write_text("not a certificate", encoding="utf-8")
    changes = sl.detect(repo)
    assert changes.added == []
    assert changes.modified == ["AWS - New One.pdf"]
    assert changes.renamed == [("COURSERA - Second.pdf", "COURSERA - Second Course.pdf")]
    assert changes.deleted == []


def test_commit_message_and_push(repo):
    make_pdf(repo / "AWS - New One.pdf", ["New One", "Completed: October 18, 2026"])
    assert sl.main(["--root", str(repo), "--yes"]) == 0
    msg = last_message(repo)
    assert msg.splitlines()[0] == "feat(certs): add 1 certificate"
    assert "A  AWS - New One.pdf" in msg
    assert "G  README.md" in msg
    assert "Index total: 2" in msg
    assert "Co-Authored-By" not in msg
    assert git(repo, "rev-parse", "HEAD") == git(repo, "rev-parse", "origin/main")
    assert git(repo, "status", "--porcelain") == ""
    assert "New One" in (repo / "README.md").read_text(encoding="utf-8")


def test_rename_is_one_commit_with_history(repo):
    (repo / "AWS - Intro to Cloud.pdf").rename(repo / "AWS - Introduction to Cloud.pdf")
    assert sl.main(["--root", str(repo), "--yes"]) == 0
    msg = last_message(repo)
    assert msg.splitlines()[0] == "chore(certs): rename 1 certificate"
    assert "R  AWS - Intro to Cloud.pdf -> AWS - Introduction to Cloud.pdf" in msg
    status = git(repo, "show", "--name-status", "-M", "--format=", "HEAD")
    assert "R100\tAWS - Intro to Cloud.pdf\tAWS - Introduction to Cloud.pdf" in status


def test_dry_run_changes_nothing(repo, capsys):
    make_pdf(repo / "AWS - New One.pdf", ["New One", "Completed: October 18, 2026"])
    head = git(repo, "rev-parse", "HEAD")
    readme = (repo / "README.md").read_bytes()
    assert sl.main(["--root", str(repo), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "feat(certs): add 1 certificate" in out and "Dry run" in out
    assert "G  README.md" in out
    assert git(repo, "rev-parse", "HEAD") == head
    assert (repo / "README.md").read_bytes() == readme
    assert git(repo, "diff", "--cached", "--name-only") == ""


def test_no_push_and_unrelated_files_stay_out(repo):
    make_pdf(repo / "AWS - New One.pdf", ["New One", "Completed: October 18, 2026"])
    (repo / "notes.txt").write_text("private", encoding="utf-8")
    git(repo, "add", "--", "notes.txt")  # staged by the user, must not ride along
    assert sl.main(["--root", str(repo), "--yes", "--no-push"]) == 0
    files = git(repo, "show", "--name-only", "--format=", "HEAD").split("\n")
    assert "notes.txt" not in files and "AWS - New One.pdf" in files
    assert git(repo, "rev-list", "--count", "origin/main..HEAD").strip() == "1"


def test_deletions_need_a_flag(repo, capsys):
    (repo / "AWS - Intro to Cloud.pdf").unlink()
    assert sl.main(["--root", str(repo), "--yes"]) == 0
    assert "skip removed file" in capsys.readouterr().out
    assert "AWS - Intro to Cloud.pdf" in git(repo, "ls-files")
    assert sl.main(["--root", str(repo), "--yes", "--include-deletions"]) == 0
    assert "AWS - Intro to Cloud.pdf" not in git(repo, "ls-files")
    assert "D  AWS - Intro to Cloud.pdf" in last_message(repo)


def test_rebases_onto_remote_before_commit(repo, tmp_path):
    other = tmp_path / "other"
    git(tmp_path, "clone", str(tmp_path / "remote.git"), str(other))
    for key, value in (("user.name", "Test"), ("user.email", "test@example.invalid")):
        git(other, "config", key, value)
    (other / "LICENSE").write_text("All rights reserved.\n", encoding="utf-8")
    git(other, "add", "--", "LICENSE")
    git(other, "commit", "-m", "docs: add licence")
    git(other, "push", "origin", "HEAD:refs/heads/main")
    make_pdf(repo / "AWS - New One.pdf", ["New One", "Completed: October 18, 2026"])
    assert sl.main(["--root", str(repo), "--yes"]) == 0
    assert (repo / "LICENSE").exists()
    assert git(repo, "rev-parse", "HEAD") == git(repo, "rev-parse", "origin/main")


def test_refuses_other_branch_and_unconfirmed(repo, capsys):
    make_pdf(repo / "AWS - New One.pdf", ["New One", "Completed: October 18, 2026"])
    head = git(repo, "rev-parse", "HEAD")
    assert sl.main(["--root", str(repo)]) == 2  # stdin is not a terminal under pytest
    assert git(repo, "rev-parse", "HEAD") == head
    git(repo, "checkout", "-q", "-b", "feature")
    assert sl.main(["--root", str(repo), "--yes"]) == 1
    assert "Switch to main" in capsys.readouterr().err


def test_nothing_to_sync(repo, capsys):
    assert sl.main(["--root", str(repo), "--yes"]) == 0
    assert "Nothing to sync." in capsys.readouterr().out


def test_message_is_deterministic_and_bounded():
    changes = sl.Changes(added=["b.pdf", "a.pdf"], modified=["m.pdf"],
                         renamed=[("o.pdf", "n.pdf")], deleted=["d.pdf"])
    first = sl.build_message(changes, 9, ["README.md"])
    assert first == sl.build_message(changes, 9, ["README.md"])
    assert len(first.splitlines()[0]) <= sl.SUBJECT_LIMIT
    assert first.splitlines()[0] == "feat(certs): add 2, update 1, rename 1, remove 1"
    assert sl.build_message(sl.Changes(), 3, ["README.md"]).startswith(
        "chore(certs): refresh index\n")


def test_push_failure_exits_non_zero(repo, tmp_path, capsys):
    make_pdf(repo / "AWS - New One.pdf", ["New One", "Completed: October 18, 2026"])
    hook = tmp_path / "remote.git" / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)
    assert sl.main(["--root", str(repo), "--yes"]) == 1
    assert "push" in capsys.readouterr().err


def test_rebase_conflict_aborts_cleanly(repo, tmp_path, capsys):
    other = tmp_path / "other"
    git(tmp_path, "clone", str(tmp_path / "remote.git"), str(other))
    for key, value in (("user.name", "Test"), ("user.email", "test@example.invalid")):
        git(other, "config", key, value)
    (other / "clash.txt").write_text("remote\n", encoding="utf-8")
    git(other, "add", "--", "clash.txt")
    git(other, "commit", "-m", "remote clash")
    git(other, "push", "origin", "HEAD:refs/heads/main")
    (repo / "clash.txt").write_text("local\n", encoding="utf-8")
    git(repo, "add", "--", "clash.txt")
    git(repo, "commit", "-m", "local clash")
    head = git(repo, "rev-parse", "HEAD")
    assert sl.main(["--root", str(repo), "--yes"]) == 1
    assert "aborted" in capsys.readouterr().err
    git_dir = Path(git(repo, "rev-parse", "--absolute-git-dir").strip())
    assert not (git_dir / "rebase-merge").exists()
    assert not (git_dir / "rebase-apply").exists()
    assert git(repo, "rev-parse", "HEAD") == head


def test_refuses_mid_rebase(repo, capsys):
    git_dir = Path(git(repo, "rev-parse", "--absolute-git-dir").strip())
    (git_dir / "rebase-merge").mkdir()
    assert sl.main(["--root", str(repo), "--yes"]) == 1
    assert "in progress" in capsys.readouterr().err
