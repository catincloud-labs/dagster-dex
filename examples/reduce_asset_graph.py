# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""Reduce a real Dagster asset graph, and show what the format makes of it.

Run it:

    uv run --no-project --with-editable . --with 'dagster>=1.13' \\
        python examples/reduce_asset_graph.py

This is the only file here that touches the orchestrator. Every test in this
repository uses fakes, deliberately - the suite has to run without Dagster
installed, which is what keeps the reduction honest about reading definitions
STRUCTURALLY rather than importing them. The cost of that choice is that nothing
in the suite would notice `from_asset_graph` breaking against the objects
Dagster actually hands it. This file is that check.

**It is also the CI step**, not a companion to one. The workflow used to carry
these assertions as a `python -c` blob inside YAML, which meant the one runnable
demonstration of the package was in the one place a reader never looks and could
not run. An example nobody executes rots; a CI step nobody can read teaches
nothing. Being both is the fix.

Two constraints follow from that, and they are constraints rather than
preferences:

- **No pytest.** The CI step that installs Dagster does not install pytest, and
  no step installs both. So the checks below are plain `assert` plus a nonzero
  exit, and they must stay that way unless a workflow gains a step.
- **Not shipped in the sdist.** `examples/` is outside
  `[tool.setuptools.packages.find]`, so a reader who only has the wheel cannot
  see this. The project URLs point at the repository, which is where it lives.

The negative checks are the valuable half. A reduction that accepted
a duplicate asset key, or that quietly grew a tier it does not implement, would
pass every positive assertion above them.

