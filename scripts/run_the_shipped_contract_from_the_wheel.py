# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""Run the shipped contract from the built wheel, outside the source tree (#186).

Every other run of `dagster_dex.conformance` in this repository installs the
tree editable and runs from `tests/`. An implementer does neither: the package
is an install, and the test module is theirs. So this copies
`scripts/a_format_outside_the_tree.py` into an empty directory, runs pytest on
it there with the interpreter it was started with, and reads each test's
outcome out of a JUnit report rather than trusting the exit code.

**The refusing arm is read first, and a passing arm is not reported until it
holds.** Each planted defect has to fail exactly the tests it is built to fail,
with the kind of error it is built to raise, and pass every other one. A
defect that stops failing, or starts failing elsewhere, is red; so is a
module that fails to import, which is how a wheel missing `conformance.py` or
`planted.py` shows. Then the passing arm: every test of this package's own
format passes.

Run it from the repository root after `uv build`, with no engine installed.
In Git Bash, as `publish.yml` runs it:

    uv run --no-project --with "./$(ls dist/*.whl)" --with pytest==8.4.1 \
      python scripts/run_the_shipped_contract_from_the_wheel.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MODULE = REPO / "scripts" / "a_format_outside_the_tree.py"

#: The tier-2 contract's classes, which must all run the same tests.
TIER_TWO = ("TestDagsterProject", "TestSourceBlindProject", "TestRaisingProject")
PASSING = ("TestDagsterProject", "TestEditableDagsterProject")

#: What each planted defect fails, and a fragment of the failure's message
#: that names the kind of error. Everything else in its class must pass.
REFUSING = {
    "TestSourceBlindProject": {
        "test_gaining_an_external_source_is_visible_as_drift": "AssertionError",
        "test_repointing_a_source_to_another_schema_is_drift": "AssertionError",
    },
    "TestRaisingProject": {
        "test_malformed_input_never_raises": "yaml.",
        "test_malformed_input_is_explained_rather_than_silent": "yaml.",
    },
}

Outcome = tuple[str, str]  # (passed | failed | error | skipped, message)


def _isolated_env() -> dict[str, str]:
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    return env


def _where_the_package_resolves(cwd: Path) -> list[str]:
    """Where `dagster_dex` and its two shipped test modules import from."""

    probe = (
        "import dagster_dex, dagster_dex.conformance, dagster_dex.planted\n"
        "for m in (dagster_dex, dagster_dex.conformance, dagster_dex.planted):\n"
        "    print(m.__file__)\n"
    )
    done = subprocess.run(
        [sys.executable, "-I", "-c", probe], cwd=cwd, env=_isolated_env(),
        capture_output=True, text=True, timeout=120,
    )
    if done.returncode != 0:
        raise SystemExit(f"FAIL: the installed package does not import:\n{done.stderr}")
    return done.stdout.split()


def _run_pytest(cwd: Path, report: Path) -> int:
    # Flushed first, so this script's lines and pytest's stay in order in a log.
    sys.stdout.flush()
    done = subprocess.run(
        [sys.executable, "-m", "pytest", MODULE.name, "-p", "no:cacheprovider",
         "-q", "-rfE", "--tb=line", f"--junitxml={report}", f"--rootdir={cwd}"],
        cwd=cwd, env=_isolated_env(), timeout=600,
    )
    return done.returncode


def _outcome(case: ET.Element) -> Outcome:
    for kind in ("failure", "error", "skipped"):
        child = case.find(kind)
        if child is not None:
            label = {"failure": "failed"}.get(kind, kind)
            return label, child.get("message", "")
    return "passed", ""


def _outcomes(report: Path) -> dict[str, dict[str, Outcome]]:
    """``{class: {test: outcome}}``, with anything outside a class under ``""``."""

    by_class: dict[str, dict[str, Outcome]] = {}
    for case in ET.parse(report).getroot().iter("testcase"):
        owner = case.get("classname", "").rpartition(".")[2]
        if not owner.startswith("Test"):
            owner = ""
        by_class.setdefault(owner, {})[case.get("name", "")] = _outcome(case)
    return by_class


def _check_shape(by_class: dict[str, dict[str, Outcome]]) -> list[str]:
    problems = [f"collected outside any class: {by_class['']}"] if "" in by_class else []
    for name in (*TIER_TWO, "TestEditableDagsterProject"):
        if not by_class.get(name):
            problems.append(f"{name} collected no tests")
    names = {cls: set(by_class.get(cls, {})) for cls in TIER_TWO}
    for cls in TIER_TWO[1:]:
        if names[cls] != names[TIER_TWO[0]]:
            problems.append(f"{cls} ran other tests than {TIER_TWO[0]}")
    return problems


def _check_refusing(by_class: dict[str, dict[str, Outcome]]) -> list[str]:
    problems = []
    for cls, expected in REFUSING.items():
        for test, (outcome, message) in sorted(by_class.get(cls, {}).items()):
            if test in expected:
                if outcome != "failed" or expected[test] not in message:
                    problems.append(f"{cls}.{test}: expected to fail with "
                                    f"{expected[test]!r}, was {outcome}: {message[:200]}")
                else:
                    print(f"  red, as built   {cls}.{test}")
            elif outcome != "passed":
                problems.append(f"{cls}.{test}: expected to pass, was {outcome}: {message[:200]}")
        missing = set(expected) - set(by_class.get(cls, {}))
        problems.extend(f"{cls}.{test}: never ran" for test in sorted(missing))
    return problems


def _check_passing(by_class: dict[str, dict[str, Outcome]]) -> list[str]:
    problems = []
    for cls in PASSING:
        results = by_class.get(cls, {})
        bad = {t: o for t, o in results.items() if o[0] != "passed"}
        problems.extend(f"{cls}.{t}: {o[0]}: {o[1][:200]}" for t, o in sorted(bad.items()))
        if not bad:
            print(f"  green           {cls}: {len(results)} tests")
    return problems


def _fail(stage: str, problems: list[str]) -> None:
    print(f"FAIL ({stage}):")
    for problem in problems:
        print(f"  {problem}")
    raise SystemExit(1)


def main() -> None:
    with tempfile.TemporaryDirectory() as scratch:
        cwd = Path(scratch)
        shutil.copy(MODULE, cwd / MODULE.name)
        resolved = _where_the_package_resolves(cwd)
        inside = [f for f in resolved if Path(f).resolve().is_relative_to(REPO)]
        if inside:
            _fail("isolation", [f"imported from the source tree: {f}" for f in inside])
        print("the package resolves from the install:")
        for f in resolved:
            print(f"  {f}")

        report = cwd / "report.xml"
        code = _run_pytest(cwd, report)
        if not report.is_file():
            _fail("collection", [f"pytest exited {code} and wrote no report"])
        by_class = _outcomes(report)

    print("\nshape:")
    if problems := _check_shape(by_class):
        _fail("shape", problems)
    print(f"  {len(by_class)} classes, the tier-2 three running the same tests")

    print("\nrefusing arm, read first:")
    if problems := _check_refusing(by_class):
        _fail("refusing arm", problems)
    if code != 1:
        _fail("refusing arm", [f"pytest exited {code}, where failing tests exit 1"])

    print("\npassing arm:")
    if problems := _check_passing(by_class):
        _fail("passing arm", problems)
    print("\nOK: each planted defect fails exactly its own tests; this format passes.")


if __name__ == "__main__":
    main()
