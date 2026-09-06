#!/usr/bin/env python3
"""The Power of 10 check fires on every kept rule, goes quiet on the known positive, and the ratchet refuses - proven before trusted.

Every fixture is staged on a throwaway tree from strings in this file and is
never shipped as a `.py` in the repository: a function at complexity 16
under `.github/actions/` would be a real finding in this repository's own
class C run, and a self-test that makes its own guard red is a self-test
nobody keeps. The estate rule this satisfies: a control observed only to
pass, against the one tree it is known to pass in, has not been shown to be
a control.

The known negatives are the record's own list - a self-call, a `while True`,
a function at the ceiling plus one, a bare `except`, a blind handler with
`pass`, a `global`, an `eval`, an `exec`, a strict-typing error - plus the
suppression and baseline shapes, and a marker added to an already-migrated
tree, refused by the ratchet. The known positive is a clean, typed class A
module that also carries the two shapes the record chose NOT to read: a
same-named delegation, and a typed handler whose body is `pass`.

Needs ruff and mypy importable, as the check does, and git on the path for
the ratchet cases.

    python3 test_check_power_of_ten.py
"""

from __future__ import annotations

import atexit
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from check_power_of_ten import (
    MARKER,
    Outcome,
    Refusal,
    check,
    classify,
    parse_declaration,
    parse_suppression,
    render_markdown,
)

failures = 0
cases = 0
FIXTURES: list[tuple[str, str]] = []  # (fixture, what the check must do with it) - the summary's list


def case(name: str, ok: bool) -> None:
    global failures, cases
    cases += 1
    if not ok:
        failures += 1
    print(f"  {'ok  ' if ok else 'FAIL'} {name}")


def fixture(name: str, expectation: str) -> None:
    FIXTURES.append((name, expectation))


STAGED: list[Path] = []
atexit.register(lambda: [shutil.rmtree(p, ignore_errors=True) for p in STAGED])


def stage(files: dict[str, str]) -> Path:
    root = Path(tempfile.mkdtemp(prefix="power-of-ten-"))
    STAGED.append(root)
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="\n")
    return root


def run(files: dict[str, str], a: str = "", b: str = "", c: str = "", base_sha: str = "") -> Outcome:
    return check(stage(files), parse_declaration(a, b, c), base_sha)


def pairs(outcome: Outcome, cls: str) -> set[tuple[str, str]]:
    return {(f.path.rsplit("/", 1)[-1], f.code) for f in outcome.reports[cls].findings}


def kinds(outcome: Outcome) -> list[str]:
    return sorted(p.kind for p in outcome.problems)


def ifs(n: int) -> str:
    """A function with n `if`s has cyclomatic complexity n + 1."""
    body = "".join(f"    if n == {i}:\n        return {i}\n" for i in range(n))
    return f"def route(n: int) -> int:\n{body}    return 0\n"


# --- fixtures, as strings ----------------------------------------------------------

POSITIVE = '''"""A clean class A module: typed, bounded, and carrying the two shapes the record does not read."""
from __future__ import annotations


def total(values: list[int]) -> int:
    n = 0
    for v in values:
        n += v
    return n


def countdown(n: int) -> int:
    while n > 0:
        n -= 1
    return n


class Codec:
    def encode(self, value: int) -> int:
        return value + 1


class Frame:
    def __init__(self) -> None:
        self.codec = Codec()

    def encode(self, value: int) -> int:
        return self.codec.encode(value)


def close(handle: object) -> None:
    try:
        hash(handle)
    except TypeError:
        pass
'''

