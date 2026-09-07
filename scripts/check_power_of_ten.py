#!/usr/bin/env python3
"""The Power of 10 is read per class against a tree: findings, deviations, and a baseline that only shrinks.

WHY THIS EXISTS (ADR-0042, ruled 2026-09-05, built the same day). The
estate had never stated a coding standard, and seven repositories carrying
Python held exactly one code-quality gate between them. The record adopts
JPL's Power of 10, tailored to Python by a recorded disposition of each rule,
applied per software ITEM at a class set by what a failure of that item
reaches - A reaches a guarantee or a stranger, B reaches production, C
reaches a pipeline run and stops - and rules that a rule of the estate exists
ONLY where a shared check reads it against the tree and refuses. This is
that check. A rule this file does not read is not a rule, whatever a prose
file says.

WHAT IT READS, per class - the record's rule-by-class table, and nothing not
in it:

  rule 1   no direct recursion (a function whose body calls its own bare name,
           or `self.<its name>`)                          A, B refused; C not read
  rule 2   a `while` whose test is a constant true       A, B refused; C not read
  rule 4   cyclomatic ceiling                             A 10; B 15; C 15
  rule 6   the `global` statement                         A, B refused; C not read
  rule 7   a bare `except`, a blind `except Exception`, and a bare or blind
           handler whose body is `pass`                   A, B refused; C not read
           (a TYPED handler with `pass` is not read: the tool's default, and
           the record says so)
  rule 7   types: strict for A, the tool's default for B  C not read
  rule 8   `eval` / `exec`                                A, B refused; C not read

Rules 3, 5 and 9 are deviated or not applicable in the record and are read
by nothing here. The tools are ruff (rules 4, 6, 7, 8) and mypy (types),
pinned by version in `requirements.txt` beside this file - the one place the
version is written, moved by Dependabot's `pip` ecosystem (rule 10). Rules 1
and 2 have no ruff code, so they are read from the AST here and carry the
code-shaped names POT001 and POT002, which ruff's `noqa` parser tolerates
silently (measured, ruff 0.16.6).

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
  - An empty population, a tool that crashed, a file that does not parse,
    a base that cannot be read: a REFUSAL, exit 1, never an empty success.
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
and the record names that hole rather than closing it.

WHAT A GREEN HERE DOES NOT SAY. That the code is correct: a ceiling and a
type check catch a class of defect measured to be real, and price no
guarantee and read no falsifier. That the declaration is right: nothing
here compares the caller's class prefixes to the record's list. That every
loop is bounded: only the constant-true half is read.

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
from typing import NamedTuple

ACTION_NAME = "power-of-ten"
MARKER = "predates ADR-0042"
CLASSES = ("A", "B", "C")
CEILING = {"A": 10, "B": 15, "C": 15}
COMPLEXITY = "C901"
RECURSION = "POT001"
UNBOUNDED = "POT002"
TYPES = "types"  # the pseudo-code a `type: ignore` names; mypy has no single code
RUFF_AB = ("PLW0603", "E722", "BLE001", "S110", "S307", "S102")
RULES = {
    COMPLEXITY: "rule 4, the cyclomatic ceiling",
    RECURSION: "rule 1, no direct recursion",
    UNBOUNDED: "rule 2, a `while` on a constant true states no bound",
    "PLW0603": "rule 6, no `global`",
    "E722": "rule 7, no bare `except`",
    "BLE001": "rule 7, no blind `except Exception`",
    "S110": "rule 7, no bare or blind handler whose body is `pass`",
    "S307": "rule 8, no `eval`",
    "S102": "rule 8, no `exec`",
    TYPES: "rule 7, types (strict for class A, the tool's default for B)",
}
TEST_EXCLUDE = r"(^|/)(tests|test_[^/]*\.py|conftest\.py)($|/)"

_ISSUE = re.compile(r"#\d+")
_NOQA = re.compile(r"#\s*noqa\b(?P<tail>.*)$", re.IGNORECASE)
_NOQA_CODES = re.compile(r"^\s*:\s*(?P<codes>[A-Z]+[0-9]+(?:\s*[,\s]\s*[A-Z]+[0-9]+)*)(?P<rest>.*)$")
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
    if cls == "C":
        return frozenset({COMPLEXITY})
    return frozenset({COMPLEXITY, RECURSION, UNBOUNDED, TYPES, *RUFF_AB})


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


def ruff_findings(tree: Path, cls: str, files: list[str]) -> list[Finding]:
    select = [COMPLEXITY] + (list(RUFF_AB) if cls != "C" else [])
    out: list[Finding] = []
    root = tree.resolve()
    for i in range(0, len(files), 200):
        cmd = [
            sys.executable, "-m", "ruff", "check", "--isolated", "--no-cache", "--quiet", "--ignore-noqa",
            "--select", ",".join(select), "--config", f"lint.mccabe.max-complexity={CEILING[cls]}",
            "--output-format", "json", "--", *files[i : i + 200],
        ]
        res = subprocess.run(cmd, cwd=tree, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if res.returncode not in (0, 1):
            raise Refusal(f"ruff exited {res.returncode} on class {cls}: {res.stderr.strip()[:400]}")
        for item in json.loads(res.stdout or "[]"):
            rel = Path(item["filename"]).resolve().relative_to(root).as_posix()
            code = item["code"] or "syntax-error"
            row = item["location"]["row"]
            out.append(Finding(rel, row, code, item["message"], item.get("noqa_row") or row))
    return out


def ast_findings(rel: str, text: str) -> list[Finding]:
    """Rules 1 and 2, which ruff has no code for. A SyntaxError is the caller's to record."""
    out: list[Finding] = []
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _calls_itself(node):
            out.append(Finding(rel, node.lineno, RECURSION, f"`{node.name}` calls itself", node.lineno))
        elif isinstance(node, ast.While) and isinstance(node.test, ast.Constant) and bool(node.test.value):
            out.append(Finding(rel, node.lineno, UNBOUNDED, "`while` on a constant true", node.lineno))
    return out


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


