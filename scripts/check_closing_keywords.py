#!/usr/bin/env python3
"""Refuse a commit message or PR body that closes an issue without saying so.

GitHub's reference parser closes an issue when a closing verb is *immediately*
followed by an issue reference. Only adjacency fires: prose around it is never
read, and a code span does not protect it. A sentence written to explain that
you are not closing an issue will close it.

This is not a ban. Deliberate closes are routine. What it refuses is an
*unacknowledged* one: the message must carry an ``Autoclose:`` trailer that
enumerates exactly the set GitHub will close.

    Autoclose: #12, #14

⚠️  The trailer is spelled without a hyphen on purpose. A hyphen is a word
boundary, so the hyphenated spelling contains a live closing verb — the
acknowledgement would close the issues it names and then satisfy this checker
with a closure it manufactured itself.

CI additionally asks GitHub what merging a pull request would *actually* close
and reconciles that against the trailer. That comparison is `--github-closes`
below rather than shell in the action, so that "find the trailer" has exactly
one implementation — see `reconcile`.

Exit codes
----------
0   the message is clean, or every close is acknowledged
1   a violation — an unacknowledged close, or a trailer that overclaims
2   the checker could not run (bad usage, unreadable input)

Usage
-----
    python scripts/check_closing_keywords.py <file>
    python scripts/check_closing_keywords.py --commit-msg .git/COMMIT_EDITMSG
    git log -1 --format=%B | python scripts/check_closing_keywords.py -
    python scripts/check_closing_keywords.py --github-closes 12,14 pr-body.md
"""

from __future__ import annotations

import argparse
import re
import sys

# The closing verbs GitHub honours, with their inflections. Written as
# alternations rather than one clever pattern so that adding a verb is obvious.
_VERBS = r"clos(?:e|es|ed)|fix(?:|es|ed)|resolv(?:e|es|ed)"

# Adjacency is the whole rule: verb, an optional colon, then the reference.
#
# ⚠️  `[ \t]` rather than `\s` is belt-and-braces, NOT the thing that stops a
# verb linking to a number on the next line — `find_closes` splits into lines
# before matching, so a newline never reaches this pattern at all. Swapping
# this for `\s` changes nothing observable, which a mutation check confirmed.
# The line split is the real enforcer; do not delete it thinking this covers it.
_GAP = r"[ \t]*:?[ \t]*"

# The three reference spellings that link: bare, cross-repo, and a full URL.
_REF = (
    r"(?:"
    r"(?:[\w.-]+/[\w.-]+)?\#(?P<bare>\d+)"
    r"|GH-(?P<gh>\d+)"
    r"|https?://github\.com/[\w.-]+/[\w.-]+/issues/(?P<url>\d+)"
    r")"
)

_CLOSING = re.compile(rf"\b(?:{_VERBS})\b{_GAP}{_REF}", re.IGNORECASE)

# `Autoclose` has no word boundary before `close`, so this trailer is invisible
# to GitHub's parser — which is exactly why it is safe to write.
_TRAILER = re.compile(r"^[ \t]*Autoclose[ \t]*:[ \t]*(?P<refs>.+?)[ \t]*$", re.IGNORECASE)
_TRAILER_REF = re.compile(r"#(\d+)")

_FENCE = re.compile(r"^[ \t]*(?:```|~~~)")
_SCISSORS = re.compile(r"^[ \t]*#[ \t]*-+[ \t]*>8[ \t]*-+")


def strip_commit_cruft(text: str) -> str:
    """Drop what git itself will drop: comment lines and the verbose diff.

    ⚠️  Narrow on purpose, and opt-in. Stripping is how a checker in a sibling
    repo once missed a real violation, so this removes only what git removes,
    and only when the caller says the input is a commit message. A PR body is
    never passed through here — `#` starts a heading there, not a comment.
    """
    kept: list[str] = []
    for line in text.splitlines():
        if _SCISSORS.match(line):
            break
        if line.lstrip().startswith("#") and not _TRAILER_REF.match(line.lstrip()):
            # A git comment. The guard above keeps a bare `#12` line — that is
            # content in a body, and git would keep it too only if it were not
            # at line start, so erring toward scoring it is the safe direction.
            continue
        kept.append(line)
    return "\n".join(kept)


