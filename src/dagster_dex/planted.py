# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""Two formats built wrong on purpose, to watch the contract refuse.

A contract observed only to pass has not been shown to be one. These ship
beside :mod:`dagster_dex.conformance` so that an implementer outside this
repository can watch it go red in their own environment, on the same install
that runs it against their format, before trusting its green.

Each is :class:`~dagster_dex.project.DagsterProject` with one defect a second
format is likely to ship, and each takes ``DagsterProject``'s constructor. Wire
one to the contract the way you wire your own format::

    from dagster_dex.conformance import FingerprintedProjectContract
    from dagster_dex.planted import SourceBlindProject

    class TestSourceBlind(FingerprintedProjectContract):
        def make_project(self, declarations, semantics, sources):
            return SourceBlindProject((), declaration_sources=declarations,
                                      semantic_sources=semantics,
                                      source_declarations=sources)

Run it, and the tests each class's docstring names fail while every other
assertion passes, as all of them do on ``DagsterProject``. A defect that stops
failing those tests, or one that starts failing others, means the contract
moved underneath you.

**They wrap ``DagsterProject`` rather than a toy format of their own.** A
shipped name is public surface, and a toy shipped to carry them would be a
second format to keep. So both are tier 2, and they reach the tier-1 and tier-2
contracts only: no planted defect for the write tier ships here.

This module does not import pytest, so it imports wherever the package does.
Like the contract's builders, the two class names are public surface.

Measures: src/dagster_dex/protocol.py, ProjectSource
Measures: src/dagster_dex/protocol.py, FingerprintedProject
"""

from __future__ import annotations

import yaml

from .model import Fingerprint, ProjectDeclarations
from .project import DagsterProject

__all__ = ["RaisingProject", "SourceBlindProject"]


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
