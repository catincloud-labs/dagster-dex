#!/usr/bin/env python3
"""The Power of 10 is read per class against a tree: findings, deviations, and a baseline that only shrinks.

WHY THIS EXISTS. The estate's coding standard is JPL's Power of 10
(Holzmann, 2006), tailored to Python by a disposition of each rule and
applied per software ITEM at a class set by what a failure of that item
reaches - A reaches a guarantee or a stranger, B reaches production, C
reaches a pipeline run and stops. A rule of the estate exists ONLY where a
check reads it and refuses: this file, against the tree, or an item's own
suite, whose presence this file reads. A rule neither reads is not a rule,
whatever a prose file says. This docstring is the public statement of the
rules, and a suite's `Measures:` line names it by file and rule number.

THE RULES, per class - each of Holzmann's rules as the estate keeps it, and
nothing more:

  rule 1   no direct recursion (a function whose body calls its own bare name,
           or `self.<its name>`)                          A, B refused; C not read
  rule 2   a `while` whose test is a constant true       A, B refused; C not read
  rule 3   an item that reads input another node produced (another owner of
           mutable state, by any channel) states a maximum, and refuses past
           it before reading the rest                     A read by the item's
                                                          own suite; B, C not read
  rule 4   cyclomatic ceiling                             A 10; B 15; C 15
  rule 4   statement ceiling                              A 40; B 60; C not read
  rule 5   a module checks the facts it holds by construction when it loads,
           with an explicit `raise`, never `assert`, and a case plants a
           wrong fact and sees the import raise           A read by the item's
                                                          own suite; B, C not read
  rule 6   the `global` statement, the `nonlocal` statement, and a mutable
           default argument                               A, B refused; C not read
  rule 7   a bare `except`, a blind `except Exception`, and a bare or blind
           handler whose body is `pass`                   A, B refused; C not read
           (a TYPED handler with `pass` is not read)
  rule 7   types: strict for A, the tool's default for B  C not read
  rule 8   `eval` / `exec`                                A, B refused; C not read
  rule 9   a name computed at run time that yields something called or
           loaded: `import_module` or `__import__`, by bare name or as an
           attribute, whose first argument is not a constant, and a call on
           the result of a `getattr` whose name is not a
           constant                                       A refused; B, C not read
  rule 10  zero findings is the passing state, and the tools are pinned with
           a mover                                        A, B, C

The tools are ruff (rules 4, 6, 7, 8) and mypy (types), pinned by version in
`requirements.txt` beside this file and moved by Dependabot's `pip`
ecosystem (rule 10). Rules 1, 2, 6's `nonlocal` and 9 have no ruff code, so
they are read from the AST here and carry the code-shaped names POT001,
POT002, POT003 and POT004. Ruff's `noqa` parser passes those silently unless
a run selects RUF102, which names each one an invalid code (measured, ruff
0.17.4).

THE OWN-SUITE READERS, rules 3 and 5. Each is a property of what an item
publishes or holds, so the item's own suite reads it, as a control holding a
violator the rule refuses, and this file reads that the reader is present.
For every class A prefix the caller declares, `power-of-ten.json` at the
tree root holds an entry keyed by that prefix:

    {"src": {"rule 3": {"reads": ["the answer frame a peer sends"],
                        "readers": [{"check": "tests/test_frame.py::test_max",
                                     "violator": "tests/test_frame.py::OVER"}]},
             "rule 5": {"readers": [{"check": "tests/test_load.py",
                                     "violator": "tests/test_load.py::WRONG"}]}}}

  For rule 3 the item lists what it reads from another node, or says
  `"none"`, and an item that reads none names no reader. Rule 5 always names
  one. A pointer is a path from the tree root, optionally `::<name>` of a
  function, class or assignment in that file, as a pytest node id reads:
  `A::b` is a `b` defined inside `A`. A reader RESOLVES when its check is a
  file under the tree's root, symlinks and `..` followed, that defines the
  name; when the check - the named definition, or else the whole file -
  holds a line reading `Measures: scripts/check_power_of_ten.py, rule <n>`
  and nothing else but its indent and a leading `#`, with <n> the rule it is
  declared under; when the check's text names its violator, as a whole word,
  by the violator's last `::` part or else its file's name; and when the
  violator is a file under the tree's root that defines the name. The files
  are read from the working tree, so an untracked file resolves. The suite
  runs the check. This file reads only that the reader is there.

HOW THE POPULATION AND THE CLASSES ARE DERIVED

  The population is every `.py` blob in the tree - read through the git
  index when the tree is a work tree, so an ignored virtualenv is not a
  population, and walked when it is a bare directory - never a list of
  files. Zero files is a REFUSAL: a matcher that found nothing rotted or was
  pointed at the wrong directory.

  The classes are DECLARED by the caller as path prefixes, the way the test
  action takes its interpreter: `--class-a`, `--class-b`, `--class-c`. A
  file under no declared prefix is class C. The longest matching prefix
  wins, so a class C carve-out inside a class B tree is one more prefix. A
  test path (a `tests/` directory anywhere, `test_*.py`, `conftest.py`) is
  class C wherever it sits, per the record. The declaration is printed in
  every run, because the record prices it as a registry that fails open: a
  repository declaring its service code class C is green at the wrong
  ceiling and nothing here says so.

DEVIATIONS AND THE BASELINE - the record's two site-level shapes

  A deviation is a suppression at the site that NAMES the rule and carries a
  reason in the same line: `# noqa: BLE001 -- closing a dead connection`, or
  `# type: ignore[attr-defined]  # the driver is untyped`. Ruff is run with
  `--ignore-noqa` and every finding it can see is read here, so this file is
  the ONE reader of suppressions: a `noqa` that names no rule, or names one
  of this check's rules with no reason, or names a rule the line does not
  break, is itself red. (Mypy applies `type: ignore` itself; this reader
  counts those and refuses one with no error code or no reason. Under
  `--strict`, class A, mypy refuses an unused one.) A suppression naming
  only a rule this check does not read is not this check's business and is
  left alone. The deviation count is emitted per class in every summary.

  The baseline is adopted code: a deviation whose reason is the literal
  `predates ADR-0042` followed by the issue that owes the fix. Every marker
  site is counted per class - that count IS the to-update list, and
  `git grep -n 'predates ADR-0042'` lists the lines (over-reading only where
  the literal sits in a string or a docstring, as it does in this file). A
  marker with no owing issue, or a marker in a comment that is not a
  suppression, is red, so a green run's count is the count of real sites.

THE RATCHET. On a pull request the check reads the base commit's marker
count per class - the candidate blobs named by `git grep` on the base
tree-ish, each then read with the SAME suppression reader as the head and
classified by the head's declaration - and REFUSES any class whose count
rose. A marker may be
removed by anyone and added by nobody - after the migration. The check knows
a migration from a later change by reading the BASE's workflows: the ratchet
runs only when the base already calls this action (a `uses:` of it, or a
`run:` of this script by name). The migration pull request is the one change
whose base does not, so it is the one change allowed to add markers, and
nothing anyone can set in the head decides that.

WHAT IS RED AND WHAT IS REPORTED

  - A finding in a rule the file's class reads, not suppressed at the site:
    RED. Zero findings is the passing state.
  - A suppression that names no rule, gives no reason, or is unused; a
    marker with no owing issue; a marker outside a suppression: RED. A
    stale or blind claim is worse than none - it is the green tick this
    estate exists to distrust.
  - The ratchet: RED where any class's count rose against the base.
  - An own-suite reader: RED where a class A item has no declaration, no
    entry, no rule, no `reads` for rule 3, or no reader; where a declared
    reader does not resolve; where the declaration does not parse or is not
    the shape above; and where it holds an entry for a prefix the caller
    does not declare class A, a stale claim being worse than none.
  - An empty population, a tool that crashed, a file that does not parse,
    a base that cannot be read, a tool the interpreter cannot load: a
    REFUSAL, exit 1, never an empty success.
  - The deviation and baseline counts per class: REPORTED on every run,
    green or red, so a baseline standing still and a standard being
    suppressed away are numbers a reader sees rather than remembers.

JUDGEMENTS THE RECORD LEFT TO THE BUILD, taken here and written down so a
later session does not re-derive them: an UNUSED suppression is red, not
reported, because it holds a count up with nothing behind it; a
repository's own ruff or mypy configuration is NOT consulted (`--isolated`,
an empty mypy config), because the rule is the estate's and a per-repository
setting that widens it is the registry the record refuses; the AST rules
follow a name, not a call graph - two functions calling each other pass,
and the record names that hole rather than closing it. Rule 9 follows a
name too: a call to any attribute named `import_module` or `__import__` is
read, whatever object holds it. Read only as those two shapes, it leaves
unread: a computed `getattr` stored in a variable and called later, an
attribute or a subscript of a computed `getattr` called (`getattr(m, n).run()`),
a constant relative import whose `package=` is computed, and a call through
`globals()[n]` or `__getattribute__(n)`. The own-suite declaration is a file
in the tree, not an input, so it changes in the same diff as the code it
describes, and a copy of this file run by a repository's own job reads it
exactly as the shared action does.

WHAT A GREEN HERE DOES NOT SAY. That the code is correct: a ceiling and a
type check catch a class of defect measured to be real, and price no
guarantee and read no falsifier. That the declaration is right: nothing
here compares the caller's class prefixes to the record's list, so an item
declared below its reach escapes the own-suite reader as it escapes the
rest. That a suite's reader is right: only that it is declared, carries its
line and names a violator that exists. That every loop is bounded: only the
constant-true half is read.

Run bare, never through a pipe - the exit code is the product. Needs ruff
and mypy importable by the running interpreter (`pip install -r
requirements.txt`).

    python3 check_power_of_ten.py --tree .                       # everything class C
    python3 check_power_of_ten.py --tree . --class-a src         # a class A package
    python3 check_power_of_ten.py --tree . --base-sha <sha>      # and the ratchet
"""

