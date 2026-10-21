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
        """The negative half, and since 2026-08-18 it is the half that rots.

        `EditableDagsterProject` reaches tier 3 and this class must not, because
        the protocols match on a method being present: one `propose_edits` on the
        base and every project claims the write tier, including one built from an
        artifact that has nowhere to write. The positive half lives in
        `tests/test_write_tier.py`; neither is worth much without the other.

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


#: The note an entry declaring both keys gets, whole. Asserted whole because a
#: note that says something false - that one list is ignored, say - would pass
#: any check for a word in it.
BOTH_KEYS = (
    "{} declares both `tests` and `data_tests`; what each lists is read here, "
    "but dbt and dex-core can refuse an entry declaring both, so keep one key"
)


class TestATestListUnderEitherKey:
    """#115: dbt reads an entry's test list under `tests:` or `data_tests:`,
    and the parser read `tests:` alone, so every `data_tests:` list was read as
    nothing, with no note. Reconcile writes that spelling itself: from
    exmergo-dex-core 1.10.0 where a file already uses it, and from 1.12.7 where
    a file has no spelling to follow.

    Each arm asserts the exact result for its key rather than that the two
    keys agree: two keys that both read as nothing agree as well. Asserted on
    the project's declarations, not on the parser, so a key or a note that
    fails to arrive there goes red here.
    """

    @pytest.mark.parametrize("key", ["tests", "data_tests"])
    def test_a_column_level_list_is_read_under_either_key(self, key):
        text = (
            "models:\n"
            "  - name: fact_orders\n"
            "    columns:\n"
            "      - name: order_id\n"
            f"        {key}:\n"
            "          - unique\n"
            "      - name: date\n"
            f"        {key}:\n"
            "          - relationships:\n"
            "              to: ref('dim_date')\n"
            "              field: date\n"
        )
        declarations = a_project(declaration_sources={"f": text}).declarations()
        assert declarations.declared_keys == (
            DeclaredKey(model="fact_orders", columns=("order_id",), source="unique"),
        )
        assert declarations.declared_joins == (
            DeclaredJoin(
                from_model="fact_orders",
                from_columns=("date",),
                to_model="dim_date",
                to_columns=("date",),
                source="relationships",
            ),
        )
        assert declarations.notes == ()

    @pytest.mark.parametrize("key", ["tests", "data_tests"])
    def test_a_model_level_list_is_read_under_either_key(self, key):
        text = (
            "models:\n"
            "  - name: fact_orders\n"
            f"    {key}:\n"
            "      - unique_combination_of_columns:\n"
            "          combination_of_columns:\n"
            "            - date\n"
            "            - provider\n"
        )
        declarations = a_project(declaration_sources={"f": text}).declarations()
        assert declarations.declared_keys == (
            DeclaredKey(model="fact_orders", columns=("date", "provider"), source="combination"),
        )
        assert declarations.notes == ()

    def test_a_column_carrying_both_is_read_as_the_union_and_says_so(self):
        """The union, in order, and nothing more. `unique` under both keys is
        one key, not two. The two relationships share a name and differ in
        their payload, so a union by test name alone drops the second, and
        reading `data_tests` first reverses the joins."""

        text = (
            "models:\n"
            "  - name: fact_orders\n"
            "    columns:\n"
            "      - name: date\n"
            "        tests:\n"
            "          - unique\n"
            "          - relationships:\n"
            "              to: ref('dim_date')\n"
            "              field: date\n"
            "        data_tests:\n"
            "          - unique\n"
            "          - relationships:\n"
            "              to: ref('dim_date')\n"
            "              field: date_key\n"
        )
        declarations = a_project(declaration_sources={"f": text}).declarations()
        assert declarations.declared_keys == (
            DeclaredKey(model="fact_orders", columns=("date",), source="unique"),
        )
        assert [(j.to_model, j.to_columns) for j in declarations.declared_joins] == [
            ("dim_date", ("date",)),
            ("dim_date", ("date_key",)),
        ]
        assert declarations.notes == (BOTH_KEYS.format("fact_orders.date"),)

    def test_a_model_carrying_both_is_read_as_the_union_and_says_so(self):
        """The composite sits under the SECOND key, so reading only the first
        key present would drop it, and this goes red."""

        text = (
            "models:\n"
            "  - name: fact_orders\n"
            "    tests:\n"
            "      - not_empty\n"
            "    data_tests:\n"
            "      - unique_combination_of_columns:\n"
            "          combination_of_columns:\n"
            "            - date\n"
            "            - provider\n"
        )
        declarations = a_project(declaration_sources={"f": text}).declarations()
        assert declarations.declared_keys == (
            DeclaredKey(model="fact_orders", columns=("date", "provider"), source="combination"),
        )
        assert declarations.notes == (BOTH_KEYS.format("'fact_orders'"),)

    def test_both_keys_are_noted_even_when_one_lists_nothing(self):
        """The note turns on both keys being present, not on both listing
        something, because that is where dex-core 1.12.7 draws its line: it
        refuses to edit a file with an entry like this one."""

        text = (
            "models:\n"
            "  - name: fact_orders\n"
            "    columns:\n"
            "      - name: order_id\n"
            "        tests:\n"
            "        data_tests:\n"
            "          - unique\n"
        )
        declarations = a_project(declaration_sources={"f": text}).declarations()
        assert declarations.declared_keys == (
            DeclaredKey(model="fact_orders", columns=("order_id",), source="unique"),
        )
        assert declarations.notes == (BOTH_KEYS.format("fact_orders.order_id"),)

    @pytest.mark.parametrize("key", ["tests", "data_tests"])
    def test_a_test_key_that_is_not_a_list_is_ignored_and_says_so(self, key):
        """`unique` written where a list belongs reads as no test at all. It was
        dropped silently before, and the module's rule is a note."""

        text = (
            "models:\n"
            "  - name: fact_orders\n"
            "    columns:\n"
            "      - name: order_id\n"
            f"        {key}: unique\n"
        )
        declarations = a_project(declaration_sources={"f": text}).declarations()
        assert declarations.declared_keys == ()
        assert declarations.notes == (
            f"fact_orders.order_id declares `{key}` as something other than a list; ignored",
        )


