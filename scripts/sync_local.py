#!/usr/bin/env python3
"""Commit and push certificate changes from this machine.

Steps, in order:
  1. Check the branch is main and no merge or rebase is in progress.
  2. Rebase onto origin/main, so the daily workflow commit never blocks the push.
  3. Detect added, modified, renamed and removed certificate files.
  4. Regenerate the index, the diagram and the README tables.
  5. Stage those paths by exact name, commit with a message built from the diff, push.

The message depends only on the set of changed paths, so the same diff always
gives the same message. The script calls no network service except the git remote.

Usage: python scripts/sync_local.py [--dry-run] [--no-push] [--include-deletions] [--yes]
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sync_certificates as sc  # noqa: E402

BRANCH = "main"
REMOTE = "origin"
GENERATED = ("README.md", "assets/architecture.svg", "docs/certificates-index.json")
SUBJECT_LIMIT = 72


class SyncError(RuntimeError):
    """A condition that stops the sync before any commit."""


@dataclass
class Changes:
    added: list[str] = field(default_factory=list)
    modified: list[str] = field(default_factory=list)
    renamed: list[tuple[str, str]] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)

    def any(self) -> bool:
        return bool(self.added or self.modified or self.renamed or self.deleted)


def git(root: Path, *args: str, check: bool = True) -> str:
    """Run git with an argument list (no shell) and return stdout."""
    proc = subprocess.run(
        ["git", "-c", "core.quotepath=off", *args],
        cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if check and proc.returncode != 0:
        raise SyncError("git %s failed: %s" % (" ".join(args[:2]), proc.stderr.strip()))
    return proc.stdout


def preflight(root: Path) -> None:
    branch = git(root, "rev-parse", "--abbrev-ref", "HEAD").strip()
    if branch != BRANCH:
        raise SyncError("Current branch is %s. Switch to %s first." % (branch, BRANCH))
    git_dir = Path(git(root, "rev-parse", "--absolute-git-dir").strip())
    for marker in ("MERGE_HEAD", "rebase-merge", "rebase-apply", "CHERRY_PICK_HEAD"):
        if (git_dir / marker).exists():
            raise SyncError("A merge or rebase is in progress. Finish it first.")


def detect(root: Path) -> Changes:
    """Classify certificate changes in the work tree against HEAD.

    A rename is a removed path and a new path with the same blob hash. The match
    is exact, so the result never depends on a similarity threshold.
    """
    raw = git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    entries = [e for e in raw.split("\0") if e]
    added, modified, deleted = [], [], []
    skip_next = False
    for entry in entries:
        if skip_next:  # second half of an index rename record: the old path
            skip_next = False
            if sc.is_certificate(entry):
                deleted.append(entry)
            continue
        code, path = entry[:2], entry[3:]
        if code[0] in "RC":
            skip_next = True
        if not sc.is_certificate(path):
            continue
        if "D" in code:
            deleted.append(path)
        elif code == "??" or "A" in code or code[0] in "RC":
            added.append(path)
        else:
            modified.append(path)

    old_hash = {p: git(root, "rev-parse", "HEAD:" + p, check=False).strip() for p in deleted}
    new_hash = {p: git(root, "hash-object", "--", p).strip() for p in added}
    by_hash: dict[str, list[str]] = {}
    for p in sorted(added):
        by_hash.setdefault(new_hash[p], []).append(p)
    changes = Changes(modified=sorted(modified))
    for old in sorted(deleted):
        candidates = by_hash.get(old_hash[old]) if old_hash[old] else None
        if candidates:
            new = candidates.pop(0)
            added.remove(new)
            changes.renamed.append((old, new))
        else:
            changes.deleted.append(old)
    changes.added = sorted(added)
    return changes


def _count(n: int, verb: str) -> str:
    return "%s %d %s" % (verb, n, "certificate" if n == 1 else "certificates")


def build_message(changes: Changes, total: int, generated: list[str]) -> str:
    """Return the commit message for a change set. Pure function of its inputs."""
    parts = []
    if changes.added:
        parts.append(_count(len(changes.added), "add"))
    if changes.modified:
        parts.append(_count(len(changes.modified), "update"))
    if changes.renamed:
        parts.append(_count(len(changes.renamed), "rename"))
    if changes.deleted:
        parts.append(_count(len(changes.deleted), "remove"))
    if not parts:
        subject = "chore(certs): refresh index"
    else:
        kind = "feat" if changes.added else "chore"
        subject = "%s(certs): %s" % (kind, ", ".join(parts))
        if len(subject) > SUBJECT_LIMIT:
            short = [p.replace(" certificates", "").replace(" certificate", "") for p in parts]
            subject = "%s(certs): %s" % (kind, ", ".join(short))
    body = ["A  " + p for p in changes.added]
    body += ["M  " + p for p in changes.modified]
    body += ["R  %s -> %s" % pair for pair in changes.renamed]
    body += ["D  " + p for p in changes.deleted]
    body += ["G  " + p for p in sorted(generated)]
    body.append("")
    body.append("Index total: %d" % total)
    return subject + "\n\n" + "\n".join(body) + "\n"


def confirm(prompt: str) -> bool:
    if not sys.stdin.isatty():
        return False
    return input(prompt + " [y/N] ").strip().lower() in ("y", "yes")


def run(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    ap.add_argument("--dry-run", action="store_true", help="print the plan, change nothing")
    ap.add_argument("--no-push", action="store_true", help="commit but do not push")
    ap.add_argument("--include-deletions", action="store_true",
                    help="also commit certificates removed from the work tree")
    ap.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve()

    preflight(root)
    if not args.dry_run:
        git(root, "fetch", "--quiet", REMOTE, BRANCH)
        behind = git(root, "rev-list", "--count", "HEAD..%s/%s" % (REMOTE, BRANCH)).strip()
        if behind != "0":
            try:
                git(root, "pull", "--rebase", "--autostash", "--quiet", REMOTE, BRANCH)
            except SyncError as err:
                git(root, "rebase", "--abort", check=False)
                raise SyncError("Rebase onto %s/%s failed and was aborted. %s"
                                % (REMOTE, BRANCH, err)) from err

    changes = detect(root)
    skipped = []
    if changes.deleted and not args.include_deletions:
        skipped, changes.deleted = changes.deleted, []

    _, pending, final = sc.plan(root)
    total = len(final)
    stale = {p.relative_to(root).as_posix() for p in pending}
    if not args.dry_run:
        rc = sc.main(["--root", str(root)])
        if rc != 0:
            raise SyncError("Index generation failed with exit code %d." % rc)
    dirty = git(root, "status", "--porcelain=v1", "-z", "--", *GENERATED)
    generated = sorted(stale | {e[3:] for e in dirty.split("\0") if e})

    for path in skipped:
        print("skip removed file (pass --include-deletions to commit): %s" % path)
    if not changes.any() and not generated:
        print("Nothing to sync.")
        return 0

    message = build_message(changes, total, generated)
    print(message, end="")
    if args.dry_run:
        print("Dry run: nothing staged, committed or pushed.")
        return 0
    if not args.yes and not confirm("Commit%s?" % ("" if args.no_push else " and push to main")):
        print("Not confirmed. Nothing staged, committed or pushed.")
        return 2

    paths = changes.added + changes.modified + changes.deleted + generated
    for old, new in changes.renamed:
        paths += [old, new]
    paths = sorted(set(paths))
    for path in paths:
        git(root, "add", "--", path)
    git(root, "commit", "--quiet", "-m", message, "--", *paths)
    print("Committed %s" % git(root, "rev-parse", "--short", "HEAD").strip())
    if args.no_push:
        return 0
    git(root, "push", "--quiet", REMOTE, "HEAD:refs/heads/%s" % BRANCH)
    print("Pushed to %s/%s" % (REMOTE, BRANCH))
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        return run(argv)
    except SyncError as err:
        print("sync stopped: %s" % err, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
