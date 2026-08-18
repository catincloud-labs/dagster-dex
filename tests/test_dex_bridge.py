# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""The boundary with dex-core, exercised against the real package.

Skipped wholesale when dex-core is absent, which is the property worth having:
everything else in this package must pass without it. If these were not
skippable, the "engine-free core" claim would be untestable.
"""

from __future__ import annotations

import pytest

from dagster_dex import DagsterProject, ProjectModel
from dagster_dex.conformance import (
    a_composite_key_declaration,
    a_join_declaration,
    a_semantic_definition,
    a_semantic_definition_with_a_duplicate_field,
    a_semantic_definition_without_expr,
    a_single_key_declaration,
    a_source_declaration,
    malformed_yaml,
)

pytest.importorskip("exmergo_dex_core", reason="the [dex] extra is not installed")

from dagster_dex.dex import (  # noqa: E402
    DexProject,
    ProjectContext,
    project_from_context,
    semantic_layer_notes,
    to_project_definitions,
    to_semantic_layer,
    to_transform_layer,
    transform_layer_notes,
)

MODELS = (
    ProjectModel(name="dim_date", layer="silver"),
    ProjectModel(name="fact_orders", depends_on=("dim_date",), layer="gold"),
    ProjectModel(name="fact_sessions", depends_on=("dim_date",), layer="gold"),
)


def a_project(**sources) -> DagsterProject:
    return DagsterProject(
        MODELS,
        name="demo_project",
        declaration_sources=sources.get("declarations", {}),
        semantic_sources=sources.get("semantics", {}),
        source_declarations=sources.get("source_declarations", {}),
    )


class TestTheMappingIsLossless:
    def test_a_single_column_key_becomes_a_declared_key(self):
        defs = to_project_definitions(
            a_project(declarations={"d": a_single_key_declaration()}).declarations()
        )
        assert [(k.model, k.column) for k in defs.declared_keys] == [("dim_date", "date")]
        assert defs.declared_composite_keys == []

    def test_a_composite_key_becomes_a_composite_key_at_full_width(self):
        """The split this asserts is the interesting half: one tuple on our
        side becomes one of two different types on theirs, chosen by width."""

        defs = to_project_definitions(
            a_project(declarations={"f": a_composite_key_declaration()}).declarations()
        )
        assert defs.declared_keys == []
        assert len(defs.declared_composite_keys) == 1
        assert defs.declared_composite_keys[0].columns == [
            "date",
            "provider",
            "product_id",
            "order_type",
        ]

    def test_a_join_becomes_a_foreign_key(self):
        defs = to_project_definitions(
            a_project(declarations={"j": a_join_declaration()}).declarations()
        )
        assert len(defs.foreign_keys) == 1
        fk = defs.foreign_keys[0]
        assert (fk.model, fk.column, fk.to_model, fk.to_column) == (
            "fact_sessions",
            "date",
            "dim_date",
            "date",
        )

    def test_a_foreign_key_keeps_its_two_columns_apart(self):
        """The case above is `date` on both ends, so it cannot distinguish
        `to_column` from a mirror of `column`. This one can, and it is the arm
        that matters: `fk.to_column` is what dex resolves against the target
        relation, so a mirrored value names a column the target may not have.

        Asserted here as well as in `conformance.py` on purpose. The contract
        proves the neutral model keeps the two apart; this proves they survive
        translation into dex-core's own `DeclaredForeignKey`, which is a
        separate mapping and could drop one side on its own.
        """

        defs = to_project_definitions(
            a_project(
                declarations={
                    "j": a_join_declaration(
                        from_model="fact_pageviews",
                        from_column="product_url",
                        to_model="dim_product",
                        to_column="canonical_url",
                    )
                }
            ).declarations()
        )
        assert len(defs.foreign_keys) == 1
        fk = defs.foreign_keys[0]
        assert (fk.model, fk.column, fk.to_model, fk.to_column) == (
            "fact_pageviews",
            "product_url",
            "dim_product",
            "canonical_url",
        )
        assert fk.column != fk.to_column

    def test_the_result_is_dex_cores_own_type(self):
        from exmergo_dex_core.dbt_project import ProjectDefinitions

        defs = to_project_definitions(a_project().declarations())
        assert isinstance(defs, ProjectDefinitions)


class TestWhatDoesNotSurvive:
    def test_not_applicable_freshness_arrives_as_false_and_is_noted(self):
        """`manifest_stale=False` on the far side reads as 'current'. It is
        not: there is no manifest at all. The note is the only place that
        distinction survives the crossing."""

        defs = to_project_definitions(a_project().declarations())
        assert defs.manifest_stale is False
        assert any("not applicable" in n for n in defs.notes)

    def test_an_empty_project_is_not_present(self):
        defs = to_project_definitions(
            DagsterProject((), name="demo_project").declarations()
        )
        assert defs.present is False

    def test_a_project_with_models_is_present(self):
        """Guards the assertion above from passing for the wrong reason."""

        assert to_project_definitions(a_project().declarations()).present is True


class TestTheTransformLayerBridge:
    """Tier 2, the Maintain channel."""

    def test_the_result_is_dex_cores_own_type(self):
        from exmergo_dex_core.maintain.snapshot import TransformLayer

        layer = to_transform_layer(a_project().declarations())
        assert isinstance(layer, TransformLayer)

    def test_it_is_accepted_into_dex_cores_own_snapshot(self):
        """The assertion that is more than a type check: the engine's baseline
        document validates what we produced. A shape that satisfies our tests
        and not their model would fail here and nowhere else."""

        from exmergo_dex_core.maintain.snapshot import Snapshot

        snapshot = Snapshot(
            created_at="2026-08-02T00:00:00Z",
            transform_layer=to_transform_layer(
                a_project(source_declarations={"dim_date": a_source_declaration()}).declarations()
            ),
        )
        assert snapshot.transform_layer is not None
        assert snapshot.transform_layer.sources[0].table == (
            "orders_export_v1"
        )

    def test_a_source_crosses_with_its_system_schema_and_columns(self):
        layer = to_transform_layer(
            a_project(source_declarations={"dim_date": a_source_declaration()}).declarations()
        )
        assert len(layer.sources) == 1
        source = layer.sources[0]
        assert source.source_name == "sales"
        assert source.schema_name == "sales"
        assert source.columns == ["placed_at", "amount"]

    def test_model_sources_names_the_reader_and_the_qualified_table(self):
        """This mapping is how a warehouse finding is traced to the models it
        lands on. Getting it empty is what gives a warehouse finding a permanently
        empty blast radius, and an empty blast radius looks exactly like an isolated
        table."""

        layer = to_transform_layer(
            a_project(
                source_declarations={"fact_orders": a_source_declaration()}
            ).declarations()
        )
        assert layer.model_sources == {
            "fact_orders": ["sales.orders_export_v1"]
        }

    def test_model_refs_names_only_models_this_project_builds(self):
        layer = to_transform_layer(a_project().declarations())
        assert layer.model_refs == {
            "fact_sessions": ["dim_date"],
            "fact_orders": ["dim_date"],
        }

    def test_files_is_empty_because_there_are_none(self):
        assert to_transform_layer(a_project().declarations()).files == {}


class TestWhatTierTwoCannotCarry:
    """What the tier-2 mapping still loses, asserted rather than described.

    Gap D closed upstream in 1.6.0 (`exmergo/dex#193`): `path` became optional
    and both layers gained `notes`. The two assertions that encoded its absence
    are now inverted rather than deleted, because the thing worth guarding did
    not go away - it moved from "we disclose the sentinel" to "we do not
    reintroduce one".
    """

    def test_a_source_path_is_none_rather_than_invented(self):
        """`SourceTable.path` is `str | None` since 1.6.0 and this format has no
        path to give. `None` reads as 'no provenance'; a synthesized one would be
        shown to an analyst as the evidence for a high-severity finding."""

        layer = to_transform_layer(
            a_project(source_declarations={"dim_date": a_source_declaration()}).declarations()
        )
        assert layer.sources[0].path is None

    def test_no_source_carries_the_retired_empty_string_sentinel(self):
        """The regression arm. `""` validated fine while the field was required
        and would validate fine now, so nothing but this fails if someone
        restores it - and `dangling_source` would go back to showing a blank
        `declared_in` instead of omitting the key."""

        layer = to_transform_layer(
            a_project(source_declarations={"dim_date": a_source_declaration()}).declarations()
        )
        assert all(source.path != "" for source in layer.sources)

    def test_the_disclosure_now_has_a_home_on_the_engines_own_type(self):
        """The inverse of what this asserted before 1.6.0. Binding the layer's
        `notes` to the function rather than re-asserting the text is the point:
        the two cannot drift apart, and a note added to one arrives in both."""

        declarations = a_project().declarations()
        layer = to_transform_layer(declarations)
        assert layer.notes == list(transform_layer_notes(declarations))
        assert layer.notes, "a project with models always discloses absent file hashes"

    def test_an_empty_projects_layer_says_nothing(self):
        """The quiet arm, paired with the loud one above. A `notes` field that is
        populated unconditionally carries no information, and equality against
        the function would hide that by moving in lockstep."""

        layer = to_transform_layer(DagsterProject((), name="c").declarations())
        assert layer.notes == []

    def test_absent_file_hashes_are_stated_not_left_to_look_like_no_drift(self):
        notes = transform_layer_notes(a_project().declarations())
        assert any("file hashes are absent" in n for n in notes)

    def test_an_empty_project_loses_nothing_and_says_nothing(self):
        """Guards the assertions above from passing for the wrong reason: if
        the notes were unconditional they would carry no information."""

        assert transform_layer_notes(DagsterProject((), name="c").declarations()) == ()

    def test_a_dependency_on_neither_a_model_nor_a_source_is_reported(self):
        """It is dropped from `model_refs`, which is correct and silent. The
        note is the part that keeps it from being invisible."""

        project = DagsterProject(
            (ProjectModel(name="fact_x", depends_on=("vanished",)),), name="demo_project"
        )
        assert "vanished" in " ".join(transform_layer_notes(project.declarations()))


class TestTheSemanticLayerMapping:
    """`to_semantic_layer`, the second half of tier 2."""

    def test_a_well_formed_declaration_maps_every_channel(self):
        layer = to_semantic_layer(
            a_project(semantics={"s": a_semantic_definition()}).declarations()
        )
        model = layer.semantic_models[0]

        assert model.name == "mart_revenue"
        assert model.model_ref == "mart_revenue"
        assert model.dimensions == {"date": "date", "provider": "provider"}
        assert model.measures == {"daily_revenue_net": "daily_revenue_net"}
        assert model.content_sha256, "the engine keys definition drift on this"

    def test_only_the_categorical_dimension_reaches_the_categorical_channel(self):
        """`categorical_dimensions` requires `str` values, so an unresolved field is
        absent from it rather than present as `None` - being absent is what stops it
        reading as a mapping to nothing."""

        layer = to_semantic_layer(
            a_project(semantics={"s": a_semantic_definition()}).declarations()
        )

        assert layer.semantic_models[0].categorical_dimensions == {"provider": "provider"}

    def test_a_metric_carries_the_measure_it_is_computed_from(self):
        layer = to_semantic_layer(
            a_project(semantics={"s": a_semantic_definition()}).declarations()
        )

        assert [m.name for m in layer.metrics] == ["daily_revenue"]
        assert layer.metrics[0].input_measures == ["daily_revenue_net"]

    def test_an_unresolvable_field_arrives_as_none_and_is_disclosed(self):
        """The two halves have to travel together.

        `None` in the layer is what stops dex-core resolving a fabricated column;
        the note is what stops a human reading the resulting silence as agreement.
        Neither alone is honest, and since 1.6.0 `SemanticLayer` has room for
        both - `notes` arrived with `exmergo/dex#193`, so the two halves now
        travel in one object instead of needing a caller to pair them.
        """

        declarations = a_project(
            semantics={"s": a_semantic_definition_without_expr()}
        ).declarations()
        layer = to_semantic_layer(declarations)
        notes = semantic_layer_notes(declarations)

        assert layer.semantic_models[0].measures == {"revenue_with_fee": None}
        assert any("no warehouse column" in note for note in notes)
        assert layer.notes == list(notes), "the pairing is the layer's job now, not the caller's"

    def test_a_project_declaring_no_semantics_produces_a_silent_layer(self):
        """The quiet arm for the semantic half.

        Added after a mutation run: deleting `notes=` from `to_semantic_layer`
        left all 91 tests green, because every semantic assertion read the
        standalone function rather than the layer. The loud arm above and this
        one together are what make the field load-bearing.
        """

        declarations = DagsterProject((), name="c").declarations()
        layer = to_semantic_layer(declarations)

        assert layer.notes == []
        assert semantic_layer_notes(declarations) == ()

    def test_a_categorical_dimension_with_no_column_is_dropped_not_passed_as_none(self):
        """The one field whose unresolved state would reach a **required** value.

        `dimensions` is `dict[str, str | None]`, so an unresolved field rides along
        as `None`. `categorical_dimensions` is `dict[str, str]`, so the same field
        cannot: passing it would be rejected outright by the engine's own model, and
        `semantic_layer()` would raise on a declaration that is perfectly legal.

        This is the assertion the first version of this suite lacked. It read
        `categorical_dimensions == {}` against a fixture with **no categorical
        dimension in it**, so it passed because the set was empty rather than because
        anything was dropped - and deleting the `f.column is not None` guard left all
        84 tests green. `region` exists in the fixture specifically to close that.
        """

        declarations = a_project(
            semantics={"s": a_semantic_definition_without_expr()}
        ).declarations()

        layer = to_semantic_layer(declarations)
        model = layer.semantic_models[0]

        # Present in the nullable channel...
        assert model.dimensions["region"] is None
        # ...and absent from the one that requires a real column.
        assert "region" not in model.categorical_dimensions
        assert model.categorical_dimensions == {}

    def test_a_redeclared_field_reaches_the_engine_once_and_deterministically(self):
        """The dict conversion assumes unique names; the parser now guarantees it.

        Without the parser-side guarantee this mapping keeps whichever duplicate came
        last, which is a coin flip dressed as a rule.

        **The disclosure is on `declarations.notes`, not `semantic_layer_notes()`,
        and the split is deliberate.** A duplicate is dropped while *reading the
        declaration*, so it belongs to the declaration channel - which reaches
        `ProjectDefinitions.notes`, a field the engine actually has.
        `semantic_layer_notes()` exists only for losses that happen in the *mapping*,
        because `SemanticLayer` has nowhere to put them. Reporting this in both would
        double-report one drop.
        """

        declarations = a_project(
            semantics={"s": a_semantic_definition_with_a_duplicate_field()}
        ).declarations()

        layer = to_semantic_layer(declarations)

        assert layer.semantic_models[0].measures == {"total": "total_a"}
        assert any("redeclare" in note for note in declarations.notes)
        assert not any("redeclare" in note for note in semantic_layer_notes(declarations))

    def test_a_project_with_no_semantics_produces_an_empty_layer_and_no_notes(self):
        declarations = a_project().declarations()

        layer = to_semantic_layer(declarations)

        assert layer.semantic_models == [] and layer.metrics == []
        assert semantic_layer_notes(declarations) == ()

    def test_the_layer_validates_inside_the_engines_own_snapshot(self):
        """Feeding ours into dex-core's `Snapshot` beats any assertion about shape:
        it is the type the engine will actually hold."""

        from exmergo_dex_core.maintain.snapshot import Snapshot

        declarations = a_project(semantics={"s": a_semantic_definition()}).declarations()

        snapshot = Snapshot(
            created_at="2026-08-04T00:00:00+00:00",
            transform_layer=to_transform_layer(declarations),
            semantic_layer=to_semantic_layer(declarations),
        )

        assert snapshot.semantic_layer.semantic_models[0].measures["daily_revenue_net"]


class TestNoPrivateImports:
    def test_the_boundary_module_imports_nothing_private(self):
        """`exmergo/dex#144`'s acceptance criterion, asserted rather than asserted-to.

        The earlier prototype called `dbt_project._declared_from_yaml` and
        `_semantic_from_yaml`, which passes tests and fails the criterion.
        """

        import ast
        import pathlib

        import dagster_dex.dex as bridge

        tree = ast.parse(pathlib.Path(bridge.__file__).read_text(encoding="utf-8"))
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
                "exmergo_dex_core"
            ):
                imported.extend(alias.name for alias in node.names)
                assert not any(
                    part.startswith("_") for part in (node.module or "").split(".")
                ), f"private module: {node.module}"

        assert imported, "expected the bridge to import from exmergo_dex_core"
        assert not [name for name in imported if name.startswith("_")]


class TestProjectContext:
    def test_it_is_constructible_with_nothing(self):
        """A format with no repository must be buildable, which is the entire
        argument for the contract not being `resolve(name)(repo_root)`."""

        assert ProjectContext().repo_root is None

    def test_options_default_is_not_shared_between_instances(self):
        first, second = ProjectContext(), ProjectContext()
        assert first.options == {} and second.options == {}
        assert first.options is not second.options


class TestWhatAnUnmappedMeasureCosts:
    """What dex-core does with a measure that names no physical column.

    This is a test about **dex-core's** behaviour, not ours, and it exists because a
    decision rests on it: `SemanticModelDef` keys each measure to a physical column
    and allows `None`, so a format could satisfy tier 2 by mapping every measure to
    `None`. The question is what that costs, and the answer turned out to decide how
    `semantic_layer()` should be written.

    Measuring it rather than reading `drift.py` is the point. The behaviour is one
    `if column is None` away from changing, and if upstream ever changes it the
    reasoning built on top of this rots with nothing saying so.
    """

    MODEL = "mart_revenue"
    MEASURE = "daily_revenue_net"

    def _findings(self, measures):
        """`semantic_free_drift` against a warehouse that DROPPED the measure's column."""

        from exmergo_dex_core.cache import ColumnProfile, Dataset
        from exmergo_dex_core.maintain.drift import semantic_free_drift
        from exmergo_dex_core.maintain.snapshot import (
            SemanticLayer,
            SemanticModelDef,
            Snapshot,
            TransformLayer,
        )

        # `date` survives; the measure's column does not. A real schema change.
        datasets = [
            Dataset(
                identifier=self.MODEL,
                columns=[ColumnProfile(name="date", data_type="DATE")],
            )
        ]
        semantic = SemanticLayer(
            semantic_models=[
                SemanticModelDef(
                    name=self.MODEL,
                    path="",
                    content_sha256="deadbeef",
                    model_ref=self.MODEL,
                    measures=measures,
                )
            ]
        )
        found = semantic_free_drift(
            TransformLayer(models=[self.MODEL]),
            semantic,
            datasets,
            Snapshot(created_at="2026-08-04T00:00:00+00:00"),
        )
        return [f for f in found if f.code == "dangling_reference"]

    def test_a_measure_mapped_to_its_column_catches_the_column_going_away(self):
        """The control arm. Without it, the assertion below could pass because the
        harness never detects anything, which is a different bug wearing the same
        green."""

        findings = self._findings({self.MEASURE: self.MEASURE})

        assert len(findings) == 1
        assert findings[0].severity == "high"
        assert findings[0].column == self.MEASURE

    def test_a_measure_mapped_to_none_is_skipped_silently(self):
        """The cost, and it is paid per measure.

        Not a fabrication risk: upstream annotates these values `str | None` and
        treats `None` as "cannot be checked here", so this is sanctioned. It is a
        *coverage* loss, and an invisible one, because `SemanticLayer` has no
        `notes` field in which a format could say how much of it went unchecked.
        """

        assert self._findings({self.MEASURE: None}) == []

    def test_our_own_pipeline_now_produces_the_mapped_arm(self):
        """The payoff, and the reason O12 was worth fixing rather than noting.

        The two assertions above are hand-built layers proving what dex-core does
        with a column and without one. This one runs the same check through **our**
        parser and boundary end to end, so it fails if `expr` stops being carried at
        any point between the YAML and `SemanticModelDef`. Before the `expr` fix it
        returned no findings, because every measure arrived as `None`.
        """

        layer = to_semantic_layer(
            a_project(semantics={"s": a_semantic_definition(self.MODEL)}).declarations()
        )
        measures = layer.semantic_models[0].measures

        assert measures == {self.MEASURE: self.MEASURE}, (
            "our pipeline must carry the declared column all the way to the engine's "
            f"model, got {measures}"
        )
        assert len(self._findings(measures)) == 1