**The declared keys are rendered as check specs here too** (#180), because this
is the step with Dagster installed. `tests/test_checks.py` hands the spec layer
a stand-in for `AssetCheckSpec`; this hands it the real one, loads the specs
into `Definitions`, and reads back where Dagster attached them. `fact_sales`
sits under a prefix for that reason: the reduction names it by its last
segment, and its check has to land on the whole key.
"""

from __future__ import annotations

import dagster as dg
from dagster._core.definitions.metadata import TableMetadataSet

from dagster_dex import DagsterProject, EditableProject, tier_of
from dagster_dex.checks import CLAIM_ID, declaration_check_specs

#: One single-column key, one composite written out of order, and one join,
#: which gets no check and is named in a note instead.
DECLARATIONS = {
    "declarations/fact_sales.yml": """version: 2
models:
  - name: fact_sales
    columns:
      - name: sale_id
        data_tests: [unique]
      - name: date_key
        data_tests:
          - relationships:
              arguments:
                to: ref('dim_date')
                field: date_key
""",
    "declarations/dim_date.yml": """version: 2
models:
  - name: dim_date
    data_tests:
      - dbt_utils.unique_combination_of_columns:
          arguments:
            combination_of_columns: [date_key, calendar]
""",
}


@dg.asset(metadata={"layer": "silver"})
def dim_date() -> None:
    """A dimension. The `layer` metadata is what the reduction reads."""


@dg.asset(key_prefix=["mart"], deps=[dim_date], metadata={"layer": "GOLD"})
def fact_sales() -> None:
    """A fact depending on the dimension.

    `GOLD` is upper case on purpose: layer names are folded, so a graph that
    spells its tiers inconsistently still fingerprints into one layer rather
    than two that differ only in case.
    """


@dg.asset(name="dim_date")
def duplicate_dim_date() -> None:
    """A second asset claiming a name the graph already uses.

    Not part of the project below. It exists for the refusal check at the end.
    """


class NotDagsters:
    """An object holding text on `.value` that is not Dagster's. Dagster stores
    it as metadata and unwraps only its own value objects, so it names no table."""

    value = "Analytics.Held"


#: Metadata an asset can carry, one case per entry, chosen so each step of the
#: rule is reached: the newer key, the older one alone, both, a value object
#: wrapping text and one wrapping something else, an object that only looks
#: like one, empty text, and no key.
TABLE_NAME_CASES = {
    "text": {"dagster/table_name": "analytics.dim_date"},
    "mixed case": {"dagster/table_name": "Analytics.Dim_Date"},
    "a text value": {"dagster/table_name": dg.MetadataValue.text("Analytics.Dim_Date")},
    "a path value": {"dagster/table_name": dg.MetadataValue.path("analytics.dim_date")},
    "the older key": {"dagster/relation_identifier": "analytics.dim_date"},
    "both keys": {
        "dagster/table_name": "analytics.new",
        "dagster/relation_identifier": "analytics.old",
    },
    "newer key empty": {
        "dagster/table_name": None,
        "dagster/relation_identifier": "analytics.old",
    },
    "empty text": {"dagster/table_name": ""},
    "a number": {"dagster/table_name": 7},
    "an int value": {"dagster/table_name": dg.MetadataValue.int(7)},
    "a json value": {"dagster/table_name": dg.MetadataValue.json({"table": "dim_date"})},
    "a null value": {"dagster/table_name": dg.MetadataValue.null()},
    "an object outside dagster": {"dagster/table_name": NotDagsters()},
    "no table key": {"layer": "gold"},
}


def check_the_relation_matches_dagster() -> None:
    """Each case as a real asset, read both ways from what Dagster hands over.

    **The relation is held equal to Dagster's own rule here** (#179). The
    reduction reads an asset's table out of its metadata by key, because
    nothing in the package imports the orchestrator, so the rule it follows is
    a copy of `TableMetadataSet.extract_normalized_table_name`. A copy can
    drift from the original, and this is the one place both run on the same
    objects. That class is not exported from `dagster` itself, so it is
    imported from the module that defines it: if Dagster moves it, this file
    fails to import, which is the comparison going red rather than going away.
    """

    placed = 0
    for label, metadata in TABLE_NAME_CASES.items():

        @dg.asset(name="table_case", metadata=metadata)
        def table_case() -> None: ...

        (key,) = table_case.keys
        theirs = TableMetadataSet.extract_normalized_table_name(table_case.metadata_by_key[key])
        ours = DagsterProject.from_asset_graph([table_case]).declarations().models[0].relation
        assert ours == theirs, f"{label}: the reduction read {ours!r}, Dagster reads {theirs!r}"
        placed += theirs is not None

    # Both arms reached, or the loop above could agree on `None` throughout.
    assert 0 < placed < len(TABLE_NAME_CASES), placed
    print(f"relation          : equal to Dagster's rule on {len(TABLE_NAME_CASES)} cases")


def main() -> None:
    project = DagsterProject.from_asset_graph(
        [dim_date, fact_sales], name="demo", declaration_sources=DECLARATIONS
    )
    declarations = project.declarations()
    models = {model.name: model for model in declarations.models}

    print(f"dagster           : {dg.__version__}")
    print(f"format            : {project.format}")
    print(f"models            : {sorted(models)}")
    print(f"tier              : {tier_of(project)}")
    print(f"freshness         : {declarations.freshness.value}")

    fingerprint = project.fingerprint()
    print(f"fingerprint layers: {sorted(fingerprint.layers)}")

    # -- what the reduction found -------------------------------------------
    assert set(models) == {"dim_date", "fact_sales"}, sorted(models)
    assert models["fact_sales"].depends_on == ("dim_date",)

    # Folded, so `GOLD` and `gold` are one layer rather than two.
    assert models["fact_sales"].layer == "gold", "metadata case was not folded"
    assert models["dim_date"].layer == "silver"

    # Neither asset names its table, so neither gets one: no guess from the name.
    assert {m.relation for m in models.values()} == {None}
    check_the_relation_matches_dagster()

    # -- what it declines ---------------------------------------------------
    #
    # Tier 2, and tier 3 declined by NOT HAVING the method rather than by a
    # flag, so a caller finds out by asking rather than by receiving an empty
    # result that looks like success.
    assert tier_of(project) == 2, tier_of(project)
    assert not isinstance(project, EditableProject), "tier 3 must stay declined"

    # -- what it refuses ----------------------------------------------------
    #
    # Two assets cannot claim one name. Silently keeping the last would produce
    # a project that looks complete and has quietly lost a model, which is worse
    # than failing to build one.
    try:
        DagsterProject.from_asset_graph([dim_date, duplicate_dim_date], name="demo")
    except ValueError as refusal:
        print(f"duplicate refused : {refusal}")
    else:
        raise AssertionError("a duplicate asset key was not refused")

    render_the_declared_keys(project)

    print()
    print("OK - the reduction works against real Dagster objects.")


def render_the_declared_keys(project: DagsterProject) -> None:
    """The declared keys as check specs, loaded by Dagster itself."""

    asset_keys = [key for asset in (dim_date, fact_sales) for key in asset.keys]
    rendered = declaration_check_specs(project.declarations(), asset_keys)
    for spec in rendered.specs:
        print(f"key check         : {spec.asset_key.to_user_string()} {spec.name}")
    for note in rendered.notes:
        print(f"check note        : {note}")

    # One spec per declared key, on the WHOLE asset key. The composite's name
    # carries both columns, sorted, so reordering them renames nothing.
    checks = {(spec.asset_key.to_user_string(), spec.name) for spec in rendered.specs}
    assert checks == {
        ("mart/fact_sales", "declared_key__sale_id"),
        ("dim_date", "declared_key__calendar__date_key"),
    }, checks
    assert all(len(spec.metadata[CLAIM_ID]) == 64 for spec in rendered.specs)

    # The join gets no spec, and the note names it.
    (note,) = rendered.notes
    assert "fact_sales(date_key) -> dim_date(date_key)" in note, note

    # Dagster loads them: names it accepts, on assets these definitions hold.
    # The check body never runs here; running it is the executor's job. No
    # return annotation: Dagster reads one as the shape of the check's outputs.
    @dg.multi_asset_check(specs=list(rendered.specs))
    def declared_keys():
        raise NotImplementedError("rendered to be loaded, not run")

    definitions = dg.Definitions(assets=[dim_date, fact_sales], asset_checks=[declared_keys])
    dg.Definitions.validate_loadable(definitions)
    loaded = definitions.resolve_asset_graph().asset_check_keys
    assert loaded == {spec.key for spec in rendered.specs}, loaded


if __name__ == "__main__":
    main()
