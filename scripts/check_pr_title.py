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

EACH COMMIT IN THE PULL REQUEST, given `--commits`. Where a pull request
merges with a merge commit, every commit on its branch lands on the default
branch with its subject as written, so the subject is a git artifact too. The
convention for commit subjects was written down and never checked: a branch
carrying a commit called `hotfix` passed every check. Each non-merge commit's
subject, read as git reads it (the first paragraph, its lines joined), is
judged by the title's form rules (1, 2 and 4 above), with two differences:

  * No length cap. Rule 3 was calibrated on titles; no rule caps a subject,
    and the default branch's subjects run past it routinely.
  * `revert` is a type, beside GitHub's and git's own `Revert "` shape. A
    pull request that reverts is titled under the title's types, as before.

and one rule of its own:

  5. The commit has a body beyond its trailers. A trailer is a `Token: value`
     line (an indented line folds into the one above it), and a trailing
     paragraph made only of them is not a body, so a message carrying only
     `Autoclose:` and `Co-Authored-By:` is refused. So is a body whose one
     paragraph is a `Note: ...` line, which git's trailer parser reads as a
     trailer too. A `Revert "` commit still needs its body.

A merge commit is skipped and counted: bringing a branch up to date by merging
the default branch into it writes one, and its subject is git's. A refusal
names each commit by its sha and subject. The machine-author exemption covers
the pull request's commits as it covers its title, and prints when it applies.

`--commits` is a file holding one JSON object per line, `sha`, `parents` (a
count) and `message`, as the pull request's commits listing prints them. A
read that saw no commit is refused, because a pull request always carries
one. So is a read whose count differs from `--commits-expected`: a short
listing is also what a token that cannot see, or a listing that stopped early
(the endpoint returns at most 250), returns, and a long one means the branch
moved after the event. So is a listing that does not hold `--head-sha`. None
of them is a verdict on the commits.

CHECK A BRANCH BEFORE PUSHING IT. A pushed commit stays in the pull request,
so a refused one is cheapest to fix before the push. `--git-range` judges the
commits `git log` names, as the listing would show them:

    python3 check_pr_title.py --git-range origin/main..HEAD

A REFUSED COMMIT ALREADY PUSHED is not rewritten on its branch: a branch with
a pull request is not rebased or force-pushed, because its review and its
comments cite its commits. The commits are reworded on a new branch, a new
pull request is opened from it, and the old one is closed. A refusal that
names a commit prints that remedy.

WHAT IT DELIBERATELY DOES NOT DO. It does not judge the summary's content, and
"one clause" stays prose: history is full of comma-joined clauses that
read fine, so a mechanical clause count would refuse history to no gain. A
two-scope `docs(a,b):` is refused for a commit as for a title. Issue
titles carry the same convention in AGENTS.md but nothing gates issue creation;
this guard binds the surface CI can reach.

    python3 check_pr_title.py --title "docs: the title under judgement"
    python3 check_pr_title.py --title "..." --author "dependabot[bot]"
    python3 check_pr_title.py --title "..." --commits commits.jsonl --commits-expected 3 --head-sha <sha>
    (the action passes the title through the environment, never interpolated
    into shell -- a title is attacker-adjacent text on a public repo)
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys
import tempfile

TYPES = ("build", "chore", "ci", "docs", "feat", "fix", "perf", "probe", "refactor", "test")

#: A commit subject's types: the title's, and `revert`, which the default
#: branch's history uses for a commit that undoes another.
COMMIT_TYPES = TYPES + ("revert",)


def _prefix(types: tuple[str, ...]) -> re.Pattern[str]:
    return re.compile(
        r"^(?P<type>" + "|".join(types) + r")"
        r"(?:\((?P<scope>[a-z0-9._-]+)\))?"
        r"!?: (?P<summary>\S.*)$"
    )


PREFIX = _prefix(TYPES)
COMMIT_PREFIX = _prefix(COMMIT_TYPES)

