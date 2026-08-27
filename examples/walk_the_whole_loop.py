# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""The whole loop, against a real warehouse, with no cloud account.

Run it:

    uv run --no-project --with-editable . --with 'dagster>=1.13' \\
        --with exmergo-dex-core==1.8.0 --with sqlglot==30.13.0 --with duckdb \\
        python examples/walk_the_whole_loop.py

`reduce_asset_graph.py` beside this one runs real Dagster and stops at the
reduction. The two drivers under `scripts/` reach the write tier, but they build
the asset graph out of fakes and hand reconcile a FABRICATED drift finding,
because their job is to exercise the boundary rather than to find anything.

So nothing in this repository put a real graph in front of a real warehouse and
let dex discover drift by itself. That is what this does, and it is the only
file here that runs the engine end to end.

WHY DUCKDB, AND WHY THAT IS NOT A COMPROMISE

dex-core's DuckDB adapter is a first-class product connector and the only free
one: the paradigm is `free_local`, so nothing here bills, needs a credential, or
reaches the network. A reader with a clean checkout can run this and get the
same answer, which is the property that makes it worth publishing at all.

WHAT EACH LEG IS FOR

  1. `explore inventory` - the warehouse is reachable and free.
  2. `maintain snapshot` BEFORE mapping. It reports `grain_baseline_count: 0`
     and says so. This leg exists because the instrument declaring itself blind
     is the behaviour worth demonstrating; a baseline taken here would make
     leg 5 find nothing and look clean doing it.
  3. `explore map` then snapshot again - the baseline now has a grain.
  4. Break one table for real: one duplicate row in `dim_date`.
  5. `maintain grain` - a real `key_lost_uniqueness`. THE LEG THAT MATTERS:
     its `impacted_models` names `fact_sales`, and nothing in the warehouse
     said so. That came through the Dagster asset graph.
  6. `maintain reconcile` - BOTH branches in one call. `dim_date.date_key` is
     declared `not_null` only, so the gap is real and an edit is proposed;
     `fact_sales.sale_id` is already declared `unique`, so there is nothing
     mechanical to add and it stays advisory. Without the second half, "an edit
     was produced" and "an edit is always produced" look identical.
  7. `transform apply` - the file changes.
  8. Re-read: the project DECLARES the key now. The write alone proves nothing;
     a format can accept an edit, write it, and mean what it did before.
  9. THE PLAN TRAVELS. Copy the project to a path this process never planned
     against, carry ONLY the stored plan JSON, and apply it there.
 10. And it refuses: re-applying over the edit it already made is a conflict.
 11. `maintain schema` after the declared SOURCE table is dropped. Two findings
     come back and the pair is the point: `table_dropped` is the warehouse
     noticing, `dangling_source` is the PROJECT noticing. Only the second needs
     a source declaration to have been read, and it names the file that made
     the claim.
 12. `maintain semantic` after a measure is redefined. `definition_changed` is
     drift that no amount of warehouse inspection finds, because nothing in the
     warehouse changed.
 13. `maintain grain` against DECLARED COMPOSITE grains, both directions in one
     run. dex-core 1.8.0's own writeup names the blind spot this closes: the
     grain axis never verified a grain the project DECLARES (`candidate_keys`
     is measurement-only), so `declared_grain_not_unique` needs no baseline -
     the combination comes from the project, and a failure means the
     declaration is false rather than that anything changed. One composite the
     data violates FIRES; one the data satisfies is SILENT in the same call.
     Without the silent half, "a declared grain was checked" and "a finding is
     always emitted" look identical.
 14. `explore relationships --infer-by-overlap` - a join proposed from measured
     value containment where NO NAME connects the columns, and the exclusion
     that keeps it honest: a column that is only a composite-grain member,
     fully contained in the same parent, is NOT proposed, because probing one
     member of a composite measures a different relationship than the whole
     key would.
 15. `transform apply` against a TAMPERED stored plan - an edit whose path was
     rewritten to leave the surface the format declares. The plan store trusts
     the file it loads (the id is a filename, not a verified digest), so this
     is exactly the input dex-core 1.7.0's apply-time containment re-check
     exists for: a hard refusal naming the surface, with `--confirm` on the
     command line and not a way past it. The quiet arm is leg 7, where the
     same apply path wrote a contained edit cleanly.

WHAT THIS COVERS OF THE ONE-LINE CLAIM

The README says a Dagster graph is read for "keys, joins, sources, semantics,
drift". All five are exercised here against a real warehouse:

  keys      leg 6 to 8 - `declared_keys` moves across the apply
            leg 13 - a declared COMPOSITE grain is verified, not just carried
  joins     the `relationships:` in the fact declaration, read as a foreign key
            leg 14 - and one proposed from measured overlap, no name involved
  sources   leg 3 and 11 - into the baseline, then a dangling one, with provenance
  semantics leg 3 and 12 - into the baseline, then a definition that moved
  drift     leg 5, 11, 12, 13 - grain (measured and declared), schema, semantic

