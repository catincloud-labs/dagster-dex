# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""The reduction, the tiers, and the cases the contract cannot state for us.

The conformance suite asserts what every format must do. This file asserts what
*this* format does, plus the negative cases - an equivalence test with no
negative case can pass while measuring nothing.
"""

from __future__ import annotations

import pytest

from dagster_dex import (
    DagsterProject,
    EditableProject,
    FingerprintedProject,
    Freshness,
    ProjectModel,
    tier_of,
)
from dagster_dex.conformance import (
    a_composite_key_declaration,
    a_join_declaration,
    a_single_key_declaration,
    a_source_declaration,
)
from dagster_dex.model import (
    DeclaredJoin,
    DeclaredKey,
    ExternalSource,
    Fingerprint,
)

MODELS = (
    ProjectModel(name="dim_date", layer="silver"),
    ProjectModel(name="fact_orders", depends_on=("dim_date",), layer="gold"),
    ProjectModel(name="mart_revenue", depends_on=("fact_orders",), layer="platinum"),
)


def a_project(**kwargs) -> DagsterProject:
    kwargs.setdefault("declaration_sources", {})
    kwargs.setdefault("semantic_sources", {})
    kwargs.setdefault("source_declarations", {})
    return DagsterProject(MODELS, name="demo_project", **kwargs)


class TestExternalSources:
    """The project's outer edge, which no amount of graph traversal finds."""

    def test_a_source_read_by_a_model_the_graph_does_not_build_is_kept_and_noted(self):
        """The table is still a real dependency on the warehouse. Dropping it
        would remove a live contract along with the stale attribution, and the
        note names the cause - a renamed reader, not a renamed subject."""

        declarations = a_project(
            source_declarations={"deleted_asset": a_source_declaration()}
        ).declarations()
        assert len(declarations.sources) == 1
        assert any("does not build" in n for n in declarations.notes)

    def test_columns_union_across_two_declarations_of_one_table(self):
        """A declaration listing fewer columns is narrower, not contradictory."""

        declarations = a_project(
            source_declarations={
                "reader_a": a_source_declaration(columns=("amount",)),
                "reader_b": a_source_declaration(columns=("amount", "placed_at")),
            }
        ).declarations()
        assert len(declarations.sources) == 1
        assert set(declarations.sources[0].columns) == {"amount", "placed_at"}

    def test_a_file_that_parses_but_declares_nothing_is_not_silent(self):
        """It reads as 'this model has no external reads', which is a claim,
        and it is indistinguishable from having supplied no file at all."""

        declarations = a_project(
            source_declarations={"reader": "sources: []\n"}
        ).declarations()
        assert declarations.sources == ()
        assert any("no source tables" in n for n in declarations.notes)

    def test_a_source_system_is_required_rather_than_defaulted(self):
        with pytest.raises(ValueError, match="source system"):
            ExternalSource(system="", table="t")

    def test_the_identifier_is_how_a_consumer_names_it(self):
        assert ExternalSource(system="sales", table="t").identifier == "sales.t"


# --- the tier boundary is structural, not a flag ----------------------------


class TestTiers:
    def test_reaches_tier_two(self):
        assert tier_of(a_project()) == 2

    def test_does_not_reach_tier_three(self):
        """The negative half. Without this, 'we decline the write path' is a
        claim in a docstring rather than a property of the object.

        Widened at dex-core 1.6.4: declining tier 3 is no longer sufficient
        to decline placement. exmergo/dex#263 put `PlacingProject` *beside* the
        tier rather than on it - deliberately, so that adding a method to tier 3
        would not demote every format already implementing it - which means the
        two are now independently reachable and have to be independently
        refused. `maintain reconcile` asks for the capability, not the tier.

        Checked here by shape, not by `isinstance` against upstream's protocol,
        and the distinction is load-bearing rather than stylistic: this module
        runs in the engine-free job, where importing `exmergo_dex_core` is the
        failure that job exists to produce. `PlacingProject` is
        `runtime_checkable`, so an isinstance against it is exactly "does the
        object have these two methods" - which is answerable from here without
        the import. `test_upstream_contract.py` asserts the same thing the
        other way, against the real protocol, where the engine is present.
        """

        project = a_project()
        assert not isinstance(project, EditableProject)
        assert not hasattr(project, "propose_edits")
        assert not hasattr(project, "edit_path")
        assert not hasattr(project, "editing_surface")

    def test_tier_two_implies_tier_one(self):
        assert isinstance(a_project(), FingerprintedProject)


# --- the declared channel ---------------------------------------------------


