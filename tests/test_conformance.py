# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""DagsterProject against the shipped contract.

The whole of the wiring is `make_project`. That is the point of shipping the
suite: a second format writes these same few lines and inherits every
assertion, rather than hand-rolling parity tests that drift from the contract
they are supposed to be checking.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from dagster_dex import DagsterProject, ProjectModel
from dagster_dex.conformance import (
    EditableProjectContract,
    FingerprintedProjectContract,
    a_single_key_declaration,
)
from dagster_dex.model import definition_hash
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