This section replaced one headed NOT COVERED HERE, DELIBERATELY, which named
sources and semantics as the two surfaces this file did not reach. It was true
when it was written and stopped being true in the change that added legs 11 and
12. A docstring is read as an instruction, so leaving it would have been worse
than never having written it.

CONSTRAINTS, INHERITED FROM `reduce_asset_graph.py`

  - **No pytest.** The CI step that installs Dagster installs no test runner, so
    these are plain asserts and a nonzero exit.
  - **Not shipped in the sdist.** `examples/` is outside
    `[tool.setuptools.packages.find]`.
  - Each dex command runs as its OWN PROCESS, through
    `python -m exmergo_dex_core`. That is how dex is built to be used - the
    subcommands are stateless and `.dex/` on disk is what carries state between
    them - and it avoids depending on a console script being on PATH.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

FAILURES: list[str] = []

#: Written into the temp project. A real Dagster graph, resolved by dotted path
#: the way a real `.dex/config.yml` names one - so the objects dex reduces are
#: built by the orchestrator in the process that reads them, not by this one.
ASSETS_MODULE = '''\
"""The asset graph the warehouse below stands for."""

import dagster as dg


@dg.asset(metadata={"layer": "silver"})
def dim_date() -> None:
    """The calendar spine. Its grain is a single column."""


@dg.asset(deps=[dim_date], metadata={"layer": "gold"})
def fact_sales() -> None:
    """A fact joining to the spine. The dependency is what makes leg 5 work."""


all_assets = [dim_date, fact_sales]
'''

#: `date_key` is the grain and only `not_null` is declared, so a break in
#: uniqueness fails no build today. That gap is what reconcile proposes to close,
#: and it is why this file has a column-level test list at all.
DIM_DATE_YML = """\
models:
  - name: dim_date
    columns:
      - name: date_key
        tests:
          - not_null
"""

#: The other branch. `sale_id` IS declared unique, so when its grain breaks
#: reconcile has nothing mechanical to add and must stay advisory. The join is
#: here because a declared relationship is half of what this format claims to
#: read, and an example that declares none never exercises it.
FACT_SALES_YML = """\
models:
  - name: fact_sales
    columns:
      - name: sale_id
        tests:
          - unique
          - not_null
      - name: date_key
        tests:
          - relationships:
              to: ref('dim_date')
              field: date_key
"""

#: The file STEM names the model that READS these tables, which is the one
#: place this format reads a key as data rather than as a label. `fact_sales`
#: reads a raw landing table the asset graph does not build - which is exactly
#: what an external source is.
SOURCES_YML = """\
sources:
  - name: raw
    schema: raw
    tables:
      - name: sales_events
        columns:
          - name: event_id
          - name: occurred_on
"""

#: `expr` on every field on purpose. A bare column reference is what a
#: consumer needs to check a definition against the warehouse; anything else
#: resolves to no column, and leg 12 turns that into an observation rather
#: than a footnote.
SEMANTICS_YML = """\
semantic_models:
  - name: sales
    model: ref('fact_sales')
    dimensions:
      - name: date_key
        expr: date_key
    measures:
      - name: amount
        expr: amount
metrics:
  - name: total_amount
    type: simple
    type_params:
      measure: amount
"""

#: Leg 13's FIRING half. The model-level combination is the only dbt shape that
#: can state a multi-column grain, and dim_date still carries leg 4's duplicated
#: row - identical in BOTH columns - so the declared combination is false in the
#: warehouse. The column-level `unique` (leg 7's applied edit) is kept
#: deliberately: the parser prefers the combination and says so, and that
#: disclosure is asserted rather than assumed.
DIM_DATE_COMPOSITE_YML = """\
models:
  - name: dim_date
    tests:
      - unique_combination_of_columns:
          combination_of_columns:
            - date_key
            - day_name
    columns:
      - name: date_key
        tests:
          - not_null
          - unique
"""

#: Leg 13's SILENT half. fact_sales is deduplicated first, so this combination
#: holds in the warehouse and must produce NO finding - the control that stops
#: "a declared grain was checked" and "a finding is always emitted" reading the
#: same.
FACT_SALES_COMPOSITE_YML = """\
models:
  - name: fact_sales
    tests:
      - unique_combination_of_columns:
          combination_of_columns:
            - sale_id
            - date_key
    columns:
      - name: sale_id
        tests:
          - not_null
      - name: date_key
        tests:
          - relationships:
              to: ref('dim_date')
              field: date_key
"""

CONFIG_YML = """\
connector: duckdb
duckdb:
  path: warehouse.duckdb
project:
  format: dagster
  options:
    assets: demo_assets:all_assets
    declarations: declarations
    sources: sources
    semantics: semantics
"""