# --- the factory: how dex-core actually constructs this format ---------------


class _FactoryKey:
    def __init__(self, name: str) -> None:
        self.path = (name,)


class _FactoryDefinition:
    """The three public attributes `from_asset_graph` reads. No orchestrator."""

    def __init__(self, keys, deps=None, metadata=None) -> None:
        self.keys = keys
        self.asset_deps = deps or {}
        self.metadata_by_key = metadata or {}


#: Module-level so the factory can reach it by dotted path, exactly as it would
#: reach a real code location. The test module is importable under pytest's
#: rootdir insertion, so `f"{__name__}:FACTORY_ASSETS"` is a genuine round trip
#: through `importlib` rather than a stub handed in.
FACTORY_ASSETS = [_FactoryDefinition([_FactoryKey("dim_date")])]


def _context(**options):
    return ProjectContext(options=options)


class TestTheFactory:
    """`project_from_context`, which is what `.dex/config.yml` resolves to."""

    def test_it_builds_a_project_dex_core_will_accept(self):
        """The loud arm. `DexProject` is not decoration here: dex refuses a bare
        `DagsterProject` as "missing name, definitions", because this package
        says `format`/`declarations()` where the seam says `name`/`definitions()`.
        """

        project = project_from_context(_context(assets=f"{__name__}:FACTORY_ASSETS", name="demo_project"))

        assert isinstance(project, DexProject)
        # `name` on the seam is the FORMAT identifier, not the instance name.
        # That ambiguity is exactly why this package calls it `format` internally
        # and why `DexProject` renames it at the boundary - so `name="demo_project"`
        # above names the graph and deliberately does NOT surface here.
        assert project.name == "dagster"

        # ...and `definitions()` returns dex-core's own type, not ours. It has no
        # `models`: that vocabulary is this package's. The model list crosses on
        # the tier-2 channel instead, which is the split the seam is built around.
        from exmergo_dex_core.dbt_project import ProjectDefinitions

        assert isinstance(project.definitions(), ProjectDefinitions)
        assert project.definitions().present is True
        assert project.transform_layer().models == ["dim_date"]

    def test_the_registered_entry_point_names_the_factory_not_the_class(self):
        """The regression guard for the entry-point defect.

        The entry point pointed at `project:DagsterProject` from 0.1.0 until
        dex-core 1.6.0 began resolving this group, and then failed on first
        contact: a `ProjectFactory` is called WITH a `ProjectContext`, so the
        context bound to `models`. Nothing could have caught it, because nothing
        looked the group up -- which is exactly why this asserts the registration
        rather than trusting that installing the package proves it.
        """

        import importlib.metadata as md

        registered = {
            ep.name: ep.value
            for ep in md.entry_points(group="exmergo_dex_core.projects")
        }
        assert registered.get("dagster") == "dagster_dex.dex:project_from_context", (
            "the 'dagster' entry point must name a factory taking a ProjectContext, "
            f"not a class. Registered: {registered!r}"
        )
        # And it must actually resolve to the callable, not merely spell it.
        assert md.EntryPoint("dagster", registered["dagster"], "x").load() is project_from_context

    def test_an_option_it_cannot_honor_is_refused_by_name(self):
        """The arm that makes the option surface trustworthy.

        A typo is the likeliest bad option, and the failure it would otherwise
        cause is silent: `declerations` ignored means a project with no declared
        keys, which is a VALID project reporting nothing -- indistinguishable
        from one that genuinely declares none, and it would widen every grain
        finding dex makes.
        """

        with pytest.raises(ValueError, match="declerations"):
            project_from_context(
                _context(assets=f"{__name__}:FACTORY_ASSETS", declerations="/tmp/x")
            )

    def test_every_known_option_is_accepted(self):
        """The quiet arm, and the reason the loud one means anything.

        A factory that refused every unrecognised key would pass the test above
        while being useless. This pins the accepted set from the outside.
        """

        import dagster_dex.dex as dex_module

        assert dex_module._KNOWN_OPTIONS == {
            "artifact",
            "assets",
            "name",
            "declarations",
            "semantics",
            "sources",
        }

    def test_a_missing_source_option_is_refused(self):
        """There is nothing to discover from a directory: the source of truth is
        code, so either the module or a serialized project has to be named."""

        with pytest.raises(ValueError, match="needs either an 'assets' option"):
            project_from_context(_context())

    def test_an_assets_target_without_a_colon_is_refused(self):
        with pytest.raises(ValueError, match="module:attribute"):
            project_from_context(_context(assets="my_project.definitions.all_assets"))

    def test_an_unimportable_assets_module_is_refused_by_name(self):
        with pytest.raises(ValueError, match="no_such_module_anywhere"):
            project_from_context(_context(assets="no_such_module_anywhere:things"))

    def test_a_missing_attribute_is_refused_by_name(self):
        with pytest.raises(ValueError, match="not_an_attribute"):
            project_from_context(_context(assets=f"{__name__}:not_an_attribute"))

    def test_a_relative_directory_with_no_repo_root_is_refused(self):
        """`ProjectContext.repo_root` is nullable, so a relative path is only
        resolvable sometimes. Refusing beats resolving against the process CWD,
        which is whatever directory dex happened to be invoked from."""

        with pytest.raises(ValueError, match="repo_root"):
            project_from_context(
                _context(assets=f"{__name__}:FACTORY_ASSETS", declarations="some/relative/dir")
            )

    def test_a_directory_that_is_not_one_is_refused(self, tmp_path):
        missing = tmp_path / "nope"
        with pytest.raises(ValueError, match="not a directory"):
            project_from_context(
                _context(assets=f"{__name__}:FACTORY_ASSETS", declarations=str(missing))
            )

    def test_declarations_are_read_from_the_directory(self, tmp_path):
        """The path that actually carries meaning: a declared key reaching the
        project changes what dex checks, so an empty read is not a smaller
        answer, it is a different one."""

        # The package's own fixture helper rather than a hand-rolled string. The
        # declaration format is dbt-shaped, and inventing a plausible-looking one
        # here would exercise the parser against a shape nothing produces - which
        # is how a green test comes to mean nothing.
        (tmp_path / "dim_date.yml").write_text(a_single_key_declaration(), encoding="utf-8")
        project = project_from_context(
            _context(assets=f"{__name__}:FACTORY_ASSETS", declarations=str(tmp_path))
        )
        keys = project.definitions().declared_keys
        assert keys, "the declaration directory was not read"
        assert [(k.model, k.column) for k in keys] == [("dim_date", "date")]

    def test_an_empty_declaration_directory_reads_as_empty(self, tmp_path):
        """The quiet arm for the pair above. Without it, the assertion that a
        declaration arrives is equally consistent with declarations arriving
        unconditionally from somewhere else."""

        project = project_from_context(
            _context(assets=f"{__name__}:FACTORY_ASSETS", declarations=str(tmp_path))
        )
        assert project.definitions().declared_keys == []


