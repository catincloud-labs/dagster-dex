#!/usr/bin/env python3
"""Proof that the closing-keyword guard can fire and can go quiet.

The estate's practice is that a control ships with both halves. A guard that
has only ever been observed to pass has not been shown to be a guard, and this
one is easy to get subtly wrong in the direction that is silently useless.

No test framework: plain asserts, so this runs anywhere python does.

    python scripts/test_check_closing_keywords.py
"""

from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_closing_keywords import check, main, parse_reported, reconcile  # noqa: E402

FAILURES: list[str] = []


def expect(name: str, text: str, code: int, *, commit_msg: bool = False) -> None:
    actual, lines = check(text, commit_msg=commit_msg)
    if actual != code:
        FAILURES.append(f"{name}: expected exit {code}, got {actual}\n    " + "\n    ".join(lines))


def expect_reconcile(name: str, text: str, reported: set[int], code: int) -> None:
    actual, lines = reconcile(text, reported)
    if actual != code:
        FAILURES.append(f"{name}: expected exit {code}, got {actual}\n    " + "\n    ".join(lines))


def expect_cli(name: str, argv: list[str], code: int) -> None:
    """Drive `main` end to end, since usage errors live there and not in `check`.

    A real file, because `main` reads its input before it validates the flags.
    Output is swallowed: this asserts on the exit code, and a test that prints
    a guard's FAIL text is a test nobody reads twice.
    """
    handle = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8")
    handle.write("docs: a body that closes nothing at all\n")
    handle.close()
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            actual = main([*argv, handle.name])
    finally:
        os.unlink(handle.name)
    if actual != code:
        FAILURES.append(f"{name}: expected exit {code}, got {actual}")


# --- it goes quiet ---------------------------------------------------------
# The cases that must not fire. A guard that trips on these gets switched off,
# and a switched-off guard is the failure mode to design against first.

expect("empty", "", 0)
expect("acknowledged single", "Closes #12\n\nAutoclose: #12\n", 0)
# The caret-line pair. A fence closes with the marker that opened it, so content
# that merely looks like the other marker - a Python 3.11+ traceback's tilde
# caret line is the case that actually fired - must not toggle the state and
# swallow a well-formed trailer written after the true close of the fence.
expect(
    "a tilde caret line inside a fence does not unfence the trailer",
    "Closes #12\n\n```\nTypeError: boom\n    a + b\n    ~~~~~~^^^\n```\n\nAutoclose: #12\n",
    0,
)
expect(
    "a tilde fence is as good as a backtick one for documentation",
    "Explaining:\n\n~~~\nAutoclose: #99\n~~~\n\nNothing here closes anything.\n",
    0,
)

# --- it fires --------------------------------------------------------------
# Each is one clause of the rule: a spelling GitHub honours, or a defence
# that has been tried somewhere in the estate and does not protect.

expect("bare unacknowledged close", "Closes #12\n", 1)
expect("prose cannot cancel it", "Closes #12 queue items. Does NOT close #12.\n", 1)
expect("backticks do not protect it", "See `Closes #12` as an example of the trap.\n", 1)
expect("a fenced block does not protect it", "```\nFixes #12\n```\n", 1)
expect("the hyphenated trailer spelling is itself a live close", "Auto-close: #12\n", 1)
expect("a colon after the verb still links", "Closes: #12\n", 1)
expect("past tense", "Resolved #12\n", 1)
# Every inflection GitHub honours is its own spelling, so each has a case.
expect("the spelling closed", "closed #12\n", 1)
expect("the spelling fixed", "fixed #12\n", 1)
expect("the spelling resolve", "resolve #12\n", 1)
expect("the spelling resolves", "resolves #12\n", 1)
# `find_closes` splits the text into lines before matching, so a refusal
# names the line its close sits on. `_GAP`'s `[ \t]` alone already stops a
# verb linking to a number on the next line, so deleting the split changes
# no verdict; it changes the line the refusal names, and this case sees that.
_code, _lines = check("docs: a thing\n\nCloses #12\n")
if _code != 1 or "    Closes #12" not in _lines:
    FAILURES.append("the refusal names the close's own line\n    " + "\n    ".join(_lines))
# The URL form is refused as cross-repo-capable (ruled 2026-09-01): the guard
# cannot know its own repository, so every URL spelling is refused, same-repo
# ones included.
expect("the URL form", "Fixes https://github.com/example/other/issues/12\n", 1)
expect("the GH- form", "Closes GH-12\n", 1)

# --- the cross-repo spelling is refused, not acknowledged (2026-09-01) ------
# GitHub closes across repositories and reports it repo-qualified - measured
# on a real unmerged pull request - but the trailer and the CI extraction
# speak bare numbers, so no trailer can honestly acknowledge a cross-repo
# close. The spelling is refused outright; 'part of' plus a manual close is
# the form.

expect("a bare cross-repo close is refused", "Closes example/other#19\n", 1)