#: A trailer line, `Token: value`, as git reads one.
TRAILER = re.compile(r"^[A-Za-z][A-Za-z0-9-]*: \S")

REVERT_SHAPE = 'Revert "'

#: A capitalized ordinary word: sentence case, the drift's actual shape.
#: `CI_DEPLOY_KEY's` / `ADR-0001` / `.gitattributes` / bare `I` all miss
#: this pattern on purpose -- an identifier is not a sentence opener.
SENTENCE_CASE = re.compile(r"^[A-Z][a-z]+$")

MAX_LEN = 100

EXEMPT_AUTHORS = ("dependabot[bot]",)


def judge_form(line: str, commit: bool = False) -> list[str]:
    """Rules 1, 2 and 4 on one headline: a title, or a commit's subject."""
    if commit:
        types, prefix, noun = COMMIT_TYPES, COMMIT_PREFIX, "subject"
        why, body = "A commit subject lands on the default branch as written", "the commit body"
    else:
        types, prefix, noun = TYPES, PREFIX, "title"
        why, body = "A PR title is the merge commit history cites as #N", "the PR body"
    problems: list[str] = []
    m = prefix.match(line)
    if not m:
        problems.append(
            f"no conventional prefix. {why}; "
            f"start it `type(scope): summary` with type one of: {', '.join(types)} "
            "(lowercase type and scope, `!` before the colon for a breaking change)."
        )
        return problems
    summary = m.group("summary")
    first = summary.split(" ", 1)[0].rstrip(",.:;")
    if SENTENCE_CASE.fullmatch(first):
        problems.append(
            f"the summary opens with a capitalized ordinary word ('{first}') -- sentence case. "
            "Lowercase it; identifiers (CI_DEPLOY_KEY, ADR-0001, .gitattributes) are fine as they are."
        )
    if summary.rstrip().endswith("."):
        problems.append(
            f"trailing period. The {noun} is a headline; the sentence belongs in {body}."
        )
    return problems


def judge(title: str, author: str = "") -> list[str]:
    """Every violation in the title, empty when it conforms."""
    if author in EXEMPT_AUTHORS:
        print(f"exempt: author '{author}' writes its own titles upstream; "
              "its prefix is per-repo configuration and its capitalization is not.")
        return []
    if title.startswith(REVERT_SHAPE):
        print("pass: GitHub's own revert shape; the quoted title was judged when it merged.")
        return []

    problems = judge_form(title)
    if len(title) > MAX_LEN:
        problems.append(
            f"{len(title)} characters; the cap is {MAX_LEN} -- "
            "move the second clause into the body."
        )
    return problems


def paragraphs_of(message: str) -> list[list[str]]:
    """The message's paragraphs, each a list of its non-blank lines."""
    paragraphs: list[list[str]] = [[]]
    for line in message.split("\n"):
        if line.strip():
            paragraphs[-1].append(line)
        elif paragraphs[-1]:
            paragraphs.append([])
    return [p for p in paragraphs if p]


def subject_of(message: str) -> str:
    """The subject as git reads it (`%s`): the first paragraph, its lines joined by spaces."""
    paragraphs = paragraphs_of(message)
    return " ".join(line.strip() for line in paragraphs[0]) if paragraphs else ""


def is_trailers(paragraph: list[str]) -> bool:
    """A paragraph of `Token: value` lines, a line opening with whitespace
    continuing the one above it, as git folds a trailer."""
    return bool(TRAILER.match(paragraph[0])) and all(
        TRAILER.match(line) or line[:1].isspace() for line in paragraph
    )


def has_body(message: str) -> bool:
    """Rule 5: a paragraph past the subject that is not in a trailing run of
    trailer paragraphs. A lone `Note: ...` paragraph reads as a trailer, as it
    does to git, so it is not a body."""
    paragraphs = paragraphs_of(message)[1:]
    while paragraphs and is_trailers(paragraphs[-1]):
        paragraphs.pop()
    return bool(paragraphs)