class TestTheKeyNamesTheFileItCameFrom:
    """A key read off a directory is a key into this format's own keyspace.

    It used to be the file's STEM, which threw away both the directory and the
    suffix. That was survivable while nothing wrote: the three parsers use the
    key as an origin label in notes, so `'orders'` and `'declarations/orders.yml'`
    read about the same to a human.

    It stops being survivable the moment an edit has to land. dex asks a format
    where an edit of a given kind goes, and the answer is a key into whatever
    that format's own view returned - then checks it against the surface the
    format declared it owns. A bare stem is in no surface, so a format keyed by
    one can name no honest region of itself.

    **One parser reads the key as data rather than as a label**, and that is the
    assertion below that matters most: `parse_source_declarations` takes the key
    to be the model doing the reading. Widening the key without moving that
    reading would rename every reader after a file path, silently, and the
    "sources declared as read by models the graph does not build" note would fire
    on every source in a working project.
    """

    def test_a_note_names_the_directory_and_the_suffix(self, tmp_path):
        """The loud arm: what the widened key buys is provenance a reader can act
        on. `'broken'` names something the reader has to go looking for."""

        directory = tmp_path / "declarations"
        directory.mkdir()
        (directory / "broken.yml").write_text(malformed_yaml(), encoding="utf-8")

        project = project_from_context(
            _context(assets=f"{__name__}:FACTORY_ASSETS", declarations=str(directory))
        )

        notes = project.definitions().notes
        assert any("declarations/broken.yml" in note for note in notes), notes

    def test_the_reader_of_a_source_is_still_the_model_not_the_path(self, tmp_path):
        """The quiet arm, and the one that discriminates.

        `read_by` is a model name, taken from the key. If the widened key reached
        it unchanged, every reader would be named `sources/fact_orders.yml`, no
        model would match, and `declarations()` would carry a note saying the
        graph builds none of them - a working project reporting itself broken.
        """

        directory = tmp_path / "sources"
        directory.mkdir()
        (directory / "dim_date.yml").write_text(
            a_source_declaration(), encoding="utf-8"
        )

        project = project_from_context(
            _context(assets=f"{__name__}:FACTORY_ASSETS", sources=str(directory))
        )
        definitions = project.definitions()

        source = project._project.declarations().sources[0]
        assert source.read_by == ("dim_date",), source.read_by
        assert not [n for n in definitions.notes if "does not build" in n]

    def test_a_source_says_where_it_was_declared(self, tmp_path):
        """`declared_in` existed and was never set, so `SourceTable.path` was
        always `None`.

        The provenance was in the caller's hand at read time and thrown away one
        line later, which is the shape this package has recorded against itself
        before: a limitation its own parser created. It is what an analyst sees
        beside a `dangling_source` finding.
        """

        directory = tmp_path / "sources"
        directory.mkdir()
        (directory / "dim_date.yml").write_text(
            a_source_declaration(), encoding="utf-8"
        )

        project = project_from_context(
            _context(assets=f"{__name__}:FACTORY_ASSETS", sources=str(directory))
        )

        source = project._project.declarations().sources[0]
        assert source.declared_in == "sources/dim_date.yml"
        assert project.transform_layer().sources[0].path == "sources/dim_date.yml"

    def test_a_hand_built_project_keys_by_nothing_in_particular_and_still_works(self):
        """The other quiet arm: the key is a label, not a schema.

        A project built in memory - by the conformance suite, by a host holding
        its own text, by `artifact.loads`, which carries stems - passes whatever
        it has. Nothing here may start requiring a path-shaped key, because an
        artifact has no directory to have come from and inventing one would be
        the fabricated provenance `declared_in` exists to avoid.
        """

        project = DagsterProject(
            MODELS,
            source_declarations={"fact_orders": a_source_declaration()},
        )
        source = project.declarations().sources[0]

        assert source.read_by == ("fact_orders",)
        assert source.declared_in is None