NEGATIVES = {
    "src/pkg/recursion.py": "def walk(n: int) -> int:\n    if n == 0:\n        return 0\n    return walk(n - 1)\n",
    "src/pkg/method_recursion.py": (
        "class Node:\n    def depth(self, n: int) -> int:\n        if n == 0:\n"
        "            return 0\n        return self.depth(n - 1)\n"
    ),
    "src/pkg/unbounded.py": "def spin() -> None:\n    while True:\n        break\n",
    "src/pkg/unbounded_one.py": "def spin() -> None:\n    while 1:\n        break\n",
    "src/pkg/complexity.py": ifs(10),
    "src/pkg/bare_except.py": "def risky() -> int:\n    try:\n        return 1\n    except:\n        return 0\n",
    "src/pkg/blind_pass.py": "def swallow() -> None:\n    try:\n        pass\n    except Exception:\n        pass\n",
    "src/pkg/globals.py": "COUNTER = 0\n\n\ndef bump() -> None:\n    global COUNTER\n    COUNTER += 1\n",
    "src/pkg/evals.py": 'def ev() -> None:\n    eval("1")\n\n\ndef ex() -> None:\n    exec("x = 1")\n',
    "src/pkg/typing_strict.py": "def add(a, b):\n    return a + b\n",
    "src/pkg/typing_default.py": 'x: int = "s"\n',
}
NEGATIVE_PAIRS_AB = {
    ("recursion.py", "POT001"),
    ("method_recursion.py", "POT001"),
    ("unbounded.py", "POT002"),
    ("unbounded_one.py", "POT002"),
    ("bare_except.py", "E722"),
    ("blind_pass.py", "BLE001"),
    ("blind_pass.py", "S110"),
    ("globals.py", "PLW0603"),
    ("evals.py", "S307"),
    ("evals.py", "S102"),
    ("typing_default.py", "types"),
}
INIT = {"src/pkg/__init__.py": ""}
GLOBAL_FN = "COUNTER = 0\n\n\ndef bump() -> None:\n    global COUNTER  {directive}\n    COUNTER += 1\n"


# --- the known positive first: a clean class A tree must pass -------------------------

fixture("positive.py as class A", "green: zero findings, zero problems")
positive = run({**INIT, "src/pkg/positive.py": POSITIVE}, a="src")
case("the known positive is green as class A, at ceiling 10 with strict typing", positive.problems == [])
case("...and it was read: two files in class A, none elsewhere", positive.reports["A"].files == 2)
case("...a same-named delegation is not recursion", ("positive.py", "POT001") not in pairs(positive, "A"))
case("...a typed handler whose body is `pass` is not read", ("positive.py", "S110") not in pairs(positive, "A"))
case("...the ratchet did not run without a base", positive.ratchet.startswith("not run: no base"))

# --- every kept rule refused in class A ---------------------------------------------

for name in NEGATIVES:
    fixture(name.rsplit("/", 1)[-1] + " as class A", "refused")
neg_a = run({**INIT, **NEGATIVES, "src/pkg/positive.py": POSITIVE}, a="src")
expected_a = NEGATIVE_PAIRS_AB | {("complexity.py", "C901"), ("typing_strict.py", "types")}
case("class A refuses every known negative and nothing else", pairs(neg_a, "A") == expected_a)
if pairs(neg_a, "A") != expected_a:
    print("     missing:", sorted(expected_a - pairs(neg_a, "A")))
    print("     extra:  ", sorted(pairs(neg_a, "A") - expected_a))
case("...the positive beside them stays clean", not any(f.path.endswith("positive.py") for f in neg_a.reports["A"].findings))
case("...every refusal is a `finding`", set(kinds(neg_a)) == {"finding"})

# --- class B: ceiling 15 and the tool's default typing --------------------------------

fixture("the same negatives as class B", "refused, except complexity 11 and the strict-only typing error")
neg_b = run({**INIT, **NEGATIVES}, b="src")
case("class B refuses the same rules at ceiling 15 with default typing", pairs(neg_b, "B") == NEGATIVE_PAIRS_AB)
case("...complexity 11 fits class B's ceiling", ("complexity.py", "C901") not in pairs(neg_b, "B"))
case("...an untyped def is strict's finding, not the default's", ("typing_strict.py", "types") not in pairs(neg_b, "B"))