from __future__ import annotations

import argparse
import ast
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import tokenize
from collections import defaultdict
from pathlib import Path
from typing import Any, NamedTuple

ACTION_NAME = "power-of-ten"
MARKER = "predates ADR-0042"
CLASSES = ("A", "B", "C")
CEILING = {"A": 10, "B": 15, "C": 15}
STATEMENT_CEILING = {"A": 40, "B": 60}  # class C reads no statement ceiling
COMPLEXITY = "C901"
STATEMENTS = "PLR0915"
RECURSION = "POT001"
UNBOUNDED = "POT002"
NONLOCAL = "POT003"
COMPUTED = "POT004"
TYPES = "types"  # the pseudo-code a `type: ignore` names; mypy has no single code
RUFF_AB = ("PLW0603", "B006", "E722", "BLE001", "S110", "S307", "S102")
RULES = {
    COMPLEXITY: "rule 4, the cyclomatic ceiling",
    STATEMENTS: "rule 4, the statement ceiling",
    RECURSION: "rule 1, no direct recursion",
    UNBOUNDED: "rule 2, a `while` on a constant true states no bound",
    NONLOCAL: "rule 6, no `nonlocal`",
    COMPUTED: "rule 9, nothing called or loaded by a name computed at run time",
    "PLW0603": "rule 6, no `global`",
    "B006": "rule 6, no mutable default argument",
    "E722": "rule 7, no bare `except`",
    "BLE001": "rule 7, no blind `except Exception`",
    "S110": "rule 7, no bare or blind handler whose body is `pass`",
    "S307": "rule 8, no `eval`",
    "S102": "rule 8, no `exec`",
    TYPES: "rule 7, types (strict for class A, the tool's default for B)",
}
TEST_EXCLUDE = r"(^|/)(tests|test_[^/]*\.py|conftest\.py)($|/)"
READERS_FILE = "power-of-ten.json"  # the own-suite declaration, at the tree root
SUITE_RULES = {"rule 3": ("reads", "readers"), "rule 5": ("readers",)}  # rule -> the keys its entry takes
MEASURES = "Measures: scripts/check_power_of_ten.py, rule {n}"

_ISSUE = re.compile(r"#\d+")
_NOQA = re.compile(r"#\s*noqa\b(?P<tail>.*)$", re.IGNORECASE)
# A separator is a comma with the whitespace around it, or a whitespace run
# alone: each run splits one way, so a failing match cannot backtrack
# exponentially. `\s*[,\s]\s*` accepted the same separators in many splits.
_NOQA_CODES = re.compile(r"^\s*:\s*(?P<codes>[A-Z]+[0-9]+(?:(?:\s*,\s*|\s+)[A-Z]+[0-9]+)*)(?P<rest>.*)$")
_TYPE_IGNORE = re.compile(r"#\s*type:\s*ignore(?:\[(?P<codes>[^\]]*)\])?(?P<rest>.*)$")
_REASON_LEAD = re.compile(r"^[\s\-#:;,]+")
_MYPY_LINE = re.compile(r"^(?P<path>[^:\n]+?):(?P<line>\d+)(?::\d+)?: error: (?P<msg>.*)$")