def a_composite_under(key: str, name: str, *, nested: bool = False) -> str:
    """A model-level composite key, its test list under ``key`` and its test
    spelled ``name``. ``nested`` puts the columns one level down, under
    ``arguments:``, and changes nothing else in the text."""

    arguments = "          arguments:\n" if nested else ""
    pad = "  " if nested else ""
    return (
        "models:\n"
        "  - name: fact_orders\n"
        f"    {key}:\n"
        f"      - {name}:\n"
        f"{arguments}"
        f"{pad}          combination_of_columns:\n"
        f"{pad}            - date\n"
        f"{pad}            - provider\n"
    )


class TestAPackageQualifiedCompositeKey:
    """#117: a model-level composite key was read under the bare test name
    alone, so `dbt_utils.unique_combination_of_columns`, the spelling dbt-utils
    documents for its own test, was read as no key, with no note.

    The rule is exmergo-dex-core's own, read from its schema-YAML reader
    (`exmergo_dex_core/dbt_project.py` in the 1.12.7 wheel): the bare name, or
    any name ending in `.unique_combination_of_columns`. So a prefix naming a
    package other than `dbt_utils` counts too, and that arm is here so a fix
    narrowed to `dbt_utils.` goes red. The bare name is the control: it reads
    under both keys before the fix, so a red arm is the prefix and not the
    probe.
    """

    @pytest.mark.parametrize("key", ["tests", "data_tests"])
    @pytest.mark.parametrize(
        "name",
        [
            "unique_combination_of_columns",
            "dbt_utils.unique_combination_of_columns",
            "my_package.unique_combination_of_columns",
        ],
    )
    def test_a_composite_key_is_read_bare_or_under_a_package_prefix(self, key, name):
        declarations = a_project(
            declaration_sources={"f": a_composite_under(key, name)}
        ).declarations()
        assert declarations.declared_keys == (
            DeclaredKey(model="fact_orders", columns=("date", "provider"), source="combination"),
        )
        assert declarations.notes == ()

    @pytest.mark.parametrize(
        "name",
        [
            "my_unique_combination_of_columns",
            "dbt_utils.unique_combination_of_columns_where",
        ],
    )
    def test_a_name_that_only_contains_the_test_name_is_not_a_composite_key(self, name):
        """The prefix ends at a dot. Matching the suffix alone, or the name
        anywhere in the string, reads a different test as this one."""

        declarations = a_project(
            declaration_sources={"f": a_composite_under("tests", name)}
        ).declarations()
        assert declarations.declared_keys == ()
        assert declarations.notes == ()


#: The note a composite key that reads as no key gets, whole. Asserted whole,
#: because the defect 0.6.4 pinned here was a note that said something false.
NO_COLUMNS = "'fact_orders' declares a composite grain with no columns; ignored"


class TestACompositeKeyNestedUnderArguments:
    """#119: a composite key whose columns sit under `arguments:`, the form
    dbt-utils' README shows, was read as no key. 0.6.4 named the form in its
    note and left it unread, because exmergo-dex-core's schema-YAML reader did
    not read it either. From 1.13.1 that reader merges `arguments:` over the
    keys beside the test's name, `arguments` winning (exmergo/dex#565), so the
    form is read here by the same rule.

    The flat control is #117's test above, on the same builder: it reads the
    key under both spellings and both keys, so a red arm here is the nesting
    and not the probe. The entries with no columns anywhere are the second
    control: they keep their note, so a fix that takes an `arguments:` mapping
    for columns in itself goes red there.
    """

    @pytest.mark.parametrize("key", ["tests", "data_tests"])
    @pytest.mark.parametrize(
        "name",
        ["unique_combination_of_columns", "dbt_utils.unique_combination_of_columns"],
    )
    def test_the_nested_form_reads_the_key(self, key, name):
        declarations = a_project(
            declaration_sources={"f": a_composite_under(key, name, nested=True)}
        ).declarations()
        assert declarations.declared_keys == (
            DeclaredKey(model="fact_orders", columns=("date", "provider"), source="combination"),
        )
        assert declarations.notes == ()

    @pytest.mark.parametrize(
        "test",
        [
            "      - dbt_utils.unique_combination_of_columns\n",
            "      - dbt_utils.unique_combination_of_columns:\n"
            "          arguments: {}\n",
            "      - dbt_utils.unique_combination_of_columns:\n"
            "          arguments:\n"
            "            combination_of_columns: []\n",
        ],
        ids=["no-body", "empty-arguments", "empty-list-under-arguments"],
    )
    def test_an_entry_with_no_columns_anywhere_keeps_its_note(self, test):
        text = "models:\n  - name: fact_orders\n    data_tests:\n" + test
        declarations = a_project(declaration_sources={"f": text}).declarations()
        assert declarations.declared_keys == ()
        assert declarations.notes == (NO_COLUMNS,)


