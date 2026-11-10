# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""Run the declared keys as Dagster asset checks, against a real warehouse.

Run it from the root of a clone:

    uv run --no-project --with-editable '.[dex]' --with 'dagster>=1.13' \\
        --with sqlglot==30.13.0 --with duckdb \\
        python examples/run_declared_key_checks.py

The `[dex]` extra resolves the newest engine its range admits, which is the
engine this example needs to show a measured check. CI runs it in
`engine-ends`, once at each end of that range: what each end must print is
below.

**This is the executor's example; `reduce_asset_graph.py` is the spec-only
one.** That file renders the declared keys with `declaration_check_specs` and
has Dagster load them, but never runs them, and it needs no engine. This file
builds the checks with `build_declaration_checks`, puts them in a job selecting
them alone (`AssetSelection.checks`), puts a schedule on the job, and runs the
job in process against a local DuckDB warehouse, so each check is judged by
dex-core's `maintain verify`.

WHAT IT SHOWS, ON AN ENGINE THAT JUDGES THIS FORMAT (exmergo-dex-core 1.12.5 on)

  1. The clean warehouse. Three keys are MEASURED and pass. Two are NOT
     MEASURED, each a WARN result with `measured` False and dex-core's reason,
     never a pass:
       - `stg_returns` names no table, so it is absent from `model_relations`;
       - `dim_customer`'s composite key is skipped by verify's own priority
         rule, because the model also declares a single-column key.
     The run succeeds, and materializes nothing: it selected checks alone.
  2. Two duplicates planted, run again with the defaults. Both broken keys
     FAIL with a duplicate count and WARN severity, and the run still succeeds,
     because nothing blocks unless a claim opts in. The two not measured stay
     not measured: a broken warehouse does not make them judged.
  3. The same warehouse, with `fact_orders`'s key opted in to blocking. That
     one failure is ERROR and fails the run; the other stays WARN.

  The declared join is never a check. It is named in a note the executor
  logs on every run, which this file reads back out of the run's log.

WHAT IT SHOWS BELOW 1.12.5

  Every check is NOT MEASURED, on both warehouses, with the reason that the
  engine predates `maintain verify` judging this format. Nothing passes and
  nothing fails. That is the floor of the published range today, and it is a
  supported configuration that judges nothing, stated rather than skipped.

WHY THERE IS NO STAND-IN ENGINE HERE

`tests/test_executor.py` has one, for the paths DuckDB cannot reach (a probe
the cost gate wants confirmed). It is not importable from here without the
test suite, since it is built on that file's fixtures and pytest, and it would
not remove the engine anyway: it replaces `verify` only, and the attribution
reads dex-core's own result types and grain plan. DuckDB is free and local
(no credential, no network, no bill), so this runs the real thing instead.

CONSTRAINTS, AS FOR THE OTHER EXAMPLES

  - **No pytest.** The CI step installs no test runner, so these are plain
    asserts and a nonzero exit.
  - **Not shipped in the sdist.** `examples/` is outside
    `[tool.setuptools.packages.find]`.
"""

from __future__ import annotations

import importlib.metadata
import logging
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

import dagster as dg
import duckdb
import yaml

from dagster_dex import DagsterProject
from dagster_dex.checks import (
    CLAIM_ID,
    DUPLICATE_COUNT,
    ENGINE,
    MEASURED,
    REASON,
    build_declaration_checks,
)

#: The first engine whose `maintain verify` judges a declared key on this
#: format, as measured on #180 (comment 6716240099). Written here rather than
#: read from `dagster_dex.dex`, so this file does not share the executor's own
#: answer to the question it is checking.
JUDGED_FROM = (1, 12, 5)

#: One file per model, as placement presumes. `dim_customer` declares two keys
#: in two files: one entry declaring both would keep the composite alone, with
#: a note, and verify would then judge it.
DECLARATIONS = {
    "declarations/dim_store.yml": """\
models:
  - name: dim_store
    tests:
      - unique_combination_of_columns:
          combination_of_columns: [region, store_code]
""",
    "declarations/fact_orders.yml": """\
models:
  - name: fact_orders
    columns:
      - name: order_id
        tests: [unique, not_null]
      - name: store_code
        tests:
          - relationships: {to: "ref('dim_store')", field: store_code}
