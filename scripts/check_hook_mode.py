#!/usr/bin/env python3
"""Refuse a tracked commit-msg hook whose index mode is not executable.

WHY THIS EXISTS. git on Linux and macOS runs a hook only when the file is
executable. A `.githooks/commit-msg` tracked as mode 100644 is skipped with a
hint, so the local closing-keyword check never runs and nothing fails. Git for
Windows runs a hook by its `#!` line and does not read the bit, so the defect
is invisible where these hooks are written, and a delete and re-add there
quietly puts 100644 back. Nothing else reads the mode; this does.

WHAT IT ASSERTS, and nothing else:

  If the hook path is tracked, it has one index entry, at stage 0, with mode
  100755. The mode is read from the index (`git ls-files -s`), never from the
  file on disk: the index is what a clone receives, and the disk bit on
  Windows says nothing. Anything else -- 100644, a symlink, a conflicted entry
  at any modes -- is refused, naming the file and the remedy:

      git update-index --chmod=+x .githooks/commit-msg

ABSENT PASSES, AND SAYS SO. A repository may reasonably have no hook. The pass
prints what it read -- how many tracked paths, and that the hook was not among
them -- so a pass is never silent about what it saw.

BLIND IS NOT ABSENT. A directory git cannot read, or an index with nothing in
it, lists no hook exactly as a repository without one does. Both are refused,
because "not tracked" read from a checkout that is not there is not a fact.
Two narrower reads would also list no hook, and neither is allowed to happen:
the whole index is read (`:(top)`, `--full-name`) wherever in the work tree
the check runs or `--root` points, the hook path is normalised (a `./` or
backslash spelling names the same entry), and the variables that point git at another repository or
index (`git rev-parse --local-env-vars`, which git exports to the hooks it
runs) are removed from every git call, so `--root` names the index read.

    python3 check_hook_mode.py                      # .githooks/commit-msg in cwd
    python3 check_hook_mode.py --root DIR PATH
    python3 check_hook_mode.py --self-test          # fires on 100644, quiet on 100755
"""

from __future__ import annotations

import argparse
import contextlib
import io
import os
import posixpath
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

HOOK = ".githooks/commit-msg"
EXECUTABLE = "100755"
# Pathspec switches that would turn `:(top)` into a literal name matching nothing.
PATHSPEC_SWITCHES = ("GIT_LITERAL_PATHSPECS", "GIT_GLOB_PATHSPECS", "GIT_NOGLOB_PATHSPECS", "GIT_ICASE_PATHSPECS")


class Blind(Exception):
    """The index could not be read, so nothing it lists or omits is a fact."""


def git_env() -> dict[str, str]:
    """The environment every git call here runs in: untranslated, and pointed at no other repository.

    git exports GIT_INDEX_FILE to a commit-msg hook, and GIT_DIR or GIT_INDEX_FILE in the
    environment outrank `-C`: the check would read an index nobody named, and the self-test
    would write into it. git's own list of such variables is the one removed."""
    env = {**os.environ, "LC_ALL": "C"}
    try:
        listed = subprocess.run(["git", "rev-parse", "--local-env-vars"],
                                capture_output=True, text=True, env=env, check=False)
    except OSError as exc:
        raise Blind(f"git could not be started, so no index was read: {exc}") from exc
    names = listed.stdout.split()
    if listed.returncode != 0 or "GIT_INDEX_FILE" not in names:
        raise Blind(f"git rev-parse --local-env-vars did not list GIT_INDEX_FILE: {listed.stderr.strip()}")
    for name in (*names, *PATHSPEC_SWITCHES):
        env.pop(name, None)
    return env


def index_entries(root: Path) -> list[tuple[str, str, str]]:
    """Every (mode, stage, path) in the whole index of the work tree holding `root`."""
    env = git_env()
    proc = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-s", "-z", "--full-name", "--", ":(top)"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, check=False,
    )
    if proc.returncode != 0:
        raise Blind(f"git ls-files failed at {root}: {proc.stderr.strip() or f'exit {proc.returncode}'}")
    entries = []
    for record in proc.stdout.split("\0"):
        if record:
            meta, _, path = record.partition("\t")
            mode, _, stage = meta.split(" ")
            entries.append((mode, stage, path))
    if not entries:
        raise Blind(f"the index at {root} lists no tracked path, which reads the same as no checkout at all")
    return entries


