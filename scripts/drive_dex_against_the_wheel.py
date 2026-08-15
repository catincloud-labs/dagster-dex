# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""Drive dex against the BUILT WHEEL, the way a host actually reaches this format.

Everything else in this repository exercises the working directory. The wheel
check beside this one installs the built artifact and proves it imports,
declares its entry point and ships `py.typed` - which is packaging, not
behaviour. Nothing anywhere proved that dex can *read a project* through the
distribution this project publishes.

That gap had a name before it had a test. This package's own recorded lesson is
that a declared-but-unresolved extension point is not evidence that registration
works; it was inert from 0.1.0 until dex-core 1.6.0 began resolving the group,
and there was no moment at which it could have failed. "The wheel installs and
the entry point is present" is a claim of exactly that shape, one level up.

WHAT THIS RUNS, AND WHY EACH LEG IS HERE

  1. `artifact.dumps` writes a project, from the wheel.
  2. `resolve_project_factory("dagster")` finds the factory through dex-core's
     own entry-point scan - not through an import of ours.
  3. `construct_project` builds it from a `ProjectContext` carrying the
     `artifact:` option, which is the deployment shape a host uses: the side
     with the graph reduces once and writes it down, the side answering
     requests reads that back.
  4. `definitions()`, `transform_layer()` and `semantic_layer()` are read, and
     their CONTENT is asserted - the models, a declared key, a declared join and
     a semantic model all have to survive the whole round trip.

Leg 4 is the one that makes this more than a smoke test. A format that resolved,
built, and returned empty layers would satisfy legs 1 to 3 completely, and an
empty transform layer compared against a warehouse reports no drift rather than
reporting that it could not look.

DELIBERATELY NO WAREHOUSE, AND NO ORCHESTRATOR

Neither is needed to answer the question this file asks, and requiring either
would make it unrunnable by a stranger from a clean checkout - which is the
property that made the old hand-counted end-to-end result unverifiable and got
it removed from the README. Nothing here reaches the network or a credential.

Run it by hand against an installed wheel:

    uv run --no-project --with "./dist/<wheel>" \\
        --with exmergo-dex-core==1.6.5 --with sqlglot==30.13.0 \\
        python scripts/drive_dex_against_the_wheel.py

Exit 0 means dex read a project through the distribution. Anything else prints
which leg failed.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

FAILURES: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if not condition:
        FAILURES.append(f"{label}{': ' + detail if detail else ''}")