def find_closes(text: str) -> dict[int, list[str]]:
    """Issue numbers GitHub would close, mapped to the lines that do it.

    Code spans and fences are scored. GitHub scores them, so this must too —
    "I put it in backticks" has already failed as a defence.
    """
    found: dict[int, list[str]] = {}
    for line in text.splitlines():
        for match in _CLOSING.finditer(line):
            number = int(match["bare"] or match["gh"] or match["url"])
            found.setdefault(number, []).append(line.strip())
    return found


def find_acknowledged(text: str) -> set[int]:
    """Issue numbers named in an ``Autoclose:`` trailer, outside code fences.

    The asymmetry with `find_closes` is deliberate. Closing verbs are scored
    inside fences because GitHub scores them there; the trailer is *our*
    convention, so a fenced example of one is documentation, not a claim.
    """
    acknowledged: set[int] = set()
    in_fence = False
    for line in text.splitlines():
        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        trailer = _TRAILER.match(line)
        if trailer:
            acknowledged.update(int(n) for n in _TRAILER_REF.findall(trailer["refs"]))
    return acknowledged


def check(text: str, *, commit_msg: bool = False) -> tuple[int, list[str]]:
    """Return an exit code and the lines to print."""
    if commit_msg:
        text = strip_commit_cruft(text)

    closes = find_closes(text)
    acknowledged = find_acknowledged(text)

    unacknowledged = sorted(set(closes) - acknowledged)
    overclaimed = sorted(acknowledged - set(closes))

    # Everything below is printed, so it stays ASCII. This runs as a commit hook
    # on a Windows console, where a stray em dash is mangled at best and raises
    # at worst -- a guard that garbles its own verdict teaches people to ignore it.
    if not unacknowledged and not overclaimed:
        if closes:
            named = ", ".join(f"#{n}" for n in sorted(closes))
            return 0, [f"OK - acknowledged close of {named}."]
        return 0, ["OK - nothing here closes an issue."]

    out: list[str] = []
    if unacknowledged:
        out.append("FAIL - this message closes an issue without acknowledging it.")
        out.append("")
        for number in unacknowledged:
            out.append(f"  issue {number}, from:")
            for line in closes[number]:
                out.append(f"    {line}")
        out.append("")
        out.append("  Either break the adjacency ('part of', 'refs', or any non-verb")
        out.append("  before the number), or add a trailer naming every close:")
        out.append("")
        named = ", ".join(f"#{n}" for n in sorted(set(closes)))
        out.append(f"    Autoclose: {named}")
        out.append("")
        out.append("  Do not hunt for a safer verb. The words that describe fixing a")
        out.append("  bug are the reserved set, so a paraphrase lands on another one.")

    if overclaimed:
        if unacknowledged:
            out.append("")
        named = ", ".join(f"#{n}" for n in overclaimed)
        out.append(f"FAIL - the trailer claims {named} will close, but nothing here")
        out.append("  closes them. Either the reference is misspelled or the trailer")
        out.append("  is stale; a trailer nobody can trust is worse than none.")

    return 1, out


def _named(numbers: set[int] | list[int]) -> str:
    """Render a set of issue numbers for printing. ASCII, like everything printed."""
    return ", ".join(f"#{n}" for n in sorted(numbers)) or "nothing"


def parse_reported(raw: str) -> set[int]:
    """Parse GitHub's answer as ``gh pr view ... --jq 'join(",")'`` renders it.

    Empty means GitHub says merging closes nothing. That is the ordinary case
    for most pull requests, so it is a valid input and never an error.
    """
    numbers: set[int] = set()
    for part in raw.replace("#", "").split(","):
        part = part.strip()
        if not part:
            continue
        if not part.isdigit():
            raise ValueError(part)
        numbers.add(int(part))
    return numbers