""",
    "declarations/dim_customer.yml": """\
models:
  - name: dim_customer
    tests:
      - unique_combination_of_columns:
          combination_of_columns: [customer_id, region]
""",
    "declarations/dim_customer_id.yml": """\
models:
  - name: dim_customer
    columns:
      - name: customer_id
        tests: [unique]
""",
    "declarations/stg_returns.yml": """\
models:
  - name: stg_returns
    columns:
      - name: return_id
        tests: [unique]
""",
}


# Each asset names its table the way Dagster does, in `dagster/table_name`,
# which is how the reduction places a model in the warehouse. Two sit under a
# prefix, so their checks have to attach to the whole key.
@dg.asset(key_prefix=["mart"], metadata={"dagster/table_name": "analytics.dim_store"})
def dim_store() -> None:
    """Stores. `store_code` repeats across regions; the pair is the key."""


@dg.asset(
    key_prefix=["mart"],
    deps=[dim_store],
    metadata={"dagster/table_name": "analytics.fact_orders"},
)
def fact_orders() -> None:
    """Orders, joining to the store they were placed at."""


@dg.asset(metadata={"dagster/table_name": "analytics.dim_customer"})
def dim_customer() -> None:
    """Customers, with a single-column key and a composite beside it."""


@dg.asset
def stg_returns() -> None:
    """Returns. Names no table, so verify cannot place it."""


ASSETS = [dim_store, fact_orders, dim_customer, stg_returns]

CLEAN_WAREHOUSE = [
    "CREATE SCHEMA analytics",
    "CREATE TABLE analytics.dim_store AS SELECT CASE WHEN i % 2 = 0 THEN 'east' "
    "ELSE 'west' END AS region, i // 2 AS store_code FROM range(0, 20) t(i)",
    "CREATE TABLE analytics.fact_orders AS SELECT i AS order_id, i % 10 AS store_code "
    "FROM range(1, 401) t(i)",
    "CREATE TABLE analytics.dim_customer AS SELECT i AS customer_id, CASE WHEN i % 3 = 0 "
    "THEN 'north' ELSE 'south' END AS region FROM range(1, 51) t(i)",
]

#: One duplicate under each of two measured keys. No value planted here may
#: reach a result: the metadata carries how many rows repeat, never which.
VIOLATIONS = [
    "INSERT INTO analytics.fact_orders SELECT * FROM analytics.fact_orders WHERE order_id = 7",
    "INSERT INTO analytics.dim_store VALUES ('east', 0)",
]
#: The planted duplicate's text value, as a whole word, so `least` is not it.
PLANTED = re.compile(r"\beast\b")
#: Every key a result's metadata may carry. A count, a flag, an id, a version,
#: a reason: nothing read out of a row.
RESULT_KEYS = {CLAIM_ID, MEASURED, ENGINE, REASON, DUPLICATE_COUNT}

#: The checks, by (asset, check name), as `build_declaration_checks` names them.
FACT_ORDERS = ("mart/fact_orders", "declared_key__order_id")
DIM_STORE = ("mart/dim_store", "declared_key__region__store_code")
CUSTOMER_ID = ("dim_customer", "declared_key__customer_id")
CUSTOMER_PAIR = ("dim_customer", "declared_key__customer_id__region")
RETURNS = ("stg_returns", "declared_key__return_id")
NOT_MEASURED = {CUSTOMER_PAIR, RETURNS}

JOB = "declared_key_checks"


def engine_version() -> tuple[int, ...]:
    release = importlib.metadata.version("exmergo-dex-core")
    return tuple(int(part) for part in re.findall(r"\d+", release)[:3])


def build_warehouse(root: Path) -> None:
    """A local DuckDB file and a `.dex/config.yml` selecting it."""

    connection = duckdb.connect(str(root / "warehouse.duckdb"))
    try:
        for statement in CLEAN_WAREHOUSE:
            connection.execute(statement)
    finally:
        connection.close()
    (root / ".dex").mkdir()
    config = {"connector": "duckdb", "duckdb": {"path": str(root / "warehouse.duckdb")}}
    (root / ".dex" / "config.yml").write_text(yaml.safe_dump(config), encoding="utf-8")


def plant_violations(root: Path) -> None:
    connection = duckdb.connect(str(root / "warehouse.duckdb"))
    try:
        for statement in VIOLATIONS:
            connection.execute(statement)
    finally:
        connection.close()


def definitions_for(root: Path, blocking: tuple[str, ...] = ()) -> dg.Definitions:
    """The assets, the checks, a job selecting the checks alone, and a schedule.

    The checks carry no automation condition, so nothing runs them when an
    asset materializes: the schedule is how they run. The cron is this
    example's choice, not a default.
    """

    project = DagsterProject.from_asset_graph(ASSETS, declaration_sources=DECLARATIONS)
    asset_keys = [key for asset in ASSETS for key in asset.keys]
    checks = build_declaration_checks(project, asset_keys, repo_root=root, blocking=blocking)
    assert all(spec.automation_condition is None for spec in checks.check_specs)

    job = dg.define_asset_job(JOB, selection=dg.AssetSelection.checks(checks))
    schedule = dg.ScheduleDefinition(job=job, cron_schedule="0 6 * * *")
    definitions = dg.Definitions(
        assets=ASSETS, asset_checks=[checks], jobs=[job], schedules=[schedule]
    )
    dg.Definitions.validate_loadable(definitions)
    return definitions


def claim_of(definitions: dg.Definitions, check: tuple[str, str]) -> str:
    """The claim id a check's spec carries: what `blocking` takes."""

    (checks,) = definitions.asset_checks or ()
    for spec in checks.check_specs:
        if (spec.asset_key.to_user_string(), spec.name) == check:
            return str(spec.metadata[CLAIM_ID])
    raise AssertionError(f"no check {check}")


