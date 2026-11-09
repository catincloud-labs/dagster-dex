# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""The shipped contract, wired the way an implementer outside this tree wires it.

Not a test of this repository, and kept out of `tests/` so nothing collects it
against the source tree. `scripts/run_the_shipped_contract_from_the_wheel.py`
copies it into an empty directory and runs it there with pytest, against the
built wheel, which is the position an implementer is in: the package is an
install, and the test module is theirs.

It imports only the installed package. Each class is the subclass
`docs/design/implementing-a-format.md` tells an implementer to write:

- `TestDagsterProject` and `TestEditableDagsterProject` are the passing arm,
  this package's own format through the tier-2 and tier-3 contracts;
- `TestSourceBlindProject` and `TestRaisingProject` are the refusing arm, the
  formats `dagster_dex.planted` ships, and are meant to go red. The runner
  asserts which of their tests fail, so a defect that stops failing is red.
"""

from __future__ import annotations

import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path

from dagster_dex import DagsterProject, EditableDagsterProject, ProjectModel, ProposedEdit
from dagster_dex.conformance import (
    EditableProjectContract,
    FingerprintedProjectContract,
    a_single_key_declaration,
)
from dagster_dex.model import definition_hash
from dagster_dex.planted import RaisingProject, SourceBlindProject

MODELS = (
    ProjectModel(name="dim_date", layer="silver"),
    ProjectModel(name="fact_orders", depends_on=("dim_date",), layer="gold"),
)


def _built(cls: type[DagsterProject], declarations: dict[str, str],
           semantics: dict[str, str], sources: dict[str, str]) -> DagsterProject:
    return cls(
        MODELS,
        name="outside",
        declaration_sources=declarations,
        semantic_sources=semantics,
        source_declarations=sources,
    )


class TestDagsterProject(FingerprintedProjectContract):
    def make_project(self, declarations: dict[str, str], semantics: dict[str, str],
                     sources: dict[str, str]) -> DagsterProject:
        return _built(DagsterProject, declarations, semantics, sources)


class TestEditableDagsterProject(EditableProjectContract):
    def an_edit_against_a_changed_target(
        self,
    ) -> tuple[EditableDagsterProject, Sequence[ProposedEdit], Callable[[], object]]:
        # A fresh directory per call: one of the write assertions writes.
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
        # The human, editing the target after the edit was proposed.
        target.write_text(
            "models: [{name: edited_by_a_human}]\n", encoding="utf-8", newline="\n"
        )
        return project, edits, lambda: target.read_text(encoding="utf-8")


class TestSourceBlindProject(FingerprintedProjectContract):
    def make_project(self, declarations: dict[str, str], semantics: dict[str, str],
                     sources: dict[str, str]) -> DagsterProject:
        return _built(SourceBlindProject, declarations, semantics, sources)


class TestRaisingProject(FingerprintedProjectContract):
    def make_project(self, declarations: dict[str, str], semantics: dict[str, str],
                     sources: dict[str, str]) -> DagsterProject:
        return _built(RaisingProject, declarations, semantics, sources)
