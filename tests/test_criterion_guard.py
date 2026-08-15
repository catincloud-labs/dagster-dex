# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""The criterion guard, proved able to fail before it is trusted to pass.

A guard that has silently stopped detecting anything passes every run, which is
the one failure mode it cannot observe about itself. `conftest.py` turns a
skipped conformance assertion into a failure; this file drives it and checks
that it does, in a temporary directory, as a subprocess.

**Four arms, and each one exists because the other three would pass without it:**

- **loud** - a skipped criterion test fails the run, and the node id *and its
  reason* reach the output. Without this the guard could be a no-op.
- **quiet** - the same file, with the variable unset, passes. Without this a
  guard that failed everything would satisfy the loud arm and be useless at a
  developer's desk, where a skip is the correct behaviour.
- **empty** - a marked file collecting nothing fails. This is the arm that
  replaces the assertion count: a green run over zero tests is the shape the
  count was watching for.
- **wiring** - the real contract file still carries the marker. Without this,
  a typo in the marker name disarms every arm above while all of them stay
  green, because they supply their own marker.

**The real `conftest.py` is copied in, never re-implemented.** A test that
asserts against its own copy of the logic proves the copy works and says nothing
about the file CI loads. That is the same principle the vendored-guard
comparison rests on, applied to a test rather than to a script.

Engine-free and orchestrator-free: it runs `sys.executable -m pytest` on a
throwaway directory, so it belongs in the control step with everything else.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
CONFTEST = HERE / "conftest.py"
CONTRACT_FILE = HERE / "test_upstream_contract.py"

_MARKED_SKIP_AND_PASS = '''
import pytest

pytestmark = pytest.mark.criterion


def test_one_is_skipped():
    pytest.skip("a hook returned None, so a declared composite key went unchecked")


def test_two_passes():
    assert True
'''

_MARKED_BUT_EMPTY = '''
import pytest

pytestmark = pytest.mark.criterion

# Deliberately no test. This is what a renamed, emptied or wholly filtered
# contract file looks like from outside, and it must not read as success.
'''

#: A marked test sits beside the unmarked skip DELIBERATELY. Without it the
#: collected set is empty and the zero-collected arm fires, so the run would go
#: red for the right reason and tell us nothing about scoping - two properties
#: tested at once, which is one too many. The marked test makes the criterion
#: genuinely present, leaving the unmarked skip as the only thing under test.
_UNMARKED_SKIP_BESIDE_A_MARKED_PASS = '''
import pytest


def test_an_ordinary_skip_is_nobody_s_business():
    pytest.skip("not a criterion assertion; this is the arm that must NOT fire")


@pytest.mark.criterion
def test_the_criterion_itself_is_present_and_passes():
    assert True
'''


def _run(tmp_path: Path, body: str, *, required: bool) -> subprocess.CompletedProcess[str]:
    """Run pytest over a one-file suite that loads the REAL conftest."""

    shutil.copy(CONFTEST, tmp_path / "conftest.py")
    (tmp_path / "test_sample.py").write_text(body, encoding="utf-8")

    env = dict(os.environ)
    if required:
        env["DEX_UPSTREAM_CONTRACT_REQUIRED"] = "1"
    else:
        env.pop("DEX_UPSTREAM_CONTRACT_REQUIRED", None)

    return subprocess.run(
        [sys.executable, "-m", "pytest", str(tmp_path), "-p", "no:cacheprovider", "-q"],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(tmp_path),
    )


def test_the_loud_arm_a_skipped_criterion_assertion_fails_the_run(tmp_path):
    result = _run(tmp_path, _MARKED_SKIP_AND_PASS, required=True)

    assert result.returncode != 0, (
        "a skipped criterion assertion left the run green:\n" + result.stdout
    )
    assert "test_one_is_skipped" in result.stdout, result.stdout
    # The reason is the useful half. Upstream's skip reasons name the assertion
    # that went unchecked, so a failure printing only node ids would send a
    # reader to rediscover what the run already knew.
    assert "went unchecked" in result.stdout, result.stdout


def test_the_quiet_arm_the_same_file_passes_without_the_variable(tmp_path):
    """Without this, a guard that failed unconditionally would look correct.

    It is also the behaviour a developer without the extra depends on: there,
    skipping is right, and only CI is entitled to call a skip a failure.
    """

    result = _run(tmp_path, _MARKED_SKIP_AND_PASS, required=False)

    assert result.returncode == 0, (
        "the guard fired with the variable unset:\n" + result.stdout + result.stderr
    )


def test_the_empty_arm_a_marked_file_collecting_nothing_fails(tmp_path):
    """This arm is what replaces the assertion count.

    A criterion that collected nothing and a criterion that collected everything
    are the same colour from outside, and the count used to be the only thing
    that told them apart.
    """

    result = _run(tmp_path, _MARKED_BUT_EMPTY, required=True)

    assert result.returncode != 0, (
        "a criterion that collected nothing reported success:\n" + result.stdout
    )
    assert "no test carrying" in result.stdout, result.stdout


def test_an_unmarked_skip_does_not_fire_the_guard(tmp_path):
    """The scoping arm.

    `publish.yml` runs the WHOLE suite with the variable set, and
    `test_ascii_only.py` carries a legitimate `skipif`. A run-scoped guard would
    fail on it, so this pins that the marker is doing the scoping.

    **The fixture carries a marked passing test beside the unmarked skip, and
    the first draft did not.** Without it the run collected no criterion at all,
    the zero-collected arm fired, and the assertion went red over something it
    was not written to check - a fixture that made two arms overlap rather than
    a guard that misbehaved. Found by running it.
    """

    result = _run(tmp_path, _UNMARKED_SKIP_BESIDE_A_MARKED_PASS, required=True)

    assert result.returncode == 0, (
        "an ordinary skip outside the criterion fired the guard:\n" + result.stdout
    )


def test_the_contract_file_still_carries_the_marker():
    """The wiring arm, and the one that closes the guard's own blind spot.

    Every arm above supplies its own marker, so a typo in the real file - or a
    later edit dropping the line - disarms the guard while leaving this whole
    file green. Reading the source is crude and it is the only check that sees
    that case without importing the engine.
    """

    source = CONTRACT_FILE.read_text(encoding="utf-8")

    assert "pytest.mark.criterion" in source, (
        "tests/test_upstream_contract.py no longer carries the criterion marker, "
        "so conftest.py is watching nothing. Restore it, or move this guard."
    )


def test_the_marker_is_registered():
    """An unregistered marker is a warning, not an error, so it would go unread.

    Registering it also means `--strict-markers` stays available as an option
    later without this being the thing that breaks.
    """

    import tomllib

    pyproject = (HERE.parent / "pyproject.toml").read_bytes()
    markers = tomllib.loads(pyproject.decode("utf-8"))["tool"]["pytest"]["ini_options"]["markers"]

    assert any(m.startswith("criterion") for m in markers), markers


if sys.version_info < (3, 11):  # pragma: no cover - exercised only at the floor
    # `tomllib` arrived in 3.11 and this package's floor is 3.10, so the
    # registration check cannot run there. Skipping the one assertion is right;
    # skipping it silently is not, which is why the reason names the floor.
    test_the_marker_is_registered = pytest.mark.skip(  # noqa: F811
        reason="tomllib needs 3.11; the marker registration is checked on newer runners"
    )(test_the_marker_is_registered)