#: `fact_orders.date` -> `dim_date.date`, the join every relationship arm below
#: declares.
DATE_JOIN = DeclaredJoin(
    from_model="fact_orders",
    from_columns=("date",),
    to_model="dim_date",
    to_columns=("date",),
    source="relationships",
)


def a_date_column_testing(key: str, test: str) -> str:
    """`fact_orders.date`, with ``test`` in its test list under ``key``.
    ``test`` is written at the list's own indent."""

    return (
        "models:\n"
        "  - name: fact_orders\n"
        "    columns:\n"
        "      - name: date\n"
        f"        {key}:\n"
        f"{test}"
    )


#: The note a test entry dbt refuses for its shape gets, whole: where it sits,
#: then its keys, sorted. Defined here because the first test to expect it is
#: in the next class; `TestATestEntryDbtRefuses` says why it exists.
REFUSED = (
    "{} lists a test as a mapping of several keys ({}) with no string "
    "`test_name`, which dbt refuses; skipped"
)


class TestATestReadTheWayDbtReadsIt:
    """#119's other rows: the same upstream change, reaching past the composite
    key. From 1.13.1, exmergo-dex-core's schema-YAML reader reads a
    `relationships` test's inputs through `arguments:` too, and names a test
    by its `test_name:` when the entry carries one (`_test_arguments` and
    `_named_tests` in `exmergo_dex_core/dbt_project.py`). On 0.6.4's parser
    each arm read something else: nothing, or, where an input is written in
    both places, the one beside the test's name. The last two arms are the
    exception, and they are guards rather than red-first arms: a `test_name:`
    that is not a string, and an `arguments:` that is not a mapping, read the
    same before and after, and a fix that drops either check raises.

    The flat forms are the controls, and they are tests above: #117's for the
    composite key, and `TestATestListUnderEitherKey`'s column-level arm for a
    flat `relationships` and a bare `unique`, under both keys. So a red arm
    here is the form and not the probe.
    """

    def test_an_input_under_arguments_wins_over_the_same_input_beside_it(self):
        """dbt merges `arguments:` over the keys beside the test's name, so the
        columns under it are the grain the test checks. Reading the keys beside
        it first, or alone, reads a grain the test does not check."""

        text = (
            "models:\n"
            "  - name: fact_orders\n"
            "    data_tests:\n"
            "      - dbt_utils.unique_combination_of_columns:\n"
            "          combination_of_columns: [date, provider]\n"
            "          arguments:\n"
            "            combination_of_columns: [product_id, order_type]\n"
        )
        declarations = a_project(declaration_sources={"f": text}).declarations()
        assert declarations.declared_keys == (
            DeclaredKey(
                model="fact_orders", columns=("product_id", "order_type"), source="combination"
            ),
        )
        assert declarations.notes == ()

    @pytest.mark.parametrize(
        "test",
        [
            "          - relationships:\n"
            "              to: ref('dim_date')\n"
            "              field: date_key\n"
            "              arguments:\n"
            "                field: date\n",
            "          - name: date_is_a_dim_date\n"
            "            test_name: relationships\n"
            "            to: ref('dim_date')\n"
            "            field: date_key\n"
            "            arguments:\n"
            "              field: date\n",
        ],
        ids=["single-key", "test_name"],
    )
    def test_a_relationship_merges_its_inputs_from_both_places(self, test):
        """`to` beside the test's name and `field` under `arguments:`, over a
        second `field` beside it. This is the merge's other caller, so a
        caller that reads one place alone, or lets the wrong one win, goes red
        here even when the composite key's caller is right. Under `test_name:`
        the inputs beside the name sit in the entry itself, so a fix that
        takes the entry's `arguments:` for its payload reads no `to`."""

        declarations = a_project(
            declaration_sources={"f": a_date_column_testing("data_tests", test)}
        ).declarations()
        assert declarations.declared_joins == (DATE_JOIN,)
        assert declarations.notes == ()

    @pytest.mark.parametrize("key", ["tests", "data_tests"])
    def test_a_relationship_under_arguments_is_read(self, key):
        test = (
            "          - relationships:\n"
            "              arguments:\n"
            "                to: ref('dim_date')\n"
            "                field: date\n"
        )
        declarations = a_project(
            declaration_sources={"f": a_date_column_testing(key, test)}
        ).declarations()
        assert declarations.declared_joins == (DATE_JOIN,)
        assert declarations.notes == ()

    @pytest.mark.parametrize("nested", [False, True], ids=["beside", "arguments"])
    def test_a_composite_key_named_by_test_name_is_read(self, nested):
        """The `beside` arm pins the payload: the inputs sit in the entry
        itself, beside `test_name:`, so a fix that reads an `arguments:`
        mapping alone reads no columns there."""

        arguments = "        arguments:\n" if nested else ""
        pad = "  " if nested else ""
        text = (
            "models:\n"
            "  - name: fact_orders\n"
            "    data_tests:\n"
            "      - name: fact_orders_grain\n"
            "        test_name: dbt_utils.unique_combination_of_columns\n"
            f"{arguments}"
            f"{pad}        combination_of_columns: [date, provider]\n"
        )
        declarations = a_project(declaration_sources={"f": text}).declarations()
        assert declarations.declared_keys == (
            DeclaredKey(model="fact_orders", columns=("date", "provider"), source="combination"),
        )
        assert declarations.notes == ()

    def test_a_relationship_named_by_test_name_is_read(self):
        test = (
            "          - name: date_is_a_dim_date\n"
            "            test_name: relationships\n"
            "            arguments:\n"
            "              to: ref('dim_date')\n"
            "              field: date\n"
        )
        declarations = a_project(
            declaration_sources={"f": a_date_column_testing("data_tests", test)}
        ).declarations()
        assert declarations.declared_joins == (DATE_JOIN,)
        assert declarations.notes == ()

    @pytest.mark.parametrize(
        "test",
        [
            "          - name: date_is_unique\n"
            "            test_name: unique\n",
            "          - test_name: unique\n",
        ],
        ids=["beside-a-name", "its-only-key"],
    )
    def test_a_unique_named_by_test_name_is_read(self, test):
        """Its `name:` names the test, not what the test runs, so a fix that
        reads `name:` as the test reads `date_is_unique`, and no key. An entry
        whose only key is `test_name:` also fits the single-key rule, as a test
        called `test_name`, so `test_name:` is checked first, as dbt checks
        it."""

        declarations = a_project(
            declaration_sources={"f": a_date_column_testing("data_tests", test)}
        ).declarations()
        assert declarations.declared_keys == (
            DeclaredKey(model="fact_orders", columns=("date",), source="unique"),
        )
        assert declarations.notes == ()

    def test_a_test_name_that_is_not_a_string_names_no_test(self):
        """dbt refuses such an entry, so it reaches here only in a broken file,
        and the module's rule is that a broken file does not raise. The entry
        has more than one key, so it reads as nothing, as it does in dex-core's
        reader. A fix that takes `test_name:` whatever its type raises here.
        Since #131's (a) the skip is noted, as `TestATestEntryDbtRefuses`
        below says."""

        text = (
            "models:\n"
            "  - name: fact_orders\n"
            "    data_tests:\n"
            "      - name: fact_orders_grain\n"
            "        test_name: 5\n"
            "        arguments:\n"
            "          combination_of_columns: [date, provider]\n"
        )
        declarations = a_project(declaration_sources={"f": text}).declarations()
        assert declarations.declared_keys == ()
        assert declarations.notes == (
            REFUSED.format("'fact_orders'", "arguments, name, test_name"),
        )

    def test_an_arguments_that_is_not_a_mapping_is_ignored(self):
        """The inputs beside the test's name are read, as dex-core's reader
        reads them. A fix that merges `arguments:` without checking it is a
        mapping raises here."""

        text = (
            "models:\n"
            "  - name: fact_orders\n"
            "    data_tests:\n"
            "      - dbt_utils.unique_combination_of_columns:\n"
            "          combination_of_columns: [date, provider]\n"
            "          arguments: [date, provider]\n"
        )
        declarations = a_project(declaration_sources={"f": text}).declarations()
        assert declarations.declared_keys == (
            DeclaredKey(model="fact_orders", columns=("date", "provider"), source="combination"),
        )
        assert declarations.notes == ()