def _write_artifact(directory, **overrides):
    """A valid artifact on disk, built through the real writer.

    Hand-rolling the JSON here would test this file's idea of the shape rather
    than the one `dumps` produces, which is exactly the drift the artifact exists
    to prevent.
    """

    from dagster_dex.artifact import dumps
    from dagster_dex.model import ProjectModel

    payload = {
        "name": "demo_project",
        "models": [ProjectModel(name="dim_date", layer="gold")],
        "generated_at": "2026-08-12T07:00:00Z",
        "declaration_sources": {"dim_date": a_single_key_declaration()},
    }
    payload.update(overrides)
    path = directory / "demo_project.json"
    path.write_text(dumps(**payload), encoding="utf-8")
    return path


class TestTheArtifactPath:
    """Reading a project somebody else reduced.

    The reason this option exists is latency: reducing the real graph costs
    ~2.6 s because it imports a code location, and a host that builds a project
    per command pays that on every request. These assertions are about the
    contract, not the timing -- the timing is measured on the box, by
    `scripts/measure_project_construction.py`.
    """

    def test_it_builds_the_same_project_the_graph_would(self, tmp_path):
        """The load-bearing arm. A declared key reaching dex through the artifact
        is the whole point; anything less makes this an expensive no-op."""

        path = _write_artifact(tmp_path)
        project = project_from_context(_context(artifact=str(path)))

        assert project.name == "dagster"
        keys = project.definitions().declared_keys
        assert [(k.model, k.column) for k in keys] == [("dim_date", "date")]

    def test_an_artifact_with_no_declarations_reads_as_empty(self, tmp_path):
        """The quiet arm. Without it, the assertion above is equally consistent
        with declarations arriving from somewhere other than the artifact."""

        path = _write_artifact(tmp_path, declaration_sources={})
        project = project_from_context(_context(artifact=str(path)))
        assert project.definitions().declared_keys == []

    def test_a_missing_artifact_is_refused_rather_than_read_as_empty(self, tmp_path):
        """The negative control that makes the empty case above safe.

        An unreadable artifact yielding an empty project is the one outcome that
        must not ship: an empty project is VALID, so it is indistinguishable from
        a warehouse that genuinely declares nothing, and dex would report "no
        declared joins" for what is really a broken deploy -- silently, and
        forever. Deliberately different from a directory-keyed format, where dex
        degrades to an empty view; there, "no project" is an ordinary state of
        the repo, and here the path was named explicitly.
        """

        missing = tmp_path / "never_written.json"
        with pytest.raises(ValueError, match="does not exist"):
            project_from_context(_context(artifact=str(missing)))

    def test_an_unreadable_artifact_is_refused_by_path(self, tmp_path):
        path = tmp_path / "demo_project.json"
        path.write_text("{not json at all", encoding="utf-8")
        with pytest.raises(ValueError, match="unusable"):
            project_from_context(_context(artifact=str(path)))

    def test_an_unknown_schema_version_is_refused(self, tmp_path):
        """Equality, not a floor: a reader meeting a version it does not know
        cannot tell 'newer and compatible' from 'newer and reinterpreted'."""

        import json

        from dagster_dex.artifact import SCHEMA_VERSION

        path = _write_artifact(tmp_path)
        document = json.loads(path.read_text(encoding="utf-8"))
        document["schema_version"] = SCHEMA_VERSION + 1
        path.write_text(json.dumps(document), encoding="utf-8")

        with pytest.raises(ValueError, match="schema_version"):
            project_from_context(_context(artifact=str(path)))

    def test_naming_both_sources_is_refused(self, tmp_path):
        """They are two different projects -- one live, one a snapshot -- so
        preferring either would serve a project nobody chose."""

        path = _write_artifact(tmp_path)
        with pytest.raises(ValueError, match="exactly one of"):
            project_from_context(
                _context(artifact=str(path), assets=f"{__name__}:FACTORY_ASSETS")
            )

    @pytest.mark.parametrize("option", ["declarations", "semantics", "sources", "name"])
    def test_options_the_artifact_answers_for_itself_are_refused(self, tmp_path, option):
        """Refused rather than ignored or honored. A `declarations:` beside an
        `artifact:` modifies nothing while reading as the live source, and a
        `name:` would lose to the file without saying so."""

        path = _write_artifact(tmp_path)
        with pytest.raises(ValueError, match=option):
            project_from_context(_context(**{"artifact": str(path), option: "x"}))

    def test_a_relative_artifact_with_no_repo_root_is_refused(self):
        with pytest.raises(ValueError, match="repo_root"):
            project_from_context(_context(artifact="some/relative/demo_project.json"))


