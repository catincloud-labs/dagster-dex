# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""The packaging claims, asserted rather than trusted.

Engine-free on purpose, so these run in the control step alongside everything
else that must work without dex-core installed.

These do not replace the release workflow's checks, which install the built
WHEEL and assert the same things against the artifact. These run against an
editable install, which can succeed on metadata that cannot produce a valid
sdist. Both exist because they fail for different reasons.
"""

from __future__ import annotations

import importlib.metadata as md
import importlib.resources as res

import dagster_dex


def test_the_two_version_strings_agree():
    """`version` in pyproject.toml and `__version__` in `__init__.py` are two
    hand-maintained strings with nothing tying them together.

    The release workflow gates the TAG against the distribution metadata, and
    would not notice these two disagreeing -- it would publish a wheel whose
    metadata matched the tag while the package reported something else at
    runtime. That is the gap this closes, and it is the only one of the three
    pairs that was previously unguarded.
    """

    assert dagster_dex.__version__ == md.version("dagster-dex")


def test_the_py_typed_marker_exists():
    """`Typing :: Typed` in the classifiers is a claim that this marker ships.

    Without the marker a consumer's type checker ignores every annotation in the
    package regardless of what the project page says, so the classifier alone is
    an unchecked claim. Asserted here against the source tree; the release
    workflow asserts it again inside the built wheel, which is where it would
    actually go missing -- a `package-data` entry is exactly the kind of thing
    that is correct in the tree and absent from the artifact.
    """

    assert res.files("dagster_dex").joinpath("py.typed").is_file()


def test_the_entry_point_is_registered_and_names_the_factory_module():
    """The registration is present and points at the factory, not the class.

    A declared entry point is not a working one. This package shipped a group
    registration from 0.1.0 that named the CLASS rather than the factory, and it
    went unnoticed for months because nothing looked the group up -- the defect
    was invisible until the day dex-core started resolving it.

    **This checks the metadata string only. It deliberately does not `.load()`
    it**, because that would import the boundary module and this file has to run
    in the engine-free control step. That the target actually loads and builds a
    project is asserted in `test_dex_bridge.py`, where the engine is present, and
    again against the built wheel in the release workflow. Three checks, none of
    them redundant: this one catches the entry point going missing from an
    install, and it is the only one that runs without dex-core.
    """

    names = {e.name: e for e in md.entry_points(group="exmergo_dex_core.projects")}
    assert "dagster" in names, f"entry point missing: {sorted(names)}"
    assert names["dagster"].value.startswith("dagster_dex.dex:")
