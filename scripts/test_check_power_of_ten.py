#!/usr/bin/env python3
"""The Power of 10 check fires on every kept rule, goes quiet on the known positive, and the ratchet refuses - proven before trusted.

Every fixture is staged on a throwaway tree from strings in this file and is
never shipped as a `.py` in the repository: a function at complexity 16
under `.github/actions/` would be a real finding in this repository's own
class C run, and a self-test that makes its own guard red is a self-test
nobody keeps. The estate rule this satisfies: a control observed only to
pass, against the one tree it is known to pass in, has not been shown to be
a control.

The known negatives are the record's own list, staged in each class that
reads the rule - a self-call, a `while True`, a function at the cyclomatic
ceiling plus one, a function at each class's statement ceiling plus one, a
bare `except`, a blind handler with `pass`, a `global`, a `nonlocal`, a
mutable default argument, an `eval`, an `exec`, a strict-typing error, and in
class A the two computed-name shapes - plus the suppression and baseline
shapes, every way the own-suite reader refuses, and a marker added to an
already-migrated tree, refused by the ratchet. The known positive is a clean,
typed class A module at its statement ceiling, with a resolved own-suite
declaration, that also carries the shapes the record chose NOT to read: a
same-named delegation, a typed handler whose body is `pass`, and a computed
`getattr` stored and called later.

Needs ruff and mypy importable, as the check does, and git on the path for
the ratchet cases. That sentence was an assumption nothing tested until
2026-09-21: the check read a tree green on an interpreter that could load
neither tool. Their absence is now a staged fixture like any other.

    python3 test_check_power_of_ten.py
"""

from __future__ import annotations

import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

from check_power_of_ten import (
    MARKER,
    READERS_FILE,
    Outcome,
    Refusal,
    check,
    classify,
    mypy_findings,
    mypy_targets,
    parse_declaration,
    parse_suppression,
    reader_version,
    ruff_findings,
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


def statements(n: int) -> str:
    """A function of n assignments, which ruff counts as n statements (measured, ruff 0.17.4)."""
    body = "".join(f"    x{i} = {i}\n" for i in range(n))
    return f"def long() -> None:\n{body}"


# --- fixtures, as strings ----------------------------------------------------------

POSITIVE = '''"""A clean class A module: typed, bounded, and carrying the shapes the record does not read."""
from __future__ import annotations

import importlib


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


def plugin() -> object:
    return importlib.import_module("json")


def encode_by_name(codec: Codec) -> int:
    result: int = getattr(codec, "encode")(1)
    return result


def dispatch(obj: object, name: str) -> None:
    handler = getattr(obj, name)
    handler()


''' + statements(40)

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
    "src/pkg/statements_41.py": statements(41),
    "src/pkg/statements_60.py": statements(60),
    "src/pkg/statements_61.py": statements(61),
    "src/pkg/nonlocals.py": (
        "def outer() -> int:\n    n = 0\n\n    def inner() -> None:\n        nonlocal n\n"
        "        n += 1\n\n    inner()\n    return n\n"
    ),
    "src/pkg/mutable_default.py": "def collect(seen: list[int] = []) -> list[int]:\n    return seen\n",
    "src/pkg/computed_import_module.py": (
        "import importlib\n\n\ndef load(name: str) -> object:\n    return importlib.import_module(name)\n"
    ),
    "src/pkg/computed_dunder_import.py": "def load(name: str) -> object:\n    return __import__(name)\n",
    "src/pkg/computed_getattr_call.py": "def run(obj: object, name: str) -> None:\n    getattr(obj, name)()\n",
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
    ("statements_61.py", "PLR0915"),
    ("nonlocals.py", "POT003"),
    ("mutable_default.py", "B006"),
}
# Class A alone: its tighter numbers, strict typing, and rule 9.
NEGATIVE_PAIRS_A_ONLY = {
    ("complexity.py", "C901"),
    ("typing_strict.py", "types"),
    ("statements_41.py", "PLR0915"),
    ("statements_60.py", "PLR0915"),
    ("computed_import_module.py", "POT004"),
    ("computed_dunder_import.py", "POT004"),
    ("computed_getattr_call.py", "POT004"),
}
INIT = {"src/pkg/__init__.py": ""}