def verdict(entries: list[tuple[str, str, str]], hook: str) -> tuple[int, list[str]]:
    """Exit code and lines for one hook path against the index entries."""
    read = f"read {len({path for _, _, path in entries})} tracked path(s)"
    ours = [(mode, stage) for mode, stage, path in entries if path == hook]
    if not ours:
        return 0, [f"OK - {hook} is not tracked here ({read}), so there is no hook to keep executable."]
    wrong = sorted({mode for mode, _ in ours if mode != EXECUTABLE})
    conflicted = sorted(stage for _, stage in ours if stage != "0")
    if not wrong and not conflicted:
        return 0, [f"OK - {hook} is tracked as {EXECUTABLE} ({read})."]
    faults = [f"tracked as {', '.join(wrong)}, not {EXECUTABLE}"] if wrong else []
    faults += [f"conflicted in the index (stages {', '.join(conflicted)}); resolve it first"] if conflicted else []
    return 1, [
        f"::error file={hook}::{hook} is {' and '.join(faults)}.",
        "git on Linux and macOS skips a hook that is not executable, so the local",
        "closing-keyword check never runs there, and nothing fails to say so.",
        "Git for Windows ignores the bit, which is why this goes unseen there.",
        "Fix it in the index, from the repository root, and commit the change:",
        "",
        f"    git update-index --chmod=+x {hook}",
    ]


def normalised(hook: str) -> str:
    """The index's spelling of a hook path given as `./x`, `a\\b` or `a//b`."""
    return posixpath.normpath(hook.replace("\\", "/"))


def check(root: Path, hook: str) -> int:
    hook = normalised(hook)
    try:
        code, lines = verdict(index_entries(root), hook)
    except Blind as exc:
        print(f"::error::REFUSED - {exc}. Blind is not absent: nothing about {hook} was read.")
        return 1
    print("\n".join(lines))
    return code


# --- self-test ---------------------------------------------------------------
# Both halves, staged in throwaway repositories. Most arms drive main() in this
# process; two run this file as a subprocess, with no `--root`, from inside
# the work tree, as a CI step runs it. The modes are set with
# `update-index`, never taken from the disk, so the arms read the same on
# Windows, where every file is added as 100644, as on Linux. The whole run
# carries a GIT_DIR and a GIT_INDEX_FILE that point at sentinels, which must
# still be absent at the end: neither the check nor its fixtures may follow them.


def _git(root: Path, *args: str, stdin: str = "") -> str:
    # Bytes, not text: a text-mode pipe on Windows writes CRLF, and `--index-info`
    # would read the CR as part of the path.
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True,
                          input=stdin.encode("utf-8"), env=git_env()).stdout.decode("utf-8")


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