def _editable(tmp_path, files=None):
    """The format built the way a host builds it, with declarations on disk.

    Through `project_from_context` rather than by constructing the class, because
    which class gets built IS the decision under test. Reaching for
    `EditableDexProject` directly would assert that the class works and say
    nothing about whether anything ever returns one.
    """

    directory = tmp_path / "declarations"
    directory.mkdir(exist_ok=True)
    files = {"orders.yml": a_single_key_declaration(model="dim_date")} if files is None else files
    for name, text in files.items():
        (directory / name).write_text(text, encoding="utf-8", newline="\n")

    return project_from_context(
        _context(assets=f"{__name__}:FACTORY_ASSETS", declarations=str(directory))
    )


class TestWhichClassTheFactoryBuilds:
    """The write tier is per instance, and the factory is where that is decided.

    Both dex-core protocols are `runtime_checkable`, so they match on methods
    being present. That makes the decision structural: it cannot be a flag, and
    it cannot be a refusal at call time, because a caller finding out by
    receiving an empty result that looks like success is what the tiers exist to
    prevent. So the assertions come in pairs - a build that reaches the tier, and
    a build that must not.
    """

    def test_declarations_on_disk_reach_the_write_tier(self, tmp_path):
        from exmergo_dex_core.adapters.project import (
            EditableProject,
            PlacingProject,
            tier_of,
        )

        project = _editable(tmp_path)

        assert tier_of(project) == 3
        assert isinstance(project, EditableProject)
        assert isinstance(project, PlacingProject)

    def test_no_declaration_directory_stays_at_tier_two(self):
        """A project with nowhere for the one kind this format places should
        decline, which upstream says more directly than answering None for every
        kind would."""

        from exmergo_dex_core.adapters.project import (
            EditableProject,
            PlacingProject,
            tier_of,
        )

        project = project_from_context(_context(assets=f"{__name__}:FACTORY_ASSETS"))

        assert tier_of(project) == 2
        assert not isinstance(project, EditableProject)
        assert not isinstance(project, PlacingProject)

    def test_an_artifact_built_project_stays_at_tier_two(self, tmp_path):
        """The half that rots, and the reason the class is split at all.

        An artifact is a JSON file carrying `{name: text}` with no directory
        behind it. Put `write_edits` on the shared class and this instance claims
        the write tier, then has to refuse every edit it is handed.
        """

        from exmergo_dex_core.adapters.project import (
            EditableProject,
            PlacingProject,
            tier_of,
        )

        path = _write_artifact(tmp_path)
        project = project_from_context(_context(artifact=str(path)))

        assert tier_of(project) == 2
        assert not isinstance(project, EditableProject)
        assert not isinstance(project, PlacingProject)