# --- class C: the ceiling and nothing else ---------------------------------------------

fixture("the same negatives as class C, plus a function at complexity 16", "one finding: the ceiling")
neg_c = run({**INIT, **NEGATIVES, "src/pkg/complexity16.py": ifs(15)})
case("class C reads the ceiling and nothing else", pairs(neg_c, "C") == {("complexity16.py", "C901")})
case("...at 15: a function at 16 is refused, one at 11 is not", len(neg_c.reports["C"].findings) == 1)
case("...and with no declaration everything is class C", neg_c.reports["C"].files == len(NEGATIVES) + 2)

# --- deviations at the site, and the baseline ------------------------------------------

SUPPRESSIONS = {
    **INIT,
    "src/pkg/sup_reason.py": GLOBAL_FN.format(directive="# noqa: PLW0603 -- the one piece of module state"),
    "src/pkg/sup_noreason.py": GLOBAL_FN.format(directive="# noqa: PLW0603"),
    "src/pkg/sup_bare.py": GLOBAL_FN.format(directive="# noqa"),
    "src/pkg/sup_unused.py": "def fine() -> int:  # noqa: C901 -- nothing here is complex\n    return 1\n",
    "src/pkg/sup_other.py": "x = 1  # noqa: E501\n",
    "src/pkg/ti_reason.py": 'y: int = "s"  # type: ignore[assignment]  # the fixture wants a string\n',
    "src/pkg/ti_bare.py": 'y: int = "s"  # type: ignore\n',
    "src/pkg/ti_noreason.py": 'y: int = "s"  # type: ignore[assignment]\n',
    "src/pkg/marker_ok.py": GLOBAL_FN.format(directive=f"# noqa: PLW0603 -- {MARKER} #7"),
    "src/pkg/marker_noissue.py": GLOBAL_FN.format(directive=f"# noqa: PLW0603 -- {MARKER}"),
    "src/pkg/marker_stray.py": f"# {MARKER} #7\nx = 1\n",
}
for name, what in (
    ("sup_reason.py", "quiet, one deviation"),
    ("sup_noreason.py", "suppression-no-reason"),
    ("sup_bare.py", "suppression-no-rule, and the finding stands"),
    ("sup_unused.py", "suppression-unused"),
    ("sup_other.py", "not this check's rule: ignored"),
    ("ti_reason.py", "quiet, one deviation"),
    ("ti_bare.py", "suppression-no-rule"),
    ("ti_noreason.py", "suppression-no-reason"),
    ("marker_ok.py", "quiet, baseline 1"),
    ("marker_noissue.py", "baseline-no-issue"),
    ("marker_stray.py", "baseline-stray"),
):
    fixture(name + " as class A", what)
sup = run(SUPPRESSIONS, a="src")
a = sup.reports["A"]
case("a suppression naming the rule with a reason is quiet, and counted as a deviation", a.deviations == 2)
case("...the baseline marker with its owing issue is quiet, and counted", a.baseline == 1)
case("...a named suppression covers its finding (the reason-less one too)", not any(f.path.endswith(("sup_reason.py", "sup_noreason.py", "marker_ok.py")) for f in a.findings))
case("...a bare `noqa` covers nothing: the finding stands", ("sup_bare.py", "PLW0603") in pairs(sup, "A"))
case(
    "...and every wrong shape is red by kind",
    kinds(sup) == sorted([
        "finding",
        "suppression-no-rule", "suppression-no-rule",
        "suppression-no-reason", "suppression-no-reason",
        "suppression-unused",
        "baseline-no-issue",
        "baseline-stray",
    ]),
)
if sup.problems:
    for p in sup.problems:
        if p.kind == "finding" and "sup_bare" not in p.where:
            print(f"     unexpected finding: {p}")