# An item's own suite, as the own-suite reader meets it, and a declaration
# that resolves against it. Staged beside every class A tree that must be
# green, because a class A item with no declaration is red.
SUITE = '''"""An item's own suite: one check per rule it reads, each beside its violator."""

OVER_THE_MAXIMUM = b"x" * 65

WRONG_FACT = {"width": -1}


class TestFrame:
    def test_refuses_past_the_maximum(self) -> None:
        """A frame past the stated maximum is refused before the rest is read.

        Measures: scripts/check_power_of_ten.py, rule 3
        """
        assert len(OVER_THE_MAXIMUM) > 64


def test_a_wrong_fact_raises_at_load() -> None:
    """A planted wrong fact makes the import raise.

    Measures: scripts/check_power_of_ten.py, rule 5
    """
    assert WRONG_FACT["width"] < 0


def test_without_its_line() -> None:
    """A check that names no rule."""
    assert OVER_THE_MAXIMUM


def test_names_no_violator() -> None:
    """A check that carries its line and touches nothing.

    Measures: scripts/check_power_of_ten.py, rule 3
    """
'''
SUITE_PATH = "tests/test_suite.py"
R3 = {"check": f"{SUITE_PATH}::TestFrame::test_refuses_past_the_maximum", "violator": f"{SUITE_PATH}::OVER_THE_MAXIMUM"}
R5 = {"check": f"{SUITE_PATH}::test_a_wrong_fact_raises_at_load", "violator": f"{SUITE_PATH}::WRONG_FACT"}
RULE3 = {"reads": ["the answer frame a peer sends"], "readers": [R3]}
RULE5 = {"readers": [R5]}
GOOD = {"src": {"rule 3": RULE3, "rule 5": RULE5}}


def declared(declaration: object) -> dict[str, str]:
    """The suite, and a declaration of it at the tree root: JSON, or a string staged as it is."""
    text = declaration if isinstance(declaration, str) else json.dumps(declaration, indent=2)
    return {SUITE_PATH: SUITE, READERS_FILE: text}


READERS_OK = declared(GOOD)
GLOBAL_FN = "COUNTER = 0\n\n\ndef bump() -> None:\n    global COUNTER  {directive}\n    COUNTER += 1\n"


# --- the known positive first: a clean class A tree must pass -------------------------

fixture(
    "positive.py as class A, with a resolved own-suite declaration",
    "green: zero findings, zero problems, at 40 statements, a constant import and getattr, and a stored computed getattr",
)
positive = run({**INIT, **READERS_OK, "src/pkg/positive.py": POSITIVE}, a="src")
case("the known positive is green as class A, at ceilings 10 and 40 with strict typing", positive.problems == [])
case("...and its own-suite readers resolved", positive.presence.startswith("resolved"))
for p in positive.problems:
    print(f"     unexpected: {p}")

# --- every kept rule refused in class A ---------------------------------------------

for name in NEGATIVES:
    fixture(name.rsplit("/", 1)[-1] + " as class A", "refused")
neg_a = run({**INIT, **NEGATIVES, "src/pkg/positive.py": POSITIVE}, a="src")
expected_a = NEGATIVE_PAIRS_AB | NEGATIVE_PAIRS_A_ONLY
case("class A refuses every known negative and nothing else", pairs(neg_a, "A") == expected_a)
if pairs(neg_a, "A") != expected_a:
    print("     missing:", sorted(expected_a - pairs(neg_a, "A")))
    print("     extra:  ", sorted(pairs(neg_a, "A") - expected_a))

# --- class B: ceilings 15 and 60, the tool's default typing, and no rule 9 ---------------

fixture(
    "the same negatives as class B",
    "refused, except complexity 11, 41 and 60 statements, the strict-only typing error and both computed-name shapes",
)
neg_b = run({**INIT, **NEGATIVES}, b="src")
case("class B refuses the same rules at ceilings 15 and 60 with default typing, and reads no rule 9", pairs(neg_b, "B") == NEGATIVE_PAIRS_AB)
if pairs(neg_b, "B") != NEGATIVE_PAIRS_AB:
    print("     missing:", sorted(NEGATIVE_PAIRS_AB - pairs(neg_b, "B")))
    print("     extra:  ", sorted(pairs(neg_b, "B") - NEGATIVE_PAIRS_AB))