def main() -> int:
    # Imported here rather than at module scope so an install failure reports as
    # a missing distribution rather than as a traceback in a helper.
    from dagster_dex import ProjectModel
    from dagster_dex.artifact import dumps

    from exmergo_dex_core.adapters.project import (
        MaintainProject,
        ProjectContext,
        tier_of,
    )
    from exmergo_dex_core.adapters.project_resolver import (
        construct_project,
        resolve_project_factory,
    )

    import dagster_dex

    print(f"dagster_dex     : {dagster_dex.__version__} from {dagster_dex.__file__}")

    # -- leg 1: write a project, from the wheel ------------------------------
    models = [
        ProjectModel(name="dim_date", layer="silver"),
        ProjectModel(name="fact_orders", depends_on=("dim_date",), layer="gold"),
    ]
    declarations = {
        "keys.yml": (
            "models:\n"
            "  - name: fact_orders\n"
            "    columns:\n"
            "      - name: order_id\n"
            "        tests:\n"
            "          - unique\n"
        ),
        "joins.yml": (
            "models:\n"
            "  - name: fact_orders\n"
            "    columns:\n"
            "      - name: date\n"
            "        tests:\n"
            "          - relationships:\n"
            "              to: ref('dim_date')\n"
            "              field: date\n"
        ),
    }
    semantics = {
        "sem.yml": (
            "semantic_models:\n"
            "  - name: fact_orders\n"
            "    model: ref('fact_orders')\n"
            "    dimensions:\n"
            "      - name: date\n"
            "        type: time\n"
            "        expr: date\n"
            "    measures:\n"
            "      - name: order_total\n"
            "        agg: sum\n"
            "        expr: order_total\n"
        )
    }

    text = dumps(
        name="demo_project",
        models=models,
        generated_at="2026-01-01T00:00:00Z",
        declaration_sources=declarations,
        semantic_sources=semantics,
    )
    document = json.loads(text)
    check(
        "leg 1: dumps wrote a schema-versioned document",
        document.get("schema_version") is not None,
        f"got {document!r}",
    )
    print("leg 1 ok        : artifact written by the wheel")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "project").mkdir()
        (root / "project" / "demo.json").write_text(text, encoding="utf-8")

        # -- leg 2: THEIR scan, not our import ------------------------------
        factory = resolve_project_factory("dagster")
        check(
            "leg 2: dex-core resolved the 'dagster' format from installed metadata",
            callable(factory),
            f"got {factory!r}",
        )
        print(f"leg 2 ok        : resolved to {getattr(factory, '__name__', factory)}")

        # -- leg 3: build it the way a host does ----------------------------
        # A RELATIVE artifact path against repo_root, which is the form a real
        # `.dex/config.yml` carries: the writer and the reader mount the shared
        # volume at different absolute paths, so the config cannot name one.
        context = ProjectContext(
            repo_root=str(root),
            project_dir=None,
            options={"artifact": "project/demo.json"},
        )
        project = construct_project("dagster", factory, context)

        check("leg 3: the built project reaches tier 2", tier_of(project) == 2,
              f"tier_of said {tier_of(project)}")
        check("leg 3: the built project satisfies MaintainProject",
              isinstance(project, MaintainProject))
        check("leg 3: the seam sees the FORMAT name", project.name == "dagster",
              f"name was {project.name!r}")
        print(f"leg 3 ok        : tier {tier_of(project)} project built from the artifact")

        # -- leg 4: the content survived the round trip ---------------------
        #
        # Attributes are read DIRECTLY, never through `getattr(x, name, None)`.
        # The first draft of this file used the defaulting form and asserted
        # `declared_keys` on the transform layer, where no such field exists -
        # so a nonexistent attribute and an empty one produced the same `None`
        # and the failure read as lost data rather than as a wrong test. Direct
        # access raises `AttributeError` and names the attribute, which is the
        # difference between finding out and guessing.
        #
        # The split below is the seam's design rather than an accident of
        # layout: DECLARED CONTENT crosses on tier 1 (`definitions()`), and the
        # model and file STRUCTURE crosses on tier 2 (`transform_layer()`).
        definitions = project.definitions()
        check("leg 4: definitions() reports the project present", definitions.present is True)
        check(
            "leg 4: the declared key survived the artifact round trip",
            bool(definitions.declared_keys),
            f"declared_keys was {definitions.declared_keys!r}",
        )
        check(
            "leg 4: the declared join survived the artifact round trip",
            bool(definitions.foreign_keys),
            f"foreign_keys was {definitions.foreign_keys!r}",
        )
        check(
            "leg 4: the declarations are sourced as declarations, not guessed",
            definitions.relationship_source == "declaration",
            f"relationship_source was {definitions.relationship_source!r}",
        )

        transform = project.transform_layer()
        check(
            "leg 4: both models crossed on the tier-2 channel",
            sorted(transform.models) == ["dim_date", "fact_orders"],
            f"transform_layer().models was {transform.models!r}",
        )
        # `notes` is the disclosure channel and it is load-bearing: an empty
        # `files` compared against an empty `files` reads as "no file drift"
        # rather than "this cannot be checked here". A reduction that disclosed
        # nothing would be the lossy-and-silent case this format refuses.
        check(
            "leg 4: the layer discloses what it could not carry",
            bool(transform.notes),
            "transform_layer().notes was empty, so a lossy mapping went undisclosed",
        )

        semantic = project.semantic_layer()
        check(
            "leg 4: the semantic model survived",
            bool(semantic.semantic_models),
            f"semantic_models was {semantic.semantic_models!r}",
        )
        print("leg 4 ok        : key, join, models, notes and semantic model all read back")

    if FAILURES:
        print("", file=sys.stderr)
        print("FAIL - dex could not read a project through this wheel:", file=sys.stderr)
        for failure in FAILURES:
            print(f"  {failure}", file=sys.stderr)
        return 1

    print("")
    print("OK - dex read a project through the built distribution, end to end.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