#: The three places dbt reads a test's inputs from, each a form the parser
#: reads since 0.6.5: beside the test's name, under `arguments:`, and beside a
#: `test_name:` that names the test.
FORMS = ["beside", "arguments", "test_name"]


def a_composite_listing(columns: str, form: str) -> str:
    """A model-level composite key on `fact_orders` whose
    `combination_of_columns` is ``columns``, a YAML flow list, written in
    ``form``, one of :data:`FORMS`."""

    if form == "test_name":
        return (
            "models:\n"
            "  - name: fact_orders\n"
            "    data_tests:\n"
            "      - name: fact_orders_grain\n"
            "        test_name: dbt_utils.unique_combination_of_columns\n"
            f"        combination_of_columns: {columns}\n"
        )
    arguments = "          arguments:\n" if form == "arguments" else ""
    pad = "  " if form == "arguments" else ""
    return (
        "models:\n"
        "  - name: fact_orders\n"
        "    data_tests:\n"
        "      - dbt_utils.unique_combination_of_columns:\n"
        f"{arguments}"
        f"{pad}          combination_of_columns: {columns}\n"
    )


#: The note a composite key listing something other than a column name gets,
#: whole.
NOT_A_NAME = (
    "'fact_orders' declares a composite grain listing something other than a "
    "column name; ignored"
)