@contextlib.contextmanager
def _environ(values: dict[str, str]) -> Iterator[None]:
    prior = {name: os.environ.get(name) for name in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for name, value in prior.items():
            os.environ.pop(name, None)
            if value is not None:
                os.environ[name] = value


def _in_process(root: Path, hook: str = HOOK) -> tuple[int, str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = main(["--root", str(root), hook])
    return code, out.getvalue()


def _as_the_action_runs(cwd: Path) -> tuple[int, str]:
    proc = subprocess.run([sys.executable, str(Path(__file__).resolve()), HOOK], cwd=cwd,
                          capture_output=True, text=True, check=False)
    return proc.returncode, proc.stdout + proc.stderr


def _expect(failures: list[str], name: str, got: tuple[int, str], code: int, words: list[str]) -> None:
    actual, text = got
    missing = [w for w in words if w not in text]
    if actual != code or missing:
        failures.append(f"{name}: expected exit {code} naming {missing or words}, got {actual}:\n{text}")


def _mode_arms(scratch: Path) -> list[str]:
    failures: list[str] = []
    planted = _repo(scratch / "planted", [HOOK, "README.md"])
    _git(planted, "update-index", "--chmod=-x", HOOK)
    _expect(failures, "a planted 100644 fires", _in_process(planted), 1,
            [HOOK, "100644", f"git update-index --chmod=+x {HOOK}"])
    _expect(failures, "a planted 100644 fires run as the action runs it, from a subdirectory",
            _as_the_action_runs(planted / ".githooks"), 1, [HOOK, "100644"])
    _expect(failures, "a planted 100644 fires with --root below the top", _in_process(planted / ".githooks"), 1,
            [HOOK, "100644"])
    _expect(failures, "a planted 100644 fires with the hook spelled ./", _in_process(planted, f"./{HOOK}"), 1,
            [HOOK, "100644"])
    _git(planted, "update-index", "--chmod=+x", HOOK)
    _expect(failures, "the same hook at 100755 goes quiet", _in_process(planted), 0, [HOOK, EXECUTABLE, "2 tracked"])
    _expect(failures, "100755 goes quiet run as the action runs it, from a subdirectory",
            _as_the_action_runs(planted / ".githooks"), 0, [EXECUTABLE, "2 tracked"])
    return failures + _entry_shape_arms(planted)


def _entry_shape_arms(planted: Path) -> list[str]:
    """A symlink, then a conflict: every stage at 100755, then one stage at 100644."""
    failures: list[str] = []
    blob = _git(planted, "rev-parse", f":{HOOK}").strip()
    _git(planted, "update-index", "--cacheinfo", f"120000,{blob},{HOOK}")
    _expect(failures, "a symlink is not executable either", _in_process(planted), 1, ["120000"])
    for name, last, words in (("a conflicted entry at 100755 in every stage fires", EXECUTABLE, ["stages 1, 2, 3"]),
                              ("a conflicted entry with one stage at 100644 fires", "100644", ["100644"])):
        stages = f"0 {'0' * 40}\t{HOOK}\n" + "".join(
            f"{mode} {blob} {stage}\t{HOOK}\n" for stage, mode in ((1, EXECUTABLE), (2, EXECUTABLE), (3, last)))
        _git(planted, "update-index", "--index-info", stdin=stages)
        _expect(failures, name, _in_process(planted), 1, ["conflicted", *words])
    return failures


def _absent_and_blind_arms(scratch: Path) -> list[str]:
    failures: list[str] = []
    absent = _repo(scratch / "absent", ["README.md", ".githooks/pre-push"])
    _expect(failures, "an absent hook passes and says what it read", _in_process(absent), 0,
            ["not tracked", "2 tracked"])
    _expect(failures, "an empty index is blind, not absent", _in_process(_repo(scratch / "empty", [])), 1,
            ["REFUSED", "no tracked path"])
    bare = scratch / "not-a-repo"
    bare.mkdir()
    # The ceiling stops git finding a repository above the scratch directory,
    # so this arm reads no index on any machine.
    with _environ({"GIT_CEILING_DIRECTORIES": str(scratch)}):
        _expect(failures, "a directory git cannot read is blind, not absent", _in_process(bare), 1,
                ["REFUSED", "git ls-files failed"])
    return failures


def self_test() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp)
        sentinels = {"GIT_DIR": str(scratch / "sentinel.git"), "GIT_INDEX_FILE": str(scratch / "sentinel-index")}
        with _environ(sentinels):
            try:
                failures = _mode_arms(scratch) + _absent_and_blind_arms(scratch)
            except subprocess.CalledProcessError as exc:
                failures = [f"a fixture's git call failed, so no arm was read: {exc}: {exc.stderr!r}"]
        failures += [f"{name} was followed: {path} exists" for name, path in sentinels.items() if Path(path).exists()]
    for failure in failures:
        print(f"self-test FAILED: {failure}", file=sys.stderr)
    if failures:
        return 1
    print("self-test OK: a planted 100644 fires naming the remedy and 100755 goes quiet, in process and as a "
          "CI step runs it from a subdirectory; 100644 fires with --root below the top and with the hook spelled "
          "./; a symlink and a conflicted entry fire, at 100755 in every stage too; an absent hook "
          "passes saying what it read; an empty index and a non-repository are refused as blind; an exported "
          "GIT_DIR and GIT_INDEX_FILE were not followed")
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