def check(label: str, condition: bool, detail: str = "") -> None:
    if not condition:
        FAILURES.append(label + (": " + detail if detail else ""))


def announce(line: str) -> bool:
    """Print a leg's result, and say whether it is safe to continue.

    Same rule as the drivers: a line reading "ok" above a FAILED block is worse
    than no line, because the eye takes the first one.
    """

    if FAILURES:
        return False
    print(line)
    return True


def dex(root: Path, *args: str, expect_ok: bool = True) -> dict:
    """One dex subcommand, in its own process, returning the parsed envelope."""

    env = dict(os.environ)
    # The assets module lives in the project, which is how a real deployment is
    # laid out. Without this the dotted path in the config cannot resolve.
    env["PYTHONPATH"] = str(root) + os.pathsep + env.get("PYTHONPATH", "")
    completed = subprocess.run(
        [sys.executable, "-m", "exmergo_dex_core", *args],
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
    )
    try:
        envelope = json.loads(completed.stdout)
    except json.JSONDecodeError:
        raise AssertionError(
            "dex {} produced no JSON envelope (rc={}):\n{}\n{}".format(
                " ".join(args), completed.returncode, completed.stdout[-2000:],
                completed.stderr[-2000:],
            )
        ) from None
    if expect_ok and envelope.get("status") != "ok":
        raise AssertionError(
            "dex {} failed: reason={} errors={}".format(
                " ".join(args), envelope.get("reason"), envelope.get("errors")
            )
        )
    return envelope


def seed_warehouse(path: Path) -> None:
    """Two tables, both with a genuine single-column grain."""

    import duckdb

    con = duckdb.connect(str(path))
    try:
        con.execute("CREATE SCHEMA IF NOT EXISTS analytics")
        con.execute(
            "CREATE TABLE analytics.dim_date AS "
            "SELECT (DATE '2026-01-01' + INTERVAL (i) DAY) AS date_key, "
            "dayname(DATE '2026-01-01' + INTERVAL (i) DAY) AS day_name "
            "FROM range(0, 60) t(i)"
        )
        # The landing table `sources/fact_sales.yml` declares. The asset graph does
        # not build it, which is the whole point of calling it a source.
        con.execute("CREATE SCHEMA IF NOT EXISTS raw")
        con.execute(
            "CREATE TABLE raw.sales_events AS "
            "SELECT i AS event_id, "
            "(DATE '2026-01-01' + INTERVAL (i % 60) DAY) AS occurred_on "
            "FROM range(0, 100) t(i)"
        )
        con.execute(
            "CREATE TABLE analytics.fact_sales AS "
            "SELECT i AS sale_id, "
            "(DATE '2026-01-01' + INTERVAL (i % 60) DAY) AS date_key, "
            "(i * 7 % 100)::DOUBLE AS amount "
            "FROM range(0, 500) t(i)"
        )
    finally:
        con.close()


def break_the_grain(path: Path) -> None:
    """One duplicate row in each table, so BOTH reconcile branches have a subject."""

    import duckdb

    con = duckdb.connect(str(path))
    try:
        con.execute(
            "INSERT INTO analytics.dim_date "
            "SELECT date_key, day_name FROM analytics.dim_date "
            "WHERE date_key = DATE '2026-01-05'"
        )
        con.execute(
            "INSERT INTO analytics.fact_sales "
            "SELECT sale_id, date_key, amount FROM analytics.fact_sales "
            "WHERE sale_id = 7"
        )
    finally:
        con.close()


def build_project(root: Path) -> None:
    (root / "declarations").mkdir(parents=True)
    # Encode first, write bytes second: a write that fails mid-encode truncates
    # the file it was opened to replace.
    (root / "declarations" / "dim_date.yml").write_bytes(DIM_DATE_YML.encode("utf-8"))
    (root / "declarations" / "fact_sales.yml").write_bytes(
        FACT_SALES_YML.encode("utf-8")
    )
    (root / "sources").mkdir()
    (root / "sources" / "fact_sales.yml").write_bytes(SOURCES_YML.encode("utf-8"))
    (root / "semantics").mkdir()
    (root / "semantics" / "sales.yml").write_bytes(SEMANTICS_YML.encode("utf-8"))
    (root / "demo_assets.py").write_bytes(ASSETS_MODULE.encode("utf-8"))
    (root / ".dex").mkdir()
    (root / ".dex" / "config.yml").write_bytes(CONFIG_YML.encode("utf-8"))
    seed_warehouse(root / "warehouse.duckdb")


def drop_raw_table(path: Path) -> None:
    """Remove the landing table the source declaration claims the project reads."""

    import duckdb

    con = duckdb.connect(str(path))
    try:
        con.execute("DROP TABLE raw.sales_events")
    finally:
        con.close()


