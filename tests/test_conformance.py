# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""DagsterProject against the shipped contract, and the contract going red.

The whole of the wiring is `make_project`. That is the point of shipping the
suite: a second format writes these same few lines and inherits every
assertion, rather than hand-rolling parity tests that drift from the contract
they are supposed to be checking.

**The calibrations at the end run the planted defects the package ships.** A
contract observed only to pass has not been shown to be one, so each format in
`dagster_dex.planted` runs through every tier-2 contract test, and the set that
fails has to be exactly the set it is built to fail. The same holds from the
built wheel, outside this tree, in `scripts/run_the_shipped_contract_from_the_wheel.py`.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
import yaml

from dagster_dex import DagsterProject, ProjectModel
from dagster_dex.conformance import (
    EditableProjectContract,
    FingerprintedProjectContract,
    a_single_key_declaration,
)
from dagster_dex.model import definition_hash
from dagster_dex.planted import RaisingProject, SourceBlindProject
from dagster_dex.project import EditableDagsterProject
from dagster_dex.protocol import ProposedEdit

MODELS = (
    ProjectModel(name="dim_date", layer="silver"),
    ProjectModel(name="dim_product", layer="silver"),
    ProjectModel(name="fact_orders", depends_on=("dim_date",), layer="gold"),
    ProjectModel(name="fact_sessions", depends_on=("dim_date",), layer="gold"),
    ProjectModel(name="mart_revenue", depends_on=("fact_orders",), layer="platinum"),
)


class TestDagsterProjectConformance(FingerprintedProjectContract):
    def make_project(self, declarations, semantics, sources):
        return DagsterProject(
            MODELS,
            name="demo_project",
            declaration_sources=declarations,
            semantic_sources=semantics,
            source_declarations=sources,
        )


class TestEditableDagsterProjectConformance(EditableProjectContract):
    """The write tier, against the contract this package asks others to pass.

    Held to our own suite as well as to dex-core's, and the two are not
    redundant: theirs judges the translation at the boundary, ours judges the
    mechanism. A format implementing only :mod:`dagster_dex.protocol` - the
    thing this package is actually proposing - is judged by this one alone.
    """

    def an_edit_against_a_changed_target(self):
        # A fresh directory per call, because both write assertions use this and
        # one of them writes. A shared one would let the second assertion see
        # what the first left behind, which is the failure that makes a staged
        # conflict stop being staged.
        root = Path(tempfile.mkdtemp())
        directory = root / "declarations"
        directory.mkdir()
        target = directory / "dim_date.yml"
        target.write_text(a_single_key_declaration(), encoding="utf-8", newline="\n")

        project = EditableDagsterProject(
            MODELS,
            root=root,
            surface=("declarations",),
            declaration_sources={
                "declarations/dim_date.yml": target.read_text(encoding="utf-8")
            },
        )
        edits = [
            ProposedEdit(
                key="declarations/dim_date.yml",
                new_content="models: []\n",
                pinned_hash=definition_hash(target.read_text(encoding="utf-8")),
            )
        ]

        # The human, arriving during review. Everything above is the proposal;
        # this line is what the write tier exists to notice.
        target.write_text(
            "models: [{name: edited_by_a_human}]\n", encoding="utf-8", newline="\n"
        )

        return project, edits, lambda: target.read_text(encoding="utf-8")


# --- calibration: the shipped planted defects, and the contract going red -----

#: Every tier-2 contract test, read off the contract rather than listed, so a
#: test the contract gains is run against each defect too.
CONTRACT_TESTS = tuple(
    sorted(name for name in dir(FingerprintedProjectContract) if name.startswith("test_"))
)

#: What each planted defect is built to fail, and how. Every other contract
#: test has to pass on it. `REFUSING` in
#: `scripts/run_the_shipped_contract_from_the_wheel.py` holds the same sets
#: against the built wheel.
PLANTED = {
    SourceBlindProject: {
        "test_gaining_an_external_source_is_visible_as_drift": AssertionError,
        "test_repointing_a_source_to_another_schema_is_drift": AssertionError,
    },
    RaisingProject: {
        "test_malformed_input_never_raises": yaml.YAMLError,
        "test_malformed_input_is_explained_rather_than_silent": yaml.YAMLError,
    },
}


def _wired(project_class):
    class Wired(FingerprintedProjectContract):
        def make_project(self, declarations, semantics, sources):
            return project_class(
                MODELS,
                name="demo_project",
                declaration_sources=declarations,
                semantic_sources=semantics,
                source_declarations=sources,
            )

    return Wired


def _failures(contract_class):
    """Run every contract test; return ``{name: exception type}`` for each failure.

    Only the two kinds a defect here raises are caught. Anything else
    propagates and fails the calibration, rather than counting as a refusal.
    """

    failed = {}
    for name in CONTRACT_TESTS:
        try:
            getattr(contract_class(), name)()
        except (AssertionError, yaml.YAMLError) as error:
            failed[name] = type(error)
    return failed


def test_the_calibration_reads_a_contract_that_is_not_empty():
    """The positive control: an empty list of tests would fail nothing."""

    for expected in PLANTED.values():
        assert set(expected) <= set(CONTRACT_TESTS)
    assert len(CONTRACT_TESTS) > sum(len(expected) for expected in PLANTED.values())


@pytest.mark.parametrize("planted", list(PLANTED), ids=lambda cls: cls.__name__)
def test_each_planted_defect_fails_exactly_the_tests_it_is_built_to_fail(planted):
    # The clean arm first: every assertion passes on the honest format.
    assert _failures(_wired(DagsterProject)) == {}

    failures = _failures(_wired(planted))

    assert set(failures) == set(PLANTED[planted])
    for name, kind in PLANTED[planted].items():
        assert issubclass(failures[name], kind), (name, failures[name])
