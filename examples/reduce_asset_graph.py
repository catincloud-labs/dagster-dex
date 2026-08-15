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

The negative checks at the end are the valuable half. A reduction that accepted
a duplicate asset key, or that quietly grew a tier it does not implement, would
pass every positive assertion above them.
"""

from __future__ import annotations

import dagster as dg

from dagster_dex import DagsterProject, EditableProject, tier_of


@dg.asset(metadata={"layer": "silver"})
def dim_date() -> None:
    """A dimension. The `layer` metadata is what the reduction reads."""


@dg.asset(deps=[dim_date], metadata={"layer": "GOLD"})
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


def main() -> None:
    project = DagsterProject.from_asset_graph([dim_date, fact_sales], name="demo")
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

    print()
    print("OK - the reduction works against real Dagster objects.")


if __name__ == "__main__":
    main()