case("...a suppression of a rule this check does not read is left alone", not any("sup_other" in p.where for p in sup.problems))
case("...markdown carries the counts", "| A | 10 |" in render_markdown(sup, parse_declaration("src", "", "")))

# --- the classes: test paths, the longest prefix, an undeclared file ----------------------

fixture("src/pkg/tests/test_x.py, src/pkg/test_y.py, src/pkg/conftest.py under a class A prefix", "class C: not typed")
tests = run(
    {
        **INIT,
        "src/pkg/tests/test_x.py": "def add(a, b):\n    return a + b\n",
        "src/pkg/test_y.py": "def add(a, b):\n    return a + b\n",
        "src/pkg/conftest.py": "def add(a, b):\n    return a + b\n",
    },
    a="src",
)
case("a test path under a class A prefix is class C, and strict typing does not reach it", tests.problems == [])
case("...three test files in C, the package init in A", (tests.reports["C"].files, tests.reports["A"].files) == (3, 1))

fixture("src/pkg/scripts/tool.py with class-b src and class-c src/pkg/scripts", "class C: the global is not read")
carve = run(
    {**INIT, "src/pkg/scripts/tool.py": GLOBAL_FN.format(directive=""), "src/pkg/svc.py": GLOBAL_FN.format(directive="")},
    b="src",
    c="src/pkg/scripts",
)
case("the longest matching prefix wins: a class C carve-out inside class B", pairs(carve, "C") == set())
case("...and the class B file beside it is still refused", ("svc.py", "PLW0603") in pairs(carve, "B"))

decl = parse_declaration("src", "svc", "scripts src/x")
case("classify: under no prefix is class C", classify("tools/a.py", decl) == "C")
case("classify: a prefix matches whole path segments only", classify("srcx/a.py", decl) == "C")
case("classify: a test path anywhere is class C", classify("src/pkg/tests/t.py", decl) == "C")
case("classify: the longer prefix wins", classify("src/x/a.py", decl) == "C" and classify("src/y/a.py", decl) == "A")
try:
    parse_declaration("src", "src", "")
    case("one prefix in two classes is a refusal", False)
except Refusal:
    case("one prefix in two classes is a refusal", True)

# --- the population -------------------------------------------------------------------

fixture("a tree with no .py file", "refused: an empty population is not a clean tree")
try:
    check(stage({"README.md": "no python here\n"}), parse_declaration("", "", ""))
    case("an empty population is a refusal, never a green", False)
except Refusal:
    case("an empty population is a refusal, never a green", True)

# --- the suppression reader, alone -----------------------------------------------------

s = parse_suppression("f.py", 3, "# noqa:C901")
case("reader: `noqa:CODE` with no space names the code", s is not None and s.codes == ("C901",) and s.reason == "")
s = parse_suppression("f.py", 3, "# NOQA: C901, E722 -- two rules, one reason")
case("reader: two codes and a reason", s is not None and s.codes == ("C901", "E722") and s.reason == "two rules, one reason")
s = parse_suppression("f.py", 3, "# noqa C901 no colon")
case("reader: a missing colon names no rule, as ruff reads it", s is not None and s.codes == ())
s = parse_suppression("f.py", 3, "# type: ignore[attr-defined, misc]  # the driver is untyped")
case("reader: a type-ignore with codes and a reason", s is not None and s.codes == ("attr-defined", "misc") and s.reason == "the driver is untyped")
case("reader: an ordinary comment is not a suppression", parse_suppression("f.py", 3, "# nothing to see") is None)

# --- the ratchet: a marker added to a migrated tree is refused ------------------------------

WORKFLOW_CALLING = "jobs:\n  p10:\n    steps:\n      - uses: ./.github/actions/power-of-ten\n"
WORKFLOW_SILENT = "jobs:\n  other:\n    steps:\n      - uses: ./.github/actions/markdown\n      # - uses: ./.github/actions/power-of-ten\n"


