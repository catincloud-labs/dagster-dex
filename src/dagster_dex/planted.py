# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""Three formats built wrong on purpose, to watch the contract refuse.

A contract observed only to pass has not been shown to be one. These ship
beside :mod:`dagster_dex.conformance` so that an implementer outside this
repository can watch it go red in their own environment, on the same install
that runs it against their format, before trusting its green.

Each is one of this package's own formats with one defect a second format is
likely to ship, and each takes that format's constructor. Wire one to the
contract the way you wire your own format::

    from dagster_dex.conformance import FingerprintedProjectContract
    from dagster_dex.planted import SourceBlindProject

    class TestSourceBlind(FingerprintedProjectContract):
        def make_project(self, declarations, semantics, sources):
            return SourceBlindProject((), declaration_sources=declarations,
                                      semantic_sources=semantics,
                                      source_declarations=sources)

Run it, and the tests each class's docstring names fail while every other
assertion passes, as all of them do on the format it wraps. A defect that stops
failing those tests, or one that starts failing others, means the contract
moved underneath you.

**They wrap this package's formats rather than a toy format of their own.** A
shipped name is public surface, and a toy shipped to carry them would be a
second format to keep. :class:`SourceBlindProject` and :class:`RaisingProject`
wrap :class:`~dagster_dex.project.DagsterProject`, so they are tier 2 and reach
the tier-1 and tier-2 contracts. :class:`ConfirmBlindProject` wraps
:class:`~dagster_dex.project.EditableDagsterProject`, so it is tier 3, and is
wired to ``EditableProjectContract`` through that contract's hook, which
stages a target a human edited after the edit was proposed and so builds the
directory the format writes into.

This module does not import pytest, so it imports wherever the package does.
Like the contract's builders, the three class names are public surface.

Measures: src/dagster_dex/protocol.py, ProjectSource
Measures: src/dagster_dex/protocol.py, FingerprintedProject
Measures: src/dagster_dex/protocol.py, EditableProject
"""

from __future__ import annotations

import os
from collections.abc import Sequence

import yaml

from .model import Fingerprint, ProjectDeclarations
from .project import DagsterProject, EditableDagsterProject
from .protocol import EditOutcome, ProposedEdit

__all__ = ["ConfirmBlindProject", "RaisingProject", "SourceBlindProject"]


class SourceBlindProject(DagsterProject):
    """Fingerprints the models alone, so a new warehouse dependency is no drift.

    Breaks the tier-2 statement in ``FingerprintedProject``: the fingerprint
    is what drift is read from, and this one cannot see the sources a project
    declares. Under ``FingerprintedProjectContract`` it fails exactly
    ``test_gaining_an_external_source_is_visible_as_drift`` and
    ``test_repointing_a_source_to_another_schema_is_drift``.
    """

    def fingerprint(self) -> Fingerprint:
        full = super().fingerprint()
        return Fingerprint(
            layers={k: v for k, v in full.layers.items() if k != "sources"},
            models=full.models,
        )


class RaisingProject(DagsterProject):
    """Parses its declarations with no guard, so bad YAML is an exception.

    Breaks the tier-1 statement in ``ProjectSource``: ``declarations()`` must
    not raise. Under ``ProjectSourceContract``, and so under
    ``FingerprintedProjectContract``, it fails exactly
    ``test_malformed_input_never_raises`` and
    ``test_malformed_input_is_explained_rather_than_silent``, each with the
    parser's ``yaml.YAMLError``. Source declarations keep the guard, so the
    source channel's assertion passes: a format can be careful on one input
    and not on the other.
    """

    def declarations(self) -> ProjectDeclarations:
        for text in self._declaration_sources.values():
            yaml.safe_load(text)
        return super().declarations()


class ConfirmBlindProject(EditableDagsterProject):
    """Writes every edit as though confirmed, so a human's edit is overwritten.

    Breaks the tier-3 statement in ``EditableProject``: a target that moved
    after the edit was proposed is a conflict, and a write left unconfirmed
    refuses the whole set. This one still checks every pin and still reports
    the conflict, then writes anyway, which is the shape of a format whose
    ``confirmed`` flag is dropped on the way down to the writer. Under
    ``EditableProjectContract`` it fails exactly
    ``test_an_unconfirmed_write_refuses_a_target_that_moved`` and
    ``test_the_outcome_reports_what_happened``, each with an
    ``AssertionError``. The second is the same defect read from the outcome:
    the overwritten target is reported in ``written``, so a caller marks the
    proposal applied. A confirmed write still lands, so the override assertion
    passes.
    """

    def propose_edits(
        self,
        edits: Sequence[ProposedEdit],
        *,
        root: str | os.PathLike[str] | None = None,
        confirmed: bool = False,
    ) -> EditOutcome:
        del confirmed  # the planted defect: the caller's answer is never read
        return super().propose_edits(edits, root=root, confirmed=True)