def reconcile(text: str, reported: set[int]) -> tuple[int, list[str]]:
    """Reconcile GitHub's own answer against the ``Autoclose:`` trailer.

    `find_closes` is this file's reimplementation of GitHub's parser. `reported`
    is what GitHub says about the pull request itself, which is the authority
    when the two disagree — so CI cross-checks the trailer against it as well.

    ⚠️  The trailer is found with `find_acknowledged`, the same function the
    rest of this file uses, and that shared call is the entire point of this
    mode. CI used to re-implement the search as a shell `grep` anchored at line
    start, which was not fence-aware. The self-test pins that a fenced example
    of a trailer is documentation rather than a claim — so the second
    implementation is how CI came to fail precisely the case this file's own
    test certifies as clean.

    ⚠️  `reported` is same-repository only: GitHub's closing keywords do not
    close an issue in another repository, so a cross-repo close that
    `find_closes` scores reads here as a trailer that overclaims. That predates
    this mode and is deliberately left as it was found. Changing it is a rule
    change, not a refactor, and belongs in its own argument.
    """
    acknowledged = find_acknowledged(text)

    unacknowledged = sorted(reported - acknowledged)
    overclaimed = sorted(acknowledged - reported)

    summary = [
        f"  GitHub reports merging will close: {_named(reported)}",
        f"  The Autoclose trailer names:       {_named(acknowledged)}",
    ]

    if not unacknowledged and not overclaimed:
        return 0, ["OK - GitHub agrees with the trailer."] + summary

    out = ["FAIL - GitHub and the trailer disagree about what merging will close.", ""]
    out.extend(summary)
    out.append("")
    if unacknowledged:
        out.append(f"  Merging closes, but the trailer omits:        {_named(unacknowledged)}")
    if overclaimed:
        out.append(f"  The trailer claims, but GitHub will not close: {_named(overclaimed)}")
    out.append("")
    out.append("  Believe GitHub over any regex here, but read the numbers before")
    out.append("  believing the disagreement: the field lags a body edit and reads")
    out.append("  empty for a short while after a pull request opens.")
    return 1, out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Refuse an unacknowledged issue close in a commit message or PR body.",
    )
    parser.add_argument("path", help="file to check, or '-' for stdin")
    parser.add_argument(
        "--commit-msg",
        action="store_true",
        help="input is a commit message: drop git comment lines and the verbose diff",
    )
    parser.add_argument(
        "--github-closes",
        metavar="LIST",
        help=(
            "comma-separated issue numbers GitHub reports the pull request will "
            "close; reconcile them against the trailer instead of scanning for "
            "closing verbs. An empty value is valid and means 'nothing'."
        ),
    )
    args = parser.parse_args(argv)

    try:
        if args.path == "-":
            text = sys.stdin.read()
        else:
            with open(args.path, encoding="utf-8") as handle:
                text = handle.read()
    except OSError as error:
        print(f"check_closing_keywords: could not read input: {error}", file=sys.stderr)
        return 2

    if args.github_closes is not None:
        # Two different questions, so refuse the combination rather than
        # silently answering one of them.
        if args.commit_msg:
            print(
                "check_closing_keywords: --github-closes and --commit-msg are "
                "different modes; pass one.",
                file=sys.stderr,
            )
            return 2
        try:
            reported = parse_reported(args.github_closes)
        except ValueError as bad:
            print(
                f"check_closing_keywords: not an issue number in --github-closes: {bad}",
                file=sys.stderr,
            )
            return 2
        code, lines = reconcile(text, reported)
    else:
        code, lines = check(text, commit_msg=args.commit_msg)

    stream = sys.stdout if code == 0 else sys.stderr
    for line in lines:
        print(line, file=stream)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
