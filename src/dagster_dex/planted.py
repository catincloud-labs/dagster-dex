# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""Six formats built wrong on purpose, to watch the contract refuse.

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
the tier-1 and tier-2 contracts. The other four wrap
:class:`~dagster_dex.project.EditableDagsterProject`, so they are tier 3, and
are wired to ``EditableProjectContract`` through that contract's hook, which
stages a target a human edited after the edit was proposed and so builds the
directory the format writes into.

**Three of the tier-3 four are the write-path defects on record** (#200):
:class:`HalfRefusingProject` writes the clean targets beside a conflict,
:class:`CreateBlindProject` does not check a create pinned to absence, and
:class:`PrefixMatchingProject` matches its surface by string prefix. Each is
the replacement ``docs/design/verification.md`` records planting in
``project.py``, made as a subclass, and each fails one test of the tier-3
contract, the one built for it. :class:`ConfirmBlindProject` is the fourth.

This module does not import pytest, so it imports wherever the package does.
Like the contract's builders, the six class names are public surface.

Measures: src/dagster_dex/protocol.py, ProjectSource
Measures: src/dagster_dex/protocol.py, FingerprintedProject
Measures: src/dagster_dex/protocol.py, EditableProject
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path, PurePosixPath

import yaml

from .model import Fingerprint, ProjectDeclarations, definition_hash
from .project import DagsterProject, EditableDagsterProject, _within
from .protocol import EditOutcome, ProposedEdit

__all__ = [
    "ConfirmBlindProject",
    "CreateBlindProject",
    "HalfRefusingProject",
    "PrefixMatchingProject",
    "RaisingProject",
    "SourceBlindProject",
]


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
    ``test_an_unconfirmed_write_refuses_a_target_that_moved``,
    ``test_the_outcome_reports_what_happened``,
    ``test_one_conflict_refuses_the_clean_edit_beside_it`` and
    ``test_a_create_whose_target_now_exists_is_a_conflict``, each with an
    ``AssertionError``. The second is the same defect read from the outcome:
    the overwritten target is reported in ``written``, so a caller marks the
    proposal applied. The last two stage a conflict of their own, a mixed set
    and a create over a file that exists, and an override nobody gave writes
    through both. A confirmed write still lands, so the override assertion
    passes, and containment is untouched, so the surface assertions pass.

    That it still reports the conflict is how it is built, not something the
    contract holds: the outcome assertion fails on ``written`` before it reads
    ``conflicts``, so a variant that also dropped the conflict would fail the
    same two tests.
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


class HalfRefusingProject(EditableDagsterProject):
    """Writes the clean targets beside a conflict, so a refused set half lands.

    Breaks the tier-3 statement in ``EditableProject``: with ``confirmed``
    false, one conflict refuses the *whole* set. This one checks every pin and
    reports the conflicts, then writes the edits that did not conflict, which
    is the shape of a writer that refuses per edit rather than per set. Under
    ``EditableProjectContract`` it fails exactly
    ``test_one_conflict_refuses_the_clean_edit_beside_it``, with an
    ``AssertionError``: the clean edit is reported in ``written``. A set of one
    conflicting edit has no clean half, so every other assertion passes.
    """

    def propose_edits(
        self,
        edits: Sequence[ProposedEdit],
        *,
        root: str | os.PathLike[str] | None = None,
        confirmed: bool = False,
    ) -> EditOutcome:
        refused = super().propose_edits(edits, root=root, confirmed=confirmed)
        if not refused.conflicts or confirmed:
            return refused
        moved = {conflict.key for conflict in refused.conflicts}
        clean = [edit for edit in edits if edit.key not in moved]
        # The planted defect: the clean half is written anyway.
        landed = super().propose_edits(clean, root=root) if clean else EditOutcome()
        return EditOutcome(written=landed.written, conflicts=refused.conflicts)


class CreateBlindProject(EditableDagsterProject):
    """Reads a create's absent pin as no expectation, so a new file is overwritten.

    Breaks the tier-3 statement in ``EditableProject``: ``pinned_hash=None``
    says the target did not exist when the edit was proposed, and a file there
    now is a conflict. This one re-pins every create to whatever its target
    holds before checking, which is the shape of a writer whose check reads
    ``None`` as "nothing to compare". Under ``EditableProjectContract`` it fails
    exactly ``test_a_create_whose_target_now_exists_is_a_conflict``, with an
    ``AssertionError``. The staged edit is pinned to a real hash, so every
    other assertion passes.
    """

    def propose_edits(
        self,
        edits: Sequence[ProposedEdit],
        *,
        root: str | os.PathLike[str] | None = None,
        confirmed: bool = False,
    ) -> EditOutcome:
        base = Path(root) if root is not None else self._root
        return super().propose_edits(
            [self._repinned(base, edit) for edit in edits], root=root, confirmed=confirmed
        )

    def _repinned(self, base: Path, edit: ProposedEdit) -> ProposedEdit:
        if edit.pinned_hash is not None or not _within(edit.key, self._surface):
            return edit
        target = base / PurePosixPath(edit.key)
        if not target.is_file():
            return edit
        # The planted defect: absence is not checked, so it is never wrong.
        return replace(edit, pinned_hash=definition_hash(target.read_text(encoding="utf-8")))


class PrefixMatchingProject(EditableDagsterProject):
    """Admits a key by string prefix, so a sibling of the surface is written.

    Breaks the containment the write tier holds to: ``declarations`` admits
    ``declarations/orders.yml`` and not ``declarations_backup/orders.yml``.
    This one admits every key that starts with a declared prefix's
    characters, which is the shape of a containment check written as
    ``startswith``. An escape through ``..`` or an absolute key is still
    refused, as it is before any surface is consulted. Under
    ``EditableProjectContract`` it fails exactly
    ``test_a_key_that_only_shares_a_prefix_with_the_surface_is_refused``, with
    an ``AssertionError``. The surface it declares is unchanged and every key
    the contract stages is inside it, so every other assertion passes.
    """

    def propose_edits(
        self,
        edits: Sequence[ProposedEdit],
        *,
        root: str | os.PathLike[str] | None = None,
        confirmed: bool = False,
    ) -> EditOutcome:
        declared = self._surface
        # The planted defect: a key that only starts with a prefix is admitted.
        self._surface = declared + tuple(
            edit.key for edit in edits
            if any(edit.key.replace("\\", "/").startswith(p) for p in declared)
        )
        try:
            return super().propose_edits(edits, root=root, confirmed=confirmed)
        finally:
            self._surface = declared
