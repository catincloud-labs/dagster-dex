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
expect("no reference at all", "docs: rewrite the roadmap preamble\n", 0)
expect("refs is safe", "Refs #12 and #14.\n", 0)
expect("part of is safe", "part of #12\n", 0)
expect("a bare number is not a reference", "Fixes 12 problems.\n", 0)
expect("a verb with no number", "This closes the argument.\n", 0)
# Pins the line split in `find_closes`, not the `[ \t]` in `_GAP`. Loosening
# that character class to `\s` is an equivalent mutation; deleting the line
# split is not, and this is the case that would catch it.
expect("verb and number on separate lines", "closes\n#12\n", 0)
expect("acknowledged single", "Closes #12\n\nAutoclose: #12\n", 0)
expect("acknowledged multiple, any order", "Fixes #14. Closes #12.\n\nAutoclose: #12, #14\n", 0)
# The cross-repo spelling with NO verb is a reference, not a close - the
# refusal is about the closing adjacency, never about citing another repo.
expect("a cross-repo reference without a verb is a citation", "See catincloud-labs/constellation#9 for the record.\n", 0)
expect("part of is safe for a cross-repo reference too", "part of catincloud-labs/constellation#9\n", 0)
expect("refs is safe for a cross-repo reference too", "Refs catincloud-labs/constellation#9.\n", 0)
expect(
    "a fenced example of the trailer is documentation, not a claim",
    "Explaining the convention:\n\n```\nAutoclose: #99\n```\n\nNothing here closes anything.\n",
    0,
)
# The wb #47 pair. A fence closes with the marker that opened it, so content
# that merely looks like the other marker — a Python 3.11+ traceback's tilde
# caret line is the case that actually fired — must not toggle the state and
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
# Every one of these is a shape that has actually happened somewhere in the
# estate, which is why each is listed separately rather than as one case.

expect("bare unacknowledged close", "Closes #12\n", 1)
expect("prose cannot cancel it", "Closes #12 queue items. Does NOT close #12.\n", 1)
expect("backticks do not protect it", "See `Closes #12` as an example of the trap.\n", 1)
expect("a fenced block does not protect it", "```\nFixes #12\n```\n", 1)
expect("the hyphenated trailer spelling is itself a live close", "Auto-close: #12\n", 1)
expect("a colon after the verb still links", "Closes: #12\n", 1)
expect("uppercase", "FIXES #12\n", 1)
expect("past tense", "Resolved #12\n", 1)
# The URL form is refused as cross-repo-capable (wb #7): the guard cannot know
# its own repository, so every URL spelling is refused, same-repo ones included.
expect("the URL form", "Fixes https://github.com/catincloud-labs/constellation/issues/12\n", 1)
expect("the GH- form", "Closes GH-12\n", 1)

# --- the cross-repo spelling is refused, not acknowledged (wb #7) ----------
# GitHub closes across repositories and reports it repo-qualified - measured
# on crosslink PR #60 - but the trailer and the CI extraction speak bare
# numbers, so no trailer can honestly acknowledge a cross-repo close. The
# spelling is refused outright; 'part of' plus a manual close is the form.

expect("a bare cross-repo close is refused", "Closes catincloud-labs/scaffold#19\n", 1)
expect(
    "a trailer cannot acknowledge a cross-repo close - this case flipped at wb #7",
    "Closes catincloud-labs/constellation#9\n\nAutoclose: #9\n",
    1,
)
expect(
    "a URL close is refused even with a trailer naming its number",
    "Fixes https://github.com/catincloud-labs/scaffold/issues/19\n\nAutoclose: #19\n",
    1,
)
expect(
    "a fenced cross-repo close is still a close, so still refused",
    "```\nFixes catincloud-labs/scaffold#19\n```\n",
    1,
)

