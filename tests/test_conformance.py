# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""DagsterProject against the shipped contract.

The whole of the wiring is `make_project`. That is the point of shipping the
suite: a second format writes these same few lines and inherits every
assertion, rather than hand-rolling parity tests that drift from the contract
they are supposed to be checking.
"""

from __future__ import annotations

from dagster_dex import DagsterProject, ProjectModel
from dagster_dex.conformance import FingerprintedProjectContract

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
