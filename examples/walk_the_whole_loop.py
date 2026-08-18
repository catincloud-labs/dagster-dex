# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""The whole loop, against a real warehouse, with no cloud account.

Run it:

    uv run --no-project --with-editable . --with 'dagster>=1.13' \\
        --with exmergo-dex-core==1.6.6 --with sqlglot==30.13.0 --with duckdb \\
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

NOT COVERED HERE, DELIBERATELY

Sources and semantics. This demo declares keys and one join, so `sources:` and
`semantics:` are surfaces the README claims and this file does not reach. Said
out loud rather than left for a reader to discover: a walkthrough that implies
coverage it does not have is the failure this repository keeps recording.

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

CONFIG_YML = """\
connector: duckdb
duckdb:
  path: warehouse.duckdb
project:
  format: dagster
  options:
    assets: demo_assets:all_assets
    declarations: declarations
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
    (root / "demo_assets.py").write_bytes(ASSETS_MODULE.encode("utf-8"))
    (root / ".dex").mkdir()
    (root / ".dex" / "config.yml").write_bytes(CONFIG_YML.encode("utf-8"))
    seed_warehouse(root / "warehouse.duckdb")


def declared_keys(root: Path) -> set:
    """What the project declares right now, read through the graph in-process."""

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
        definitions = project.definitions()
        return {(k.model, k.column) for k in definitions.declared_keys}
    finally:
        sys.path.remove(str(root))
        for name in [m for m in sys.modules if m == "demo_assets"]:
            del sys.modules[name]


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
            "leg 1: both tables are visible",
            objects
            == {"warehouse.analytics.dim_date", "warehouse.analytics.fact_sales"},
            "saw {}".format(sorted(objects)),
        )
        check(
            "leg 1: and the work is free, so this file needs no budget",
            inventory["cost"]["paradigm"] == "free_local",
            "paradigm was {}".format(inventory["cost"]["paradigm"]),
        )
        if not announce("leg 1 ok          : {} objects, free_local".format(len(objects))):
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
            "leg 3: both objects were profiled",
            mapped["data"]["profiled_count"] == 2,
            "profiled_count was {}".format(mapped["data"]["profiled_count"]),
        )
        snapshot = dex(root, "maintain", "snapshot")
        baseline = snapshot["data"]["baseline"]
        check(
            "leg 3: the baseline now holds a grain for each table",
            baseline["grain_baseline_count"] == 2,
            "grain_baseline_count was {}".format(baseline["grain_baseline_count"]),
        )
        check(
            "leg 3: and the transform layer came from the ASSET GRAPH",
            snapshot["data"]["transform_layer"]["model_count"] == 2,
            "model_count was {}".format(
                snapshot["data"]["transform_layer"]["model_count"]
            ),
        )
        if not announce(
            "leg 3 ok          : baseline from cache, {} grains, {} models".format(
                baseline["grain_baseline_count"],
                snapshot["data"]["transform_layer"]["model_count"],
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

    return report()


def report() -> int:
    if FAILURES:
        print("")
        print("FAILED:")
        for failure in FAILURES:
            print("  - {}".format(failure))
        return 1
    print("")
    print("OK - a real graph, a real warehouse, a real drift finding, and an")
    print("     edit that travelled to a second checkout and landed there.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