class TestACompositeKeyListingSomethingOtherThanAName:
    """#131's (b), the mixed lists: a `combination_of_columns` holding a
    non-string, such as `[date, 1]` or `[date, provider, 1]`, was read as a key
    on its strings alone, on `date` or on `(date, provider)`. That is a key on
    fewer columns than the test checks, so it claims more than the test does.
    exmergo-dex-core's schema-YAML reader reads a composite only from a list of
    two or more columns that are all strings (`_declared_from_yaml` in
    `exmergo_dex_core/dbt_project.py`, read in 1.15.2), so it reads no key from
    either list, in any form. The owner ruled this aligned here, with a note.

    Each list is read in all three forms. The form beside the test's name read
    the same way in 0.6.4, and the other two are the forms 0.6.5 added, so all
    three go red. The lists of names are the controls, on the same builder:
    `[date, provider]` reads the composite, and `[date]` keeps its key on
    `date`, which the owner ruled kept here while exmergo/dex is asked. So a
    red arm is the non-string, not the probe or the form.
    """

    @pytest.mark.parametrize("form", FORMS)
    @pytest.mark.parametrize("columns", ["[date, 1]", "[date, provider, 1]"])
    def test_a_list_holding_a_non_string_reads_no_key_and_says_so(self, columns, form):
        declarations = a_project(
            declaration_sources={"f": a_composite_listing(columns, form)}
        ).declarations()
        assert declarations.declared_keys == ()
        assert declarations.notes == (NOT_A_NAME,)

    @pytest.mark.parametrize("form", FORMS)
    @pytest.mark.parametrize(
        "columns, key",
        [("[date, provider]", ("date", "provider")), ("[date]", ("date",))],
        ids=["two-names", "one-name"],
    )
    def test_a_list_of_names_reads_its_key(self, columns, key, form):
        declarations = a_project(
            declaration_sources={"f": a_composite_listing(columns, form)}
        ).declarations()
        assert declarations.declared_keys == (
            DeclaredKey(model="fact_orders", columns=key, source="combination"),
        )
        assert declarations.notes == ()

    def test_a_list_with_no_name_in_it_keeps_its_note(self):
        """A guard rather than a red-first arm: `[1]` holds a non-string too,
        and it read as no key before, with the note that it lists no usable
        column. A fix that checks for a non-string first rewords that note."""

        declarations = a_project(
            declaration_sources={"f": a_composite_listing("[1]", "arguments")}
        ).declarations()
        assert declarations.declared_keys == ()
        assert declarations.notes == (
            "'fact_orders' declares a composite grain with no usable columns; ignored",
        )


def a_relationship_to(target: str, form: str) -> str:
    """`fact_orders.date` tested as a `relationships` join to ``target``, on
    `date`, written in ``form``, one of :data:`FORMS`."""

    if form == "test_name":
        test = (
            "          - name: date_is_a_dim_date\n"
            "            test_name: relationships\n"
            f"            to: {target}\n"
            "            field: date\n"
        )
    else:
        arguments = "              arguments:\n" if form == "arguments" else ""
        pad = "  " if form == "arguments" else ""
        test = (
            "          - relationships:\n"
            f"{arguments}"
            f"{pad}              to: {target}\n"
            f"{pad}              field: date\n"
        )
    return a_date_column_testing("data_tests", test)


#: The note a relationship whose target is not read gets, whole.
UNRESOLVED = (
    "fact_orders.date declares a relationship that names no resolvable model "
    "and column; ignored"
)


class TestARelationshipToABareName:
    """#131's (c), the bare arm: a `relationships` test whose `to:` is a bare
    model name, `to: dim_date`, was read as a join to `dim_date`. dbt draws no
    edge to it: it keeps `to:` as the string and the test depends on its own
    model alone (#131, measured with dbt-core 1.12.6). exmergo-dex-core's
    schema-YAML reader takes `to:` only as a `ref()` or a `source()`
    (`_parse_relation_ref` in `exmergo_dex_core/dbt_project.py`, read in
    1.15.2), so it reads no join, and the owner ruled this aligned here. The
    join is now unread, with the note every other unread target gets.

    Each form goes red: the bare name beside the test's name was read the same
    way in 0.6.4, and the other two are the forms 0.6.5 added. `ref('dim_date')`
    in each form is the control, so a red arm is the bare name and not the
    form.
    """

    @pytest.mark.parametrize("form", FORMS)
    def test_a_bare_name_reads_no_join_and_says_so(self, form):
        declarations = a_project(
            declaration_sources={"f": a_relationship_to("dim_date", form)}
        ).declarations()
        assert declarations.declared_joins == ()
        assert declarations.notes == (UNRESOLVED,)

    @pytest.mark.parametrize("form", FORMS)
    def test_a_ref_reads_the_join(self, form):
        declarations = a_project(
            declaration_sources={"f": a_relationship_to("ref('dim_date')", form)}
        ).declarations()
        assert declarations.declared_joins == (DATE_JOIN,)
        assert declarations.notes == ()

    def test_a_semantic_model_still_reads_a_bare_model_name(self):
        """A guard rather than a red-first arm. A semantic model's `model:`
        goes through the helper the relationship's `to:` went through, and a
        bare name is read there. Aligning `to:` must not reach it, so a fix
        that drops the bare arm from the shared helper goes red here."""

        text = "semantic_models:\n  - name: revenue\n    model: mart_revenue\n"
        declarations = a_project(semantic_sources={"s": text}).declarations()
        assert [m.model for m in declarations.semantic_models] == ["mart_revenue"]