class TestPlacement:
    def test_one_kind_resolves_and_the_rest_decline(self, tmp_path):
        """`None` per kind is the answer this seam was built to allow.

        A model here is a node in a running asset graph, so an authored
        `MODEL_SQL` would be regenerated away; the declared keys are hand-written
        YAML that nothing regenerates. One path and several `None`s is a
        complete, honest answer rather than a partial implementation.
        """

        from exmergo_dex_core.transform.plans import EditKind

        project = _editable(tmp_path)

        placed = {
            kind: project.edit_path(kind, "orders")
            for kind in EditKind
            if project.edit_path(kind, "orders") is not None
        }

        assert placed == {EditKind.SCHEMA_YML: "declarations/orders.yml"}

    def test_every_placement_lands_inside_the_declared_surface(self, tmp_path):
        """The two answers have to describe the same project.

        Containment is checked against `editing_surface()` at plan time whatever
        `edit_path` returned, so a placement outside it is an edit built and then
        refused - and the refusal reads as dex declining rather than as this
        format contradicting itself.
        """

        from exmergo_dex_core.transform.plans import EditKind, contained_key

        project = _editable(tmp_path)
        surface = project.editing_surface()

        for kind in EditKind:
            path = project.edit_path(kind, "orders")
            if path is not None:
                contained_key(path, surface)

    def test_the_declared_surface_cannot_reach_outside_the_project(self, tmp_path):
        from pathlib import PurePosixPath

        for prefix in _editable(tmp_path).editing_surface():
            candidate = PurePosixPath(str(prefix).replace("\\", "/"))
            assert not candidate.is_absolute() and ".." not in candidate.parts