class Refusal(RuntimeError):
    """Could not check. Which is not 'all clear', and never exits 0."""


class Finding(NamedTuple):
    path: str
    line: int
    code: str
    message: str
    noqa_row: int  # the line a suppression must sit on to cover it


class Suppression(NamedTuple):
    path: str
    line: int
    form: str  # the directive's form: a ruff-style one, or a mypy type-ignore
    codes: tuple[str, ...]
    reason: str


class Problem(NamedTuple):
    kind: str
    where: str
    detail: str


class ClassReport(NamedTuple):
    cls: str
    files: int
    findings: tuple[Finding, ...]  # the unsuppressed ones
    suppressed: int
    deviations: int
    baseline: int


class Outcome(NamedTuple):
    reports: dict[str, ClassReport]
    problems: list[Problem]
    ratchet: str  # what the ratchet did, in words
    base: dict[str, int] | None  # the base's marker count per class, when compared
    readers: tuple[str, ...] = ()  # each tool's own version line, or why it was not run
    presence: str = ""  # what the own-suite reader did, in words


Declared = dict[str, tuple[str, ...]]

EXPLANATIONS = {
    "finding": (
        "The file's class reads this rule and the site breaks it. Fix the site, "
        "or record a deviation there: a suppression naming the rule with the "
        "reason in the same line."
    ),
    "syntax": "The file does not parse, so nothing about its shape can be read.",
    "suppression-no-rule": (
        "A bare `# noqa` or a `# type: ignore` with no error code hides every "
        "rule at once. A deviation names the rule it deviates from."
    ),
    "suppression-no-reason": (
        "The suppression names a rule this check reads and says nothing about "
        "why. A deviation is a recorded event; the reason goes in the same line."
    ),
    "suppression-unused": (
        "The suppression names a rule the line does not break. It holds a "
        "deviation count up with nothing behind it; remove it."
    ),
    "baseline-no-issue": (
        f"A `{MARKER}` marker names the issue that owes the fix, or it is an "
        "exemption with no expiry."
    ),
    "baseline-stray": (
        f"`{MARKER}` outside a suppression that names a rule. The marker is a "
        "deviation's reason, not a free-standing comment; the count here and "
        "`git grep` must agree."
    ),
    "ratchet": (
        "The marker count rose against the base in this class. After the "
        "migration a marker may be removed by anyone and added by nobody: new "
        "code cannot be adopted code. Fix the site or record a deviation with "
        "its reason."
    ),
    "reader-undeclared": (
        "A class A item's own suite reads rules 3 and 5, so the item names a "
        f"reader for each in `{READERS_FILE}`, and for rule 3 lists what it reads "
        'from another node or says "none". A rule with no declared reader is a '
        "rule nobody can see being read."
    ),
    "reader-unresolved": (
        "The declared reader does not resolve. Its check is a file in the tree "
        f"holding `{MEASURES.format(n='<n>')}` on a line of its own - inside the "
        "named definition, not on a docstring's opening line or in a comment above "
        "it - and naming its violator; the violator is a file in the tree. A "
        "`::<name>` names a definition there, `A::b` a `b` inside `A`. A pointer "
        "at nothing is a stale claim."
    ),
    "reader-malformed": (
        f"`{READERS_FILE}` does not parse, or is not the shape this file's "
        "docstring gives, so nothing it declares can be read."
    ),
    "reader-orphan": (
        "An entry for a prefix the caller does not declare class A. A "
        "declaration for an item this run does not read is a stale claim: "
        "remove it, or declare the prefix."
    ),
}


# --- population and classes ----------------------------------------------------


def is_test_path(rel: str) -> bool:
    """A test path is class C wherever it sits, per the record."""
    parts = rel.split("/")
    name = parts[-1]
    return "tests" in parts[:-1] or name.startswith("test_") or name == "conftest.py"


def normalise_prefix(raw: str) -> str:
    p = raw.strip().replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p.strip("/")


def parse_declaration(class_a: str, class_b: str, class_c: str) -> Declared:
    """Whitespace-separated prefixes per class. One prefix in two classes is a refusal."""
    declared: Declared = {}
    seen: dict[str, str] = {}
    for cls, raw in (("A", class_a), ("B", class_b), ("C", class_c)):
        prefixes = tuple(sorted({normalise_prefix(p) for p in raw.split() if normalise_prefix(p)}))
        for p in prefixes:
            if p in seen:
                raise Refusal(f"'{p}' is declared class {seen[p]} and class {cls}; a path has one class")
            seen[p] = cls
        declared[cls] = prefixes
    return declared


def classify(rel: str, declared: Declared) -> str:
    if is_test_path(rel):
        return "C"
    best, best_len = "C", -1
    for cls, prefixes in declared.items():
        for p in prefixes:
            if (rel == p or rel.startswith(p + "/")) and len(p) > best_len:
                best, best_len = cls, len(p)
    return best


def population(tree: Path) -> list[str]:
    """Every `.py` blob in the tree - the index of a work tree, or a walk of a bare directory."""
    res = subprocess.run(
        ["git", "-C", str(tree), "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", "*.py"],
        capture_output=True,
    )
    if res.returncode == 0:
        names = (n.decode("utf-8", "replace") for n in res.stdout.split(b"\0") if n)
        return sorted(n for n in names if (tree / n).is_file())
    found: list[str] = []
    for p in tree.rglob("*.py"):
        rel = p.relative_to(tree)
        if any(part.startswith(".") or part == "__pycache__" for part in rel.parts[:-1]):
            continue
        found.append(rel.as_posix())
    return sorted(found)


# --- suppressions --------------------------------------------------------------


def read_comments(text: str) -> list[tuple[int, str]]:
    """(line, comment) for every comment token. Raises on a file that does not tokenize."""
    out: list[tuple[int, str]] = []
    for tok in tokenize.generate_tokens(io.StringIO(text).readline):
        if tok.type == tokenize.COMMENT:
            out.append((tok.start[0], tok.string))
    return out


def _reason(rest: str) -> str:
    return _REASON_LEAD.sub("", rest).strip()