def redefine_the_measure(root: Path) -> None:
    """Change what `amount` MEANS, without touching a single warehouse row."""

    target = root / "semantics" / "sales.yml"
    text = target.read_text(encoding="utf-8")
    changed = text.replace(
        "      - name: amount\n        expr: amount\n",
        "      - name: amount\n        expr: amount * 1.2\n",
        1,
    )
    if changed == text:
        raise AssertionError("the measure fixture moved; leg 12 would test nothing")
    target.write_bytes(changed.encode("utf-8"))


def dedupe_fact_sales(path: Path) -> None:
    """Remove leg 4's duplicate, so leg 13's fact_sales combination HOLDS."""

    import duckdb

    con = duckdb.connect(str(path))
    try:
        con.execute(
            "CREATE OR REPLACE TABLE analytics.fact_sales AS "
            "SELECT DISTINCT * FROM analytics.fact_sales"
        )
    finally:
        con.close()


def declare_composite_grains(root: Path) -> None:
    """Rewrite both declarations to state model-level composite grains."""

    (root / "declarations" / "dim_date.yml").write_bytes(
        DIM_DATE_COMPOSITE_YML.encode("utf-8")
    )
    (root / "declarations" / "fact_sales.yml").write_bytes(
        FACT_SALES_COMPOSITE_YML.encode("utf-8")
    )


def seed_overlap_tables(path: Path) -> None:
    """Three tables for leg 14, keyed by strings no other fixture uses.

    String keys with a disjoint prefix, deliberately: fact_sales.sale_id is
    0..499 and any small-integer key here would be CONTAINED in it, so the
    sweep would propose a cross-family join that is measurement-true and
    meaning-false - a real hazard for a real warehouse, and exactly the noise
    this calibration leg must not depend on.

      customers    customer_key 'C000'..'C039', unique - the parent.
      orders       buyer_ref, same 40 values, unique - key-shaped, contained,
                   and NO NAME connects it to customer_key. The sweep's target.
      order_lines  (order_ref, line_no) composite; order_ref repeats 3x, so it
                   is key-shaped only as a member - contained in the SAME
                   parent, and must NOT be proposed.
    """

    import duckdb

    con = duckdb.connect(str(path))
    try:
        con.execute(
            "CREATE TABLE analytics.customers AS "
            "SELECT 'C' || lpad(i::VARCHAR, 3, '0') AS customer_key, "
            "'tier' || (i % 3)::VARCHAR AS tier "
            "FROM range(0, 40) t(i)"
        )
        con.execute(
            "CREATE TABLE analytics.orders AS "
            "SELECT 'O' || lpad(i::VARCHAR, 3, '0') AS order_key, "
            "'C' || lpad(i::VARCHAR, 3, '0') AS buyer_ref "
            "FROM range(0, 40) t(i)"
        )
        con.execute(
            "CREATE TABLE analytics.order_lines AS "
            "SELECT 'C' || lpad((i % 40)::VARCHAR, 3, '0') AS order_ref, "
            "(i // 40)::INTEGER AS line_no "
            "FROM range(0, 120) t(i)"
        )
    finally:
        con.close()


def project_definitions(root: Path):
    """The project's definitions, read through the graph in-process."""

    sys.path.insert(0, str(root))
    try:
        from exmergo_dex_core.adapters.project import ProjectContext
        from exmergo_dex_core.adapters.project_resolver import (
            construct_project,
            resolve_project_factory,
        )

        project = construct_project(
            "dagster",
            resolve_project_factory("dagster"),
            ProjectContext(
                repo_root=str(root),
                project_dir=None,
                options={
                    "assets": "demo_assets:all_assets",
                    "declarations": "declarations",
                },
            ),
        )
        return project.definitions()
    finally:
        sys.path.remove(str(root))
        for name in [m for m in sys.modules if m == "demo_assets"]:
            del sys.modules[name]


def declared_keys(root: Path) -> set:
    """What the project declares right now, read through the graph in-process."""

    return {(k.model, k.column) for k in project_definitions(root).declared_keys}