class TestTheViewTheCallersActuallyRequire:
    """`load()` is declared by no protocol upstream and required by two callers.

    `transform.plans.plan` calls it to pin each edit against the file it would
    change, and `maintain.commands` calls it before reconcile builds a proposal.
    So a format can satisfy `EditableProject` and `PlacingProject` in full, pass
    both shipped conformance contracts, and fail at the first real reconcile.
    These assertions exist because the contract's do not.
    """

    def test_it_carries_the_files_and_their_hashes(self, tmp_path):
        view = _editable(tmp_path).load()

        assert set(view.files) == {"declarations/orders.yml"}
        entry = view.files["declarations/orders.yml"]
        assert entry.content and entry.sha256

    def test_it_is_not_a_dbt_view_which_is_what_routes_the_neutral_branch(
        self, tmp_path
    ):
        """`plans.plan` asks the VIEW whether dbt's checks apply, rather than
        asking the class that produced it - deliberately, so the seam does not
        become the `isinstance(project, DbtProject)` gate it replaced. Handing
        back a dbt view would opt this format into dbt's macro-path and
        root-manifest rules and then be refused by them."""

        from exmergo_dex_core.dbt_project import DbtProjectView

        assert not isinstance(_editable(tmp_path).load(), DbtProjectView)

    def test_the_root_is_what_the_keys_are_relative_to(self, tmp_path):
        from pathlib import Path

        view = _editable(tmp_path).load()

        assert (Path(view.root) / "declarations/orders.yml").is_file()


