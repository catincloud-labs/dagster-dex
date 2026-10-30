# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""A second project format, written against the shipped contract.

`docs/design/implementing-a-format.md` walks through this file. It exists so
the guide's example runs: it sits in `tests/`, so the engine-free control step
collects it on every interpreter CI claims, and a change to the contract that
breaks an outside implementer breaks this file first.

**The toy is not `DagsterProject` under another name.** Its models come from a
catalog, a plain mapping of model name to upstream names held in memory, and it
has one fingerprint layer where `DagsterProject` has one per medallion layer.
What it shares is the declaration vocabulary: the contract's builders hand
`make_project` schema-test YAML, so any format passing the contract reads that
text, and this one reads it with the package's own parsers rather than
re-deriving them. A format whose declarations live elsewhere writes its own
reader and is held to the same assertions.

**It declines the write tier, and says so negatively.** It has no place an edit
could land, so it has no `propose_edits`, and the last test asserts the decline
with `not isinstance` rather than trusting the absence.

**The two calibrations at the end are the contract going red.** A contract
observed only to pass has not been shown to be one, so each plants a defect a
second format is likely to ship and asserts that the named contract test fails
on it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import pytest
import yaml

from dagster_dex.conformance import FingerprintedProjectContract
from dagster_dex.declarations import (
    parse_declarations,
    parse_semantics,
    parse_source_declarations,
)
from dagster_dex.model import (
    Fingerprint,
    Freshness,
    ProjectDeclarations,
    ProjectModel,
    definition_hash,
)
from dagster_dex.protocol import EditableProject, FingerprintedProject, tier_of


class CatalogProject:
    """A tier-2 format whose models are a catalog of names and upstreams."""

    format = "catalog"

    def __init__(
        self,
        catalog: Mapping[str, Sequence[str]],
        *,
        name: str,
        declaration_sources: Mapping[str, str] | None = None,
        semantic_sources: Mapping[str, str] | None = None,
        source_declarations: Mapping[str, str] | None = None,
    ) -> None:
        # Sorted on the way in, so two catalogs listing the same models in a
        # different order are the same project and fingerprint alike.
        self._models = tuple(
            ProjectModel(name=model, depends_on=tuple(sorted(upstream)))
            for model, upstream in sorted(catalog.items())
        )
        self._name = name
        self._declaration_sources = dict(declaration_sources or {})
        self._semantic_sources = dict(semantic_sources or {})
        self._source_declarations = dict(source_declarations or {})

    def declarations(self) -> ProjectDeclarations:
        """Never raises: the parsers turn bad input into notes, and so does this."""

        keys, joins, notes = parse_declarations(self._declaration_sources)
        semantic_models, metrics, semantic_notes = parse_semantics(self._semantic_sources)
        sources, source_notes = parse_source_declarations(self._source_declarations)

        # The format's own disclosure. A key on a model the catalog does not
        # list is kept, because it is still the author's statement, and said.
        built = {model.name for model in self._models}
        unlisted = sorted({key.model for key in keys if key.model not in built})
        if unlisted:
            notes.append(
                f"keys are declared on {', '.join(unlisted)}, which the catalog "
                "does not list"
            )

        return ProjectDeclarations(
            format=self.format,
            name=self._name,
            models=self._models,
            sources=tuple(sources),
            declared_keys=tuple(keys),
            declared_joins=tuple(joins),
            semantic_models=tuple(semantic_models),
            metrics=tuple(metrics),
            # A catalog compiles to nothing, so there is nothing to be stale.
            freshness=Freshness.NOT_APPLICABLE,
            notes=(*notes, *semantic_notes, *source_notes),
        )

    def fingerprint(self) -> Fingerprint:
        """One layer for the catalog, and one for sources when there are any."""

        layers = {
            "catalog": definition_hash(
                "\n".join(f"{m.name}({','.join(m.depends_on)})" for m in self._models)
            )
        }
        sources, _notes = parse_source_declarations(self._source_declarations)
        if sources:
            layers["sources"] = definition_hash(
                "\n".join(
                    f"{s.system}.{s.schema_name or ''}.{s.table}"
                    for s in sorted(sources, key=lambda s: (s.system, s.table))
                )
            )
        return Fingerprint(layers=layers, models=tuple(m.name for m in self._models))


CATALOG = {
    "dim_date": (),
    "dim_product": (),
    "fact_orders": ("dim_date", "dim_product"),
    "fact_sessions": ("dim_date",),
    "mart_revenue": ("fact_orders",),
}


class TestCatalogProjectConformance(FingerprintedProjectContract):
    """The whole of the wiring. Every tier-1 and tier-2 assertion is inherited."""

    def make_project(self, declarations, semantics, sources):
        return CatalogProject(
            CATALOG,
            name="toy",
            declaration_sources=declarations,
            semantic_sources=semantics,
            source_declarations=sources,
        )


def test_the_catalog_format_declines_the_write_tier():
    """Asserted negatively, so reaching tier 3 by accident is caught."""

    project = CatalogProject(CATALOG, name="toy")
    assert isinstance(project, FingerprintedProject)
    assert tier_of(project) == 2
    assert not isinstance(project, EditableProject)


# --- calibration: the contract going red on a planted defect -----------------


class _SourceBlindCatalog(CatalogProject):
    """Fingerprints the catalog alone, so a new warehouse dependency is no drift."""

    def fingerprint(self) -> Fingerprint:
        full = super().fingerprint()
        return Fingerprint(
            layers={"catalog": full.layers["catalog"]}, models=full.models
        )


class _RaisingCatalog(CatalogProject):
    """Parses its declarations with no guard, so bad YAML is an exception."""

    def declarations(self) -> ProjectDeclarations:
        for text in self._declaration_sources.values():
            yaml.safe_load(text)
        return super().declarations()


def test_the_contract_reports_a_fingerprint_blind_to_sources():
    class Blind(TestCatalogProjectConformance):
        def make_project(self, declarations, semantics, sources):
            return _SourceBlindCatalog(
                CATALOG,
                name="toy",
                declaration_sources=declarations,
                semantic_sources=semantics,
                source_declarations=sources,
            )

    # The clean arm first: the same assertion passes on the honest format.
    TestCatalogProjectConformance().test_gaining_an_external_source_is_visible_as_drift()
    with pytest.raises(AssertionError):
        Blind().test_gaining_an_external_source_is_visible_as_drift()


def test_the_contract_reports_a_format_that_raises_on_malformed_input():
    class Raising(TestCatalogProjectConformance):
        def make_project(self, declarations, semantics, sources):
            return _RaisingCatalog(
                CATALOG,
                name="toy",
                declaration_sources=declarations,
                semantic_sources=semantics,
                source_declarations=sources,
            )

    TestCatalogProjectConformance().test_malformed_input_never_raises()
    with pytest.raises(yaml.YAMLError):
        Raising().test_malformed_input_never_raises()