# Whether a suppression is this check's business is read per class: rule 9's
# code names a rule class B does not read, so there it is left alone, and in
# class A the same line names a rule it reads and breaks nothing.
UNUSED_POT004 = {**INIT, "src/pkg/quiet.py": "x = 1  # noqa: POT004\n"}
fixture("`# noqa: POT004` on a line that breaks nothing, as class B", "not this check's rule in class B: ignored")
case("a rule 9 suppression is left alone in class B", run(UNUSED_POT004, b="src").problems == [])
fixture("the same line as class A", "suppression-unused and suppression-no-reason")
case(
    "...and refused in class A, which reads rule 9",
    kinds(run({**UNUSED_POT004, **READERS_OK}, a="src")) == ["suppression-no-reason", "suppression-unused"],
)

# --- a shipped script under a namespace directory, declared beside the package -------
# A consumer's shape: `scripts/` deliberately has no `__init__.py`, the package imports
# `scripts.<name>` at module level, and the script is COPY'd into the image, so the
# record's test makes it class B. Passed to mypy by path beside the package, the one
# file used to arrive under two module names and mypy exited 2 before reading a
# line. The case is mixed on purpose: the clean script reads clean, and a real type
# error in a script declared the same way is still a class B finding, so the flag
# that stops the refusal is seen not to silence the reader.
NAMESPACE_SCRIPTS = {
    "pkg/__init__.py": "from scripts.tool import answer\n\n__all__ = [\"answer\"]\n",
    "scripts/tool.py": "def answer() -> int:\n    return 42\n",
    "scripts/wrong.py": "def answer() -> int:\n    return \"forty-two\"\n",
}
fixture(
    "a package importing `scripts.<name>` with the script declared class B beside it",
    "read, not refused: the clean script is clean and the wrong one is a class B typing finding",
)
ns = run(NAMESPACE_SCRIPTS, b="pkg scripts/tool.py scripts/wrong.py")
case("...with nothing else refused", pairs(ns, "B") == {("wrong.py", "types")})

# The flag alone would have moved a reading: a `src/` layout's own imports resolve
# only if `src` is a package base. A `src/` layout's shape - `src/pkg/` declared as
# `src`, one module importing another by `from pkg.x import` - is the case that
# read one strict finding (`no-any-return`) under the flag without the base, and
# zero on `main`: the cross-module import is clean under strict.
SRC_LAYOUT = {
    "src/pkg/__init__.py": "",
    "src/pkg/a.py": "def one() -> int:\n    return 1\n",
    "src/pkg/b.py": "from pkg.a import one\n\n\ndef two() -> int:\n    return one() + 1\n",
}
fixture(
    "a `src/` layout importing its own package by name, declared class A",
    "read with `src` as a package base: the import resolves",
)
src_layout = run(SRC_LAYOUT, a="src")
case("a `src/` layout's own import resolves, so nothing crossing it reads as Any", ("b.py", "types") not in pairs(src_layout, "A"))

# --- class C: the ceiling and nothing else ---------------------------------------------

fixture("the same negatives as class C, plus a function at complexity 16", "one finding: the ceiling")
neg_c = run({**INIT, **NEGATIVES, "src/pkg/complexity16.py": ifs(15)})
case("class C reads the ceiling and nothing else", pairs(neg_c, "C") == {("complexity16.py", "C901")})

# --- deviations at the site, and the baseline ------------------------------------------

SUPPRESSIONS = {
    **INIT,
    **READERS_OK,
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
    ("sup_reason.py", "quiet"),
    ("sup_noreason.py", "suppression-no-reason"),
    ("sup_bare.py", "suppression-no-rule, and the finding stands"),
    ("sup_unused.py", "suppression-unused"),
    ("sup_other.py", "not this check's rule: ignored"),
    ("ti_reason.py", "quiet"),
    ("ti_bare.py", "suppression-no-rule"),
    ("ti_noreason.py", "suppression-no-reason"),
    ("marker_ok.py", "quiet"),
    ("marker_noissue.py", "baseline-no-issue"),
    ("marker_stray.py", "baseline-stray"),
):
    fixture(name + " as class A", what)