def main() -> int:
    import dagster as dg

    print("dagster           : {}".format(dg.__version__))

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "project"
        root.mkdir()
        build_project(root)

        # -- leg 1: the warehouse is reachable, and free ---------------------
        inventory = dex(root, "explore", "inventory")
        objects = {o["identifier"] for o in inventory["data"]["objects"]}
        check(
            "leg 1: the two tables the graph builds are visible",
            {"warehouse.analytics.dim_date", "warehouse.analytics.fact_sales"}
            <= objects,
            "saw {}".format(sorted(objects)),
        )
        # And the landing table, which the graph does NOT build. The warehouse
        # cannot tell the two kinds apart; the project is the only thing that
        # knows one is a source and the others are models, which is what leg 11
        # goes on to depend on.
        check(
            "leg 1: and so is the landing table the graph does not build",
            "warehouse.raw.sales_events" in objects,
            "saw {}".format(sorted(objects)),
        )
        check(
            "leg 1: and the work is free, so this file needs no budget",
            inventory["cost"]["paradigm"] == "free_local",
            "paradigm was {}".format(inventory["cost"]["paradigm"]),
        )
        if not announce(
            "leg 1 ok          : {} objects ({} built by the graph), free_local".format(
                len(objects), 2
            )
        ):
            return report()

        # -- leg 2: the instrument says it is blind, rather than saying clean -
        blind = dex(root, "maintain", "snapshot")
        check(
            "leg 2: a metadata-only baseline has no grain to compare against",
            blind["data"]["baseline"]["grain_baseline_count"] == 0,
            "grain_baseline_count was {}".format(
                blind["data"]["baseline"]["grain_baseline_count"]
            ),
        )
        check(
            "leg 2: and it SAYS so, which is what stops leg 5 reading as clean",
            any("grain" in w for w in blind["warnings"]),
            "warnings were {}".format(blind["warnings"]),
        )
        if not announce("leg 2 ok          : baseline is blind to grain, and discloses it"):
            return report()

        # -- leg 3: give it a baseline ---------------------------------------
        mapped = dex(root, "explore", "map", "--confirm")
        check(
            "leg 3: every object was profiled, the landing table included",
            mapped["data"]["profiled_count"] == 3,
            "profiled_count was {}".format(mapped["data"]["profiled_count"]),
        )
        snapshot = dex(root, "maintain", "snapshot")
        baseline = snapshot["data"]["baseline"]
        check(
            "leg 3: the baseline now holds a grain for each table",
            baseline["grain_baseline_count"] == 3,
            "grain_baseline_count was {}".format(baseline["grain_baseline_count"]),
        )
        check(
            "leg 3: and the transform layer came from the ASSET GRAPH",
            snapshot["data"]["transform_layer"]["model_count"] == 2,
            "model_count was {}".format(
                snapshot["data"]["transform_layer"]["model_count"]
            ),
        )
        # The other two surfaces the README claims, carried into the baseline. A
        # project that parsed them and dropped them would look identical here
        # without these two lines, and legs 11 and 12 would then be testing
        # nothing while still going green.
        check(
            "leg 3: the declared SOURCE reached the baseline",
            snapshot["data"]["transform_layer"]["source_count"] == 1,
            "source_count was {}".format(
                snapshot["data"]["transform_layer"]["source_count"]
            ),
        )
        check(
            "leg 3: and so did the SEMANTIC model and its metric",
            snapshot["data"]["semantic_layer"]
            == {"semantic_model_count": 1, "metric_count": 1},
            "semantic_layer was {}".format(snapshot["data"]["semantic_layer"]),
        )
        if not announce(
            "leg 3 ok          : baseline from cache, {} grains, {} models, "
            "{} source, {} metric".format(
                baseline["grain_baseline_count"],
                snapshot["data"]["transform_layer"]["model_count"],
                snapshot["data"]["transform_layer"]["source_count"],
                snapshot["data"]["semantic_layer"]["metric_count"],
            )
        ):
            return report()

        before = declared_keys(root)
        check(
            "leg 3: dim_date declares no key yet, which is what makes leg 8 a pair",
            ("dim_date", "date_key") not in before,
            "declared {}".format(sorted(before)),
        )

        # -- leg 4 and 5: break it, and let dex find it ----------------------
        break_the_grain(root / "warehouse.duckdb")
        grain = dex(root, "maintain", "grain", "--confirm")
        findings = {
            (f["identifier"].rsplit(".", 1)[-1], f["column"]): f
            for f in grain["data"]["findings"]
        }
        check(
            "leg 5: the broken grain was found on both tables",
            set(findings) == {("dim_date", "date_key"), ("fact_sales", "sale_id")},
            "found {}".format(sorted(findings)),
        )
        dim_finding = findings.get(("dim_date", "date_key"))
        if dim_finding is not None:
            check(
                "leg 5: it is the uniqueness code, measured exactly rather than sampled",
                dim_finding["code"] == "key_lost_uniqueness" and dim_finding["exact"],
                "code={} exact={}".format(dim_finding["code"], dim_finding["exact"]),
            )
            # THE ASSERTION THIS WHOLE FILE EXISTS FOR. `fact_sales` is implicated
            # by a break in `dim_date`, and the only thing that knows they are
            # connected is the Dagster graph.
            check(
                "leg 5: the blast radius crossed the ASSET GRAPH to the dependent model",
                "fact_sales" in dim_finding["impacted_models"],
                "impacted_models was {}".format(dim_finding["impacted_models"]),
            )
        if not announce(
            "leg 5 ok          : {} finding(s); dim_date impacts {}".format(
                len(findings),
                dim_finding["impacted_models"] if dim_finding else "?",
            )
        ):
            return report()

        # -- leg 6: BOTH branches, from one call -----------------------------
        reconcile = dex(root, "maintain", "reconcile")
        plan_id = reconcile["data"].get("plan_id")
        paths = {
            p["column"]: p.get("paths") or [] for p in reconcile["data"]["proposals"]
        }
        check(
            "leg 6: a plan was stored for the declaration that had not caught up",
            bool(plan_id),
            "no plan_id; warnings were {}".format(reconcile.get("warnings")),
        )
        check(
            "leg 6: the edit was placed where this format declares its files live",
            paths.get("date_key") == ["declarations/dim_date.yml"],
            "date_key paths were {}".format(paths.get("date_key")),
        )
        # The half that makes the half above mean something. `sale_id` is already
        # declared `unique`, so there is nothing mechanical to add; an edit here
        # would mean reconcile proposes regardless of what the project says.
        check(
            "leg 6: and NOTHING was proposed where the test is already declared",
            paths.get("sale_id") == [],
            "sale_id paths were {}".format(paths.get("sale_id")),
        )
        check(
            "leg 6: one diff, for the one file",
            len(reconcile.get("diffs") or []) == 1,
            "diffs were {}".format(
                [d.get("path") for d in reconcile.get("diffs") or []]
            ),
        )
        if not announce(
            "leg 6 ok          : plan {}, 1 edit, 1 advisory-only".format(plan_id)
        ):
            return report()

        # The copy is taken HERE, before the apply below, so leg 9 judges a tree
        # that was never edited. Copying it afterwards made leg 9 pass its apply
        # and fail its own precondition - the copy already carried the change,
        # so "the plan travelled" and "the file was already correct" would have
        # been the same observation.
        elsewhere = Path(tmp) / "elsewhere"
        shutil.copytree(root, elsewhere, ignore=shutil.ignore_patterns(".dex"))
        (elsewhere / ".dex" / "plans").mkdir(parents=True)
        (elsewhere / ".dex" / "config.yml").write_bytes(CONFIG_YML.encode("utf-8"))
        shutil.copyfile(
            root / ".dex" / "plans" / (plan_id + ".json"),
            elsewhere / ".dex" / "plans" / (plan_id + ".json"),
        )

        # -- leg 7 and 8: apply, then re-read --------------------------------
        applied = dex(root, "transform", "apply", plan_id, "--confirm")
        check(
            "leg 7: the apply wrote the declaration",
            applied["data"]["written"] == ["declarations/dim_date.yml"],
            "written was {}".format(applied["data"]["written"]),
        )
        after = declared_keys(root)
        check(
            "leg 8: and the project DECLARES the key now, which the write alone "
            "does not prove",
            ("dim_date", "date_key") in after,
            "declared {} before and {} after".format(sorted(before), sorted(after)),
        )
        if not announce(
            "leg 7/8 ok        : wrote it, and the project gained {}".format(
                sorted(after - before)
            )
        ):
            return report()

        # -- leg 9: THE PLAN TRAVELS -----------------------------------------
        #
        # A copy at a path this process never planned against, given ONLY the
        # stored plan JSON. This is the shape of a proposal made on one machine
        # and applied where a checkout already lives.
        travelled_before = declared_keys(elsewhere)
        check(
            "leg 9: the copy has not been edited yet",
            ("dim_date", "date_key") not in travelled_before,
            "declared {}".format(sorted(travelled_before)),
        )
        carried = dex(elsewhere, "transform", "apply", plan_id, "--confirm")
        check(
            "leg 9: a plan made elsewhere applies here",
            carried["data"]["written"] == ["declarations/dim_date.yml"],
            "written was {}".format(carried["data"]["written"]),
        )
        travelled_after = declared_keys(elsewhere)
        check(
            "leg 9: and the copy declares the key it was never planned against",
            ("dim_date", "date_key") in travelled_after,
            "declared {}".format(sorted(travelled_after)),
        )
        if not announce(
            "leg 9 ok          : the plan travelled and applied at a second path"
        ):
            return report()

        # -- leg 10: and it refuses -------------------------------------------
        #
        # Re-applying over the edit it already made. The pin no longer matches,
        # so this is a conflict rather than a quiet rewrite - which is what stops
        # an automated applier reopening the same change forever.
        repeat = dex(elsewhere, "transform", "apply", plan_id, expect_ok=False)
        check(
            "leg 10: a second apply wrote nothing",
            not (repeat.get("data") or {}).get("written"),
            "written was {}".format((repeat.get("data") or {}).get("written")),
        )
        announce("leg 10 ok         : re-applying refused rather than rewriting")

        # -- leg 11: the declared SOURCE does work ----------------------------
        #
        # Drop the landing table the project says it reads. Two findings come
        # back and the pair is the point: `table_dropped` is the WAREHOUSE
        # noticing something it used to have, and `dangling_source` is the
        # PROJECT noticing something it still claims. Only the second one needs
        # a source declaration to exist, so only the second one is evidence
        # that `sources:` was read.
        #
        # `declared_in` is asserted because it was `None` for every source this
        # format produced until 2026-08-18 - the provenance was in the reader's
        # hand and discarded one line later. A finding that cannot say where the
        # claim was written sends a reader looking through the whole project.
        drop_raw_table(root / "warehouse.duckdb")
        schema = dex(root, "maintain", "schema")
        by_code = {f["code"]: f for f in schema["data"]["findings"]}
        check(
            "leg 11: the project noticed its declared source is gone",
            "dangling_source" in by_code,
            "codes were {}".format(sorted(by_code)),
        )
        dangling = by_code.get("dangling_source")
        if dangling is not None:
            check(
                "leg 11: and it named the table the declaration named",
                dangling["identifier"] == "raw.sales_events",
                "identifier was {}".format(dangling["identifier"]),
            )
            check(
                "leg 11: and said WHICH FILE claimed it",
                (dangling.get("data") or {}).get("declared_in")
                == "sources/fact_sales.yml",
                "declared_in was {}".format(
                    (dangling.get("data") or {}).get("declared_in")
                ),
            )
        if not announce(
            "leg 11 ok         : dangling_source on {}, declared_in {}".format(
                dangling["identifier"] if dangling else "?",
                (dangling.get("data") or {}).get("declared_in") if dangling else "?",
            )
        ):
            return report()

        # -- leg 12: the SEMANTIC layer does work too --------------------------
        #
        # Redefine a measure. `definition_changed` is the semantic axis noticing
        # that what the project means by `amount` is not what the baseline
        # agreed to - a class of drift no amount of warehouse inspection finds,
        # because nothing in the warehouse changed.
        #
        # The second assertion is the more interesting one. The new expression
        # is `amount * 1.2`, which is not a bare column reference, so the field
        # resolves to NO warehouse column. dex says so rather than checking it
        # and reporting agreement: "their absence is indistinguishable from
        # agreement". A measure that silently stopped being checkable would look
        # exactly like one that passed.
        redefine_the_measure(root)
        semantic = dex(root, "maintain", "semantic", "--confirm")
        codes = {f["code"] for f in semantic["data"]["findings"]}
        check(
            "leg 12: the redefinition was caught",
            "definition_changed" in codes,
            "codes were {}".format(sorted(codes)),
        )
        check(
            "leg 12: and the now-uncheckable field was DISCLOSED, not passed",
            any(
                "indistinguishable from agreement" in w and "sales.amount" in w
                for w in semantic.get("warnings") or []
            ),
            "warnings were {}".format(semantic.get("warnings")),
        )
        if not announce(
            "leg 12 ok         : definition_changed, and sales.amount reported "
            "as uncheckable"
        ):
            return report()

        # -- leg 13: a DECLARED composite grain is verified, both directions ---
        #
        # 1.8.0 closed the axis's own blind spot: `candidate_keys` is
        # measurement-only, so a grain the project DECLARES was never checked.
        # `declared_grain_not_unique` has no baseline because the combination
        # comes from the project - a failure means the declaration is false,
        # not that anything changed.
        #
        # Both directions in one call: dim_date still carries leg 4's duplicate
        # (identical in both declared columns), so its combination FIRES;
        # fact_sales is deduplicated first, so its combination is checked and
        # SILENT. Without the silent half, "a declared grain was checked" and
        # "a finding is always emitted" are the same observation.
        dedupe_fact_sales(root / "warehouse.duckdb")
        declare_composite_grains(root)
        grain2 = dex(root, "maintain", "grain", "--confirm")
        declared_findings = {
            f["identifier"].rsplit(".", 1)[-1]: f
            for f in grain2["data"]["findings"]
            if f["code"] == "declared_grain_not_unique"
        }
        check(
            "leg 13: the violated declaration fired, and ONLY that one",
            set(declared_findings) == {"dim_date"},
            "declared findings on {}".format(sorted(declared_findings)),
        )
        fired = declared_findings.get("dim_date")
        if fired is not None:
            check(
                "leg 13: the finding names the whole combination, in order",
                (fired.get("data") or {}).get("columns") == ["date_key", "day_name"],
                "columns were {}".format((fired.get("data") or {}).get("columns")),
            )
            check(
                "leg 13: and says the grain was DECLARED, not measured",
                (fired.get("data") or {}).get("declared") is True,
                "data was {}".format(fired.get("data")),
            )
        # The authoring conflict is disclosed, not swallowed: dim_date's file
        # still carries leg 7's column-level `unique` beside the combination,
        # and the format says which one it read. The note travels on
        # `ProjectDefinitions.notes` - the format's channel - so it is read
        # there; whether a given dex command surfaces that channel in its
        # envelope is the engine's affair, not this format's.
        definition_notes = list(project_definitions(root).notes)
        check(
            "leg 13: the composite-wins-over-single conflict was disclosed",
            any("composite" in n and "dim_date" in n for n in definition_notes),
            "definition notes were {}".format(definition_notes),
        )
        if not announce(
            "leg 13 ok         : declared grain (date_key, day_name) refuted on "
            "dim_date; fact_sales's holds, silently"
        ):
            return report()

        # -- leg 14: a join proposed from OVERLAP, and the member exclusion ----
        #
        # `--infer-by-overlap` proposes an edge from measured value containment
        # where no naming convention connects the columns - buyer_ref to
        # customer_key. The half that keeps it honest: order_ref is contained
        # in the SAME parent, but it is unique only as a member of a composite
        # grain, and probing one member of a composite measures a different
        # relationship than the whole key would - so it must NOT be proposed.
        seed_overlap_tables(root / "warehouse.duckdb")
        dex(root, "explore", "map", "--refresh", "--confirm")
        inferred = dex(
            root, "explore", "relationships", "--infer-by-overlap", "--confirm"
        )
        edges = [
            e
            for e in (inferred["data"].get("relationships") or [])
            if "overlap" in str(e.get("kind", "")).lower()
        ]
        edge_shapes = [
            (
                e.get("from_dataset"), e.get("from_columns"),
                e.get("to_dataset"), e.get("to_columns"),
            )
            for e in edges
        ]
        edge_columns = {
            column
            for e in edges
            for column in (e.get("from_columns") or []) + (e.get("to_columns") or [])
        }
        check(
            "leg 14: an edge was proposed where NO NAME connects the columns",
            any(
                {"buyer_ref", "customer_key"}
                == set((e.get("from_columns") or []) + (e.get("to_columns") or []))
                for e in edges
            ),
            "overlap-inferred edges were {}".format(edge_shapes),
        )
        check(
            "leg 14: and the composite-member column, equally contained, was NOT",
            "order_ref" not in edge_columns,
            "overlap-inferred edges were {}".format(edge_shapes),
        )
        if not announce(
            "leg 14 ok         : buyer_ref->customer_key inferred from overlap; "
            "order_ref (composite member) excluded"
        ):
            return report()

        # -- leg 15: a tampered stored edit is refused AT APPLY, hard ---------
        #
        # dex-core 1.7.0 made containment dex's own re-check at apply time: a
        # stored plan is an artifact that sat through a human review, and what
        # it was validated against at plan time is not what it is being written
        # into. The plan store trusts the file it loads - the id is a filename,
        # not a verified digest - so a stored edit whose path was rewritten to
        # leave the declared surface is exactly the input the re-check exists
        # for. A hard refusal, and `--confirm` is not a way past it: that flag
        # is the handshake for a human edit someone can look at and accept, and
        # nobody accepts a write outside the surface the format itself
        # declared. The quiet arm is leg 7 - this same apply path wrote a
        # CONTAINED edit cleanly - so the gate discriminates rather than
        # refusing everything.
        plans_dir = root / ".dex" / "plans"
        stored = json.loads(
            (plans_dir / (plan_id + ".json")).read_text(encoding="utf-8")
        )
        tampered_id = plan_id[:-4] + (
            "beef" if not plan_id.endswith("beef") else "f00d"
        )
        stored["plan_id"] = tampered_id
        stored["applied_at"] = None
        for edit in stored["edits"]:
            edit["path"] = "declarations_backup/" + edit["path"].rsplit("/", 1)[-1]
        (plans_dir / (tampered_id + ".json")).write_text(
            json.dumps(stored), encoding="utf-8"
        )

        refused = dex(
            root, "transform", "apply", tampered_id, "--confirm", expect_ok=False
        )
        envelope_text = json.dumps(refused)
        check(
            "leg 15: the apply refused, with `--confirm` on the command line",
            refused.get("status") != "ok",
            "envelope was {}".format(envelope_text[:500]),
        )
        check(
            "leg 15: and the refusal names the SURFACE, not a hash conflict",
            "outside the editing surface" in envelope_text,
            "envelope was {}".format(envelope_text[:500]),
        )
        check(
            "leg 15: nothing was written where the tampered path pointed",
            not (root / "declarations_backup").exists(),
            "declarations_backup/ exists",
        )
        announce(
            "leg 15 ok         : a stored edit tampered off the surface was "
            "refused at apply; --confirm was no bypass"
        )

    return report()


def report() -> int:
    if FAILURES:
        print("")
        print("FAILED:")
        for failure in FAILURES:
            print("  - {}".format(failure))
        return 1
    print("")
    print("OK - a real graph, a real warehouse, and real drift on three axes:")
    print("     an edit that travelled to a second checkout and landed there, a")
    print("     dangling source that named the file declaring it, a semantic")
    print("     definition that moved without the warehouse changing, a DECLARED")
    print("     composite grain refuted by the data beside one that held, and a")
    print("     join proposed from measured overlap where no name connects the")
    print("     columns - with a composite member, equally contained, excluded -")
    print("     and a stored edit tampered off the declared surface, refused at")
    print("     the apply gate with confirmation on the command line.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