def run(definitions: dg.Definitions, label: str) -> tuple[bool, dict[tuple[str, str], Any], list[str]]:
    """Run the job in process, as its schedule would. Returns the run's
    success, each check's evaluation, and the warnings the run logged."""

    instance = dg.DagsterInstance.ephemeral()
    result = definitions.resolve_job_def(JOB).execute_in_process(
        instance=instance, raise_on_error=False
    )
    assert result.get_asset_materialization_events() == [], "a check run materialized an asset"
    evaluations = {
        (evaluation.asset_key.to_user_string(), evaluation.check_name): evaluation
        for evaluation in result.get_asset_check_evaluations()
    }
    warnings = [
        entry.user_message
        for entry in instance.all_logs(result.run_id)
        if entry.level == logging.WARNING
    ]
    print(f"--- {label}: the run {'succeeded' if result.success else 'FAILED'}")
    for check in sorted(evaluations):
        print(f"  {describe(check, evaluations[check])}")
    return result.success, evaluations, warnings


def value(evaluation: Any, key: str) -> Any:
    entry = evaluation.metadata.get(key)
    return None if entry is None else entry.value


def describe(check: tuple[str, str], evaluation: Any) -> str:
    asset, name = check
    severity = evaluation.severity.value
    if not value(evaluation, MEASURED):
        return f"{asset} {name}: not measured ({severity}): {value(evaluation, REASON)}"
    if evaluation.passed:
        return f"{asset} {name}: passed"
    count = value(evaluation, DUPLICATE_COUNT)
    return f"{asset} {name}: FAILED ({severity}), {count} duplicate row(s)"


def state(evaluation: Any) -> tuple[bool, bool, str]:
    """(measured, passed, severity), as the evaluation reports them."""

    return bool(value(evaluation, MEASURED)), evaluation.passed, evaluation.severity.value


def states(evaluations: dict[tuple[str, str], Any]) -> dict[tuple[str, str], tuple[bool, bool, str]]:
    return {check: state(evaluation) for check, evaluation in evaluations.items()}


def assert_never_passes_unmeasured(evaluations: dict[tuple[str, str], Any]) -> None:
    for check, evaluation in evaluations.items():
        if not value(evaluation, MEASURED):
            assert not evaluation.passed, f"{check} passed without being measured"
            assert evaluation.severity.value == "WARN", check
            assert value(evaluation, REASON), f"{check} carries no reason"


