# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""The engine version is named in many places, and nothing held them together.

Every `exmergo-dex-core` pin in this repository is a separate hand-maintained
string. They have agreed so far, which is not the same as anything checking that
they do. The failure this prevents is quiet and specific: bump the workflow and
miss the README, and the documented reproduction command installs a different
engine from the one CI proved the mapping against - so a reader following the
README verifies something nobody tested, and the difference is invisible from
either side.

**Two pins that DISAGREE ON PURPOSE, and the reason this is a test rather than a
lint.** `AGENTS.md` states the rule and then forbids the obvious fix:

    Published (pyproject.toml, the [dex] extra): a compatible-release range
    Tested (CI and the commands above): the same version, pinned exactly
    These disagree on purpose. ... Do not "fix" the mismatch by aligning them.

(Paraphrased rather than quoted with its version strings, and deliberately: a
verbatim quote here would BE a pin site, and this file would count itself. An
exemption would have hidden that instead of removing it, and an exempted file
and an unscanned one produce the same green.)

A checker that demanded one version everywhere would report the correct state of
this repository as a failure, and the first person to satisfy it would break the
plugin. So this asserts a RELATION rather than equality:

  - every exact pin names the same version;
  - every compatible-release pin shares that version's minor and does not float
    ahead of it.

That is what "they disagree on purpose" actually means, written as something
that runs. Aligning them still fails - `~=` and `==` are different operators and
the test reads them differently - and so does letting them drift apart.

**It holds no version literal.** There is nothing here to go stale, and a bump
never has to edit this file. Adding or removing a pin site does, which is the
point: `EXPECTED` is per-file, so a deleted pin cannot be masked by a duplicated
one somewhere else, and a file that stops being scanned fails rather than
quietly contributing nothing.

