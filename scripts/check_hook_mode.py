#!/usr/bin/env python3
"""Refuse a tracked commit-msg hook whose index mode is not executable.

WHY THIS EXISTS. git on Linux and macOS runs a hook only when the file is
executable. A `.githooks/commit-msg` tracked as mode 100644 is skipped with a
hint, so the local closing-keyword check never runs and nothing fails. Git for
Windows runs a hook by its `#!` line and does not read the bit, so the defect
is invisible where these hooks are written, and a delete and re-add there
quietly puts 100644 back. Three public hooks were found at 100644 this way, on
2026-11-03, with nothing reading the mode. This is the thing that reads it.

WHAT IT ASSERTS, and nothing else:

  If the hook path is tracked, every index entry for it has mode 100755. The
  mode is read from the index (`git ls-files -s`), never from the file on
  disk: the index is what a clone receives, and the disk bit on Windows says
  nothing. Anything else -- 100644, a symlink, a conflicted entry -- is refused,
  naming the file and the remedy:

      git update-index --chmod=+x .githooks/commit-msg

ABSENT PASSES, AND SAYS SO. A repository may reasonably have no hook. The pass
prints what it read -- how many tracked paths, and that the hook was not among
them -- so a pass is never silent about what it saw.

BLIND IS NOT ABSENT. A directory git cannot read, or an index with nothing in
it, lists no hook exactly as a repository without one does. Both are refused,
because "not tracked" read from a checkout that is not there is not a fact.

    python3 check_hook_mode.py                      # .githooks/commit-msg in cwd
    python3 check_hook_mode.py --root DIR PATH
    python3 check_hook_mode.py --self-test          # fires on 100644, quiet on 100755
"""

from __future__ import annotations

import argparse
import contextlib
import io
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HOOK = ".githooks/commit-msg"
EXECUTABLE = "100755"


class Blind(Exception):
    """The index could not be read, so nothing it lists or omits is a fact."""


def index_entries(root: Path) -> list[tuple[str, str]]:
    """Every (mode, path) pair in the index at `root`, from `git ls-files -s -z`."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-s", "-z"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            env={**os.environ, "LC_ALL": "C"},
        )
    except OSError as exc:
        raise Blind(f"git could not be started, so no index was read: {exc}") from exc
    if proc.returncode != 0:
        raise Blind(f"git ls-files failed at {root}: {proc.stderr.strip() or f'exit {proc.returncode}'}")
    entries = []
    for record in proc.stdout.split("\0"):
        if record:
            meta, _, path = record.partition("\t")
            entries.append((meta.split(" ", 1)[0], path))
    if not entries:
        raise Blind(f"the index at {root} lists no tracked path, which reads the same as no checkout at all")
    return entries


def verdict(entries: list[tuple[str, str]], hook: str) -> tuple[int, list[str]]:
    """Exit code and lines for one hook path against the index entries."""
    modes = [mode for mode, path in entries if path == hook]
    if not modes:
        return 0, [f"OK - {hook} is not tracked here (read {len(entries)} tracked path(s)), "
                   "so there is no hook to keep executable."]
    wrong = [mode for mode in modes if mode != EXECUTABLE]
    if not wrong:
        return 0, [f"OK - {hook} is tracked as {EXECUTABLE} (read {len(entries)} tracked path(s))."]
    return 1, [
        f"::error file={hook}::{hook} is tracked as {', '.join(wrong)}, not {EXECUTABLE}.",
        "git on Linux and macOS skips a hook that is not executable, so the local",
        "closing-keyword check never runs there, and nothing fails to say so.",
        "Git for Windows ignores the bit, which is why this goes unseen there.",
        "Fix it in the index, from the repository root, and commit the change:",
        "",
        f"    git update-index --chmod=+x {hook}",
    ]


def check(root: Path, hook: str) -> int:
    try:
        code, lines = verdict(index_entries(root), hook)
    except Blind as exc:
        print(f"::error::REFUSED - {exc}. Blind is not absent: nothing about {hook} was read.")
        return 1
    print("\n".join(lines))
    return code


# --- self-test ---------------------------------------------------------------
# Both halves, staged in throwaway repositories and driven through main(), the
# entry point the action runs. The modes are set with `update-index`, never
# taken from the disk, so the arms read the same on Windows, where every file
# is added as 100644, as on Linux.


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout


def _repo(root: Path, files: list[str]) -> Path:
    root.mkdir(parents=True)
    _git(root, "init", "-q")
    for rel in files:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"#!/bin/sh\nexit 0\n")
    if files:
        _git(root, "add", "--", *files)
    return root


def _run(root: Path) -> tuple[int, str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = main(["--root", str(root), HOOK])
    return code, out.getvalue()


def _expect(failures: list[str], name: str, root: Path, code: int, words: list[str]) -> None:
    actual, text = _run(root)
    missing = [w for w in words if w not in text]
    if actual != code or missing:
        failures.append(f"{name}: expected exit {code} naming {missing or words}, got {actual}:\n{text}")


def self_test() -> int:
    failures: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp)
        planted = _repo(scratch / "planted", [HOOK, "README.md"])
        _git(planted, "update-index", "--chmod=-x", HOOK)
        _expect(failures, "a planted 100644 fires", planted, 1,
                [HOOK, "100644", f"git update-index --chmod=+x {HOOK}"])
        _git(planted, "update-index", "--chmod=+x", HOOK)
        _expect(failures, "the same hook at 100755 goes quiet", planted, 0, [HOOK, EXECUTABLE, "2 tracked"])
        blob = _git(planted, "rev-parse", f":{HOOK}").strip()
        _git(planted, "update-index", "--cacheinfo", f"120000,{blob},{HOOK}")
        _expect(failures, "a symlink is not executable either", planted, 1, ["120000"])
        absent = _repo(scratch / "absent", ["README.md", ".githooks/pre-push"])
        _expect(failures, "an absent hook passes and says what it read", absent, 0,
                ["not tracked", "2 tracked"])
        _expect(failures, "an empty index is blind, not absent", _repo(scratch / "empty", []), 1,
                ["REFUSED", "no tracked path"])
        bare = scratch / "not-a-repo"
        bare.mkdir()
        # The ceiling stops git finding a repository above the scratch
        # directory, so this arm reads no index on any machine.
        prior = os.environ.get("GIT_CEILING_DIRECTORIES")
        os.environ["GIT_CEILING_DIRECTORIES"] = str(scratch)
        try:
            _expect(failures, "a directory git cannot read is blind, not absent", bare, 1,
                    ["REFUSED", "git ls-files failed"])
        finally:
            os.environ.pop("GIT_CEILING_DIRECTORIES")
            if prior is not None:
                os.environ["GIT_CEILING_DIRECTORIES"] = prior
    for failure in failures:
        print(f"self-test FAILED: {failure}", file=sys.stderr)
    if failures:
        return 1
    print("self-test OK: a planted 100644 fires naming the remedy, 100755 goes quiet, a symlink fires, "
          "an absent hook passes saying what it read, an empty index and a non-repository are refused as blind")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("hook", nargs="?", default=HOOK, help=f"the hook's path in the index (default: {HOOK})")
    parser.add_argument("--root", default=".", help="the checkout to read (default: cwd)")
    parser.add_argument("--self-test", action="store_true", help="prove the check fires and goes quiet")
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()
    return check(Path(args.root), args.hook)


if __name__ == "__main__":
    sys.exit(main())
