#!/usr/bin/env python3
"""Refuse a pull-request title that is not a conventional-commit line.

WHY THIS EXISTS. A pull-request title is a git artifact: the estate merges with
merge commits, so the title is what `git log` and every future `#N` citation
resolve to. The convention (`type(scope): summary`) held unwritten across almost
every early pull request, then vanished inside one day once nothing but memory
carried it. An unwritten convention holds exactly as long as the sessions that
remember it, and a rule that lives only in prose is not a control; this file is
the control.

WHAT IT ASSERTS, each rule calibrated against the estate's pre-guard title
corpus so history's legitimate shapes stay legal. The corpus -- its dates, its
numbers and the titles themselves -- lives in CALIBRATION.md beside this file's
canonical copy and deliberately does NOT travel with it: this file is vendored
byte-identical into public repositories, and a measurement a stranger cannot
re-run stays where it was taken. Do not tighten a rule here without re-running
that calibration:

  1. The title starts `type(scope): ` -- type one of TYPES, scope optional
     lowercase [a-z0-9._-], an optional `!` for a breaking change.
  2. The summary does not open with a CAPITALIZED ORDINARY WORD (`^[A-Z][a-z]+$`).
     Strict lowercase would refuse legitimate corpus titles that open with
     identifiers -- an ALL_CAPS name and its possessive, an `ADR-0001`-style
     reference, a dotfile, bare `I` -- so the rule refuses sentence case
     specifically, which is what the drift actually looked like. Dependabot's
     `Bump` shape fails it, and Dependabot is exempted BY AUTHOR below, not by
     teaching the rule that capitalized words are fine.
  3. At most 100 characters -- a cap set from the corpus's length distribution,
     generous to every real shape and refusing only headline-plus-sentence
     titles.
  4. No trailing period. The title is a headline, not a sentence; the sentence
     belongs in the body.

TWO SHAPES PASS WHOLE, each printed when applied, because an exemption nobody
can see applied is indistinguishable from a gate that did not fire:

  * A title starting `Revert "` -- GitHub's own revert button writes it and the
    quoted part is the ORIGINAL title, already judged when it merged.
  * `--author dependabot[bot]` -- the machine authors its own titles upstream;
    its prefix is per-repo configuration and its capitalization is not.
    The exemption is the author, never the word: the same `Bump ...` title
    without that author is refused.

WHAT IT DELIBERATELY DOES NOT DO. It does not judge the summary's content, and
"one clause" stays prose: history is full of comma-joined clauses that
read fine, so a mechanical clause count would refuse history to no gain. Issue
titles carry the same convention in AGENTS.md but nothing gates issue creation;
this guard binds the surface CI can reach.

    python3 check_pr_title.py --title "docs: the title under judgement"
    python3 check_pr_title.py --title "..." --author "dependabot[bot]"
    (the action passes the title through the environment, never interpolated
    into shell -- a title is attacker-adjacent text on a public repo)
"""

from __future__ import annotations

import argparse
import re
import sys

TYPES = ("build", "chore", "ci", "docs", "feat", "fix", "perf", "probe", "refactor", "test")

PREFIX = re.compile(
    r"^(?P<type>" + "|".join(TYPES) + r")"
    r"(?:\((?P<scope>[a-z0-9._-]+)\))?"
    r"!?: (?P<summary>\S.*)$"
)

#: A capitalized ordinary word: sentence case, the drift's actual shape.
#: `CI_DEPLOY_KEY's` / `ADR-0001` / `.gitattributes` / bare `I` all miss
#: this pattern on purpose -- an identifier is not a sentence opener.
SENTENCE_CASE = re.compile(r"^[A-Z][a-z]+$")

MAX_LEN = 100

EXEMPT_AUTHORS = ("dependabot[bot]",)