class TestWriteEditsAcrossTheBoundary:
    """dex-core's write tier, translated. Both arms, because neither is worth
    much alone: the refusal is satisfied by a writer that never writes."""

    def _an_edit(self, project, content="models: []\n"):
        from exmergo_dex_core.dbt_project import Edit

        current = project.load().files["declarations/orders.yml"]
        return Edit(
            path="declarations/orders.yml",
            new_content=content,
            old_content_hash=current.sha256,
        )

    def test_a_clean_apply_reports_what_it_wrote(self, tmp_path):
        project = _editable(tmp_path)
        result = project.write_edits([self._an_edit(project)], tmp_path)

        assert result.written == ["declarations/orders.yml"]
        assert result.conflicts == []

    def test_an_unconfirmed_apply_refuses_a_target_that_moved(self, tmp_path):
        project = _editable(tmp_path)
        edit = self._an_edit(project)

        target = tmp_path / "declarations/orders.yml"
        target.write_text("models: [{name: edited_by_a_human}]\n", encoding="utf-8")
        before = target.read_text(encoding="utf-8")

        result = project.write_edits([edit], tmp_path)

        assert target.read_text(encoding="utf-8") == before
        assert result.written == []
        # `transform apply` reads exactly these two to tell a refusal from an
        # apply, and they fail closed in opposite directions.
        assert [c.path for c in result.conflicts] == ["declarations/orders.yml"]
        assert result.conflicts[0].expected_sha256 != result.conflicts[0].found_sha256

    def test_a_confirmed_apply_overrides(self, tmp_path):
        project = _editable(tmp_path)
        edit = self._an_edit(project)

        target = tmp_path / "declarations/orders.yml"
        target.write_text("models: [{name: edited_by_a_human}]\n", encoding="utf-8")

        result = project.write_edits([edit], tmp_path, confirmed=True)

        assert result.written == ["declarations/orders.yml"]
        assert target.read_text(encoding="utf-8") == "models: []\n"

    def test_a_delete_crosses_as_a_delete(self, tmp_path):
        """`op` is orthogonal to `kind` upstream, and a delete carries no
        content. Reading `new_content` alone would turn every delete into an
        upsert of `None`, which the neutral model refuses."""

        from exmergo_dex_core.dbt_project import Edit, EditOp

        project = _editable(tmp_path)
        current = project.load().files["declarations/orders.yml"]
        result = project.write_edits(
            [
                Edit(
                    path="declarations/orders.yml",
                    op=EditOp.DELETE,
                    old_content_hash=current.sha256,
                )
            ],
            tmp_path,
        )

        assert result.written == ["declarations/orders.yml"]
        assert not (tmp_path / "declarations/orders.yml").exists()

    def test_the_callers_directory_wins_over_the_configured_one(self, tmp_path):
        """The plan is the authority on where its own hashes came from.

        This instance points wherever the engine was configured when it was
        built; the plan points where it was pinned. The two agreeing is the
        common case rather than a guarantee, and the disagreement is silent - so
        `transform apply` passes the plan's directory and it has to win.
        """

        project = _editable(tmp_path)
        edit = self._an_edit(project)

        elsewhere = tmp_path / "elsewhere"
        (elsewhere / "declarations").mkdir(parents=True)
        (elsewhere / "declarations/orders.yml").write_text(
            (tmp_path / "declarations/orders.yml").read_text(encoding="utf-8"),
            encoding="utf-8",
            newline="\n",
        )

        result = project.write_edits([edit], elsewhere)

        assert result.written == ["declarations/orders.yml"]
        assert (elsewhere / "declarations/orders.yml").read_text(
            encoding="utf-8"
        ) == "models: []\n"
        assert (tmp_path / "declarations/orders.yml").read_text(
            encoding="utf-8"
        ) != "models: []\n"