def parse_suppression(path: str, line: int, comment: str) -> Suppression | None:
    m = _NOQA.search(comment)
    if m:
        c = _NOQA_CODES.match(m["tail"])
        if c:
            codes = tuple(x for x in re.split(r"[,\s]+", c["codes"].strip()) if x)
            return Suppression(path, line, "noqa", codes, _reason(c["rest"]))
        return Suppression(path, line, "noqa", (), _reason(m["tail"]))
    t = _TYPE_IGNORE.search(comment)
    if t:
        codes = tuple(x.strip() for x in (t["codes"] or "").split(",") if x.strip())
        return Suppression(path, line, "type-ignore", codes, _reason(t["rest"]))
    return None


def read_rules(cls: str) -> frozenset[str]:
    """The codes a class reads: C its cyclomatic ceiling; B the table but rule 9; A all of it.

    Per class, because whether a suppression is this check's business turns on
    it: a `noqa: POT004` in class B names a rule class B does not read, so it
    is left alone there, as any other rule this check does not read is.
    """
    if cls == "C":
        return frozenset({COMPLEXITY})
    ab = {COMPLEXITY, STATEMENTS, RECURSION, UNBOUNDED, NONLOCAL, TYPES, *RUFF_AB}
    return frozenset(ab | {COMPUTED} if cls == "A" else ab)


def is_baseline(sup: Suppression) -> bool:
    """A marker: names a rule, carries the literal, and names the issue after it. One definition, both sides of the ratchet."""
    return bool(sup.codes) and MARKER in sup.reason and bool(_ISSUE.search(sup.reason.split(MARKER, 1)[1]))


def relevant(sup: Suppression, cls: str) -> bool:
    """Could this suppression hide a rule the class reads?"""
    rules = read_rules(cls)
    if sup.form == "type-ignore":
        return TYPES in rules
    return not sup.codes or any(c in rules for c in sup.codes)


def apply_suppressions(findings: list[Finding], sups: list[Suppression]) -> tuple[list[Finding], int]:
    """A finding is covered by a `noqa` on its noqa row naming its code. Types are mypy's to cover."""
    named = {(s.path, s.line, c) for s in sups if s.form == "noqa" for c in s.codes}
    kept = [f for f in findings if f.code == TYPES or (f.path, f.noqa_row, f.code) not in named]
    return kept, len(findings) - len(kept)


def judge_suppressions(
    cls: str, sups: list[Suppression], findings: list[Finding]
) -> tuple[list[Problem], int, int]:
    """Problems, the deviation count, the baseline count - one reading of every suppression."""
    problems: list[Problem] = []
    deviations = baseline = 0
    broken = {(f.path, f.noqa_row, f.code) for f in findings}
    rules = read_rules(cls)
    for s in sups:
        marker = MARKER in s.reason
        if not marker and not relevant(s, cls):
            continue
        where = f"class {cls} {s.path}:{s.line}"
        if not s.codes:
            problems.append(Problem("suppression-no-rule", where, s.form))
            continue
        # Unused is judged for ruff's and the AST's codes, whose findings are
        # all in hand; mypy covers its own, and refuses an unused one under
        # --strict. A suppression with nothing behind it is red, and is not a
        # deviation - there is nothing it deviates from.
        unused = [c for c in s.codes if s.form == "noqa" and c in rules and (s.path, s.line, c) not in broken]
        if unused:
            problems.append(Problem("suppression-unused", where, ", ".join(unused)))
        if marker:
            if is_baseline(s):
                baseline += 1
            else:
                problems.append(Problem("baseline-no-issue", where, s.reason))
        elif not s.reason:
            problems.append(Problem("suppression-no-reason", where, f"{s.form}: {', '.join(s.codes)}"))
        elif not unused:
            deviations += 1
    return problems, deviations, baseline


# --- the readers: ruff, mypy, the AST ------------------------------------------


Interpreter = tuple[str, ...]
PYTHON: Interpreter = (sys.executable,)


def reader_version(tool: str, interpreter: Interpreter = PYTHON) -> str:
    """The tool's own version line, or a REFUSAL when the interpreter cannot load it.

    `python -m <tool>` with the tool absent exits 1 and says so on stderr only.
    1 is also the code both tools use for "findings present", so a reader that
    tolerates it and parses an empty stdout reports zero findings: a tree over
    its ceiling read green on an interpreter holding neither tool, while the
    AST rules beside them still fired and made the report look whole (measured
    2026-09-20). The probe asks the one question whose answer is not
    ambiguous, before any reader runs, and the answer is printed on every run
    so a log that was kept says which tool read the tree.
    """
    res = subprocess.run(
        [*interpreter, "-m", tool, "--version"], capture_output=True, text=True, encoding="utf-8",
        errors="replace",
    )
    line = (res.stdout.strip().splitlines() or [""])[0]
    if res.returncode != 0 or not line:
        said = (res.stderr.strip().splitlines() or ["nothing on stderr"])[-1][:300]
        raise Refusal(
            f"`{' '.join(interpreter)} -m {tool} --version` exited {res.returncode} ({said}). The rules "
            f"{tool} reads cannot be read without it, and a run that skips them is not a green: "
            "pip install -r requirements.txt, from the directory this file is in, into the "
            "interpreter running it."
        )
    return line


def reader_versions(need_mypy: bool, interpreter: Interpreter = PYTHON) -> tuple[str, ...]:
    """ruff reads every class; mypy reads A and B, and is asked for only when one has a file."""
    ruff = reader_version("ruff", interpreter)
    if not need_mypy:
        return (ruff, "mypy not run (no class A or B file)")
    return (ruff, reader_version("mypy", interpreter))


def ruff_findings(tree: Path, cls: str, files: list[str], interpreter: Interpreter = PYTHON) -> list[Finding]:
    select = [COMPLEXITY] + ([STATEMENTS, *RUFF_AB] if cls != "C" else [])
    config = ["--config", f"lint.mccabe.max-complexity={CEILING[cls]}"]
    if cls in STATEMENT_CEILING:
        config += ["--config", f"lint.pylint.max-statements={STATEMENT_CEILING[cls]}"]
    out: list[Finding] = []
    root = tree.resolve()
    for i in range(0, len(files), 200):
        cmd = [
            *interpreter, "-m", "ruff", "check", "--isolated", "--no-cache", "--quiet", "--ignore-noqa",
            "--select", ",".join(select), *config,
            "--output-format", "json", "--", *files[i : i + 200],
        ]
        res = subprocess.run(cmd, cwd=tree, capture_output=True, text=True, encoding="utf-8", errors="replace")
        # The JSON format prints `[]` on a clean read, so an empty stdout is a
        # ruff that did not run, whatever it exited: never an empty success.
        if res.returncode not in (0, 1) or not res.stdout.strip():
            raise Refusal(f"ruff exited {res.returncode} on class {cls}: {res.stderr.strip()[:400] or 'and printed nothing'}")
        for item in json.loads(res.stdout):
            rel = Path(item["filename"]).resolve().relative_to(root).as_posix()
            code = item["code"] or "syntax-error"
            row = item["location"]["row"]
            out.append(Finding(rel, row, code, item["message"], item.get("noqa_row") or row))
    return out