#: `fact_orders.date` -> `erp.calendar.date`: a relationship to
#: `source('erp', 'calendar')`, its target named as exmergo-dex-core's reader
#: names a source, the source and the table joined by a dot.
SOURCE_JOIN = DeclaredJoin(
    from_model="fact_orders",
    from_columns=("date",),
    to_model="erp.calendar",
    to_columns=("date",),
    source="relationships",
)


class TestARelationshipToASource:
    """#131's (c), the `source()` arm: a `relationships` test whose `to:` is
    `source('erp', 'calendar')` was read as no join, with the note that it
    names no resolvable model and column. exmergo-dex-core's schema-YAML
    reader reads it as a join to `erp.calendar` (`_parse_relation_ref` in
    `exmergo_dex_core/dbt_project.py`, read in 1.15.2): beside the test's name
    at every release #131 measured, and under `arguments:` from 1.13.1
    (exmergo/dex#566). dbt makes the test depend on that source. The owner
    ruled it aligned here, reading the join that reader reads, so the join's
    `to_model` names a source, not a model the project builds.

    Each form goes red, and `ref('dim_date')` in each form is the control in
    the class above. The spacing arm holds the pattern to that reader's, which
    takes either quote and spaces around each argument.
    """

    @pytest.mark.parametrize("form", FORMS)
    def test_a_source_reads_the_join_that_reader_reads(self, form):
        declarations = a_project(
            declaration_sources={"f": a_relationship_to("source('erp', 'calendar')", form)}
        ).declarations()
        assert declarations.declared_joins == (SOURCE_JOIN,)
        assert declarations.notes == ()

    def test_either_quote_and_spaces_are_read(self):
        declarations = a_project(
            declaration_sources={
                "f": a_relationship_to('source( "erp" , "calendar" )', "arguments")
            }
        ).declarations()
        assert declarations.declared_joins == (SOURCE_JOIN,)
        assert declarations.notes == ()


def two_composites(first: str, second: str, form: str = "beside") -> str:
    """`fact_orders` declaring two composite keys, ``first`` then ``second``,
    each a YAML flow list, both written in ``form``, one of :data:`FORMS`."""

    second_entry = a_composite_listing(second, form).split("    data_tests:\n", 1)[1]
    return a_composite_listing(first, form) + second_entry


def a_composite(*columns: str) -> DeclaredKey:
    return DeclaredKey(model="fact_orders", columns=columns, source="combination")


class TestTwoCompositeKeysOnOneModel:
    """#131's (e): a model declaring two composite keys, `[date, provider]`
    then `[product_id, order_type]`, was read as the first alone. dbt runs
    both tests, and exmergo-dex-core's schema-YAML reader reads both
    (`_declared_from_yaml` in `exmergo_dex_core/dbt_project.py`, read in
    1.15.2). `maintain reconcile` reads the grain through `definitions()`, so
    with the second unread it would propose a column-level `unique` on a
    column of that grain, a key the project never declared, which is the
    defect #117 fixed for the prefixed spelling. The owner ruled this aligned
    here.

    That reader keeps one composite per model and set of columns, compared
    without order or case, and keeps the first. The same key written twice
    therefore reads once, before and after this change, so those arms are
    guards: a fix that reads every composite without that rule goes red there.
    So is the arm whose first composite lists no column, which is skipped with
    its note while the second is read.
    """

    @pytest.mark.parametrize("form", FORMS)
    def test_both_composite_keys_are_read_in_order(self, form):
        text = two_composites("[date, provider]", "[product_id, order_type]", form)
        declarations = a_project(declaration_sources={"f": text}).declarations()
        assert declarations.declared_keys == (
            a_composite("date", "provider"),
            a_composite("product_id", "order_type"),
        )
        assert declarations.notes == ()

    @pytest.mark.parametrize(
        "second",
        ["[date, provider]", "[provider, date]", "[DATE, Provider]"],
        ids=["again", "reordered", "recased"],
    )
    def test_the_same_key_written_again_is_read_once(self, second):
        text = two_composites("[date, provider]", second)
        declarations = a_project(declaration_sources={"f": text}).declarations()
        assert declarations.declared_keys == (a_composite("date", "provider"),)
        assert declarations.notes == ()

    def test_a_composite_listing_no_column_is_skipped_and_the_next_is_read(self):
        text = two_composites("[]", "[product_id, order_type]")
        declarations = a_project(declaration_sources={"f": text}).declarations()
        assert declarations.declared_keys == (a_composite("product_id", "order_type"),)
        assert declarations.notes == (NO_COLUMNS,)

    def test_both_composite_keys_beat_a_single_column_one_and_say_so(self):
        """The composite still wins over a column-level `unique` (#131's (g),
        not ruled), and with two composites it is both that win."""

        text = two_composites("[date, provider]", "[product_id, order_type]") + (
            "    columns:\n"
            "      - name: order_id\n"
            "        data_tests:\n"
            "          - unique\n"
        )
        declarations = a_project(declaration_sources={"f": text}).declarations()
        assert declarations.declared_keys == (
            a_composite("date", "provider"),
            a_composite("product_id", "order_type"),
        )
        assert declarations.notes == (
            "'fact_orders' declares a composite grain and also a column-level "
            "unique on order_id; the composite wins",
        )