Engine-free and offline: it reads tracked files through `git ls-files`, so it
runs in the control step with everything else.
"""

from __future__ import annotations

import re
import subprocess
from collections import Counter
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Both operators, captured separately, because the whole point is that they are
#: allowed to differ and are not allowed to differ arbitrarily.
_PIN = re.compile(r"exmergo-dex-core(?:\[[^\]]*\])?\s*(==|~=)\s*([0-9][^\s\"',\]`]*)")

#: Per-file counts, deliberately not a global total. A global count lets a pin
#: deleted from the workflow be masked by one added to a document, which is the
#: shape that makes a coherence check feel fine while covering less.
#:
#: These are counts of pin SITES, not versions, so an ordinary version bump does
#: not touch this map. A change here means a command was added or removed, which
#: is a thing worth reviewing on its own.
#: Keyed by OPERATOR as well as by file, which a plain count is not. Counting
#: alone cannot see the one change AGENTS.md warns about most loudly - aligning
#: the published range to the tested pin leaves every count identical and only
#: the operator moves. Found by mutation: an earlier version of this file counted
#: sites, checked that both operators appeared SOMEWHERE, and passed that
#: mutation, because two of the three compatible-release strings are prose and
#: prose kept the operator alive after the guarantee had gone.
EXPECTED: dict[str, dict[str, int]] = {
    ".github/dependabot.yml": {"~=": 1},
    ".github/workflows/checks.yml": {"==": 2},
    # Three: the suite step, and the two end-to-end steps that drive dex through
    # the built wheel - one for the read path, one for the write path. Each was
    # added after this guard existed and caught on its first run, which is the
    # per-file map earning its keep twice.
    ".github/workflows/publish.yml": {"==": 3},
    # Four commands plus the "Tested" line in the two-pins section. That line
    # named the version without naming the package until the 1.6.5 bump, which
    # put the one sentence stating the tested version outside this scan. The
    # fourth command is the write-path driver's, in the section on the two
    # drivers.
    "AGENTS.md": {"==": 4, "~=": 1},
    "CONTRIBUTING.md": {"==": 2},
    # Three `==` and one `~=`: the two runnable commands, plus the two-pins
    # paragraph, which named both versions without naming the package until
    # 2026-08-15 and so stated the tested version from outside this scan. It
    # went stale at the 1.6.5 bump exactly as AGENTS.md's own note predicted,
    # and the guard passed the whole time. The `~=` here is the published range
    # restated in prose; it is in scope so the minor-alignment arm reads it.
    "README.md": {"==": 3, "~=": 1},
    # The published guarantee. This one entry is the reason the map is keyed by
    # operator: `==` here would be a different promise to every consumer's
    # resolver, with no count anywhere changing to show it.
    "pyproject.toml": {"~=": 1},
    # The by-hand command in each end-to-end driver's docstring. Runnable
    # commands, so they are held like every other one: a reader who runs one
    # against a different engine than CI does is not reproducing CI.
    "scripts/drive_dex_against_the_wheel.py": {"==": 1},
    "scripts/drive_the_write_path_against_the_wheel.py": {"==": 1},
}


def _tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def _pins() -> dict[str, list[tuple[str, str]]]:
    """Every pin in every tracked file, keyed by path.

    Scans everything rather than only the files in `EXPECTED`, so a pin added to
    a file nobody thought to list is found. A scan restricted to its own
    allowlist can only ever confirm what it already knew.
    """

    found: dict[str, list[tuple[str, str]]] = {}
    for name in _tracked_files():
        path = REPO_ROOT / name
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        matches = [(m.group(1), m.group(2)) for m in _PIN.finditer(text)]
        if matches:
            found[name] = matches
    return found


def test_every_expected_file_exists_and_still_carries_pins():
    """A missing file is a failure, never a skip.

    A checker that silently scans nothing exits zero and reads as "all clear",
    which is the one outcome it must not be able to produce.
    """

    missing = [name for name in EXPECTED if not (REPO_ROOT / name).is_file()]
    assert not missing, (
        f"files named in EXPECTED do not exist: {missing}. If a file was renamed "
        "or removed, move its entry in the same change rather than leaving a "
        "scan that covers nothing."
    )


def test_the_pin_sites_are_where_this_test_thinks_they_are():
    """Per-file counts, in both directions.

    The second direction is the one that rots: a pin added to a file not in
    `EXPECTED` is a site nothing holds, and it would otherwise be found only by
    the bump that gets it wrong.
    """

    actual = {
        name: dict(Counter(operator for operator, _ in matches))
        for name, matches in _pins().items()
    }

    assert actual == EXPECTED, (
        "the exmergo-dex-core pin sites have changed, by file and by operator.\n"
        f"  expected: {dict(sorted(EXPECTED.items()))}\n"
        f"  actual:   {dict(sorted(actual.items()))}\n"
        "Update EXPECTED in the same change that adds, removes or re-operators a "
        "pin, and say in the commit why it moved. If an operator changed in "
        "`pyproject.toml`, read the 'two pins' section of AGENTS.md first: that "
        "one is a promise to every consumer's resolver, not a local preference."
    )


def test_every_exact_pin_names_one_version():
    """The plain half. Nine or so strings, all of which must say the same thing."""

    exact = {
        version
        for matches in _pins().values()
        for operator, version in matches
        if operator == "=="
    }

    assert len(exact) == 1, (
        f"exact pins disagree about the engine version: {sorted(exact)}. CI, the "
        "release workflow and every documented reproduction command install the "
        "same engine, or the command a reader runs is not the command that was "
        "proved."
    )


def test_the_published_range_tracks_the_tested_version_without_being_aligned_to_it():
    """The half that encodes 'they disagree on purpose'.

    `~=X.Y.Z` means `>=X.Y.Z, ==X.Y.*`. Two things must hold, and neither is
    equality:

    - **Same minor.** If the tested version moved to a new minor and the
      published range did not, consumers resolve an engine the mapping was never
      checked against - and a minor is exactly where the danger has been
      observed, since 1.6.0 began resolving this entry-point group and the
      pointer failed on first contact.
    - **Floor at or below the tested version.** A floor ahead of what CI runs
      would mean the tested configuration is one this package refuses to install.

    Aligning the two operators does not satisfy this test; it fails
    `test_the_pin_sites_are_where_this_test_thinks_they_are` by changing the
    operator mix, and it is forbidden by AGENTS.md for a reason this test cannot
    restate without becoming a second copy of it.
    """

    pins = _pins()
    exact = {v for m in pins.values() for op, v in m if op == "=="}
    compatible = {v for m in pins.values() for op, v in m if op == "~="}

    assert exact, "no exact pin found at all; the tested version is unstated"
    assert compatible, "no compatible-release pin found; the published range is unstated"

    tested = _parse(next(iter(exact)))

    for raw in compatible:
        published = _parse(raw)
        assert published[:2] == tested[:2], (
            f"the published range ~={raw} and the tested pin =={next(iter(exact))} "
            "are on different minors. Consumers would resolve an engine the "
            "mapping was never checked against."
        )
        assert published <= tested, (
            f"the published floor ~={raw} is ahead of the tested pin "
            f"=={next(iter(exact))}, so the configuration CI proves is one this "
            "package refuses to install."
        )


def test_the_published_extra_is_a_range_and_the_tested_pin_is_exact():
    """The arm that catches somebody 'fixing' the mismatch, named where it lives.

    An earlier version of this test asked whether both operators appeared
    ANYWHERE in the repository, and a mutation aligning `pyproject.toml` to `==`
    sailed through it: two of the three compatible-release strings are prose, and
    prose kept the operator alive after the guarantee behind it had gone. A
    property asserted over a whole repository is not the same property asserted
    where it is load-bearing.

    So this names the two files that carry the actual promises:

    - `pyproject.toml` publishes a RANGE. An `==` there makes every dex-core
      release uninstallable beside this package until it re-releases, which
      inverts the dependency for a plugin whose host is the pinned thing.
    - the workflow pins EXACTLY. A `~=` there stops naming the version a claim
      was proved against, and "it passed against some 1.6.x" is not a claim.
    """

    pins = _pins()

    published = [op for op, _ in pins.get("pyproject.toml", [])]
    assert published == ["~="], (
        f"pyproject.toml's [dex] extra uses {published or 'no pin'} where a "
        "compatible-release range belongs. Read the 'two pins' section of "
        "AGENTS.md before changing this: it is a promise to every consumer's "
        "resolver, not a local preference."
    )

    tested = [op for op, _ in pins.get(".github/workflows/checks.yml", [])]
    assert tested and set(tested) == {"=="}, (
        f"the checks workflow uses {tested or 'no pin'} where an exact pin "
        "belongs. A demonstration should name the version it ran against."
    )


def _parse(version: str) -> tuple[int, ...]:
    """`1.6.4` to `(1, 6, 4)`, tolerating a trailing suffix.

    Compares numerically so `1.6.10` sorts after `1.6.9`, which a string compare
    gets backwards, and that is a real bump this project will reach.
    """

    parts: list[int] = []
    for chunk in version.split("."):
        digits = ""
        for char in chunk:
            if not char.isdigit():
                break
            digits += char
        if not digits:
            break
        parts.append(int(digits))
    if not parts:
        pytest.fail(f"unparseable version string in a pin: {version!r}")
    return tuple(parts)