def ast_findings(rel: str, text: str, cls: str) -> list[Finding]:
    """Rules 1, 2, 6's `nonlocal` and, in class A only, 9: what ruff has no code for.

    The class is a parameter because rule 9 reads class A alone. A SyntaxError
    is the caller's to record.
    """
    out: list[Finding] = []
    for node in ast.walk(ast.parse(text)):
        found = _ast_finding(node, cls)
        if found:
            line = getattr(node, "lineno", 0)  # every node that can break a rule is a statement or a call
            out.append(Finding(rel, line, found[0], found[1], line))
    return out


def _ast_finding(node: ast.AST, cls: str) -> tuple[str, str] | None:
    """The code and message one node breaks, or None."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _calls_itself(node):
        return RECURSION, f"`{node.name}` calls itself"
    if isinstance(node, ast.While) and isinstance(node.test, ast.Constant) and bool(node.test.value):
        return UNBOUNDED, "`while` on a constant true"
    if isinstance(node, ast.Nonlocal):
        return NONLOCAL, f"`nonlocal {', '.join(node.names)}`"
    if cls == "A" and isinstance(node, ast.Call):
        return _computed_name(node)
    return None


def _callee(func: ast.expr) -> str:
    """The name a call is made by: a bare name, or the last attribute."""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _computed_name(call: ast.Call) -> tuple[str, str] | None:
    """Rule 9's two shapes, read from the call alone.

    An import by `import_module` or `__import__` whose first argument (or
    `name=`) is not a constant, and a call made directly on the result of a
    `getattr` whose name is not a constant. A starred argument is not a
    constant, so it is read as computed. A computed `getattr` stored and called
    later is a different node from the call, and is not read.
    """
    name = _callee(call.func)
    if name in ("import_module", "__import__"):
        first = call.args[0] if call.args else next((k.value for k in call.keywords if k.arg == "name"), None)
        if not isinstance(first, ast.Constant):
            return COMPUTED, f"`{name}` of a name computed at run time"
    inner = call.func
    if isinstance(inner, ast.Call) and _callee(inner.func) == "getattr":
        if len(inner.args) < 2 or not isinstance(inner.args[1], ast.Constant):
            return COMPUTED, "a call on the result of `getattr` of a name computed at run time"
    return None


def _calls_itself(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """A call to the bare name, or to `self.<name>`.

    `other.<name>` is a delegation and is not read - the record's eight
    candidates in class A were all of that shape. `cls.<name>` and
    `Class.<name>` are not read either: the rule follows a bare name, and a
    classmethod recursing through `cls` is a hole of the same kind as
    mutual recursion, named here rather than closed.
    """
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if isinstance(f, ast.Name) and f.id == fn.name:
            return True
        if (
            isinstance(f, ast.Attribute)
            and f.attr == fn.name
            and isinstance(f.value, ast.Name)
            and f.value.id == "self"
        ):
            return True
    return False


def mypy_targets(cls: str, declared: Declared, tree: Path) -> list[str]:
    return [p for p in declared.get(cls, ()) if (tree / p).exists()]


def _base_of(tree: Path, rel: str) -> Path:
    """The directory a module name is counted from, for one declared path.

    Walk the path from the tree root; the first directory carrying `__init__.py` is a
    package, and the module name starts there, so its parent is the base. A path with
    no package on it (`scripts/tool.py`, a directory that deliberately has none) is
    counted from the root, which is the name a package in the tree imports it by:
    `scripts.tool`. A directory declared whole with the package one level down
    (`src` holding `src/pkg/`) is counted from itself, so the package is `pkg`, the
    name its own modules import.
    """
    here = tree
    for part in Path(rel).parts:
        if (here / part / "__init__.py").is_file():
            return here
        here = here / part
    if here.is_dir() and any((here / c / "__init__.py").is_file() for c in os.listdir(here)):
        return here
    return tree


def package_bases(tree: Path, targets: list[str]) -> list[str]:
    """`MYPYPATH` for one class: the root, and every base a declared path needs.

    Together with `--explicit-package-bases` this gives a file one module name
    whichever way mypy meets it - passed by path, or imported by a package in the
    same tree. Without both, `scripts/tool.py` under a `scripts/` with no
    `__init__.py` is `tool` by path and `scripts.tool` by import, and mypy exits 2
    on "source file found twice" before reading a line, so a class B declaration
    naming a shipped script is refused rather than read. The flag alone is not
    enough: with only the root as a base a `src/` layout's `src/pkg/x.py` is
    `src.pkg.x`, its own `from pkg.y import` goes unresolved, and strict typing
    reports every value crossing that import as `Any` - a finding the same tree
    does not have when `src` is a base, so the flag alone moves a reading. mypy
    takes the longest base that holds a file, so listing the root beside `src`
    is safe. Both shapes are in the self-test, which is where a stranger
    reproduces them; the consumers they were measured on are not.
    """
    bases = [tree.resolve()] + [_base_of(tree, t).resolve() for t in targets]
    seen: list[str] = []
    for b in bases:
        if str(b) not in seen:
            seen.append(str(b))
    return seen


def mypy_findings(
    tree: Path, cls: str, targets: list[str], declared: Declared, interpreter: Interpreter = PYTHON
) -> list[Finding]:
    """Class A strict, class B at the tool's default; `--platform linux` because the hosts are.

    `--explicit-package-bases` with `MYPYPATH` from `package_bases`: see there.
    """
    if not targets:
        return []
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "mypy.ini"
        cfg.write_text("[mypy]\n", encoding="utf-8")
        cmd = [
            *interpreter, "-m", "mypy", "--config-file", str(cfg), "--cache-dir", tmp,
            "--platform", "linux", "--ignore-missing-imports", "--no-error-summary",
            "--no-color-output", "--show-error-codes", "--exclude", TEST_EXCLUDE,
            "--explicit-package-bases",
        ]
        if cls == "A":
            cmd.append("--strict")
        env = {**os.environ, "MYPYPATH": os.pathsep.join(package_bases(tree, targets))}
        res = subprocess.run(
            cmd + targets, cwd=tree, env=env, capture_output=True, text=True, encoding="utf-8",
            errors="replace",
        )
    if res.returncode not in (0, 1):
        raise Refusal(f"mypy exited {res.returncode} on class {cls}: {(res.stdout + res.stderr).strip()[:600]}")
    out: list[Finding] = []
    placed = 0
    for line in res.stdout.splitlines():
        m = _MYPY_LINE.match(line)
        if m:
            placed += 1
            rel = m["path"].replace("\\", "/")
            if classify(rel, declared) == cls:
                out.append(Finding(rel, int(m["line"]), TYPES, m["msg"], int(m["line"])))
        elif "error:" in line:
            raise Refusal(f"mypy said something this reader cannot place on a line: {line}")
    if res.returncode == 1 and not placed:
        # 1 is "errors found". With none on stdout it was not mypy that said so.
        raise Refusal(f"mypy exited 1 on class {cls} and named no error: {res.stderr.strip()[:400] or 'and printed nothing'}")
    return out


# --- one class ----------------------------------------------------------------


def read_class(
    tree: Path, cls: str, files: list[str], declared: Declared, interpreter: Interpreter = PYTHON
) -> tuple[ClassReport, list[Problem]]:
    findings: list[Finding] = []
    sups: list[Suppression] = []
    problems: list[Problem] = []
    readable: list[str] = []
    for rel in files:
        text = (tree / rel).read_text(encoding="utf-8", errors="replace")
        try:
            comments = read_comments(text)
            if cls != "C":
                findings += ast_findings(rel, text, cls)
        except (SyntaxError, tokenize.TokenError) as exc:
            # Reported once, here; the file is kept out of the tool runs so
            # the same defect does not come back as a second finding.
            problems.append(Problem("syntax", f"class {cls} {rel}", str(exc).splitlines()[0]))
            continue
        readable.append(rel)
        for line, comment in comments:
            s = parse_suppression(rel, line, comment)
            if s:
                sups.append(s)
            elif MARKER in comment:
                problems.append(Problem("baseline-stray", f"class {cls} {rel}:{line}", comment.strip()))
    if readable:
        findings += ruff_findings(tree, cls, readable, interpreter)
        if cls != "C":
            findings += mypy_findings(tree, cls, mypy_targets(cls, declared, tree), declared, interpreter)
    kept, suppressed = apply_suppressions(findings, sups)
    sp, deviations, baseline = judge_suppressions(cls, sups, findings)
    problems += sp
    for f in kept:
        hint = f"  (a suppression goes on line {f.noqa_row})" if f.noqa_row != f.line else ""
        problems.append(Problem("finding", f"class {cls} {f.path}:{f.line}", f"{f.code}  {f.message}{hint}"))
    return ClassReport(cls, len(files), tuple(kept), suppressed, deviations, baseline), problems


# --- the own-suite readers: rules 3 and 5 ----------------------------------------


def presence(tree: Path, declared: Declared) -> tuple[str, list[Problem]]:
    """Each class A item declares a reader for each rule its own suite reads, and each reader resolves.

    Resolved the way the known-negatives action resolves a pointer: the named
    file exists and holds what the declaration says it holds. Absence of the
    file is read only where a class A item is declared; a file with no class A
    item declared is read for orphans.
    """
    items = declared.get("A", ())
    path = tree / READERS_FILE
    if not path.is_file():
        if not items:
            return f"not read: no class A item is declared and there is no {READERS_FILE}", []
        missing = [Problem("reader-undeclared", f"class A {p}", f"no {READERS_FILE} at the tree root") for p in items]
        return f"REFUSED: no {READERS_FILE}", missing
    data, wrong = _load_declaration(path)
    if wrong:
        return f"REFUSED: {READERS_FILE} cannot be read", [Problem("reader-malformed", READERS_FILE, wrong)]
    problems = [
        Problem("reader-orphan", f"{READERS_FILE} {k!r}", "no class A prefix of that name is declared")
        for k in data
        if k not in items
    ]
    for prefix in items:
        problems += _read_item(tree, prefix, data.get(prefix))
    verdict = "REFUSED" if problems else "resolved"
    return f"{verdict}: {len(items)} class A item(s) read against {READERS_FILE}", problems


def _load_declaration(path: Path) -> tuple[dict[str, Any], str]:
    """The declaration, or why it cannot be read: it does not parse, or it is not the docstring's shape."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, RecursionError) as exc:  # a JSONDecodeError and a UnicodeDecodeError are ValueErrors; deep nesting recurses
        return {}, f"does not parse as JSON: {type(exc).__name__}: {str(exc)[:200]}"
    if not isinstance(data, dict):
        return {}, "the top level is an object keyed by class A prefix"
    for prefix, entry in data.items():
        wrong = _shape(entry)
        if wrong:
            return {}, f"{prefix!r}: {wrong}"
    return data, ""