#: The key every arm below declares on `fact_orders.date`.
DATE_KEY = DeclaredKey(model="fact_orders", columns=("date",), source="unique")


class TestUniqueWrittenTwiceOnOneColumn:
    """#131's (f): a column's `unique` written twice was read as two keys on
    that column. Written bare twice, 0.6.4 read it so too, on a file dbt
    refuses; written once bare and once by `test_name:`, or twice by
    `test_name:`, it is reachable since 0.6.5, and dbt runs both tests.
    exmergo-dex-core's schema-YAML reader reads one key per model and column
    (`_declared_from_yaml` in `exmergo_dex_core/dbt_project.py`, read in
    1.15.2), and #115 already reads `unique` under both `tests:` and
    `data_tests:` once. The owner ruled this aligned here: it is one claim.

    The column listed twice, each with its `unique`, is the same claim and
    reads once in that reader too. `unique` on two columns is the control, so
    a fix that keeps one key per model goes red there.
    """

    @pytest.mark.parametrize(
        "test",
        [
            "          - unique\n"
            "          - unique\n",
            "          - unique\n"
            "          - name: date_is_unique\n"
            "            test_name: unique\n",
            "          - name: date_is_unique\n"
            "            test_name: unique\n"
            "          - name: date_is_still_unique\n"
            "            test_name: unique\n",
        ],
        ids=["bare-twice", "bare-then-test_name", "test_name-twice"],
    )
    def test_unique_written_twice_reads_one_key(self, test):
        declarations = a_project(
            declaration_sources={"f": a_date_column_testing("data_tests", test)}
        ).declarations()
        assert declarations.declared_keys == (DATE_KEY,)
        assert declarations.notes == ()

    def test_a_column_listed_twice_with_unique_reads_one_key(self):
        text = (
            "models:\n"
            "  - name: fact_orders\n"
            "    columns:\n"
            "      - name: date\n"
            "        data_tests: [unique]\n"
            "      - name: date\n"
            "        data_tests: [unique]\n"
        )
        declarations = a_project(declaration_sources={"f": text}).declarations()
        assert declarations.declared_keys == (DATE_KEY,)
        assert declarations.notes == ()

    def test_unique_on_two_columns_reads_two_keys(self):
        text = (
            "models:\n"
            "  - name: fact_orders\n"
            "    columns:\n"
            "      - name: date\n"
            "        data_tests: [unique]\n"
            "      - name: order_id\n"
            "        data_tests: [unique]\n"
        )
        declarations = a_project(declaration_sources={"f": text}).declarations()
        assert declarations.declared_keys == (
            DATE_KEY,
            DeclaredKey(model="fact_orders", columns=("order_id",), source="unique"),
        )
        assert declarations.notes == ()


def a_unique_on(column: str) -> str:
    """`fact_orders` declaring a column-level `unique` on ``column``."""

    return (
        "models:\n"
        "  - name: fact_orders\n"
        "    columns:\n"
        f"      - name: {column}\n"
        "        data_tests: [unique]\n"
    )


def a_composite_on(columns: str) -> str:
    """`fact_orders` declaring one composite key, ``columns`` a YAML flow list."""

    return (
        "models:\n"
        "  - name: fact_orders\n"
        "    data_tests:\n"
        "      - dbt_utils.unique_combination_of_columns:\n"
        f"          combination_of_columns: {columns}\n"
    )