# The refusal message accounts for the trailer entry itself: the number of a
# refused spelling must not ALSO be reported as a trailer that overclaims -
# one defect, one message, one fix.
_code, _lines = check("Closes catincloud-labs/scaffold#19\n\nAutoclose: #19\n")
if _code != 1:
    FAILURES.append("refused-with-trailer: expected exit 1")
if any("trailer claims" in line for line in _lines):
    FAILURES.append(
        "refused-with-trailer: the refused number was double-reported as an overclaim\n    "
        + "\n    ".join(_lines)
    )
expect("one acknowledged, one not", "Closes #12 and fixes #14.\n\nAutoclose: #12\n", 1)
expect("a trailer that overclaims", "Nothing closes here.\n\nAutoclose: #12\n", 1)
# The other direction of wb #47: a backtick line inside a tilde fence is
# content too, so a trailer written there stays documentation and the real
# close outside stays unacknowledged.
expect(
    "a trailer fenced by tildes is documentation even past a stray backtick line",
    "Closes #12\n\n~~~\n```\nAutoclose: #12\n~~~\n",
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
    "# Summary\n\nCloses #12\n",
    1,
)

# --- the CI cross-check reconciles, and finds the trailer only one way -----
# `reconcile` compares GitHub's own answer against the trailer. It exists so
# that "find the trailer" has a single implementation. The shell `grep` it
# replaced was anchored at line start and not fence-aware, so CI failed the
# fenced case pinned above while this file certified it clean — a guard against
# two copies of a rule, containing two copies of a rule.

expect_reconcile("both empty is the ordinary pull request", "docs: rewrite the preamble\n", set(), 0)
expect_reconcile("agrees on one", "Closes #12\n\nAutoclose: #12\n", {12}, 0)
expect_reconcile(
    "agrees regardless of the order the trailer lists them",
    "Fixes #14. Closes #12.\n\nAutoclose: #14, #12\n",
    {12, 14},
    0,
)
# The regression case. This is the shape that failed CI and cost a run.
expect_reconcile(
    "a fenced example of the trailer is not a claim, and CI must agree",
    "Explaining the convention:\n\n```\nAutoclose: #99\n```\n\nNothing here closes anything.\n",
    set(),
    0,
)
expect_reconcile("GitHub closes something the trailer omits", "Closes #12\n", {12}, 1)
expect_reconcile("the trailer claims what GitHub will not close", "Autoclose: #12\n", set(), 1)
expect_reconcile(
    "a partial overlap fires rather than rounding to agreement",
    "Closes #12 and fixes #14.\n\nAutoclose: #12\n",
    {12, 14},
    1,
)
# The measured false agreement (crosslink PR #60, 2026-09-01): GitHub reported
# scaffold#19 and crosslink#59 as the bare numbers 19,59; the trailer named
# both; the old guard printed "OK - GitHub agrees with the trailer" while #19
# meant another repository's issue. Number agreement must not clear a
# cross-repo spelling.
expect_reconcile(
    "agreement on bare numbers cannot clear a cross-repo spelling",
    "Closes #59\nCloses catincloud-labs/scaffold#19\n\nAutoclose: #19, #59\n",
    {19, 59},
    1,
)
expect_reconcile(
    "a cross-repo citation without a verb reconciles normally",
    "part of catincloud-labs/scaffold#19\n",
    set(),
    0,
)

# GitHub's field arrives as a joined string, and empty is a valid answer rather
# than a parse failure — the shape that once aborted the step before it printed.
if parse_reported("") != set():
    FAILURES.append("parse_reported: an empty answer should mean nothing, not an error")
if parse_reported("12,14") != {12, 14}:
    FAILURES.append("parse_reported: should parse a joined list")
if parse_reported(" #12 , 14 ") != {12, 14}:
    FAILURES.append("parse_reported: should tolerate hashes and whitespace")
try:
    parse_reported("12,banana")
except ValueError:
    pass
else:
    FAILURES.append("parse_reported: should refuse a non-number rather than silently drop it")

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