def _shape(entry: Any) -> str:
    """What is wrong with one item's entry, or ''."""
    if not isinstance(entry, dict):
        return "an item's entry is an object keyed by rule"
    for rule, spec in entry.items():
        if rule not in SUITE_RULES:
            return f"{rule!r} is not a rule an item's own suite reads ({', '.join(SUITE_RULES)})"
        if not isinstance(spec, dict) or set(spec) - set(SUITE_RULES[rule]):
            return f"{rule!r} is an object holding {' and '.join(SUITE_RULES[rule])} only"
        reads = spec.get("reads", "none")
        if reads != "none" and not (isinstance(reads, list) and reads and all(_text(r) for r in reads)):
            return f'{rule!r}: `reads` is "none", or a list of what the item reads from another node'
        readers = spec.get("readers", [])
        if not isinstance(readers, list) or not all(_is_reader(r) for r in readers):
            return f'{rule!r}: `readers` is a list of {{"check": <pointer>, "violator": <pointer>}}'
    return ""


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_reader(value: Any) -> bool:
    return isinstance(value, dict) and set(value) == {"check", "violator"} and all(_text(v) for v in value.values())


def _read_item(tree: Path, prefix: str, entry: dict[str, Any] | None) -> list[Problem]:
    where = f"class A {prefix}"
    if entry is None:
        return [Problem("reader-undeclared", where, f"no entry in {READERS_FILE}")]
    return [p for rule in SUITE_RULES for p in _read_rule(tree, where, rule, entry.get(rule))]


