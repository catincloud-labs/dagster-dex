# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""An importable contract for project formats.

Ships inside the package rather than beside it, because a contract that lives
in a repository's test tree only serves formats inside that repository. An
implementer outside it cannot run the one artifact that tells them whether they
got it right.

Use it by subclassing and supplying a constructor::

    from dagster_dex.conformance import FingerprintedProjectContract

    class TestMyFormat(FingerprintedProjectContract):
        def make_project(self, declarations, semantics, sources):
            return MyProject(..., declaration_sources=declarations,
                             semantic_sources=semantics,
                             source_declarations=sources)

Everything else runs for free.

**``make_project`` gained a third argument when external sources landed.** It
is a breaking change to this contract, taken deliberately while the suite has no
outside implementers rather than carried forever as an optional side-door: a
format's external reads are part of what it declares, and a hook that could be
skipped would let the assertions covering them go quietly unrun. A skip is not a
signal.

**The assertions here are behavioural, not structural.** A format can satisfy
every type signature and still be wrong in the way that matters: raising on an
absent or malformed project, on a read path where absence is ordinary. That is
the property a second implementation is most likely to get wrong, and a suite
that only checks shapes will pass it. Hence ``test_*_never_raises``.

Once this is depended on, the builder names and the assertions are public
surface: a format pins against them, and renaming one is a breaking change.
That is worth accepting deliberately rather than discovering later.
"""

from __future__ import annotations

import pytest

from .model import Freshness
from .protocol import EditableProject, FingerprintedProject, ProjectSource, tier_of

__all__ = [
    "EditableProjectContract",
    "FingerprintedProjectContract",
    "ProjectSourceContract",
    "a_composite_key_declaration",
    "a_join_declaration",
    "a_semantic_definition",
    "a_semantic_definition_with_a_duplicate_field",
    "a_semantic_definition_without_expr",
    "a_single_key_declaration",
    "a_source_declaration",
    "malformed_yaml",
]


# --- fixture builders -------------------------------------------------------


def a_single_key_declaration(model: str = "dim_date", column: str = "date") -> str:
    """A model whose grain is one column."""

    return (
        "models:\n"
        f"  - name: {model}\n"
        "    columns:\n"
        f"      - name: {column}\n"
        "        tests:\n"
        "          - unique\n"
        "          - not_null\n"
    )


def a_composite_key_declaration(
    model: str = "fact_orders",
    columns: tuple[str, ...] = ("date", "provider", "product_id", "order_type"),
) -> str:
    """A model whose grain needs more than one column.

    The default is four columns rather than two on purpose: a format that
    handles pairs by special-casing them passes a two-column test and fails
    this one.
    """

    listed = "\n".join(f"            - {c}" for c in columns)
    return (
        "models:\n"
        f"  - name: {model}\n"
        "    tests:\n"
        "      - unique_combination_of_columns:\n"
        "          combination_of_columns:\n"
        f"{listed}\n"
    )


def a_join_declaration(
    from_model: str = "fact_sessions",
    from_column: str = "date",
    to_model: str = "dim_date",
    to_column: str = "date",
) -> str:
    """A declared relationship between two models."""

    return (
        "models:\n"
        f"  - name: {from_model}\n"
        "    columns:\n"
        f"      - name: {from_column}\n"
        "        tests:\n"
        "          - relationships:\n"
        f"              to: ref('{to_model}')\n"
        f"              field: {to_column}\n"
    )


def a_semantic_definition(model: str = "mart_revenue") -> str:
    """A well-formed semantic model: two dimensions, one measure, one metric.

    Every field carries ``expr``, because that is what a complete declaration looks
    like and it is what lets a consumer check the definition against the warehouse.
    ``provider`` is ``type: categorical``, so the categorical channel is exercised
    too. For the degraded shapes, see :func:`a_semantic_definition_without_expr`.
    """

    return (
        "semantic_models:\n"
        f"  - name: {model}\n"
        f"    model: ref('{model}')\n"
        "    dimensions:\n"
        "      - name: date\n"
        "        type: time\n"
        "        expr: date\n"
        "      - name: provider\n"
        "        type: categorical\n"
        "        expr: provider\n"
        "    measures:\n"
        "      - name: daily_revenue_net\n"
        "        agg: sum\n"
        "        expr: daily_revenue_net\n"
        "\n"
        "metrics:\n"
        "  - name: daily_revenue\n"
        "    type: simple\n"
        "    type_params:\n"
        "      measure: daily_revenue_net\n"
    )


def a_semantic_definition_without_expr(model: str = "mart_revenue") -> str:
    """Three fields that resolve to no column, one per way of getting there.

    - ``date`` omits ``expr`` entirely;
    - ``region`` omits it **and** is ``type: categorical``, which is the case a
      consumer requiring non-null column values has to handle separately;
    - ``revenue_with_fee`` declares an ``expr`` that is an **expression**.

    All three are legal declarations rather than malformed input, so a format may
    not refuse them, and none of them may be answered with an invented column. The
    categorical one is here because it is the only field whose unresolved state can
    reach a *required* value on the far side of a boundary.
    """

    return (
        "semantic_models:\n"
        f"  - name: {model}\n"
        f"    model: ref('{model}')\n"
        "    dimensions:\n"
        "      - name: date\n"
        "        type: time\n"
        "      - name: region\n"
        "        type: categorical\n"
        "    measures:\n"
        "      - name: revenue_with_fee\n"
        "        agg: sum\n"
        "        expr: daily_revenue_net * 1.2\n"
    )


def a_semantic_definition_with_a_duplicate_field(
    model: str = "mart_revenue",
) -> str:
    """Two measures declaring the same name, resolving to different columns.

    A consumer keyed by name keeps one of them, so a format that passes both
    through has already lost a declaration by the time anyone can notice.
    """

    return (
        "semantic_models:\n"
        f"  - name: {model}\n"
        f"    model: ref('{model}')\n"
        "    measures:\n"
        "      - name: total\n"
        "        agg: sum\n"
        "        expr: total_a\n"
        "      - name: total\n"
        "        agg: sum\n"
        "        expr: total_b\n"
    )


def a_source_declaration(
    system: str = "sales",
    table: str = "orders_export_v1",
    schema: str = "sales",
    columns: tuple[str, ...] = ("placed_at", "amount"),
) -> str:
    """A warehouse table the project reads but does not build.

    The default names a table that is not also a model name, on purpose: a
    format that resolved sources by matching them against its own models would
    pass a test whose source shares a model's name and fail this one.
    """

    listed = "\n".join(f"          - name: {c}" for c in columns)
    return (
        "sources:\n"
        f"  - name: {system}\n"
        f"    schema: {schema}\n"
        "    tables:\n"
        f"      - name: {table}\n"
        "        columns:\n"
        f"{listed}\n"
    )


def malformed_yaml() -> str:
    """Input that is not parseable. A format must survive it, not refuse."""

    return "models:\n  - name: broken\n   columns: [oops\n"


# --- the contracts ----------------------------------------------------------


class ProjectSourceContract:
    """Tier 1. Subclass and implement :meth:`make_project`.

    External sources are asserted here rather than at tier 2, because a
    project's external reads are something it *declares* - they arrive through
    ``declarations()`` like every other statement. What tier 2 adds is a
    consumer for them, not a way to express them.
    """

    def make_project(
        self,
        declarations: dict[str, str],
        semantics: dict[str, str],
        sources: dict[str, str],
    ):
        """Build the format under test from declaration, semantic, and source text.

        ``sources`` is keyed by the model that reads the declared tables.
        """

        raise NotImplementedError  # pragma: no cover - always overridden

    # -- shape ---------------------------------------------------------------

    def test_satisfies_the_tier_one_protocol(self):
        project = self.make_project({}, {}, {})
        assert isinstance(project, ProjectSource)
        assert tier_of(project) >= 1

    def test_declares_a_stable_format_name(self):
        first = self.make_project({}, {}, {})
        second = self.make_project({"d": a_single_key_declaration()}, {}, {})
        assert first.format == second.format
        assert first.format, "a format needs a non-empty name to be resolvable"

    # -- behaviour: the half a shape check cannot reach -----------------------

    def test_an_empty_project_never_raises(self):
        declarations = self.make_project({}, {}, {}).declarations()
        assert declarations.is_empty or declarations.models

    def test_malformed_input_never_raises(self):
        """The property most likely to be got wrong, asserted directly."""

        declarations = self.make_project(
            {"broken": malformed_yaml()}, {}, {}
        ).declarations()
        assert declarations is not None

    def test_malformed_input_is_explained_rather_than_silent(self):
        """Degrading quietly still owes the reader a reason."""

        declarations = self.make_project(
            {"broken": malformed_yaml()}, {}, {}
        ).declarations()
        assert declarations.notes, "a skipped declaration must leave a note"

    def test_a_malformed_source_declaration_never_raises_and_is_explained(self):
        """Same contract on the source channel. Asserted separately because it
        is a different parser: a format can be careful on one input and not on
        the other, and one test over both would pass on either."""

        declarations = self.make_project(
            {}, {}, {"broken": malformed_yaml()}
        ).declarations()
        assert declarations is not None
        assert declarations.notes, "a skipped source declaration must leave a note"

    # -- the declared channel ------------------------------------------------

    def test_a_single_column_key_is_read(self):
        declarations = self.make_project(
            {"dim_date": a_single_key_declaration()}, {}, {}
        ).declarations()
        keys = [k for k in declarations.declared_keys if k.model == "dim_date"]
        assert [k.columns for k in keys] == [("date",)]

    def test_a_composite_key_keeps_every_column_and_their_order(self):
        """The failure this catches is silent: a truncated key still looks
        like a declared grain, and reads as a narrower one that is simply
        wrong rather than as a missing declaration."""

        declarations = self.make_project(
            {"fact": a_composite_key_declaration()}, {}, {}
        ).declarations()
        keys = [k for k in declarations.declared_keys if k.model == "fact_orders"]
        assert len(keys) == 1
        assert keys[0].columns == ("date", "provider", "product_id", "order_type")
        assert keys[0].is_composite

    def test_a_declared_join_carries_both_sides(self):
        declarations = self.make_project({"j": a_join_declaration()}, {}, {}).declarations()
        assert len(declarations.declared_joins) == 1
        join = declarations.declared_joins[0]
        assert join.from_model == "fact_sessions"
        assert join.to_model == "dim_date"
        assert join.from_columns == ("date",)
        assert join.to_columns == ("date",)

    def test_a_join_keeps_the_two_sides_apart_when_they_are_named_differently(self):
        """The case above cannot fail for the right reason: both of its sides
        are called ``date``, so an implementation that mirrored the source
        column onto the target would satisfy it exactly.

        That is not hypothetical. Mutating ``to_columns=(field,)`` to
        ``to_columns=(column,)`` left the entire suite green until this test
        existed, and dbt's ``relationships`` test exists precisely to express a
        foreign key whose two ends are spelled differently. A format that
        mirrored would join on a column the target may not even have, and the
        error would surface as a wrong answer rather than a failure.

        ``a_join_declaration``'s default stays mirrored, deliberately, so an
        outside implementer's suite does not change meaning underneath them.
        This case is the explicit widening.
        """

        declarations = self.make_project(
            {
                "j": a_join_declaration(
                    from_model="fact_pageviews",
                    from_column="product_url",
                    to_model="dim_product",
                    to_column="canonical_url",
                )
            },
            {},
            {},
        ).declarations()
        assert len(declarations.declared_joins) == 1
        join = declarations.declared_joins[0]
        assert join.from_columns == ("product_url",)
        assert join.to_columns == ("canonical_url",)
        assert join.from_columns != join.to_columns

    def test_semantic_models_and_metrics_are_read(self):
        declarations = self.make_project(
            {}, {"s": a_semantic_definition()}, {}
        ).declarations()
        assert [m.name for m in declarations.semantic_models] == ["mart_revenue"]
        assert [m.name for m in declarations.metrics] == ["daily_revenue"]

    def test_a_semantic_field_carries_the_column_behind_it(self):
        """The names alone are not enough, and this suite once asserted only names.

        A consumer checking whether a semantic definition still resolves has to
        check the **column** against the warehouse. A format that reads the names
        and drops the columns passes every name-only assertion while leaving that
        check unable to run, which is exactly what happened here.
        """

        declarations = self.make_project(
            {}, {"s": a_semantic_definition()}, {}
        ).declarations()
        model = declarations.semantic_models[0]

        assert model.dimension_names() == ("date", "provider")
        assert model.measure_names() == ("daily_revenue_net",)
        assert [d.column for d in model.dimensions] == ["date", "provider"]
        assert [m.column for m in model.measures] == ["daily_revenue_net"]

    def test_a_categorical_dimension_is_marked_as_one(self):
        declarations = self.make_project(
            {}, {"s": a_semantic_definition()}, {}
        ).declarations()
        by_name = {d.name: d for d in declarations.semantic_models[0].dimensions}

        assert by_name["provider"].categorical
        assert not by_name["date"].categorical

    def test_a_field_with_no_bare_column_reports_none_rather_than_inventing_one(self):
        """An expression is not a column, and neither is an absent ``expr``.

        Both are legal declarations rather than malformed input, so the format may
        not refuse them; and a consumer that resolves column names would treat a
        fabricated value as a reference that no longer resolves. ``None`` plus a
        note is the honest answer, and the note is what makes the gap fixable.
        """

        declarations = self.make_project(
            {}, {"s": a_semantic_definition_without_expr()}, {}
        ).declarations()
        model = declarations.semantic_models[0]

        assert [d.column for d in model.dimensions] == [None, None]
        assert [m.column for m in model.measures] == [None]
        assert declarations.notes, "a dropped column mapping must be disclosed"

    def test_a_categorical_dimension_can_be_categorical_with_no_column(self):
        """The two properties are independent, and a consumer needs both.

        ``categorical`` says how the dimension behaves; ``column`` says whether it
        can be resolved. Collapsing them - treating "no column" as "not
        categorical", or assuming a categorical field always has one - is what
        breaks a consumer whose categorical channel requires non-null values.
        """

        declarations = self.make_project(
            {}, {"s": a_semantic_definition_without_expr()}, {}
        ).declarations()
        region = next(
            d for d in declarations.semantic_models[0].dimensions if d.name == "region"
        )

        assert region.categorical
        assert region.column is None

    def test_a_redeclared_field_name_keeps_the_first_and_says_so(self):
        """Names have to be unique, because consumers key on them.

        A consumer mapping ``{name: column}`` keeps whichever duplicate it saw last,
        so passing both through loses a declaration silently and by no rule anybody
        chose. The first wins and the drop is disclosed.
        """

        declarations = self.make_project(
            {}, {"s": a_semantic_definition_with_a_duplicate_field()}, {}
        ).declarations()
        measures = declarations.semantic_models[0].measures

        assert [(m.name, m.column) for m in measures] == [("total", "total_a")]
        assert any("redeclare" in note for note in declarations.notes)

    # -- the source channel --------------------------------------------------

    def test_an_external_source_is_read_and_attributed_to_its_reader(self):
        declarations = self.make_project(
            {}, {}, {"orders_raw": a_source_declaration()}
        ).declarations()
        assert len(declarations.sources) == 1
        source = declarations.sources[0]
        assert source.system == "sales"
        assert source.table == "orders_export_v1"
        assert source.schema_name == "sales"
        assert source.columns == ("placed_at", "amount")
        assert "orders_raw" in source.read_by

    def test_a_source_requires_a_system_it_cannot_invent(self):
        """A source entry with no name is skipped and explained, not given a
        placeholder. The consumer identifies a source as ``system.table``, so a
        fabricated system produces a finding about a table that does not
        exist under that name."""

        declarations = self.make_project(
            {}, {}, {"reader": "sources:\n  - schema: sales\n    tables:\n      - name: t\n"}
        ).declarations()
        assert declarations.sources == ()
        assert declarations.notes

    def test_one_table_declared_twice_is_one_source_with_two_readers(self):
        """Emitting it twice would be reported as two contracts with the
        warehouse, so a single missing table would raise two findings."""

        declaration = a_source_declaration()
        declarations = self.make_project(
            {}, {}, {"reader_a": declaration, "reader_b": declaration}
        ).declarations()
        assert len(declarations.sources) == 1
        assert set(declarations.sources[0].read_by) == {"reader_a", "reader_b"}

    def test_a_project_that_only_declares_sources_is_not_empty(self):
        """A project that builds nothing but names what it reads has still
        said something, and reporting it as empty discards the only statement
        it made."""

        declarations = self.make_project(
            {}, {}, {"reader": a_source_declaration()}
        ).declarations()
        assert not declarations.is_empty

    def test_the_declared_channel_is_not_vacuous(self):
        """Guards every assertion above. If the builders stopped producing
        anything, the tests would still pass while measuring nothing."""

        declarations = self.make_project(
            {"a": a_single_key_declaration(), "b": a_join_declaration()},
            {"s": a_semantic_definition()},
            {"c": a_source_declaration()},
        ).declarations()
        assert declarations.declared_keys
        assert declarations.declared_joins
        assert declarations.semantic_models
        assert declarations.sources

    def test_freshness_is_never_a_bare_boolean(self):
        """A format with no compiled artifact must say so, not say 'current'."""

        declarations = self.make_project({}, {}, {}).declarations()
        assert isinstance(declarations.freshness, Freshness)


class FingerprintedProjectContract(ProjectSourceContract):
    """Tier 2. Inherits every tier-1 assertion."""

    def test_satisfies_the_tier_two_protocol(self):
        assert isinstance(self.make_project({}, {}, {}), FingerprintedProject)
        assert tier_of(self.make_project({}, {}, {})) >= 2

    def test_a_fingerprint_is_stable_across_calls(self):
        project = self.make_project({}, {}, {})
        assert project.fingerprint() == project.fingerprint()

    def test_two_identical_projects_fingerprint_alike(self):
        left = self.make_project({"a": a_single_key_declaration()}, {}, {})
        right = self.make_project({"a": a_single_key_declaration()}, {}, {})
        assert left.fingerprint().layers == right.fingerprint().layers

    def test_fingerprinting_never_raises_on_an_empty_project(self):
        assert self.make_project({}, {}, {}).fingerprint() is not None

    def test_gaining_an_external_source_is_visible_as_drift(self):
        """A new warehouse dependency is a change in the project. A fingerprint
        that missed it would report no drift on the one axis a snapshot exists
        to watch."""

        without = self.make_project({}, {}, {}).fingerprint()
        with_source = self.make_project(
            {}, {}, {"reader": a_source_declaration()}
        ).fingerprint()
        assert without.layers != with_source.layers
        assert with_source.changed_layers(without)

    def test_repointing_a_source_to_another_schema_is_drift(self):
        """Two tables of the same name in different datasets are two different
        warehouse objects. A hash over the bare table name calls the swap no
        change - and it is the change most likely to be made by accident."""

        here = self.make_project(
            {}, {}, {"reader": a_source_declaration(schema="sales")}
        ).fingerprint()
        there = self.make_project(
            {}, {}, {"reader": a_source_declaration(schema="sales_backup")}
        ).fingerprint()
        assert here.layers != there.layers


class EditableProjectContract:
    """Tier 3, the write path.

    **Mixed in beside** :class:`FingerprintedProjectContract` **rather than
    inheriting it**, because the two need different constructors. A tier-1 or
    tier-2 project can be built from text held in memory; a project that can
    receive an edit has somewhere for the edit to land, and a hook shaped for the
    first cannot produce the second without inventing a place.

    **Everything here is behavioural, and none of it is optional.** This is the
    tier where getting it wrong costs somebody their work rather than costing an
    inaccurate report. No shape check can tell a ``propose_edits`` that refuses
    correctly from one that never writes at all, which is why the refusing arm
    and the writing arm are both required and neither counts alone.

    Supply one hook::

        class TestMyFormatWrites(EditableProjectContract):
            def an_edit_against_a_changed_target(self):
                ...
                return project, edits, read_target
    """

    def an_edit_against_a_changed_target(self):
        """A staged conflict: ``(project, edits, read_target)``.

        Build a project, propose an edit against something in it, then change
        that target behind the proposal's back - which is what a human editing
        during review does. Return, in order:

        - ``project``: the tier-3 project the edits go through.
        - ``edits``: the edit set, pinned to the content from *before* the change.
        - ``read_target``: a zero-argument callable returning what the target
          holds right now. Any value comparing equal to itself will do; these
          assertions only ask whether it moved.

        **Return a freshly staged scenario on every call.** Both write
        assertions use it and one of them writes, so a shared fixture would let
        the second see what the first left behind.

        This hook is mandatory, unlike ``make_unreadable_project`` on the read
        contract. A format may honestly have no unparseable state; a format that
        writes into a source of truth a human can also edit always has the state
        where the human got there first. One that cannot stage that scenario
        cannot detect it either, and one that cannot detect it overwrites work
        silently.
        """

        raise NotImplementedError(
            "a tier-3 conformance subclass must implement "
            "an_edit_against_a_changed_target() -> (project, edits, read_target), "
            "staging the case the write tier exists to get right: a human edited "
            "the target after the edit was proposed"
        )

    def test_satisfies_the_write_tier(self):
        project, _edits, _read_target = self.an_edit_against_a_changed_target()
        assert isinstance(project, EditableProject)
        assert tier_of(project) == 3

    def test_an_unconfirmed_write_refuses_a_target_that_moved(self):
        """The human edit survives, and nothing is written.

        This is propose-don't-impose at the only layer that can enforce it. The
        content an edit was proposed against is pinned precisely so the window
        between proposing and writing - a human review, and it can be long - does
        not end with somebody's work replaced by a proposal written before it
        existed.
        """

        project, edits, read_target = self.an_edit_against_a_changed_target()
        before = read_target()

        project.propose_edits(edits)

        assert read_target() == before, (
            "propose_edits() overwrote a target that changed after the edit was "
            "proposed, with confirmed left at its default. A conflict has to "
            "refuse the whole set and write nothing until a human confirms it"
        )

    def test_a_confirmed_write_overrides_the_conflict(self):
        """Without this the refusal above is satisfied by a write path that never
        writes, and a format could pass by doing nothing at all."""

        project, edits, read_target = self.an_edit_against_a_changed_target()
        before = read_target()

        project.propose_edits(edits, confirmed=True)

        assert read_target() != before, (
            "propose_edits() left the target unchanged with confirmed=True. The "
            "override is what a human reaches for after reading the conflict, so "
            "a format that refuses either way has no write path at all"
        )

    def test_the_outcome_reports_what_happened(self):
        """A caller has to be able to tell a refusal from a write.

        Both readings fail closed on an outcome answering neither, and they fail
        in opposite directions: a proposal recorded as applied that wrote
        nothing, or a conflict that never reaches the person it was raised for.
        Asserted on the refusing case, which is the one where the two fields
        disagree and so the one an outcome reporting nothing gets wrong.
        """

        project, edits, _read_target = self.an_edit_against_a_changed_target()

        outcome = project.propose_edits(edits)

        assert not outcome.written, (
            "propose_edits() reported paths in `written` while refusing an "
            "unconfirmed conflict, so a caller marks the proposal applied and "
            "nobody is asked about the conflict"
        )
        assert outcome.conflicts, (
            "propose_edits() refused the write and reported no `conflicts`, so "
            "the divergence it refused over never reaches a human and the "
            "refusal looks like a clean no-op"
        )

    def test_the_declared_surface_cannot_reach_outside_the_project(self):
        """A surface is a region of the project, not a way out of it.

        Escapes are refused whatever is declared, so this widens nothing;
        declaring one means the format believes it owns something it does not,
        and the belief is worth catching here rather than as a refusal on the
        first edit that uses it.
        """

        from pathlib import PurePosixPath

        project, _edits, _read_target = self.an_edit_against_a_changed_target()

        for prefix in project.editing_surface():
            candidate = PurePosixPath(str(prefix).replace("\\", "/"))
            assert not candidate.is_absolute() and ".." not in candidate.parts, (
                f"editing_surface() declares '{prefix}', which is absolute or "
                "climbs out of the project"
            )


@pytest.fixture
def _conformance_marker():  # pragma: no cover - keeps pytest importing this module happy
    """Present so this module is importable as a plugin without side effects."""

    return None