expect("one acknowledged, one not", "Closes #12 and fixes #14.\n\nAutoclose: #12\n", 1)
expect("a trailer that overclaims", "Nothing closes here.\n\nAutoclose: #12\n", 1)
# The other direction of the caret-line pair: a backtick line inside a tilde
# fence is content too, so a trailer written there stays documentation and
# the real close outside stays unacknowledged.
expect(
    "a trailer fenced by tildes is documentation even past a stray backtick line",
    "Closes #12\n\n~~~\n```\nAutoclose: #12\n~~~\n",
    1,
)
# A fence closes only on a run at least as long as its opener, with nothing
# after the run but whitespace. A shorter run, or an opener-shaped line with
# an info string, inside the fence is content, so the trailer stays fenced.
expect(
    "a shorter run inside a longer fence does not close it",
    "Closes #12\n\n````\n```\nAutoclose: #12\n````\n",
    1,
)
expect(
    "a marker line with text after it does not close the fence",
    "Closes #12\n\n```\n```text\nAutoclose: #12\n```\n",
    1,
)
expect(
    "a second close introduced while paraphrasing the first",
    "The durable fix #12 has been waiting on.\n",
    1,
)

# --- the commit-message stripping stays narrow -----------------------------
# Stripping is how a sibling repo's checker once missed a real violation, so
# both directions are pinned: it must drop git's own comments, and it must not
# reach past them.

expect(
    "git comment lines are dropped",
    "docs: a thing\n\n# Please enter the commit message. Closes #12 is just advice.\n",
    0,
    commit_msg=True,
)
expect(
    "the verbose diff below the scissors is dropped",
    "docs: a thing\n\n# ------------------------ >8 ------------------------\n"
    "diff --git a/x b/x\n+Closes #12\n",
    0,
    commit_msg=True,
)
expect(
    "stripping does not reach real body text",
    "docs: a thing\n\nCloses #12\n\n# a trailing git comment\n",
    1,
    commit_msg=True,
)
expect(
    "a PR body is not stripped: '#' starts a heading there, not a comment",
    "# Closes #12\n",
    1,
)
expect(
    "a body line opening with an issue number is not a git comment",
    "docs: a thing\n\n#12 closes #14\n",
    1,
    commit_msg=True,
)

# --- the CI cross-check reconciles, and finds the trailer only one way -----
# `reconcile` compares GitHub's own answer against the trailer. It exists so
# that "find the trailer" has a single implementation. A second reader in CI
# that is not fence-aware, such as a shell `grep` for the trailer, would fail
# the fenced case pinned below while this file certified it clean - a guard
# against two copies of a rule, containing two copies of a rule.

expect_reconcile("both empty is the ordinary pull request", "docs: rewrite the preamble\n", set(), 0)
expect_reconcile("agrees on one", "Closes #12\n\nAutoclose: #12\n", {12}, 0)
# The regression case. This is the shape that failed CI and cost a run.
expect_reconcile(
    "a fenced example of the trailer is not a claim, and CI must agree",
    "Explaining the convention:\n\n```\nAutoclose: #99\n```\n\nNothing here closes anything.\n",
    set(),
    0,
)
expect_reconcile("GitHub closes something the trailer omits", "Closes #12\n", {12}, 1)
expect_reconcile("the trailer claims what GitHub will not close", "Autoclose: #12\n", set(), 1)
# The measured false agreement (a real pull request, 2026-09-01): GitHub
# reported example/other#19 and a same-repository issue as two bare numbers;
# the trailer named both; the old guard printed "OK - GitHub agrees with the
# trailer" while #19 meant another repository's issue. Number agreement must
# not clear a cross-repo spelling.
expect_reconcile(
    "agreement on bare numbers cannot clear a cross-repo spelling",
    "Closes #12\nCloses example/other#19\n\nAutoclose: #19, #12\n",
    {19, 12},
    1,
)

# GitHub's field arrives as a joined string, as the action's `join(",")` renders it.
if parse_reported("12,14") != {12, 14}:
    FAILURES.append("parse_reported: should parse a joined list")

# --- the command line refuses two questions at once ------------------------
# `--github-closes` asks about a pull request; `--commit-msg` asks about a
# commit. Requesting both is a usage error, not a preference, so it exits 2 --
# "the checker could not run" -- rather than 1, which would read as a violation
# the author must go and fix.

expect_cli("the two modes are refused together", ["--github-closes", "12", "--commit-msg"], 2)
expect_cli("a non-number in the GitHub answer is a usage error", ["--github-closes", "12,banana"], 2)
expect_cli("reconcile alone runs", ["--github-closes", ""], 0)
expect_cli("the ordinary scan still runs", [], 0)
expect_cli("commit-msg alone runs", ["--commit-msg"], 0)

if FAILURES:
    print(f"FAIL - {len(FAILURES)} case(s):\n", file=sys.stderr)
    for failure in FAILURES:
        print(f"  {failure}", file=sys.stderr)
    raise SystemExit(1)

print("OK - guard fires and goes quiet on every pinned case.")