def _read_rule(tree: Path, where: str, rule: str, spec: dict[str, Any] | None) -> list[Problem]:
    """One rule of one item: declared, and every reader it names resolves."""
    here = f"{where} {rule}"
    if spec is None:
        return [Problem("reader-undeclared", here, "no entry: the item's own suite reads this rule, so it names the reader")]
    if rule == "rule 3" and "reads" not in spec:
        return [Problem("reader-undeclared", here, 'no `reads`: the item lists what it reads from another node, or says "none"')]
    readers = spec.get("readers", [])
    if not readers and spec.get("reads") != "none":
        return [Problem("reader-undeclared", here, "no reader is declared")]
    n = rule.split()[1]
    return [p for r in readers for p in _resolve_reader(tree, here, n, r)]


def _resolve_reader(tree: Path, here: str, n: str, reader: dict[str, str]) -> list[Problem]:
    """The check exists, carries its `Measures:` line and names its violator; the violator exists."""
    problems: list[Problem] = []
    want = MEASURES.format(n=n)
    check, violator = reader["check"], reader["violator"]
    lines, why = _pointer(tree, check)
    if why:
        problems.append(Problem("reader-unresolved", here, f"check {why}"))
    elif not any(line.strip().lstrip("#").strip() == want for line in lines):
        problems.append(Problem("reader-unresolved", here, f"check `{check}` holds no line of its own reading `{want}`"))
    _, why = _pointer(tree, violator)
    if why:
        problems.append(Problem("reader-unresolved", here, f"violator {why}"))
    elif lines and not _names(lines, violator):
        problems.append(Problem("reader-unresolved", here, f"check `{check}` does not name its violator `{violator}`"))
    return problems


def _names(lines: list[str], violator: str) -> bool:
    """Does the check's text name the violator: its last `::` part, or else its file's name, as a whole word?"""
    rel, _, name = violator.partition("::")
    word = name.split("::")[-1] if name else Path(rel).name
    return re.search(rf"(?<!\w){re.escape(word)}(?!\w)", "\n".join(lines)) is not None


def _pointer(tree: Path, pointer: str) -> tuple[list[str], str]:
    """The lines a pointer names - the whole file, or one definition in it - or why it names nothing.

    The file is read from the working tree, and must resolve, symlinks and
    `..` followed, to a file under the tree's root.
    """
    rel, _, name = pointer.partition("::")
    file = tree / rel
    if not rel or not file.is_file() or not file.resolve().is_relative_to(tree.resolve()):
        return [], f"`{rel}` is not a file in the tree"
    lines = file.read_text(encoding="utf-8", errors="replace").splitlines()
    if not name:
        return lines, ""
    try:
        module = ast.parse("\n".join(lines))
    except SyntaxError:
        return [], f"`{rel}` does not parse, so `{name}` cannot be found in it"
    node = _definition(module, name.split("::"))
    if node is None:
        return [], f"`{rel}` defines no `{name}`"
    return lines[getattr(node, "lineno", 1) - 1 : getattr(node, "end_lineno", None)], ""


def _definition(module: ast.AST, parts: list[str]) -> ast.AST | None:
    """The definition a pytest-style `A::b` names: the first part anywhere, each later part inside the one before."""
    scope = module
    for part in parts:
        found = next((d for d in ast.walk(scope) if d is not scope and part in _names_defined(d)), None)
        if found is None:
            return None
        scope = found
    return scope