class TestDeclarations:
    def test_a_composite_grain_survives_at_full_width(self):
        declarations = a_project(
            declaration_sources={"f": a_composite_key_declaration()}
        ).declarations()
        key = next(k for k in declarations.declared_keys if k.model == "fact_orders")
        assert key.columns == ("date", "provider", "product_id", "order_type")

    def test_a_composite_declaration_beats_a_single_column_one_and_says_so(self):
        """Both statements in one file is a real authoring conflict. Picking
        one silently would hide it."""

        both = (
            "models:\n"
            "  - name: fact_orders\n"
            "    tests:\n"
            "      - unique_combination_of_columns:\n"
            "          combination_of_columns:\n"
            "            - date\n"
            "            - provider\n"
            "    columns:\n"
            "      - name: date\n"
            "        tests:\n"
            "          - unique\n"
        )
        declarations = a_project(declaration_sources={"f": both}).declarations()
        keys = [k for k in declarations.declared_keys if k.model == "fact_orders"]
        assert [k.columns for k in keys] == [("date", "provider")]
        assert any("composite wins" in n for n in declarations.notes)

    def test_a_declaration_for_an_unbuilt_model_is_kept_and_flagged(self):
        """Dropping it would hide the likely cause - a renamed asset - by
        making the declaration disappear alongside the model."""

        declarations = a_project(
            declaration_sources={"x": a_single_key_declaration(model="gone_away")}
        ).declarations()
        assert any(k.model == "gone_away" for k in declarations.declared_keys)
        assert any("does not build" in n for n in declarations.notes)

    def test_freshness_is_not_applicable_rather_than_fresh(self):
        """The reduction has no compiled artifact between it and the graph, so
        there is nothing that can go stale. Saying FRESH would be a claim
        nobody checked."""

        assert a_project().declarations().freshness is Freshness.NOT_APPLICABLE

    def test_an_unresolvable_relationship_target_is_dropped_with_a_note(self):
        broken = (
            "models:\n"
            "  - name: fact_orders\n"
            "    columns:\n"
            "      - name: date\n"
            "        tests:\n"
            "          - relationships:\n"
            "              to: \"{{ some_macro() }}\"\n"
            "              field: date\n"
        )
        declarations = a_project(declaration_sources={"b": broken}).declarations()
        assert declarations.declared_joins == ()
        assert any("resolvable" in n for n in declarations.notes)

    def test_a_join_is_read_end_to_end(self):
        declarations = a_project(declaration_sources={"j": a_join_declaration()}).declarations()
        assert len(declarations.declared_joins) == 1


class TestDeclarationsIsMemoized:
    """The memo is a performance property, so it is asserted by counting parses.

    Identity alone would pass against a class that re-parsed and happened to
    return a cached object, and equality alone would pass with no memo at all.
    """

    def test_the_declaration_files_are_parsed_once_per_instance(self, monkeypatch):
        import dagster_dex.project as project_module

        calls = []
        real = project_module.parse_declarations

        def counting(sources):
            calls.append(sources)
            return real(sources)

        monkeypatch.setattr(project_module, "parse_declarations", counting)

        project = a_project(declaration_sources={"f": a_single_key_declaration()})
        for _ in range(4):
            project.declarations()

        assert len(calls) == 1, (
            f"expected one parse for four reads, got {len(calls)}. DexProject's "
            "definitions(), transform_layer(), semantic_layer() and notes() each "
            "call declarations(), so a lost memo costs a full re-parse per call"
        )

    def test_every_read_returns_the_same_value(self):
        project = a_project(declaration_sources={"f": a_single_key_declaration()})

        first = project.declarations()
        second = project.declarations()

        assert first is second
        assert first.declared_keys == second.declared_keys

    def test_two_instances_do_not_share_a_memo(self):
        """The memo is per instance, which is what makes it safe to hold.

        A class-level cache keyed by nothing would serve one project's
        declarations to another, and both fixtures here declare the same model.
        """

        one = a_project(declaration_sources={"f": a_single_key_declaration()})
        two = a_project(declaration_sources={"f": a_composite_key_declaration()})

        assert one.declarations() is not two.declarations()
        assert one.declarations().declared_keys != two.declarations().declared_keys

    def test_the_memo_does_not_change_what_is_reported(self):
        """Reading twice must not differ from reading once."""

        sources = {"f": a_composite_key_declaration(), "j": a_join_declaration()}

        fresh = a_project(declaration_sources=sources).declarations()
        reused = a_project(declaration_sources=sources)
        reused.declarations()

        assert reused.declarations() == fresh


# --- the fingerprint --------------------------------------------------------


