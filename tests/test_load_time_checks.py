# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""Each load-time check in `src` refuses a wrong fact, and none goes unplanted.

A module that holds a fact by construction checks it when it loads, with an
explicit `raise`. A check nobody has seen fire is not shown to be a check, so
each one has a row in `PLANTS`: the module's own source with one fact made
wrong, which must make the import raise with that check's message. The clean
source runs first, so a check that raises on everything is caught too.

The second case reads the population a different way from the table: it walks
every module under `src/dagster_dex`, counts the top-level statements other
than a `def` or a `class` that hold a `raise`, and requires as many distinct
planted messages for that module. A check added with no plant is red here.

This file is the coding standard's rule 5 reader for `src`, declared in
`power-of-ten.json`:

Measures: scripts/check_power_of_ten.py, rule 5

Both arms run without the engine or Dagster: neither module imports either at
load, so this file runs in the engine-free control.
"""

from __future__ import annotations

import ast
import importlib.util
import re
import sys
from pathlib import Path
from typing import NamedTuple

import pytest

PACKAGE = Path(__file__).resolve().parent.parent / "src" / "dagster_dex"


class Plant(NamedTuple):
    id: str
    module: str
    fact: str
    wrong: str
    message: str


PLANTS = (
    Plant(
        "dex-a-source-option-unknown",
        "dex",
        '_SOURCE_OPTIONS = frozenset({"assets", "artifact"})',
        '_SOURCE_OPTIONS = frozenset({"assets", "artifact", "manifest"})',
        "dex: a source option is not a known option",
    ),
    Plant(
        "dex-an-artifact-refusal-unknown",
        "dex",
        '_ARTIFACT_INAPPLICABLE = frozenset({"semantics", "sources", "name"})',
        '_ARTIFACT_INAPPLICABLE = frozenset({"semantics", "sources", "name", "graph"})',
        "dex: an option refused beside an artifact is not a known option",
    ),
    Plant(
        "dex-an-artifact-refusal-is-a-source",
        "dex",
        '_ARTIFACT_INAPPLICABLE = frozenset({"semantics", "sources", "name"})',
        '_ARTIFACT_INAPPLICABLE = frozenset({"semantics", "sources", "name", "assets"})',
        "dex: an option refused beside an artifact is a source option",
    ),
    Plant(
        "dex-grain-coverage-below-verify",
        "dex",
        "GRAIN_COVERAGE_FROM = (1, 17, 5)",
        "GRAIN_COVERAGE_FROM = (1, 12, 5)",
        "dex: grain coverage is read from an engine whose verify does not judge",
    ),
    Plant(
        "dex-a-measured-status-not-judged",
        "dex",
        '    "unchecked": ',
        '    "broken": ',
        "dex: a measured grain status is described as not judged",
    ),
    Plant(
        "checks-two-metadata-keys-one-string",
        "checks",
        'ENGINE = "dagster_dex/engine"',
        'ENGINE = "dagster_dex/reason"',
        "checks: two metadata keys are one string",
    ),
    Plant(
        "checks-a-prefix-not-a-dagster-name",
        "checks",
        '_PREFIX = "declared_key"',
        '_PREFIX = "declared-key"',
        "checks: a check name's prefix or separator is not a Dagster name",
    ),
    Plant(
        "checks-an-empty-suffix",
        "checks",
        "_SUFFIX_LENGTH = 12",
        "_SUFFIX_LENGTH = 0",
        "checks: the claim id suffix is empty or longer than a claim id",
    ),
    Plant(
        "checks-a-suffix-past-the-claim-id",
        "checks",
        "_SUFFIX_LENGTH = 12",
        "_SUFFIX_LENGTH = 65",
        "checks: the claim id suffix is empty or longer than a claim id",
    ),
)


def _load(module: str, source: str) -> None:
    """Run ``source`` as a fresh copy of ``dagster_dex.<module>``.

    Registered in ``sys.modules`` while it runs, because a dataclass looks its
    own module up there, and removed after, so the real module is untouched.
    """

    name = f"dagster_dex._load_time_check_{module}"
    spec = importlib.util.spec_from_loader(name, loader=None)
    assert spec is not None
    copy = importlib.util.module_from_spec(spec)
    copy.__package__ = "dagster_dex"
    sys.modules[name] = copy
    try:
        exec(compile(source, str(PACKAGE / f"{module}.py"), "exec"), copy.__dict__)
    finally:
        del sys.modules[name]


def _source(module: str) -> str:
    return (PACKAGE / f"{module}.py").read_text(encoding="utf-8")


@pytest.mark.parametrize("plant", PLANTS, ids=[plant.id for plant in PLANTS])
def test_a_planted_wrong_fact_makes_the_import_raise(plant: Plant) -> None:
    source = _source(plant.module)
    # The clean arm first: the module's own source loads.
    _load(plant.module, source)
    # The fact must be in the source exactly once, or the plant planted nothing.
    assert source.count(plant.fact) == 1, plant.fact
    with pytest.raises(RuntimeError, match=re.escape(plant.message)):
        _load(plant.module, source.replace(plant.fact, plant.wrong))


def _load_time_checks(path: Path) -> int:
    """Top-level statements, other than a ``def`` or ``class``, holding a ``raise``."""

    tree = ast.parse(path.read_text(encoding="utf-8"))
    return sum(
        1
        for node in tree.body
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and any(isinstance(inner, ast.Raise) for inner in ast.walk(node))
    )


def test_every_load_time_check_in_src_has_a_plant() -> None:
    modules = sorted(PACKAGE.rglob("*.py"))
    # The positive control: a walk that found nothing would pass the loop.
    assert len(modules) > 5, modules
    counted = {}
    for path in modules:
        found = _load_time_checks(path)
        if found:
            counted[path.stem] = found
    planted = {
        module: len({plant.message for plant in PLANTS if plant.module == module})
        for module in {plant.module for plant in PLANTS}
    }
    assert counted == planted