def _names_defined(node: ast.AST) -> tuple[str, ...]:
    """The names a function, class or assignment binds at its own node."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return (node.name,)
    if isinstance(node, ast.Assign):
        return tuple(t.id for t in node.targets if isinstance(t, ast.Name))
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return (node.target.id,)
    return ()


# --- the ratchet ---------------------------------------------------------------


def _git(tree: Path, *args: str) -> str:
    res = subprocess.run(
        ["git", "-C", str(tree), *args], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if res.returncode != 0:
        raise Refusal(f"git {' '.join(args[:2])} failed: {res.stderr.strip()[:300]}")
    return res.stdout


def ensure_base(tree: Path, sha: str) -> None:
    """A shallow checkout has the merge commit and little else; the base is fetched by sha when absent."""
    have = subprocess.run(["git", "-C", str(tree), "cat-file", "-e", f"{sha}^{{commit}}"], capture_output=True)
    if have.returncode != 0:
        _git(tree, "fetch", "--quiet", "--depth=1", "origin", sha)


def base_calls_action(tree: Path, sha: str, action_name: str) -> bool:
    """Does any workflow at the base use this action (or run this script by name)? Comments do not count."""
    needles = (f".github/actions/{action_name}", f"check_{action_name.replace('-', '_')}.py")
    for path in _git(tree, "ls-tree", "-r", "--name-only", sha, "--", ".github/workflows").split("\n"):
        if not path.endswith((".yml", ".yaml")):
            continue
        for line in _git(tree, "show", f"{sha}:{path}").splitlines():
            code = line.split("#", 1)[0]
            if any(n in code for n in needles):
                return True
    return False


def base_markers(tree: Path, sha: str, declared: Declared) -> dict[str, int]:
    """Baseline sites per class at the base, read with the SAME reader as the head.

    `git grep` names the candidate blobs; each is then tokenised and its
    suppressions judged exactly as the head's are, so a marker inside a
    string literal - this checker's own source holds three - is not a
    marker on either side. The first draft counted grep lines here, which
    read seven in this repository against a head of four, and would have
    let three markers in unrefused.
    """
    res = subprocess.run(
        ["git", "-C", str(tree), "grep", "-l", "-F", MARKER, sha, "--", "*.py"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if res.returncode > 1:
        raise Refusal(f"git grep on the base failed: {res.stderr.strip()[:300]}")
    counts = {c: 0 for c in CLASSES}
    for line in res.stdout.splitlines():
        path = line.split(":", 1)[1]
        text = _git(tree, "show", f"{sha}:{path}")
        try:
            comments = read_comments(text)
        except (SyntaxError, tokenize.TokenError):
            continue  # a base file that does not tokenise carried no readable marker
        sups = (parse_suppression(path, line_no, comment) for line_no, comment in comments)
        counts[classify(path, declared)] += sum(1 for s in sups if s and is_baseline(s))
    return counts


def ratchet(
    tree: Path, base_sha: str, action_name: str, declared: Declared, head: dict[str, int]
) -> tuple[str, dict[str, int] | None, list[Problem]]:
    if not base_sha:
        return "not run: no base commit - not a pull request - so the baseline is reported, not compared", None, []
    ensure_base(tree, base_sha)
    short = base_sha[:12]
    if not base_calls_action(tree, base_sha, action_name):
        return (
            f"not run: the base {short} does not call this action, so this is the migration "
            "pull request - the one change allowed to add markers",
            None,
            [],
        )
    base = base_markers(tree, base_sha, declared)
    problems = [
        Problem("ratchet", f"class {c}", f"{head[c]} marker(s) in this tree against {base[c]} in the base")
        for c in CLASSES
        if head[c] > base[c]
    ]
    verdict = "REFUSED" if problems else "held"
    shown = ", ".join(f"{c} {base[c]}" for c in CLASSES)
    return f"{verdict}: the base {short} calls this action and carries {shown} marker(s)", base, problems


# --- the whole -------------------------------------------------------------------


def check(
    tree: Path,
    declared: Declared,
    base_sha: str = "",
    action_name: str = ACTION_NAME,
    interpreter: Interpreter = PYTHON,
) -> Outcome:
    files = population(tree)
    if not files:
        raise Refusal(
            f"no .py file under {tree}. A population of zero is a matcher that rotted or a wrong "
            "directory, not a clean tree."
        )
    by_class: dict[str, list[str]] = defaultdict(list)
    for f in files:
        by_class[classify(f, declared)].append(f)
    readers = reader_versions(bool(by_class.get("A") or by_class.get("B")), interpreter)
    reports: dict[str, ClassReport] = {}
    problems: list[Problem] = []
    for cls in CLASSES:
        reports[cls], found = read_class(tree, cls, by_class.get(cls, []), declared, interpreter)
        problems += found
    suite_note, pp = presence(tree, declared)
    note, base, rp = ratchet(tree, base_sha, action_name, declared, {c: reports[c].baseline for c in CLASSES})
    return Outcome(reports, problems + pp + rp, note, base, readers, suite_note)


def by_code(report: ClassReport) -> str:
    counts: dict[str, int] = defaultdict(int)
    for f in report.findings:
        counts[f.code] += 1
    return ", ".join(f"{code} {n}" for code, n in sorted(counts.items())) or "-"


def render(outcome: Outcome, declared: Declared) -> list[str]:
    lines = [f"readers: {'; '.join(outcome.readers)}", ""]
    lines.append("declaration (a file under no prefix, and every test path, is class C):")
    for cls in CLASSES:
        lines.append(f"  class {cls} (ceilings {ceilings(cls)}): {' '.join(declared.get(cls, ())) or '-'}")
    lines.append("")
    lines.append(f"{'class':<7}{'files':>6}{'findings':>10}{'suppressed':>12}{'deviations':>12}{'baseline':>10}  by rule")
    for cls in CLASSES:
        r = outcome.reports[cls]
        base = f" (base {outcome.base[cls]})" if outcome.base is not None else ""
        lines.append(
            f"{cls:<7}{r.files:>6}{len(r.findings):>10}{r.suppressed:>12}{r.deviations:>12}"
            f"{r.baseline:>10}{base}  {by_code(r)}"
        )
    lines.append("")
    lines.append(f"own-suite readers (rules 3 and 5): {outcome.presence}")
    lines.append(f"ratchet: {outcome.ratchet}")
    return lines


def ceilings(cls: str) -> str:
    """The class's two rule 4 numbers: cyclomatic, then statements."""
    return f"{CEILING[cls]} / {STATEMENT_CEILING.get(cls, 'not read')}"


def render_markdown(outcome: Outcome, declared: Declared) -> str:
    rows = ["| class | ceilings (cyclomatic / statements) | declared | files | findings | deviations | baseline | by rule |", "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for cls in CLASSES:
        r = outcome.reports[cls]
        base = f" (base {outcome.base[cls]})" if outcome.base is not None else ""
        rows.append(
            f"| {cls} | {ceilings(cls)} | `{' '.join(declared.get(cls, ())) or '-'}` | {r.files} | "
            f"{len(r.findings)} | {r.deviations} | {r.baseline}{base} | {by_code(r)} |"
        )
    verdict = f"**{len(outcome.problems)} refusal(s)**" if outcome.problems else "**green** - zero findings"
    readers = f"readers: {'; '.join(outcome.readers)}"
    suite = f"own-suite readers (rules 3 and 5): {outcome.presence}"
    return "\n".join(["### power of ten", "", *rows, "", readers, "", suite, "", f"ratchet: {outcome.ratchet}", "", verdict, ""])


def write_summary(text: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(text)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tree", metavar="DIR", default=".", help="the checked-out tree to read")
    ap.add_argument("--class-a", default="", help="whitespace-separated path prefixes that are class A")
    ap.add_argument("--class-b", default="", help="whitespace-separated path prefixes that are class B")
    ap.add_argument("--class-c", default="", help="whitespace-separated path prefixes that are class C (the default class)")
    ap.add_argument("--base-sha", default="", help="the pull request's base commit; runs the ratchet when the base calls this action")
    ap.add_argument("--action-name", default=ACTION_NAME, help="the directory name the base's workflows would call")
    args = ap.parse_args(argv)

    tree = Path(args.tree)
    try:
        declared = parse_declaration(args.class_a, args.class_b, args.class_c)
        outcome = check(tree, declared, args.base_sha, args.action_name)
    except Refusal as exc:
        # Everything on ONE stream, as the sibling guards do: the runner
        # interleaves stdout and stderr by arrival, and a verdict can land
        # above the report it judges. The exit code is the verdict.
        print(f"power of ten REFUSED: {exc}")
        return 1

    print(f"power of ten: read {tree.resolve()}")
    for line in render(outcome, declared):
        print(line)
    print()
    write_summary(render_markdown(outcome, declared))

    if outcome.problems:
        print(f"REFUSALS: {len(outcome.problems)}\n")
        grouped: dict[str, list[Problem]] = defaultdict(list)
        for p in outcome.problems:
            grouped[p.kind].append(p)
        for kind in EXPLANATIONS:
            if kind not in grouped:
                continue
            print(f"  [{kind}] {len(grouped[kind])} site(s):")
            for p in grouped[kind]:
                print(f"    {p.where}  {p.detail}")
            print(f"    {EXPLANATIONS[kind]}\n")
        print(f"power of ten FAILED: {len(outcome.problems)} refusal(s), listed above")
        return 1

    total = sum(r.files for r in outcome.reports.values())
    print(f"power of ten: green - {total} file(s) read, zero findings in every class.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
