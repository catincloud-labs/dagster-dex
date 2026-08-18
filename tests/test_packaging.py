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
from pathlib import Path

import dagster_dex

REPO_ROOT = Path(__file__).resolve().parent.parent


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


def test_every_name_in_all_resolves():
    """`__all__` is a hand-maintained list beside the imports it describes.

    A name in it that resolves to nothing breaks `from dagster_dex import *` and,
    more to the point, breaks a documented import for a consumer who read the
    project page - while every ordinary `import dagster_dex` keeps working, so
    nothing else here would notice. Cheap to state, and the list grew by four
    names when the write tier became importable from the top level.
    """

    missing = [name for name in dagster_dex.__all__ if not hasattr(dagster_dex, name)]
    assert not missing, f"__all__ names nothing importable: {missing}"


def test_the_top_level_exports_the_write_tier_vocabulary():
    """The seam and the words to call it with are exported together, or neither.

    `tier_of` and `EditableProject` were exported from `0.1.0`, so a consumer
    could ask whether a project reaches tier 3 from the top level and then had to
    reach into `dagster_dex.protocol` for the type to call it with. That
    asymmetry reads as an oversight rather than a decision, and this is the
    assertion that keeps it from returning by accident - a reordered import block
    is enough to drop one.

    **Held to what a caller CONSTRUCTS.** `EditConflict`, `ProjectFile` and
    `ProjectFileView` are values a caller receives and reads, never names, so
    they stay module-scoped. Exporting a type with no consumer is a promise made
    for nothing, and this contract is alpha.
    """

    assert {
        "EditableDagsterProject",
        "EditOutcome",
        "ProposedEdit",
    } <= set(dagster_dex.__all__)


def test_the_changelog_has_an_entry_for_the_version_being_shipped():
    """A release with no entry is the way this file stops being true.

    Not "a changelog exists" - that is satisfied forever by the day it was
    written. The version in `pyproject.toml` must have a heading, so a bump with
    no entry fails here rather than shipping a release a consumer cannot read
    about. It is the same argument as the two version strings above: the release
    workflow gates the tag against the metadata and has no opinion about whether
    anybody was told what changed.

    Deliberately not asserting the entry's CONTENT. A heading with nothing useful
    under it would pass, and no test can tell a real entry from a placeholder -
    that part is review's, and this stops the case review never sees because
    there is nothing on screen to notice.
    """

    changelog = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    version = md.version("dagster-dex")

    assert f"## {version}" in changelog, (
        f"CHANGELOG.md has no `## {version}` heading. Every release needs an "
        "entry, and the bump is the moment to write it - afterwards it gets "
        "reconstructed from git history, which is how the 0.1.0 and 0.2.0 "
        "entries in that file came to be shorter than they deserve."
    )


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