class TestFingerprint:
    def test_layers_come_from_the_models(self):
        assert set(a_project().fingerprint().layers) == {"silver", "gold", "platinum"}

    def test_rewiring_a_dependency_changes_the_layer_hash(self):
        """A change that moves no model between layers still changes what the
        layer computes. A fingerprint that missed it would call a real change
        no change."""

        before = a_project().fingerprint()
        rewired = DagsterProject(
            (
                ProjectModel(name="dim_date", layer="silver"),
                ProjectModel(name="fact_orders", depends_on=(), layer="gold"),
                ProjectModel(
                    name="mart_revenue", depends_on=("fact_orders",), layer="platinum"
                ),
            ),
            name="demo_project",
        ).fingerprint()

        assert before.layers["gold"] != rewired.layers["gold"]
        assert before.layers["silver"] == rewired.layers["silver"]
        assert before.changed_layers(rewired) == ("gold",)

    def test_a_model_with_no_layer_is_grouped_not_dropped(self):
        project = DagsterProject((ProjectModel(name="orphan"),), name="demo_project")
        assert "unassigned" in project.fingerprint().layers
        assert project.fingerprint().models == ("orphan",)

    def test_a_removed_layer_counts_as_changed(self):
        """Absent on one side is a difference. Treating it as unchanged is how
        a deleted layer vanishes from a drift report."""

        left = Fingerprint(layers={"gold": "a", "silver": "b"})
        right = Fingerprint(layers={"gold": "a"})
        assert left.changed_layers(right) == ("silver",)

    def test_a_project_with_no_sources_carries_no_sources_entry(self):
        """The compatibility half of adding sources to the fingerprint: a
        project that never declared any must hash exactly as it did before the
        field existed, or a new capability reads as drift on every project that
        ignores it."""

        assert "sources" not in a_project().fingerprint().layers

    def test_declaring_a_source_leaves_every_model_layer_untouched(self):
        """Guards the entry from being folded into a model layer, which would
        make a source change look like a transform change."""

        before = a_project().fingerprint()
        after = a_project(
            source_declarations={"dim_date": a_source_declaration()}
        ).fingerprint()
        assert after.changed_layers(before) == ("sources",)


# --- the model refuses what it cannot represent -----------------------------


class _Key:
    """The only part of an asset key this reduction reads."""

    def __init__(self, *path: str) -> None:
        self.path = path

    def __hash__(self) -> int:
        return hash(self.path)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _Key) and self.path == other.path


class _Definition:
    """A stand-in for the orchestrator's public AssetsDefinition surface.

    Duck-typed on purpose: reducing through `keys` / `asset_deps` /
    `metadata_by_key` rather than an internal graph type is what makes this
    testable without installing an orchestrator at all.
    """

    def __init__(self, keys, deps=None, metadata=None) -> None:
        self.keys = keys
        self.asset_deps = deps or {}
        self.metadata_by_key = metadata or {}


class TestFromAssetGraph:
    def test_it_reduces_keys_deps_and_layers(self):
        parent, child = _Key("dim_date"), _Key("fact_orders")
        project = DagsterProject.from_asset_graph(
            [
                _Definition([parent], metadata={parent: {"layer": "Silver"}}),
                _Definition(
                    [child], deps={child: {parent}}, metadata={child: {"layer": "Gold"}}
                ),
            ]
        )
        models = {m.name: m for m in project.declarations().models}
        assert set(models) == {"dim_date", "fact_orders"}
        assert models["fact_orders"].depends_on == ("dim_date",)
        assert models["dim_date"].layer == "silver"

    def test_a_duplicate_key_is_refused(self):
        """The guard has to run against the raw definitions: a built graph
        collapses two definitions sharing a key into one node silently, so a
        check made after that point can never fire."""

        key = _Key("dim_date")
        with pytest.raises(ValueError, match="same model name"):
            DagsterProject.from_asset_graph([_Definition([key]), _Definition([key])])

    def test_a_case_only_collision_is_refused(self):
        """Two names differing only in case collide the moment anything writes
        them to a case-insensitive filesystem, dropping one without a word."""

        with pytest.raises(ValueError, match="same model name"):
            DagsterProject.from_asset_graph(
                [_Definition([_Key("dim_date")]), _Definition([_Key("Dim_Date")])]
            )

    def test_an_asset_with_no_layer_metadata_is_kept(self):
        """Layer metadata is the orchestrator's convention, not this model's
        requirement; a model without it still exists."""

        key = _Key("stray")
        project = DagsterProject.from_asset_graph([_Definition([key])])
        assert project.declarations().models[0].layer is None
        assert "unassigned" in project.fingerprint().layers

    def test_an_empty_graph_reduces_to_an_empty_project(self):
        assert DagsterProject.from_asset_graph([]).declarations().is_empty


class TestModelInvariants:
    def test_a_key_with_no_columns_is_refused(self):
        with pytest.raises(ValueError):
            DeclaredKey(model="m", columns=())

    def test_a_lopsided_join_is_refused(self):
        """Two columns on one side and one on the other is not a join anyone
        can act on, and storing it would push the error to whoever reads it."""

        with pytest.raises(ValueError, match="one side"):
            DeclaredJoin(
                from_model="a",
                from_columns=("x", "y"),
                to_model="b",
                to_columns=("x",),
            )

    def test_a_single_column_key_is_not_composite(self):
        assert not DeclaredKey(model="m", columns=("id",)).is_composite