def assert_counts_only(evaluations: dict[tuple[str, str], Any]) -> None:
    """The keys are the executor's own, and the planted value is in none of it.

    A light reading, not the control: the executor's row-value control, with
    an engine that does quote a value, is `tests/test_executor.py`'s
    `TestNoRowValueIsCarried`.
    """

    for check, evaluation in evaluations.items():
        assert set(evaluation.metadata) <= RESULT_KEYS, (check, set(evaluation.metadata))
    reported = " ".join(
        f"{evaluation.description} {[value(evaluation, key) for key in evaluation.metadata]}"
        for evaluation in evaluations.values()
    )
    assert PLANTED.search(reported) is None, "a planted row value reached a result"


def assert_the_join_is_a_note(warnings: list[str]) -> None:
    joins = [line for line in warnings if "declared joins are not rendered as checks" in line]
    assert joins, warnings
    assert "fact_orders(store_code) -> dim_store(store_code)" in joins[0], joins


def walk_a_judging_engine(root: Path) -> None:
    # 1. The clean warehouse: three measured passes, two not measured.
    succeeded, evaluations, warnings = run(definitions_for(root), "clean warehouse")
    assert succeeded
    assert states(evaluations) == {
        FACT_ORDERS: (True, True, "WARN"),
        DIM_STORE: (True, True, "WARN"),
        CUSTOMER_ID: (True, True, "WARN"),
        CUSTOMER_PAIR: (False, False, "WARN"),
        RETURNS: (False, False, "WARN"),
    }, states(evaluations)
    assert "absent from model_relations" in value(evaluations[RETURNS], REASON)
    assert "grain plan" in value(evaluations[CUSTOMER_PAIR], REASON)
    assert_never_passes_unmeasured(evaluations)
    assert_the_join_is_a_note(warnings)

    # 2. Two duplicates, the defaults: both fail, as WARN, and the run succeeds.
    plant_violations(root)
    succeeded, evaluations, _ = run(definitions_for(root), "two duplicates, the defaults")
    assert succeeded, "a non-blocking failure failed the run"
    assert states(evaluations) == {
        FACT_ORDERS: (True, False, "WARN"),
        DIM_STORE: (True, False, "WARN"),
        CUSTOMER_ID: (True, True, "WARN"),
        CUSTOMER_PAIR: (False, False, "WARN"),
        RETURNS: (False, False, "WARN"),
    }, states(evaluations)
    assert value(evaluations[FACT_ORDERS], DUPLICATE_COUNT) == 1
    assert value(evaluations[DIM_STORE], DUPLICATE_COUNT) == 1
    assert_never_passes_unmeasured(evaluations)
    assert_counts_only(evaluations)

    # 3. The same warehouse, one claim opted in to blocking.
    blocked = claim_of(definitions_for(root), FACT_ORDERS)
    succeeded, evaluations, _ = run(
        definitions_for(root, blocking=(blocked,)), "two duplicates, fact_orders blocking"
    )
    assert not succeeded, "a blocking claim's measured failure did not fail the run"
    print("  (the step failure Dagster logged for this run is that blocking failure)")
    assert state(evaluations[FACT_ORDERS]) == (True, False, "ERROR")
    assert state(evaluations[DIM_STORE]) == (True, False, "WARN")
    assert_never_passes_unmeasured(evaluations)


def walk_an_engine_below_the_floor(root: Path) -> None:
    floor = ".".join(str(part) for part in JUDGED_FROM)
    for label in ("clean warehouse", "two duplicates"):
        if label == "two duplicates":
            plant_violations(root)
        succeeded, evaluations, warnings = run(definitions_for(root), label)
        assert succeeded
        assert set(evaluations) == {FACT_ORDERS, DIM_STORE, CUSTOMER_ID, CUSTOMER_PAIR, RETURNS}
        for check, evaluation in evaluations.items():
            assert state(evaluation) == (False, False, "WARN"), check
            reason = value(evaluation, REASON)
            assert "predates maintain verify" in reason and floor in reason, reason
        assert_the_join_is_a_note(warnings)


def main() -> int:
    version = engine_version()
    judges = version >= JUDGED_FROM
    print(
        f"exmergo-dex-core {'.'.join(map(str, version))}: "
        f"{'judges' if judges else 'predates'} maintain verify on this format"
    )
    root = Path(tempfile.mkdtemp(prefix="dagster-dex-checks-"))
    try:
        build_warehouse(root)
        if judges:
            walk_a_judging_engine(root)
        else:
            walk_an_engine_below_the_floor(root)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("every assertion held")
    return 0


if __name__ == "__main__":
    sys.exit(main())
