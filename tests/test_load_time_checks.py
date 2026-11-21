# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""Each load-time check in `src` refuses a wrong fact, and none goes unplanted.

A module that holds a fact by construction checks it when it loads, with an
explicit `raise`. A check nobody has seen fire is not shown to be a check, so
each one has a row in `PLANTS`: the module's own source with one fact made
wrong, which must make the import raise with that check's message. The clean
source runs first, so a check that raises on everything is caught too.

The second case reads the population a different way from the table: it walks
every module under `src/dagster_dex`, reads the message of every `raise` in a
top-level statement other than a `def` or a `class`, and requires that set,
module by module, to equal the messages the table plants. A check added with no
plant is red here, and so is a new arm of an existing check with its own
message, or a plant whose check is gone.

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
        "dex: a source option is not a known option, so it is refused",
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
        "checks: two metadata keys are one string, so one value overwrites another",
    ),
    Plant(
        "checks-a-prefix-not-a-dagster-name",
        "checks",
        '_PREFIX = "declared_key"',
        '_PREFIX = "declared-key"',
        "checks: a check name's prefix or separator is not a Dagster name",
    ),
    Plant(
        "checks-a-separator-not-a-dagster-name",
        "checks",
        '_SEPARATOR = "__"',
        '_SEPARATOR = "--"',
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
    Plant(
        "init-an-export-not-defined",
        "__init__",
        "__all__ = [",
        '__all__ = ["_not_defined_anywhere", ',
        "dagster_dex: a name in __all__ is not defined in the module",
    ),
    Plant(
        "artifact-an-export-not-defined",
        "artifact",
        "__all__ = [",
        '__all__ = ["_not_defined_anywhere", ',
        "artifact: a name in __all__ is not defined in the module",
    ),
    Plant(
        "checks-an-export-not-defined",
        "checks",
        "__all__ = [",
        '__all__ = ["_not_defined_anywhere", ',
        "checks: a name in __all__ is not defined in the module",
    ),
    Plant(
        "conformance-an-export-not-defined",
        "conformance",
        "__all__ = [",
        '__all__ = ["_not_defined_anywhere", ',
        "conformance: a name in __all__ is not defined in the module",
    ),
    Plant(
        "declarations-an-export-not-defined",
        "declarations",
        "__all__ = [",
        '__all__ = ["_not_defined_anywhere", ',
        "declarations: a name in __all__ is not defined in the module",
    ),
    Plant(
        "dex-an-export-not-defined",
        "dex",
        "__all__ = [",
        '__all__ = ["_not_defined_anywhere", ',
        "dex: a name in __all__ is not defined in the module",
    ),
    Plant(
        "model-an-export-not-defined",
        "model",
        "__all__ = [",
        '__all__ = ["_not_defined_anywhere", ',
        "model: a name in __all__ is not defined in the module",
    ),
    Plant(
        "planted-an-export-not-defined",
        "planted",
        "__all__ = [",
        '__all__ = ["_not_defined_anywhere", ',
        "planted: a name in __all__ is not defined in the module",
    ),
    Plant(
        "project-an-export-not-defined",
        "project",
        "__all__ = [",
        '__all__ = ["_not_defined_anywhere", ',
        "project: a name in __all__ is not defined in the module",
    ),
    Plant(
        "protocol-an-export-not-defined",
        "protocol",
        "__all__ = [",
        '__all__ = ["_not_defined_anywhere", ',
        "protocol: a name in __all__ is not defined in the module",
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
    with pytest.raises(RuntimeError, match=f"^{re.escape(plant.message)}$"):
        _load(plant.module, source.replace(plant.fact, plant.wrong))


def _raised_at_load(path: Path) -> set[str]:
    """The message of every ``raise`` in a top-level statement other than a
    ``def`` or ``class``, each arm of a compound check read on its own.

    A ``raise`` whose message is not a string constant is read as its line,
    which no plant can match, so it reads red rather than going uncounted.
    """

    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        for inner in ast.walk(node):
            if not isinstance(inner, ast.Raise):
                continue
            exc = inner.exc
            if (
                isinstance(exc, ast.Call)
                and exc.args
                and isinstance(exc.args[0], ast.Constant)
                and isinstance(exc.args[0].value, str)
            ):
                found.add(exc.args[0].value)
            else:
                found.add(f"<a raise with no constant message, line {inner.lineno}>")
    return found


def test_every_load_time_check_in_src_has_a_plant() -> None:
    modules = sorted(PACKAGE.rglob("*.py"))
    # The positive control: a walk that found nothing would pass the loop.
    assert len(modules) > 5, modules
    raised = {}
    for path in modules:
        found = _raised_at_load(path)
        if found:
            # Keyed by the path under the package, so two modules sharing a
            # stem in different subpackages stay two.
            raised[path.relative_to(PACKAGE).with_suffix("").as_posix()] = found
    planted: dict[str, set[str]] = {}
    for plant in PLANTS:
        planted.setdefault(plant.module, set()).add(plant.message)
    assert raised == planted