sup = run(SUPPRESSIONS, a="src")
a = sup.reports["A"]
case("...a named suppression covers its finding (the reason-less one too)", not any(f.path.endswith(("sup_reason.py", "sup_noreason.py", "marker_ok.py")) for f in a.findings))
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

# --- the classes: test paths, the longest prefix, an undeclared file ----------------------

fixture("src/pkg/tests/test_x.py, src/pkg/test_y.py, src/pkg/conftest.py under a class A prefix", "class C: not typed")
tests = run(
    {
        **INIT,
        **READERS_OK,
        "src/pkg/tests/test_x.py": "def add(a, b):\n    return a + b\n",
        "src/pkg/test_y.py": "def add(a, b):\n    return a + b\n",
        "src/pkg/conftest.py": "def add(a, b):\n    return a + b\n",
    },
    a="src",
)
case("a test path under a class A prefix is class C, and strict typing does not reach it", tests.problems == [])
case("...three test files and the item's suite in C, the package init in A", (tests.reports["C"].files, tests.reports["A"].files) == (4, 1))

fixture("src/pkg/scripts/tool.py with class-b src and class-c src/pkg/scripts", "class C: the global is not read")
carve = run(
    {**INIT, "src/pkg/scripts/tool.py": GLOBAL_FN.format(directive=""), "src/pkg/svc.py": GLOBAL_FN.format(directive="")},
    b="src",
    c="src/pkg/scripts",
)
case("the longest matching prefix wins: a class C carve-out inside class B", pairs(carve, "C") == set())
case("...and the class B file beside it is still refused", ("svc.py", "PLW0603") in pairs(carve, "B"))

decl = parse_declaration("src", "svc", "scripts src/x")
case("classify: a prefix matches whole path segments only", classify("srcx/a.py", decl) == "C")
# The longer prefix is declared in the class read FIRST, so the order the
# classes are read in cannot give the answer: only the length can.
inside_out = parse_declaration("src/core", "", "src")
case("classify: the longest matching prefix wins, whichever class declares it", classify("src/core/a.py", inside_out) == "A")
try:
    parse_declaration("src", "src", "")
    case("one prefix in two classes is a refusal", False)
except Refusal:
    case("one prefix in two classes is a refusal", True)

# --- the own-suite readers: every way a declaration is refused, and two that pass ----------
#
# Each tree is a clean class A package beside the suite above; only the
# declaration differs, so the one refusal each must raise is the whole of
# what it raises.

NO_READS = {"readers": [R3]}
NO_READER = {"reads": ["the answer frame a peer sends"]}
CHECK_MISSING = {"check": "tests/test_gone.py::test_refuses_past_the_maximum", "violator": R3["violator"]}
NAME_MISSING = {"check": f"{SUITE_PATH}::test_nowhere", "violator": R3["violator"]}
CLASS_MISSING = {"check": f"{SUITE_PATH}::TestNowhere::test_refuses_past_the_maximum", "violator": R3["violator"]}
NO_LINE = {"check": f"{SUITE_PATH}::test_without_its_line", "violator": R3["violator"]}
NAMES_NO_VIOLATOR = {"check": f"{SUITE_PATH}::test_names_no_violator", "violator": R3["violator"]}
VIOLATOR_MISSING = {"check": R3["check"], "violator": "tests/fixtures/over.bin"}
REFUSED_DECLARATIONS = [
    ("no declaration at all", None, "reader-undeclared"),
    ("an empty declaration, with no entry for the item", {}, "reader-undeclared"),
    ("no rule 5 entry", {"src": {"rule 3": RULE3}}, "reader-undeclared"),
    ("rule 3 with no `reads`", {"src": {"rule 3": NO_READS, "rule 5": RULE5}}, "reader-undeclared"),
    ("rule 3 listing reads and naming no reader", {"src": {"rule 3": NO_READER, "rule 5": RULE5}}, "reader-undeclared"),
    ("a check that is not a file", {"src": {"rule 3": {**RULE3, "readers": [CHECK_MISSING]}, "rule 5": RULE5}}, "reader-unresolved"),
    ("a check whose name the file does not define", {"src": {"rule 3": {**RULE3, "readers": [NAME_MISSING]}, "rule 5": RULE5}}, "reader-unresolved"),
    ("a check whose class part the file does not define", {"src": {"rule 3": {**RULE3, "readers": [CLASS_MISSING]}, "rule 5": RULE5}}, "reader-unresolved"),
    ("a check with no `Measures:` line", {"src": {"rule 3": {**RULE3, "readers": [NO_LINE]}, "rule 5": RULE5}}, "reader-unresolved"),
    ("a check that does not name its violator", {"src": {"rule 3": {**RULE3, "readers": [NAMES_NO_VIOLATOR]}, "rule 5": RULE5}}, "reader-unresolved"),
    ("a check whose `Measures:` line names another rule", {"src": {"rule 3": {**RULE3, "readers": [R5]}, "rule 5": RULE5}}, "reader-unresolved"),
    ("a violator that is not a file", {"src": {"rule 3": {**RULE3, "readers": [VIOLATOR_MISSING]}, "rule 5": RULE5}}, "reader-unresolved"),
    ("a declaration that is not JSON", '{"src": ', "reader-malformed"),
    ("`readers` that is not a list of pointers", {"src": {"rule 3": {"reads": "none", "readers": SUITE_PATH}, "rule 5": RULE5}}, "reader-malformed"),
    ("an entry for a prefix not declared class A", {**GOOD, "lib": GOOD["src"]}, "reader-orphan"),
]
for what, declaration, kind in REFUSED_DECLARATIONS:
    fixture(f"own-suite declaration: {what}", kind)
    files = {**INIT, **(declared(declaration) if declaration is not None else {SUITE_PATH: SUITE})}
    got = run(files, a="src")
    case(f"the own-suite reader refuses {what}: {kind}", kinds(got) == [kind])
    if kinds(got) != [kind]:
        for p in got.problems:
            print(f"     got: {p}")