def judge_commit(message: str) -> list[str]:
    """Every violation in one non-merge commit's message, empty when it conforms."""
    subject = subject_of(message)
    problems: list[str] = []
    if not subject.startswith(REVERT_SHAPE):
        problems = judge_form(subject, commit=True)
    if not has_body(message):
        problems.append(
            "no body beyond trailers. Say why the change is made, under the subject and above the trailers."
        )
    return problems


#: One commit as the listing gives it: sha, parent count, message.
Commit = tuple[str, int, str]

#: The most commits the pull request commits listing returns.
LISTING_CAP = 250


def read_commit(number: int, line: str) -> Commit:
    """One listing line, or ValueError naming it: never a skipped commit."""
    record = json.loads(line)
    shaped = (
        isinstance(record, dict)
        and isinstance(record.get("sha"), str)
        and type(record.get("parents")) is int
        and isinstance(record.get("message"), str)
    )
    if not shaped:
        raise ValueError(
            f"line {number} is not an object carrying a string sha, an integer parents and "
            f"a string message: {line[:80]!r}"
        )
    return record["sha"], record["parents"], record["message"]


def read_commits(text: str) -> list[Commit]:
    """The pull request's commits, one JSON object per line. Split on newlines
    only: a message may carry a character str.splitlines() would break on."""
    return [read_commit(n, line) for n, line in enumerate(text.split("\n"), 1) if line.strip()]


def unread(commits: list[Commit], expected: int | None, head: str) -> str:
    """Why the listing is no verdict on the pull request, or empty when it is one."""
    read = len(commits)
    if not read:
        return "read 0 commit(s); a pull request always carries one, so the read was blind."
    if expected is not None and read < expected:
        cap = f" The listing returns at most {LISTING_CAP}." if expected > LISTING_CAP else ""
        return (f"read {read} commit(s) where the pull request carries {expected}. A short read is also "
                f"what a token that cannot see returns, so it is no verdict on the commits.{cap}")
    if expected is not None and read > expected:
        return (f"read {read} commit(s) where the event counted {expected}: the branch moved after the "
                "event, and the run for its newer head is the one that decides.")
    if head and head not in {sha for sha, _, _ in commits}:
        return (f"the listing does not hold the head this run is for, {head[:12]}: the branch moved "
                "after the event, and the run for its newer head is the one that decides.")
    return ""


def judge_commits(commits: list[Commit], expected: int | None, head: str = "") -> list[str]:
    """Every refusal across the commits, each naming its commit; empty when all conform."""
    reason = unread(commits, expected, head)
    if reason:
        return [reason]
    refusals: list[str] = []
    merges = 0
    for sha, parents, message in commits:
        if parents > 1:
            merges += 1
            continue
        for problem in judge_commit(message):
            refusals.append(f"commit {sha[:12]} {subject_of(message)!r}: {problem}")
    print(f"commits: judged {len(commits) - merges} non-merge commit(s), skipped {merges} merge commit(s).")
    return refusals


def judge_listing(text: str, expected: int | None, head: str = "") -> list[str]:
    """A commits file's text to its refusals."""
    try:
        return judge_commits(read_commits(text), expected, head)
    except ValueError as error:
        return [f"the commits file could not be read, so no commit was judged: {error}"]


def judge_pr(title: str | None, author: str, text: str | None, expected: int | None, head: str) -> list[str]:
    """What main() runs: the title when given, then the commits when given,
    the machine-author exemption covering both."""
    problems = [] if title is None else judge(title, author)
    if text is None:
        return problems
    if author in EXEMPT_AUTHORS:
        print(f"exempt: the commits of a pull request by '{author}' are not judged either.")
        return problems
    return problems + judge_listing(text, expected, head)