def markers(n: int) -> str:
    fns = "".join(
        f"def bump{i}() -> None:\n    global COUNTER  # noqa: PLW0603 -- {MARKER} #7\n    COUNTER += 1\n\n\n"
        for i in range(n)
    )
    return "COUNTER = 0\n\n\n" + fns


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), "-c", "user.name=self-test", "-c", "user.email=self-test@example.invalid",
         "-c", "commit.gpgsign=false", *args],
        check=True, capture_output=True, text=True, encoding="utf-8",
    ).stdout.strip()


def repo_with_base(workflow: str, base_markers: int) -> tuple[Path, str]:
    root = stage({".github/workflows/checks.yml": workflow, "src/pkg/m.py": markers(base_markers)})
    git(root, "init", "-q")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "base")
    return root, git(root, "rev-parse", "HEAD")


def head_with(root: Path, n: int) -> None:
    (root / "src/pkg/m.py").write_text(markers(n), encoding="utf-8", newline="\n")


fixture("a marker added where the base already calls the action", "refused by the ratchet")
root, base = repo_with_base(WORKFLOW_CALLING, 1)
head_with(root, 2)
raised = check(root, parse_declaration("", "", ""), base)
case("the ratchet refuses a marker added to a tree whose base calls the action", kinds(raised) == ["ratchet"])
case("...and says what it compared", raised.ratchet.startswith("REFUSED") and raised.base == {"A": 0, "B": 0, "C": 1})

fixture("the same marker count as the base", "held")
head_with(root, 1)
held = check(root, parse_declaration("", "", ""), base)
case("the same count is held", held.problems == [] and held.ratchet.startswith("held"))

fixture("a marker removed", "held: the baseline may fall")
head_with(root, 0)
fell = check(root, parse_declaration("", "", ""), base)
case("a removed marker is allowed: the baseline only shrinks", fell.problems == [] and fell.reports["C"].baseline == 0)

fixture("the base carries the marker text inside a string literal, not a suppression", "not a marker: a real one added is still refused")
root3, base3 = repo_with_base(WORKFLOW_CALLING, 0)
(root3 / "src/pkg/m.py").write_text(f'TEXT = "{MARKER} #1 in a string"\n', encoding="utf-8", newline="\n")
git(root3, "add", "-A")
git(root3, "commit", "-q", "-m", "a literal, not a marker")
base3 = git(root3, "rev-parse", "HEAD")
head_with(root3, 1)
literal = check(root3, parse_declaration("", "", ""), base3)
case("the base is read with the same reader as the head: a literal is not a marker", kinds(literal) == ["ratchet"])
case("...and the base count says 0, not 1", literal.base == {"A": 0, "B": 0, "C": 0})

fixture("a marker added where the base does NOT call the action", "allowed: the migration pull request")
root2, base2 = repo_with_base(WORKFLOW_SILENT, 0)
head_with(root2, 2)
migration = check(root2, parse_declaration("", "", ""), base2)
case("a base that does not call the action is the migration, and markers may be added", migration.problems == [])
case("...a commented-out `uses:` does not count as calling it", "migration" in migration.ratchet)
case("...and the head's markers are counted", migration.reports["C"].baseline == 2)

# --- the fixture list, to the summary ------------------------------------------------------

print()
print(f"fixtures staged: {len(FIXTURES)}")
for name, what in FIXTURES:
    print(f"  {name}  ->  {what}")
summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
if summary_path:
    with open(summary_path, "a", encoding="utf-8") as fh:
        fh.write("### power of ten - self-test fixtures\n\n")
        fh.write("| fixture | the check must |\n| --- | --- |\n")
        for name, what in FIXTURES:
            fh.write(f"| `{name}` | {what} |\n")
        fh.write(f"\n{cases} case(s), {failures} failure(s).\n\n")

print()
print(f"self-test: {cases} case(s), {failures} failure(s)")
sys.exit(1 if failures else 0)