class TestAKeyDeclaredInTwoEntries:
    """#131's (e) and (f) across entries: a model's declarations may be split
    over several files, and `scripts/drive_dex_against_the_wheel.py` declares
    `fact_orders` in two. exmergo-dex-core's schema-YAML reader keeps one key
    per model and column, and one composite per model and set of columns,
    across every file it reads: its two maps are built outside its loop over
    files (`_declared_from_yaml` in `exmergo_dex_core/dbt_project.py`, read in
    1.15.2). #131 words (f)'s alignment as one key per model and columns. So a
    key written again in another file, or in a second entry for the model in
    the same file, reads once here too, where it read once per entry (cold
    review of #138, finding 1).

    Keys that differ are the control: both are read, across files as in one.
    """

    @pytest.mark.parametrize(
        "sources",
        [
            {"a": a_unique_on("date"), "b": a_unique_on("date")},
            {"a": a_unique_on("date") + a_unique_on("date").split("models:\n", 1)[1]},
        ],
        ids=["two-files", "two-entries-one-file"],
    )
    def test_a_unique_declared_again_reads_one_key(self, sources):
        declarations = a_project(declaration_sources=sources).declarations()
        assert declarations.declared_keys == (DATE_KEY,)
        assert declarations.notes == ()

    @pytest.mark.parametrize("second", ["[date, provider]", "[Provider, DATE]"], ids=["again", "reordered-recased"])
    def test_a_composite_declared_again_in_another_file_reads_once(self, second):
        sources = {"a": a_composite_on("[date, provider]"), "b": a_composite_on(second)}
        declarations = a_project(declaration_sources=sources).declarations()
        assert declarations.declared_keys == (a_composite("date", "provider"),)
        assert declarations.notes == ()

    def test_different_keys_in_two_files_are_both_read(self):
        sources = {
            "a": a_unique_on("date"),
            "b": a_unique_on("order_id"),
            "c": a_composite_on("[product_id, order_type]"),
        }
        declarations = a_project(declaration_sources=sources).declarations()
        assert declarations.declared_keys == (
            DATE_KEY,
            DeclaredKey(model="fact_orders", columns=("order_id",), source="unique"),
            a_composite("product_id", "order_type"),
        )
        assert declarations.notes == ()


class TestATestEntryDbtRefuses:
    """#131's (a): a test written as a mapping of more than one key with no
    string `test_name:` naming it was skipped with no note. The common shape
    is a test's `config:` written beside its name rather than inside it. dbt
    refuses the project over such an entry: "test definition dictionary must
    have exactly one key", or, for a `test_name:` that is not a string, "test
    name must be a str" (#131, read from dbt-core 1.12.6). exmergo-dex-core's
    schema-YAML reader reads the test among the keys, on purpose
    (exmergo/dex#566 keeps it lenient about entries dbt itself refuses). The
    owner ruled the skip kept here, with a note, while exmergo/dex is asked.
    The note is what the module's first rule asks of input it skips.

    Each arm read nothing before and reads nothing after; the note is what is
    red. The test in the class above whose `test_name:` is not a string is a
    fifth arm. The controls are the classes above: an entry of one key, and
    one named by a string `test_name:`, each asserted to carry no note.
    """

    @pytest.mark.parametrize(
        "text, where, keys",
        [
            (
                "models:\n"
                "  - name: fact_orders\n"
                "    data_tests:\n"
                "      - dbt_utils.unique_combination_of_columns:\n"
                "          combination_of_columns: [date, provider]\n"
                "        config:\n"
                "          severity: warn\n",
                "'fact_orders'",
                "config, dbt_utils.unique_combination_of_columns",
            ),
            (
                a_date_column_testing(
                    "data_tests",
                    "          - unique:\n"
                    "            config:\n"
                    "              where: \"date > '2026-01-01'\"\n",
                ),
                "fact_orders.date",
                "config, unique",
            ),
            (
                a_date_column_testing(
                    "data_tests",
                    "          - relationships:\n"
                    "              to: ref('dim_date')\n"
                    "              field: date\n"
                    "            config:\n"
                    "              severity: warn\n",
                ),
                "fact_orders.date",
                "config, relationships",
            ),
            (
                "models:\n"
                "  - name: fact_orders\n"
                "    data_tests:\n"
                "      - name: fact_orders_grain\n"
                "        test_name: 5\n"
                "        dbt_utils.unique_combination_of_columns:\n"
                "          combination_of_columns: [date, provider]\n",
                "'fact_orders'",
                "dbt_utils.unique_combination_of_columns, name, test_name",
            ),
        ],
        ids=["composite-and-config", "unique-and-config", "relationship-and-config", "test_name-5"],
    )
    def test_the_entry_is_skipped_and_says_so(self, text, where, keys):
        declarations = a_project(declaration_sources={"f": text}).declarations()
        assert declarations.declared_keys == ()
        assert declarations.declared_joins == ()
        assert declarations.notes == (REFUSED.format(where, keys),)

    def test_the_entry_under_both_keys_is_noted_once(self):
        """The union reads an identical entry under `tests:` and `data_tests:`
        once, so its note is said once too (cold review of #138, finding 6)."""

        entry = (
            "          - unique:\n"
            "            config:\n"
            "              severity: warn\n"
        )
        text = (
            "models:\n"
            "  - name: fact_orders\n"
            "    columns:\n"
            "      - name: date\n"
            f"        tests:\n{entry}"
            f"        data_tests:\n{entry}"
        )
        declarations = a_project(declaration_sources={"f": text}).declarations()
        assert declarations.declared_keys == ()
        assert declarations.notes == (
            BOTH_KEYS.format("fact_orders.date"),
            REFUSED.format("fact_orders.date", "config, unique"),
        )

    def test_an_empty_mapping_is_skipped_quietly(self):
        """A guard rather than a red-first arm: the ruling covers entries of two
        or more keys, and `{}` read as nothing, with no note, before and after
        (cold review of #138, finding 7). A fix that notes every mapping it
        cannot name goes red here."""

        declarations = a_project(
            declaration_sources={"f": a_date_column_testing("data_tests", "          - {}\n")}
        ).declarations()
        assert declarations.declared_keys == ()
        assert declarations.notes == ()


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