def git_listing(revisions: str, cwd: str = ".") -> str:
    """The commits `git log <revisions>` names, as the listing prints them,
    so an author can check a branch before pushing it."""
    out = subprocess.run(
        ["git", "log", "--format=%H%x00%P%x00%B%x1e", revisions],
        cwd=cwd, capture_output=True, check=True, text=True, encoding="utf-8",
    ).stdout
    lines = []
    for record in out.split("\x1e"):
        if record.strip("\n"):
            sha, parents, message = record.strip("\n").split("\x00", 2)
            lines.append(json.dumps({"sha": sha, "parents": len(parents.split()), "message": message}))
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--title", help="the pull-request title to judge")
    parser.add_argument("--author", default="", help="the PR author's login, for the machine-author exemption")
    parser.add_argument("--commits", help="a file of the pull request's commits, one JSON object per line")
    parser.add_argument("--commits-expected", type=int, help="how many commits the pull request carries")
    parser.add_argument("--head-sha", default="", help="the head commit the run is for; the listing must hold it")
    parser.add_argument("--git-range", help="judge the commits `git log` names instead, e.g. origin/main..HEAD")
    parser.add_argument("--self-test", action="store_true", help="prove the guard fires and goes quiet")
    args = parser.parse_args()

    if args.self_test:
        return self_test()
    if args.title is None and args.commits is None and args.git_range is None:
        parser.error("give --title, --commits or --git-range outside --self-test")

    text = None
    if args.git_range is not None:
        text = git_listing(args.git_range)
    elif args.commits is not None:
        with open(args.commits, encoding="utf-8") as handle:
            text = handle.read()
    problems = judge_pr(args.title, args.author, text, args.commits_expected, args.head_sha)
    shown = args.title if args.title is not None else args.git_range or args.commits
    sys.stdout.flush()
    if not problems:
        print(f"pr-title OK: {shown!r}")
        return 0
    print(f"pr-title REFUSED: {shown!r}", file=sys.stderr)
    for p in problems:
        print(f"  - {p}", file=sys.stderr)
    if any(p.startswith("commit ") for p in problems):
        print(REMEDY, file=sys.stderr)
    return 1


#: Printed under a refusal that names a commit: what its author does next.
REMEDY = (
    "To fix a refused commit already pushed: do not rebase or force-push this branch, whose review "
    "and comments cite its commits. Reword the commits on a new branch, open a new pull request from "
    "it, and close this one. Check a branch before pushing it with "
    "`check_pr_title.py --git-range origin/main..HEAD`."
)


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
        ("revert(ci): the probe step comes back out", "", "prefix"),                  # `revert` is a commit type only
    ]
    failed = sum(
        verdict_wrong(repr(title), judge(title, author), must_name)
        for title, author, must_name in [(t, a, "") for t, a in passes] + refusals
    )
    failed += commit_cases() + pr_cases() + cli_cases()
    cases = (len(passes) + len(refusals) + len(COMMIT_PASSES) + len(COMMIT_REFUSALS) + len(LISTINGS)
             + len(PR_CASES) + len(CLI_CASES) + 1)
    if failed:
        print(f"self-test: {failed} of {cases} case(s) FAILED")
        return 1
    print(f"self-test OK: {cases} cases, titles, commits, listings and the command line, every refusal naming its cause")
    return 0


def verdict_wrong(case: str, problems: list[str], must_name: str) -> int:
    """1 when a case's verdict is wrong: `must_name` empty means it must pass,
    otherwise it must be refused by a cause that names `must_name`."""
    if not must_name and problems:
        print(f"SELF-TEST FAIL: should pass but was refused: {case} -> {problems}")
        return 1
    if must_name and not problems:
        print(f"SELF-TEST FAIL: should be refused but passed: {case}")
        return 1
    if must_name and not any(must_name in p for p in problems):
        print(f"SELF-TEST FAIL: refused, but no cause names '{must_name}': {case} -> {problems}")
        return 1
    return 0