# A pointer that leaves the tree is refused even where the file it reaches is
# real: the tree is staged one directory down, beside a copy of the suite.
fixture("own-suite declaration: a check at `../` that exists outside the tree", "reader-unresolved")
outer = stage({"outside.py": SUITE, "tree/src/pkg/__init__.py": ""})
escaping = {"src": {"rule 3": {**RULE3, "readers": [{**R3, "check": "../outside.py::TestFrame::test_refuses_past_the_maximum"}]}, "rule 5": RULE5}}
for rel, text in declared(escaping).items():
    (outer / "tree" / rel).parent.mkdir(parents=True, exist_ok=True)
    (outer / "tree" / rel).write_text(text, encoding="utf-8", newline="\n")
escaped = check(outer / "tree", parse_declaration("src", "", ""))
case("the own-suite reader refuses a pointer out of the tree at a real file: reader-unresolved", kinds(escaped) == ["reader-unresolved"])

# Rule 3 declared "none" needs no reader; and a check named by its file alone
# is read whole for its line.
NONE_READ = {"src": {"rule 3": {"reads": "none"}, "rule 5": {"readers": [{"check": SUITE_PATH, "violator": R5["violator"]}]}}}
fixture("own-suite declaration: rule 3 reads none, rule 5's check named by file alone", "green")
none_read = run({**INIT, **declared(NONE_READ)}, a="src")
case("a declared none, and a check read whole, resolve", none_read.problems == [] and none_read.presence.startswith("resolved"))

# --- the population -------------------------------------------------------------------

fixture("a tree with no .py file", "refused: an empty population is not a clean tree")
try:
    check(stage({"README.md": "no python here\n"}), parse_declaration("", "", ""))
    case("an empty population is a refusal, never a green", False)
except Refusal:
    case("an empty population is a refusal, never a green", True)

# --- a reader the interpreter cannot load ---------------------------------------------
#
# `-S` starts the interpreter without `site`, so without the site-packages both
# tools are installed into: the same absence a virtualenv that never installed
# them has, staged without uninstalling anything. The premise is asserted
# first, because on a machine where `-S` still finds the tools every case below
# would be red for the wrong reason, and should say so.

BLIND = (sys.executable, "-S")
OVER = {**INIT, "src/pkg/over.py": ifs(13)}


def refuses(call: Callable[[], object], *words: str) -> bool:
    try:
        call()
    except Refusal as exc:
        return all(w in str(exc) for w in words)
    return False