def judge(title: str, author: str = "") -> list[str]:
    """Every violation in the title, empty when it conforms."""
    if author in EXEMPT_AUTHORS:
        print(f"exempt: author '{author}' writes its own titles upstream; "
              "its prefix is per-repo configuration and its capitalization is not.")
        return []
    if title.startswith('Revert "'):
        print("pass: GitHub's own revert shape; the quoted title was judged when it merged.")
        return []

    problems: list[str] = []
    m = PREFIX.match(title)
    if not m:
        problems.append(
            "no conventional prefix. A PR title is the merge commit history cites as #N; "
            f"start it `type(scope): summary` with type one of: {', '.join(TYPES)} "
            "(lowercase type and scope, `!` before the colon for a breaking change)."
        )
    else:
        summary = m.group("summary")
        first = summary.split(" ", 1)[0].rstrip(",.:;")
        if SENTENCE_CASE.fullmatch(first):
            problems.append(
                f"the summary opens with a capitalized ordinary word ('{first}') -- sentence case. "
                "Lowercase it; identifiers (CI_DEPLOY_KEY, ADR-0001, .gitattributes) are fine as they are."
            )
        if summary.rstrip().endswith("."):
            problems.append(
                "trailing period. The title is a headline; the sentence belongs in the PR body."
            )
    if len(title) > MAX_LEN:
        problems.append(
            f"{len(title)} characters; the cap is {MAX_LEN} -- "
            "move the second clause into the body."
        )
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--title", help="the pull-request title to judge")
    parser.add_argument("--author", default="", help="the PR author's login, for the machine-author exemption")
    parser.add_argument("--self-test", action="store_true", help="prove the guard fires and goes quiet")
    args = parser.parse_args()

    if args.self_test:
        return self_test()
    if args.title is None:
        parser.error("--title is required outside --self-test")

    problems = judge(args.title, args.author)
    if not problems:
        print(f"pr-title OK: {args.title!r}")
        return 0
    print(f"pr-title REFUSED: {args.title!r}", file=sys.stderr)
    for p in problems:
        print(f"  - {p}", file=sys.stderr)
    return 1


def self_test() -> int:
    """Calibrate both polarities. Every fixture below is constructed to pin one
    rule. The historical titles the rules were originally calibrated against --
    including the verbatim fixtures this list once carried -- are recorded in
    CALIBRATION.md beside this file's canonical copy; each historical shape is
    still pinned here by a constructed equivalent."""
    passes = [
        # (title, author) -- the identifier shapes strict-lowercase would refuse:
        ("docs: CI_DEPLOY_KEY's rotation is recorded where it happens", ""),          # ALL_CAPS possessive opener
        ("docs: .gitattributes is the enforcement, not the convention", ""),          # dotfile opener
        ("docs: I corrected the claim in three places", ""),                          # bare I is not sentence case
        ("chore(deps): bump packaging from 24.0 to 26.3 in /tests", ""),              # scoped, ordinary lowercase
        ("probe: move the published image path, to be reverted immediately", ""),     # probe type, comma-joined clause
        ("fix(env): the writer logs the identity it authenticates as", ""),           # plain fix with scope
        ('Revert "feat(ci): judge the title from the environment"', ""),              # GitHub's own revert shape
        ("build(deps-dev): Bump pytest from 8.4.1 to 9.0.3", "dependabot[bot]"),      # exempt BY AUTHOR
    ]
    refusals = [
        # (title, author, a word the refusal must NAME) -- cause named, not just red:
        ("The title rule was held by prose alone", "", "prefix"),                     # full-sentence drift shape
        ("Pin sweep to a new baseline", "", "prefix"),                                # short headline, no type
        ("Sentence case arrived and nothing refused it", "", "prefix"),               # the drift, verbatim in spirit
        ("build(deps-dev): Bump pytest from 8.4.1 to 9.0.3", "", "capitalized"),      # same title, NO exempt author
        ("docs: The summary opens with sentence case", "", "capitalized"),            # sentence case behind a prefix
        ("fix: the trailing period arrives.", "", "period"),
        ("feat(adr-preconditions): a scope list is compared against the computed population, red in both directions, again", "", "characters"),  # 112 chars, measured
        ("Fix: the type must be lowercase", "", "prefix"),                            # capitalized type
    ]

    failed = 0
    for title, author in passes:
        if judge(title, author):
            print(f"SELF-TEST FAIL: should pass but was refused: {title!r}")
            failed += 1
    for title, author, must_name in refusals:
        problems = judge(title, author)
        if not problems:
            print(f"SELF-TEST FAIL: should be refused but passed: {title!r}")
            failed += 1
        elif not any(must_name in p for p in problems):
            print(f"SELF-TEST FAIL: refused, but no cause names '{must_name}': {title!r} -> {problems}")
            failed += 1

    if failed:
        print(f"self-test: {failed} case(s) FAILED")
        return 1
    print(f"self-test OK: {len(passes)} pass, {len(refusals)} refusals, every refusal naming its cause")
    return 0


if __name__ == "__main__":
    sys.exit(main())