BODY = "\n\nThe reason the change is made, in a sentence.\n"
TRAILERS = "\n\nAutoclose: none\n\nCo-Authored-By: A Contributor <a@example.invalid>\n"

#: Commit messages that must pass: each pins one way history's legitimate
#: commits differ from a title.
COMMIT_PASSES = [
    "revert(ci): the probe step comes back out" + BODY,                          # revert is a commit type
    "docs(readme): " + "a subject past the title's cap " * 4 + BODY,           # 134 chars: no cap
    'Revert "feat(ci): judge the title from the environment"\n\nThis reverts commit 0123abc.\n',
    "docs: CI_DEPLOY_KEY's rotation is recorded" + BODY + TRAILERS,              # identifier opener, trailers
    "fix: the note line is prose\n\nNote: a body may open with a colon after a word.\n\nMore of it.\n",
    "fix: a body in CRLF\r\n\r\nThe reason, written on another platform.\r\n",
]

#: (message, a word the refusal must NAME).
COMMIT_REFUSALS = [
    ("hotfix", "prefix"),                                                         # the outside contributor's shape
    ("hotfix" + BODY, "prefix"),                                                  # a body does not rescue the subject
    ("docs(runbook,features): two scopes in one" + BODY, "prefix"),              # one scope, as for a title
    ("docs: The summary opens with sentence case" + BODY, "capitalized"),
    ("fix: the trailing period arrives." + BODY, "period"),
    ("fix: a subject\nThe Second Line Is Still The Subject." + BODY, "period"),  # git joins the first paragraph
    ("fix: a subject and nothing under it", "body"),
    ("fix: a subject and trailers only" + TRAILERS, "body"),                      # trailers are not a body
    ("fix: a folded trailer\n\nCo-Authored-By: A Contributor\n  <a@example.invalid>\n", "body"),
    ("fix: a lone note\n\nNote: the cache was stale, so it is cleared.\n", "body"),  # git reads it as a trailer too
    ('Revert "feat: a change"', "body"),                                          # a revert still needs its body
    ("Update README.md", "prefix"),                                               # the web editor's default
]


def listing(*records: tuple[str, int, str]) -> str:
    return "\n".join(json.dumps({"sha": s, "parents": p, "message": m}) for s, p, m in records) + "\n"


GOOD = ("a" * 40, 1, "feat: a commit in form" + BODY)
HOTFIX = ("b" * 40, 1, "hotfix")
MERGE = ("c" * 40, 2, "Merge branch 'main' into feat/x")
BUMP = ("e" * 40, 1, "build(deps): Bump a package from 1 to 2" + BODY)
#: A message carrying U+0085, which gh writes unescaped and splitlines() breaks on.
NEL = json.dumps({"sha": "d" * 40, "parents": 1, "message": "feat: a next line" + BODY + "\x85here\n"},
                 ensure_ascii=False) + "\n"

#: (a commits file's text, expected count or None, head sha, a word the refusal must NAME).
LISTINGS = [
    (listing(GOOD, MERGE), 2, "", ""),                                            # a merge commit is skipped
    (listing(GOOD, HOTFIX), 2, "", "b" * 12),                                     # refused BY SHA
    (listing(GOOD, HOTFIX), 2, "", "'hotfix'"),                                   # and by subject
    (listing(GOOD), 2, "", "read 1"),                                             # a short read is no verdict
    (listing(GOOD, MERGE), 1, "", "moved after"),                                 # nor is a long one
    (listing(GOOD), 300, "", "at most 250"),                                      # the endpoint's cap is named
    ("", None, "", "read 0"),                                                     # nor is an empty one
    (listing(GOOD), 1, "f" * 40, "does not hold the head"),                       # nor one without the head
    (listing(GOOD), 1, "a" * 40, ""),                                             # the head is in it
    (NEL, 1, "", ""),                                                             # a next-line character reads
    ('{"sha": "d"}\n', 1, "", "could not be read"),                               # a malformed line is an error
    ('{"sha": "d", "parents": null, "message": "x"}\n', 1, "", "could not be read"),
]