def mypy_findings(tree: Path, cls: str, targets: list[str], declared: Declared) -> list[Finding]:
    """Class A strict, class B at the tool's default; `--platform linux` because the hosts are.

    `--explicit-package-bases` with `MYPYPATH` from `package_bases`: see there.
    """
    if not targets:
        return []
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "mypy.ini"
        cfg.write_text("[mypy]\n", encoding="utf-8")
        cmd = [
            sys.executable, "-m", "mypy", "--config-file", str(cfg), "--cache-dir", tmp,
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
    for line in res.stdout.splitlines():
        m = _MYPY_LINE.match(line)
        if m:
            rel = m["path"].replace("\\", "/")
            if classify(rel, declared) == cls:
                out.append(Finding(rel, int(m["line"]), TYPES, m["msg"], int(m["line"])))
        elif "error:" in line:
            raise Refusal(f"mypy said something this reader cannot place on a line: {line}")
    return out


# --- one class ----------------------------------------------------------------


def read_class(tree: Path, cls: str, files: list[str], declared: Declared) -> tuple[ClassReport, list[Problem]]:
    findings: list[Finding] = []
    sups: list[Suppression] = []
    problems: list[Problem] = []
    readable: list[str] = []
    for rel in files:
        text = (tree / rel).read_text(encoding="utf-8", errors="replace")
        try:
            comments = read_comments(text)
            if cls != "C":
                findings += ast_findings(rel, text)
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
        findings += ruff_findings(tree, cls, readable)
        if cls != "C":
            findings += mypy_findings(tree, cls, mypy_targets(cls, declared, tree), declared)
    kept, suppressed = apply_suppressions(findings, sups)
    sp, deviations, baseline = judge_suppressions(cls, sups, findings)
    problems += sp
    for f in kept:
        hint = f"  (a suppression goes on line {f.noqa_row})" if f.noqa_row != f.line else ""
        problems.append(Problem("finding", f"class {cls} {f.path}:{f.line}", f"{f.code}  {f.message}{hint}"))
    return ClassReport(cls, len(files), tuple(kept), suppressed, deviations, baseline), problems


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


def check(tree: Path, declared: Declared, base_sha: str = "", action_name: str = ACTION_NAME) -> Outcome:
    files = population(tree)
    if not files:
        raise Refusal(
            f"no .py file under {tree}. A population of zero is a matcher that rotted or a wrong "
            "directory, not a clean tree."
        )
    by_class: dict[str, list[str]] = defaultdict(list)
    for f in files:
        by_class[classify(f, declared)].append(f)
    reports: dict[str, ClassReport] = {}
    problems: list[Problem] = []
    for cls in CLASSES:
        reports[cls], found = read_class(tree, cls, by_class.get(cls, []), declared)
        problems += found
    note, base, rp = ratchet(tree, base_sha, action_name, declared, {c: reports[c].baseline for c in CLASSES})
    return Outcome(reports, problems + rp, note, base)


def by_code(report: ClassReport) -> str:
    counts: dict[str, int] = defaultdict(int)
    for f in report.findings:
        counts[f.code] += 1
    return ", ".join(f"{code} {n}" for code, n in sorted(counts.items())) or "-"


def render(outcome: Outcome, declared: Declared) -> list[str]:
    lines = ["declaration (a file under no prefix, and every test path, is class C):"]
    for cls in CLASSES:
        lines.append(f"  class {cls} (ceiling {CEILING[cls]}): {' '.join(declared.get(cls, ())) or '-'}")
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
    lines.append(f"ratchet: {outcome.ratchet}")
    return lines


def render_markdown(outcome: Outcome, declared: Declared) -> str:
    rows = ["| class | ceiling | declared | files | findings | deviations | baseline | by rule |", "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for cls in CLASSES:
        r = outcome.reports[cls]
        base = f" (base {outcome.base[cls]})" if outcome.base is not None else ""
        rows.append(
            f"| {cls} | {CEILING[cls]} | `{' '.join(declared.get(cls, ())) or '-'}` | {r.files} | "
            f"{len(r.findings)} | {r.deviations} | {r.baseline}{base} | {by_code(r)} |"
        )
    verdict = f"**{len(outcome.problems)} refusal(s)**" if outcome.problems else "**green** - zero findings"
    return "\n".join(["### power of ten", "", *rows, "", f"ratchet: {outcome.ratchet}", "", verdict, ""])


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