fixture("an interpreter that cannot load ruff or mypy", "refused: a reader that did not run is not a green")
for tool in ("ruff", "mypy"):
    probe = subprocess.run([*BLIND, "-m", tool, "--version"], capture_output=True)
    case(f"premise: `python -S` cannot load {tool}, so the absence is real", probe.returncode != 0)
case("the probe refuses an interpreter that cannot load ruff", refuses(lambda: reader_version("ruff", BLIND), "ruff", "requirements.txt"))
over_root = stage(OVER)
over_decl = parse_declaration("src", "", "")
case("the ruff reader refuses an exit with nothing on stdout, without the probe", refuses(lambda: ruff_findings(over_root, "A", ["src/pkg/over.py"], BLIND), "ruff exited 1"))
case("the mypy reader refuses an exit 1 that names no error, without the probe", refuses(lambda: mypy_findings(over_root, "A", mypy_targets("A", over_decl, over_root), over_decl, BLIND), "named no error"))
case("a green run names the version of each reader it used", positive.readers[0].startswith("ruff ") and positive.readers[1].startswith("mypy "))
only_c = run({"tools/a.py": "X = 1\n"})
case("mypy is not asked for where no class A or B file exists, and the run says so", only_c.problems == [] and only_c.readers[1].startswith("mypy not run"))

# --- the suppression reader, alone -----------------------------------------------------

s = parse_suppression("f.py", 3, "# noqa:C901")
case("reader: `noqa:CODE` with no space names the code", s is not None and s.codes == ("C901",) and s.reason == "")
s = parse_suppression("f.py", 3, "# NOQA: C901, E722 -- two rules, one reason")
case("reader: two codes and a reason", s is not None and s.codes == ("C901", "E722") and s.reason == "two rules, one reason")
s = parse_suppression("f.py", 3, "# noqa C901 no colon")
case("reader: a missing colon names no rule, as ruff reads it", s is not None and s.codes == ())
s = parse_suppression("f.py", 3, "# type: ignore[attr-defined, misc]  # the driver is untyped")
case("reader: a type-ignore with codes and a reason", s is not None and s.codes == ("attr-defined", "misc") and s.reason == "the driver is untyped")

# --- the code-list pattern ------------------------------------------------------------------

# Code-list shapes the estate's comments held when the separator was rewritten,
# and a whitespace-only separator the pattern has always accepted. Each must
# read to the same codes and reason as before the rewrite.
CODE_LISTS = [
    ("# noqa: E402  (engine-only from here)", ("E402",), "(engine-only from here)"),
    ("# noqa: N802  # the handler's name is the stdlib's", ("N802",), "the handler's name is the stdlib's"),
    ("# noqa: C901 , E722 -- spaces both sides", ("C901", "E722"), "spaces both sides"),
    ("# noqa: C901 E722 -- a space alone", ("C901", "E722"), "a space alone"),
    ("# noqa: C901, -- a trailing comma", ("C901",), "a trailing comma"),
]
for comment, codes, reason in CODE_LISTS:
    s = parse_suppression("f.py", 3, comment)
    case(f"reader: {comment!r} reads {codes} and its reason", s is not None and s.codes == codes and s.reason == reason)

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

fixture("the same marker count as the base", "held")
head_with(root, 1)
held = check(root, parse_declaration("", "", ""), base)
case("the same count is held", held.problems == [] and held.ratchet.startswith("held"))

fixture("the base carries the marker text inside a string literal, not a suppression", "not a marker: a real one added is still refused")
root3, base3 = repo_with_base(WORKFLOW_CALLING, 0)
(root3 / "src/pkg/m.py").write_text(f'TEXT = "{MARKER} #1 in a string"\n', encoding="utf-8", newline="\n")
git(root3, "add", "-A")
git(root3, "commit", "-q", "-m", "a literal, not a marker")
base3 = git(root3, "rev-parse", "HEAD")
head_with(root3, 1)
literal = check(root3, parse_declaration("", "", ""), base3)
case("the base is read with the same reader as the head: a literal is not a marker", kinds(literal) == ["ratchet"])

fixture("a marker added where the base does NOT call the action", "allowed: the migration pull request")
root2, base2 = repo_with_base(WORKFLOW_SILENT, 0)
head_with(root2, 2)
migration = check(root2, parse_declaration("", "", ""), base2)
case("a base that does not call the action is the migration, and markers may be added", migration.problems == [])

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