#: (title or None, author, listing, a word the refusal must NAME), through judge_pr().
PR_CASES = [
    ("chore(deps): bump a package", "dependabot[bot]", listing(BUMP), ""),       # the exemption covers commits
    ("chore(deps): bump a package", "someone", listing(BUMP), "capitalized"),    # and only for that author
    (None, "", listing(GOOD, HOTFIX), "'hotfix'"),                                # commits alone, no title
]


def commit_cases() -> int:
    failed = sum(verdict_wrong(repr(m[:40]), judge_commit(m), "") for m in COMMIT_PASSES)
    failed += sum(verdict_wrong(repr(m[:40]), judge_commit(m), name) for m, name in COMMIT_REFUSALS)
    failed += sum(
        verdict_wrong(f"listing {text[:40]!r}", judge_listing(text, expected, head), name)
        for text, expected, head, name in LISTINGS
    )
    return failed


def pr_cases() -> int:
    return sum(
        verdict_wrong(f"pull request by {author!r}", judge_pr(title, author, text, None, ""), name)
        for title, author, text, name in PR_CASES
    )


#: (arguments after the commits file, the listing, exit status, a word stderr must NAME):
#: main()'s own wiring, run as a process.
CLI_CASES = [
    (["--title", "feat: x", "--commits-expected", "2"], listing(GOOD), 1, "read 1"),
    (["--title", "feat: x", "--head-sha", "f" * 40], listing(GOOD), 1, "does not hold the head"),
    (["--title", "feat: x", "--author", "dependabot[bot]"], listing(HOTFIX), 0, ""),
    (["--title", "feat: x"], listing(HOTFIX), 1, "'hotfix'"),
    (["--title", "feat: x"], listing(HOTFIX), 1, "Reword the commits on a new branch"),  # the remedy prints
]


def cli_cases() -> int:
    failed = 0
    with tempfile.TemporaryDirectory() as tmp:
        path = pathlib.Path(tmp, "commits.jsonl")
        for extra, text, status, name in CLI_CASES:
            path.write_text(text, encoding="utf-8", newline="\n")
            run = subprocess.run([sys.executable, __file__, "--commits", str(path), *extra],
                                 capture_output=True, text=True, encoding="utf-8")
            if run.returncode != status or name not in run.stderr:
                print(f"SELF-TEST FAIL: {extra} exited {run.returncode}, not {status}, or named no '{name}': "
                      f"{run.stderr.strip()[:200]}")
                failed += 1
        failed += git_range_case(tmp)
    return failed


def git_range_case(tmp: str) -> int:
    """--git-range, run as a process in a real repository, reads its commits
    as the listing does: the `hotfix` is refused, and git's own merge commit,
    whose subject is not in form, is skipped as a merge."""
    repo = pathlib.Path(tmp, "repo")
    repo.mkdir()
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-C", str(repo)]
    for step in (["init", "-q", "-b", "main"],
                 ["commit", "-q", "--allow-empty", "-m", "feat: a commit in form" + BODY],
                 ["switch", "-q", "-c", "side"],
                 ["commit", "-q", "--allow-empty", "-m", "hotfix"],
                 ["switch", "-q", "main"],
                 ["commit", "-q", "--allow-empty", "-m", "fix: another commit in form" + BODY],
                 ["merge", "-q", "--no-ff", "--no-edit", "side"]):
        subprocess.run([*git, *step], check=True, capture_output=True)
    run = subprocess.run([sys.executable, __file__, "--git-range", "HEAD"], cwd=repo,
                         capture_output=True, text=True, encoding="utf-8")
    if run.returncode != 1 or "'hotfix'" not in run.stderr or "Merge" in run.stderr:
        print(f"SELF-TEST FAIL: --git-range exited {run.returncode}, or named no 'hotfix' or named the merge: "
              f"{run.stderr.strip()[:200]}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
