# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""The executor: declared keys run as Dagster asset checks through dex-core.

#180's *How we would know it worked*, as the owner's ruling on it amends them
(keys only; comment 6715768229), each on both arms against #179's DuckDB
reproduction, which `test_dex_bridge.py` holds and this file imports rather
than copies:

2. a violated key fails, the composite (`region`, `store_code`) included;
3. the clean arm passes every key check;
4. a key the engine did not measure never reports passed, whichever route
   leaves it unmeasured;
5. the harness control: the clean arm, run against an executor that never
   calls the engine, fails this file's own clean-arm assertion;
6. each result carries the claim id its spec carries.

Check 7, the engine-free import, is `test_checks.py`'s, since it has to run
where the engine is absent. The never-auto-confirm path runs against a
stand-in engine, because DuckDB never asks for confirmation.

**Dagster is a stand-in here, and dex-core is real.** No pytest step installs
the orchestrator, so the `multi_asset_check` is built from a stand-in
`dagster` module whose names take the arguments the real ones take (read in
dagster 1.13.29), and the check body is run directly with a stand-in context.
The engine, its `verify` and the warehouse are real wherever the engine can
judge this format, which is from exmergo-dex-core 1.12.5. Below that the
warehouse tests skip by version, as `test_dex_bridge.py`'s do, and the version
gate's own test runs instead.
"""

from __future__ import annotations

import enum
import sys
import types
from collections.abc import Callable, Iterator
from typing import Any

import pytest
import yaml
from test_checks import StandInAssetCheckSpec, StandInAssetKey

from dagster_dex import DagsterProject, DeclaredKey
from dagster_dex import dex as bridge
from dagster_dex.checks import (
    CLAIM_ID,
    DUPLICATE_COUNT,
    ENGINE,
    MEASURED,
    REASON,
    build_declaration_checks,
    claim_id,
)

pytest.importorskip("exmergo_dex_core", reason="the [dex] extra is not installed")

# #179's reproduction, imported so there is one copy of it. After the skip,
# because that module skips itself without the engine too.
from test_dex_bridge import (  # noqa: E402 - the fixture's module needs the engine
    CLEAN_WAREHOUSE,
    CORRECTIONS,
    MISPLACED_ASSETS,
    PLACED_ASSETS,
    VERIFY_DECLARATIONS,
    VERIFY_SEAM_FROM,
    VIOLATIONS,
    _engine_version,
    _metadata_asset,
)

# --- a stand-in for the orchestrator ------------------------------------------


class StandInSeverity(enum.Enum):
    WARN = "WARN"
    ERROR = "ERROR"


class StandInAssetCheckResult:
    """``dagster.AssetCheckResult``'s keyword arguments, kept for reading."""

    def __init__(
        self,
        *,
        passed: bool,
        asset_key: Any = None,
        check_name: str | None = None,
        metadata: Any = None,
        severity: StandInSeverity = StandInSeverity.ERROR,
        description: str | None = None,
    ) -> None:
        self.passed = passed
        self.asset_key = asset_key
        self.check_name = check_name
        self.metadata = dict(metadata or {})
        self.severity = severity
        self.description = description


class StandInChecks:
    """What the stand-in ``multi_asset_check`` returns: the specs and the body."""

    def __init__(self, fn: Callable[..., Any], specs: list[Any], **options: Any) -> None:
        self.fn = fn
        self.specs = specs
        self.options = options


def stand_in_multi_asset_check(*, specs: Any, **options: Any) -> Callable[..., StandInChecks]:
    return lambda fn: StandInChecks(fn, list(specs), **options)


class StandInCheckKey:
    def __init__(self, path: list[str], name: str) -> None:
        self.asset_key = StandInAssetKey(path)
        self.name = name


class StandInLog:
    def __init__(self) -> None:
        self.warnings: list[str] = []

    def warning(self, message: str) -> None:
        self.warnings.append(message)


class StandInContext:
    def __init__(self, keys: list[StandInCheckKey]) -> None:
        self.selected_asset_check_keys = keys
        self.log = StandInLog()


@pytest.fixture(autouse=True)
def _dagster(monkeypatch: pytest.MonkeyPatch) -> None:
    module = types.ModuleType("dagster")
    setattr(module, "AssetCheckSpec", StandInAssetCheckSpec)
    setattr(module, "AssetKey", StandInAssetKey)
    setattr(module, "AssetCheckResult", StandInAssetCheckResult)
    setattr(module, "AssetCheckSeverity", StandInSeverity)
    setattr(module, "multi_asset_check", stand_in_multi_asset_check)
    monkeypatch.setitem(sys.modules, "dagster", module)


def run(checks: StandInChecks, *, only: list[str] | None = None) -> tuple[dict[str, Any], StandInContext]:
    """Run the check body once, as a scheduled run selecting the checks would.

    Returns each result by its model, and the context, for its log.
    """

    selected = [
        StandInCheckKey(list(spec.asset_key.path), spec.name)
        for spec in checks.specs
        if only is None or spec.asset_key.path[-1] in only
    ]
    context = StandInContext(selected)
    results = {result.asset_key.path[-1]: result for result in checks.fn(context)}
    return results, context


# --- #179's reproduction, as a check run reads it -----------------------------


def project_of(assets: list[Any], declarations: dict[str, str] | None = None, **options: Any) -> DagsterProject:
    sources = {
        f"declarations/{name}": text
        for name, text in (declarations or VERIFY_DECLARATIONS).items()
    }
    return DagsterProject.from_asset_graph(assets, declaration_sources=sources, **options)


def asset_keys(assets: list[Any]) -> list[Any]:
    return [key for asset in assets for key in asset.keys]


def warehouse(tmp_path: Any, *, violated: bool) -> Any:
    """A local DuckDB warehouse and a `.dex/config.yml` selecting it.

    Skips below the engine that judges this format, by version and never by
    a failed import: from there a missing `duckdb` is a failure.
    """

    if _engine_version() < VERIFY_SEAM_FROM:
        pytest.skip("this engine predates maintain verify judging this format")
    import duckdb

    path = tmp_path / "warehouse.duckdb"
    connection = duckdb.connect(str(path))
    try:
        for statement in CLEAN_WAREHOUSE + (VIOLATIONS if violated else []):
            connection.execute(statement)
    finally:
        connection.close()
    (tmp_path / ".dex").mkdir()
    config = {"connector": "duckdb", "duckdb": {"path": str(path)}}
    (tmp_path / ".dex" / "config.yml").write_text(yaml.safe_dump(config), encoding="utf-8")
    return tmp_path


class VerifySpy:
    """Counts real ``DexEngine.verify`` calls, and the models each was asked for."""

    def __init__(self) -> None:
        self.calls: list[list[str] | None] = []


@pytest.fixture
def spy(monkeypatch: pytest.MonkeyPatch) -> VerifySpy:
    """A spy on the real verify, so it skips where `warehouse` does: by version."""

    if _engine_version() < VERIFY_SEAM_FROM:
        pytest.skip("this engine predates maintain verify judging this format")
    from exmergo_dex_core import DexEngine

    recorder = VerifySpy()
    real = DexEngine.verify

    def verify(self: Any, objects: list[str] | None = None, **kwargs: Any) -> Any:
        recorder.calls.append(objects)
        return real(self, objects, **kwargs)

    monkeypatch.setattr(DexEngine, "verify", verify)
    return recorder


def state(result: Any) -> tuple[bool, bool]:
    """(measured, passed), as the result reports them."""

    return result.metadata[MEASURED], result.passed


def assert_clean_arm(results: dict[str, Any], spy: VerifySpy) -> None:
    """Every key measured and passed, by ONE real call of verify over all three.

    The call count is what makes a pass here mean something: a clean
    warehouse and an executor that judged nothing look alike in the results.
    """

    assert {model: state(result) for model, result in results.items()} == {
        "dim_date": (True, True),
        "dim_store": (True, True),
        "fact_orders": (True, True),
    }
    assert spy.calls == [["dim_date", "dim_store", "fact_orders"]]


# --- 2 and 3: a violated key fails, and the clean arm passes ------------------


class TestTheReproduction:
    def test_each_violated_key_fails_with_its_count_and_the_untouched_one_passes(
        self, tmp_path: Any, spy: VerifySpy
    ) -> None:
        root = warehouse(tmp_path, violated=True)
        checks = build_declaration_checks(project_of(PLACED_ASSETS), asset_keys(PLACED_ASSETS), repo_root=root)

        results, _ = run(checks)

        assert {model: state(result) for model, result in results.items()} == {
            "dim_date": (True, True),
            "dim_store": (True, False),
            "fact_orders": (True, False),
        }
        assert results["dim_store"].metadata[DUPLICATE_COUNT] == 1
        assert results["fact_orders"].metadata[DUPLICATE_COUNT] == 1
        assert results["dim_store"].check_name == "declared_key__region__store_code"
        assert len(spy.calls) == 1

    def test_the_clean_arm_passes_every_key(self, tmp_path: Any, spy: VerifySpy) -> None:
        root = warehouse(tmp_path, violated=False)
        checks = build_declaration_checks(project_of(PLACED_ASSETS), asset_keys(PLACED_ASSETS), repo_root=root)

        results, _ = run(checks)

        assert_clean_arm(results, spy)
        assert all(DUPLICATE_COUNT not in result.metadata for result in results.values())

    def test_every_result_warns_and_carries_counts_and_its_claim_never_a_row_value(
        self, tmp_path: Any, spy: VerifySpy
    ) -> None:
        root = warehouse(tmp_path, violated=True)
        project = project_of(PLACED_ASSETS)
        checks = build_declaration_checks(project, asset_keys(PLACED_ASSETS), repo_root=root)

        results, _ = run(checks)

        claims = {spec.asset_key.path[-1]: spec.metadata[CLAIM_ID] for spec in checks.specs}
        for model, result in results.items():
            assert result.severity is StandInSeverity.WARN
            assert result.metadata[CLAIM_ID] == claims[model]
            assert result.metadata[ENGINE].startswith("exmergo-dex-core ")
            assert set(result.metadata) <= {CLAIM_ID, MEASURED, ENGINE, REASON, DUPLICATE_COUNT}
            assert all(isinstance(value, (bool, int, str)) for value in result.metadata.values())
        # The planted rows are ('east', 0) and order 7: no value of either is
        # in what the results report, only how many rows repeat.
        reported = " ".join(
            f"{result.description} {result.metadata}" for result in results.values()
        )
        assert "east" not in reported

    def test_a_subset_run_asks_verify_for_the_selected_models_only(
        self, tmp_path: Any, spy: VerifySpy
    ) -> None:
        root = warehouse(tmp_path, violated=True)
        checks = build_declaration_checks(project_of(PLACED_ASSETS), asset_keys(PLACED_ASSETS), repo_root=root)

        results, _ = run(checks, only=["fact_orders"])

        assert list(results) == ["fact_orders"]
        assert state(results["fact_orders"]) == (True, False)
        assert spy.calls == [["fact_orders"]]


# --- 5. the harness control ---------------------------------------------------


class TestTheHarnessCatchesAnExecutorThatNeverCallsTheEngine:
    """The clean arm, run against an executor that never asks the engine,
    must fail `assert_clean_arm`. Otherwise its pass proves nothing: a clean
    warehouse reports no finding, and so does a verify nobody ran."""

    def test_verdicts_made_up_without_an_engine_fail_the_clean_arm(
        self, tmp_path: Any, spy: VerifySpy, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = warehouse(tmp_path, violated=False)

        def never_asks(claims: Any, open_engine: Any) -> tuple[Any, ...]:
            return tuple(bridge.KeyVerdict(claim=c, measured=True, passed=True) for c, _ in claims)

        monkeypatch.setattr(bridge, "verify_declared_keys", never_asks)
        checks = build_declaration_checks(project_of(PLACED_ASSETS), asset_keys(PLACED_ASSETS), repo_root=root)

        results, _ = run(checks)

        with pytest.raises(AssertionError):
            assert_clean_arm(results, spy)

    def test_an_engine_opened_but_never_asked_fails_the_clean_arm(
        self, tmp_path: Any, spy: VerifySpy
    ) -> None:
        """The subtler shape: the engine opens and verify is skipped, so the
        executor reads an empty result. Every key then reads as held, and only
        the call count tells it apart from a real clean run."""

        from exmergo_dex_core.maintain.results import VerifyResult

        root = warehouse(tmp_path, violated=False)
        project = project_of(PLACED_ASSETS)

        class Unasked:
            def __enter__(self) -> Unasked:
                return self

            def __exit__(self, *_: Any) -> None:
                return None

            def verify(self, objects: Any = None) -> Any:
                return VerifyResult()

            def project_format(self) -> Any:
                return bridge.DexProject(project)

        checks = build_declaration_checks(project, asset_keys(PLACED_ASSETS), open_engine=Unasked)
        results, _ = run(checks)

        # From 1.17.5 an empty result carries no record, so nothing passes
        # (#194); before it, silence read as every key held.
        empty = (False, False) if carries_grain_coverage() else (True, True)
        assert all(state(result) == empty for result in results.values())
        with pytest.raises(AssertionError):
            assert_clean_arm(results, spy)
        # And the real executor over the same warehouse passes it.
        real, _ = run(build_declaration_checks(project, asset_keys(PLACED_ASSETS), repo_root=root))
        assert_clean_arm(real, spy)


# --- 4. a key the engine did not measure never reports passed -----------------

#: `region` declared unique on `dim_store`, beside its composite.
REGION_UNIQUE = """\
models:
  - name: dim_store
    columns:
      - name: region
        tests: [unique]
"""

#: In a second file, so both keys reach verify: `dim_store`'s composite is
#: then skipped by verify's priority rule (a model with a single-column unique
#: test has its composite unchecked). `region` repeats, so that key fails.
BOTH_ON_DIM_STORE = {**VERIFY_DECLARATIONS, "dim_store_region.yml": REGION_UNIQUE}

#: The same two keys in ONE entry, where this package's parser keeps the
#: composite, drops the single-column key, and says so in a note that names
#: `dim_store`'s grain. Verify copies the note into its warnings.
BOTH_IN_ONE_ENTRY = {
    **VERIFY_DECLARATIONS,
    "dim_store.yml": VERIFY_DECLARATIONS["dim_store.yml"].replace(
        "    tests:\n", "    columns:\n      - name: region\n        tests: [unique]\n    tests:\n"
    ),
}

#: `fact_orders` declares a key on a column its table does not have.
A_MISSING_COLUMN = {
    **VERIFY_DECLARATIONS,
    "fact_orders.yml": VERIFY_DECLARATIONS["fact_orders.yml"].replace(
        "      - name: order_date_key\n",
        "      - name: order_ref\n        tests: [unique]\n      - name: order_date_key\n",
    ),
}


def unmeasured(result: Any) -> str:
    """The reason, once the result is shown not measured and not passed."""

    assert state(result) == (False, False)
    assert result.severity is StandInSeverity.WARN
    reason: str = result.metadata[REASON]
    assert reason and result.description == reason
    return reason


@pytest.mark.parametrize("violated", [True, False], ids=["violated", "clean"])
class TestUnmeasuredNeverPasses:
    def test_a_model_absent_from_model_relations_is_not_measured(
        self, tmp_path: Any, violated: bool
    ) -> None:
        """#179's return: no relation means absent from the map, and the
        project's own note is the reason. `dim_store` names a table that is
        not there, which verify reports as `no_relation`."""

        root = warehouse(tmp_path, violated=violated)
        checks = build_declaration_checks(
            project_of(MISPLACED_ASSETS), asset_keys(MISPLACED_ASSETS), repo_root=root
        )

        results, _ = run(checks)

        assert "absent from model_relations" in unmeasured(results["fact_orders"])
        assert "dim_store" in unmeasured(results["dim_store"])
        assert state(results["dim_date"]) == (True, True)

    def test_the_relations_option_brings_both_back_to_measured(
        self, tmp_path: Any, violated: bool
    ) -> None:
        """The quiet arm of the test above: corrected, the same graph is judged."""

        root = warehouse(tmp_path, violated=violated)
        project = project_of(MISPLACED_ASSETS, relations=CORRECTIONS)
        checks = build_declaration_checks(project, asset_keys(MISPLACED_ASSETS), repo_root=root)

        results, _ = run(checks)

        assert all(state(result)[0] for result in results.values())
        assert state(results["fact_orders"]) == (True, not violated)

    def test_a_composite_verify_skips_for_its_priority_rule_is_not_measured(
        self, tmp_path: Any, violated: bool
    ) -> None:
        root = warehouse(tmp_path, violated=violated)
        checks = build_declaration_checks(
            project_of(PLACED_ASSETS, BOTH_ON_DIM_STORE), asset_keys(PLACED_ASSETS), repo_root=root
        )

        results_by_name = {
            result.check_name: result for result in checks.fn(StandInContext([
                StandInCheckKey(list(spec.asset_key.path), spec.name) for spec in checks.specs
            ]))
        }

        assert "grain plan" in unmeasured(results_by_name["declared_key__region__store_code"])
        assert state(results_by_name["declared_key__region"]) == (True, False)

    def test_this_packages_own_note_on_a_grain_does_not_unmeasure_it(
        self, tmp_path: Any, violated: bool
    ) -> None:
        """The quiet arm of the test above. One entry declaring both keeps the
        composite alone, so verify judges it; the parser's note naming
        `dim_store`'s grain reaches verify's warnings and must not read as
        verify saying it skipped the model."""

        root = warehouse(tmp_path, violated=violated)
        project = project_of(PLACED_ASSETS, BOTH_IN_ONE_ENTRY)
        assert any("the composite wins" in note for note in project.declarations().notes)
        checks = build_declaration_checks(project, asset_keys(PLACED_ASSETS), repo_root=root)

        results, _ = run(checks)

        assert state(results["dim_store"]) == (True, not violated)

    def test_a_key_on_a_column_the_relation_lacks_is_not_measured(
        self, tmp_path: Any, violated: bool
    ) -> None:
        """Two engines, two shapes, one rule. A newer verify skips the missing
        column, notes it, and still judges `order_id`; 1.12.5 sends the column
        to the warehouse, which refuses the statement, and nothing in the call
        is judged. Either way `order_ref` is not measured, and `order_id` is
        never passed unless it was judged."""

        root = warehouse(tmp_path, violated=violated)
        checks = build_declaration_checks(
            project_of(PLACED_ASSETS, A_MISSING_COLUMN), asset_keys(PLACED_ASSETS), repo_root=root
        )

        results_by_name = {
            result.check_name: result for result in checks.fn(StandInContext([
                StandInCheckKey(list(spec.asset_key.path), spec.name) for spec in checks.specs
            ]))
        }

        reason = unmeasured(results_by_name["declared_key__order_ref"])
        order_id = results_by_name["declared_key__order_id"]
        if "WarehouseQueryError" in reason:
            # The warehouse's message named the column, and it is cut: it
            # is the same message that can quote a row value.
            assert "not carried" in reason
            assert "WarehouseQueryError" in unmeasured(order_id)
        else:
            assert "order_ref" in reason and "fact_orders" in reason
            assert state(order_id) == (True, not violated)


# --- the stand-in engine: what DuckDB cannot reach ----------------------------


class StandInEngine:
    """An engine whose ``verify`` raises, or returns, what it is given, and
    whose project format reads ``project`` (#179's placed graph unless said)."""

    opened = 0

    def __init__(self, outcome: Any, project: Any = None) -> None:
        self.outcome = outcome
        self.project = project_of(PLACED_ASSETS) if project is None else project

    def project_format(self) -> Any:
        return bridge.DexProject(self.project)

    def __call__(self) -> StandInEngine:
        StandInEngine.opened += 1
        return self

    def __enter__(self) -> StandInEngine:
        return self

    def __exit__(self, *_: Any) -> None:
        return None

    def verify(self, objects: Any = None) -> Any:
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


def _cost() -> Any:
    from exmergo_dex_core import Cost

    return Cost(estimate=12.0, ceiling=10.0, unit="credits")


def _refusals() -> Iterator[Any]:
    import exmergo_dex_core as engine

    yield pytest.param(lambda: engine.ConfirmationRequiredError(_cost(), "confirm a scan"), id="wants-confirming")
    yield pytest.param(lambda: engine.OverCeilingError("over the ceiling", cost=_cost()), id="over-ceiling")
    yield pytest.param(lambda: engine.BudgetExhaustedError("the session budget is spent"), id="budget-spent")
    yield pytest.param(lambda: engine.QueryRefusedError("the firewall refused it"), id="firewall")
    yield pytest.param(lambda: engine.WarehouseQueryError("the warehouse refused it"), id="warehouse")


@pytest.fixture
def engine_judges() -> None:
    """Skip below the engine that judges this format, by version.

    The stand-in replaces the engine's verify, not the rest of dex-core: the
    attribution reads verify's own grain plan and result types, which the
    floor's engine does not ship. Below the gate there is nothing to stand in
    for, and `TestTheVersionGate` reads that arm.
    """

    if _engine_version() < VERIFY_SEAM_FROM:
        pytest.skip("this engine predates maintain verify judging this format")


@pytest.mark.usefixtures("engine_judges")
class TestNeverAutoConfirm:
    @pytest.mark.parametrize("refusal", list(_refusals()))
    def test_a_refused_probe_leaves_every_key_not_measured_with_dex_reason(self, refusal: Any) -> None:
        error = refusal()
        checks = build_declaration_checks(
            project_of(PLACED_ASSETS), asset_keys(PLACED_ASSETS), open_engine=StandInEngine(error)
        )

        results, _ = run(checks)

        for result in results.values():
            reason = unmeasured(result)
            assert type(error).__name__ in reason
            if "the warehouse refused a statement dex built:" in str(error):
                assert "not carried" in reason and "refused it" not in reason
            else:
                assert str(error) in reason

    @pytest.mark.parametrize("field", ["pending_confirmation", "pending_offer"])
    def test_a_probe_returned_for_confirmation_leaves_every_key_not_measured(self, field: str) -> None:
        from exmergo_dex_core import ConfirmationRequest
        from exmergo_dex_core.maintain.results import VerifyResult

        request = ConfirmationRequest(cost=_cost(), message="confirm a scan")
        checks = build_declaration_checks(
            project_of(PLACED_ASSETS),
            asset_keys(PLACED_ASSETS),
            open_engine=StandInEngine(VerifyResult(**{field: request})),
        )

        results, _ = run(checks)

        assert all("confirm" in unmeasured(result) for result in results.values())

    def test_a_suppressed_grain_check_leaves_every_key_not_measured(self) -> None:
        from exmergo_dex_core.maintain.results import VerifyResult

        result = VerifyResult(suppressed={"grain": "warehouse unreachable: nobody home"})
        checks = build_declaration_checks(
            project_of(PLACED_ASSETS), asset_keys(PLACED_ASSETS), open_engine=StandInEngine(result)
        )

        results, _ = run(checks)

        assert all("nobody home" in unmeasured(result) for result in results.values())

    @pytest.mark.parametrize("opted_in", [False, True], ids=["default", "opted-in"])
    def test_the_engine_is_confirmed_only_when_the_builder_opts_in(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any, opted_in: bool
    ) -> None:
        import exmergo_dex_core

        seen: list[dict[str, Any]] = []

        class Recorder:
            def __init__(self, **kwargs: Any) -> None:
                seen.append(kwargs)

            @classmethod
            def from_repo(cls, root: str, **kwargs: Any) -> Recorder:
                return cls(repo_root=root, **kwargs)

        monkeypatch.setattr(exmergo_dex_core, "DexEngine", Recorder)
        project = project_of(PLACED_ASSETS)

        bridge.open_verify_engine(project, connector="duckdb", confirm_spend=opted_in)
        bridge.open_verify_engine(project, repo_root=tmp_path, confirm_spend=opted_in)

        assert [kwargs["confirmed"] for kwargs in seen] == [opted_in, opted_in]
        assert all(isinstance(kwargs["project_format"], bridge.DexProject) for kwargs in seen)


@pytest.mark.usefixtures("engine_judges")
class TestBlocking:
    def _checks(self, outcome: Any, blocking: list[str]) -> StandInChecks:
        return build_declaration_checks(
            project_of(PLACED_ASSETS),
            asset_keys(PLACED_ASSETS),
            open_engine=StandInEngine(outcome),
            blocking=blocking,
        )

    def test_a_blocking_claims_measured_failure_is_an_error_and_others_warn(self) -> None:
        from exmergo_dex_core.maintain.drift import DriftFinding
        from exmergo_dex_core.maintain.results import VerifyResult

        broken = [
            DriftFinding(
                axis="grain",
                code="grain_broken",
                identifier=model,
                detail=f"{model} repeats",
                data={"model": model, "columns": columns, "duplicate_count": 3, "source": source},
            )
            for model, columns, source in [
                ("fact_orders", ["order_id"], "unique_test"),
                ("dim_store", ["region", "store_code"], "unique_test_composite"),
            ]
        ]
        fact_orders = claim_id(DeclaredKey("fact_orders", ("order_id",)))
        result = VerifyResult(findings=broken)
        if carries_grain_coverage():
            result = proven_except([record("fact_orders", "broken", rows=10, distinct=7)], findings=broken)
            result.grain_coverage[1] = record("dim_store", "broken", rows=10, distinct=7)
        checks = self._checks(result, [fact_orders])

        results, _ = run(checks)

        assert results["fact_orders"].severity is StandInSeverity.ERROR
        assert results["dim_store"].severity is StandInSeverity.WARN
        assert results["dim_store"].metadata[DUPLICATE_COUNT] == 3
        assert [spec.blocking for spec in checks.specs if spec.asset_key.path[-1] == "fact_orders"] == [True]

    def test_an_unmeasured_blocking_claim_warns_rather_than_blocks(self) -> None:
        import exmergo_dex_core

        fact_orders = claim_id(DeclaredKey("fact_orders", ("order_id",)))
        checks = self._checks(exmergo_dex_core.BudgetExhaustedError("spent"), [fact_orders])

        results, _ = run(checks)

        unmeasured(results["fact_orders"])


class TestTheVersionGate:
    def test_below_the_floor_every_key_is_unmeasured_and_no_engine_opens(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(bridge, "engine_release", lambda: "1.12.4")
        StandInEngine.opened = 0
        checks = build_declaration_checks(
            project_of(PLACED_ASSETS), asset_keys(PLACED_ASSETS), open_engine=StandInEngine(None)
        )

        results, _ = run(checks)

        assert all("1.12.4 predates" in unmeasured(result) for result in results.values())
        assert StandInEngine.opened == 0

    @pytest.mark.usefixtures("engine_judges")
    def test_at_the_floor_the_engine_is_asked(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The other arm: the gate opens at exactly the measured version."""

        from exmergo_dex_core.maintain.results import VerifyResult

        monkeypatch.setattr(bridge, "engine_release", lambda: "1.12.5")
        StandInEngine.opened = 0
        checks = build_declaration_checks(
            project_of(PLACED_ASSETS), asset_keys(PLACED_ASSETS), open_engine=StandInEngine(VerifyResult())
        )

        run(checks)

        assert StandInEngine.opened == 1

    def test_the_installed_engine_below_the_floor_reports_every_key_unmeasured(self) -> None:
        """Unpatched: the floor cell's own engine (1.8.0) is gated."""

        if _engine_version() >= VERIFY_SEAM_FROM:
            pytest.skip("the installed engine judges this format; the tests above read it")
        checks = build_declaration_checks(project_of(PLACED_ASSETS), asset_keys(PLACED_ASSETS))

        results, _ = run(checks)

        assert all("predates" in unmeasured(result) for result in results.values())

    def test_the_gate_and_the_bridge_tests_name_one_floor(self) -> None:
        assert bridge.VERIFY_JUDGES_FROM == VERIFY_SEAM_FROM


class TestTheBuilder:
    def test_the_spec_layers_notes_are_logged_on_every_run(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(bridge, "engine_release", lambda: "1.12.4")
        checks = build_declaration_checks(project_of(PLACED_ASSETS), asset_keys(PLACED_ASSETS))

        _, context = run(checks)

        (note,) = context.log.warnings
        assert note.startswith("declared joins are not rendered") and "ship_date_key" in note

    def test_the_checks_can_run_as_a_subset(self) -> None:
        checks = build_declaration_checks(project_of(PLACED_ASSETS), asset_keys(PLACED_ASSETS))
        assert checks.options["can_subset"] is True

    def test_a_project_declaring_no_key_is_refused_with_the_notes(self) -> None:
        only_joins = {"fact_orders.yml": VERIFY_DECLARATIONS["fact_orders.yml"].replace(
            "        tests: [unique, not_null]\n", "        tests: [not_null]\n"
        )}
        with pytest.raises(ValueError, match="no declared key renders to a check: declared joins"):
            build_declaration_checks(project_of(PLACED_ASSETS, only_joins), asset_keys(PLACED_ASSETS))

    @pytest.mark.parametrize(
        "options",
        [
            {"repo_root": "."},
            {"connector": "duckdb"},
            {"connection": object()},
            {"connection": 0},
            {"confirm_spend": True},
        ],
        ids=["repo_root", "connector", "connection", "connection-equal-to-false", "confirm_spend"],
    )
    def test_open_engine_beside_an_engine_option_is_refused(self, options: dict[str, Any]) -> None:
        with pytest.raises(ValueError, match="cannot be combined with: " + next(iter(options))):
            build_declaration_checks(
                project_of(PLACED_ASSETS), asset_keys(PLACED_ASSETS), open_engine=StandInEngine(None), **options
            )

    def test_a_connector_beside_a_repo_root_is_refused(self, tmp_path: Any) -> None:
        with pytest.raises(ValueError, match="pass connector or repo_root, not both"):
            bridge.open_verify_engine(project_of(PLACED_ASSETS), repo_root=tmp_path, connector="duckdb")


# --- routes the cold review of the executor's pull request found ------------


def a_warehouse(tmp_path: Any, statements: list[str]) -> Any:
    """`warehouse`, over statements of a test's own rather than #179's."""

    if _engine_version() < VERIFY_SEAM_FROM:
        pytest.skip("this engine predates maintain verify judging this format")
    import duckdb

    path = tmp_path / "warehouse.duckdb"
    connection = duckdb.connect(str(path))
    try:
        for statement in statements:
            connection.execute(statement)
    finally:
        connection.close()
    (tmp_path / ".dex").mkdir()
    config = {"connector": "duckdb", "duckdb": {"path": str(path)}}
    (tmp_path / ".dex" / "config.yml").write_text(yaml.safe_dump(config), encoding="utf-8")
    return tmp_path


def unique_on(column: str, *models: str) -> dict[str, str]:
    """One declaration file per model, each declaring ``column`` unique."""

    return {
        f"{model}.yml": (
            f"models:\n  - name: {model}\n    columns:\n"
            f"      - name: {column}\n        tests: [unique]\n"
        )
        for model in models
    }


class TestTheEngineJudgesWhatItRead:
    def test_an_engine_reading_another_project_does_not_pass_what_it_could_not_place(
        self, tmp_path: Any
    ) -> None:
        """`open_engine`'s engine reads the misplaced graph, where `fact_orders`
        has no relation, while the checks come from the placed one. Verify
        judged nothing for `fact_orders`, whose key is broken in this
        warehouse; read against the checks' project it passed."""

        from exmergo_dex_core import DexEngine

        root = warehouse(tmp_path, violated=True)
        other = bridge.DexProject(project_of(MISPLACED_ASSETS))
        checks = build_declaration_checks(
            project_of(PLACED_ASSETS),
            asset_keys(PLACED_ASSETS),
            open_engine=lambda: DexEngine.from_repo(str(root), project_format=other),
        )

        results, _ = run(checks)

        assert "absent from model_relations" in unmeasured(results["fact_orders"])
        assert state(results["dim_date"]) == (True, True)

    def test_two_models_keyed_on_one_column_keep_their_own_verdicts(self, tmp_path: Any) -> None:
        """The model half of the attribution: `id` repeats in `orders_a` only."""

        root = a_warehouse(tmp_path, [
            "CREATE SCHEMA analytics",
            "CREATE TABLE analytics.orders_a AS SELECT i AS id FROM range(1, 11) t(i)",
            "INSERT INTO analytics.orders_a VALUES (3), (4)",
            "CREATE TABLE analytics.orders_b AS SELECT i AS id FROM range(1, 11) t(i)",
        ])
        assets = [
            _metadata_asset("orders_a", table="analytics.orders_a"),
            _metadata_asset("orders_b", table="analytics.orders_b"),
        ]
        checks = build_declaration_checks(
            project_of(assets, unique_on("id", "orders_a", "orders_b")), asset_keys(assets), repo_root=root
        )

        results, _ = run(checks)

        assert state(results["orders_a"]) == (True, False)
        assert results["orders_a"].metadata[DUPLICATE_COUNT] == 2
        assert state(results["orders_b"]) == (True, True)

    def test_a_relation_two_schemas_hold_is_not_measured(self, tmp_path: Any) -> None:
        """Verify's note that no single relation matched, reached on a real
        engine: `fact_orders` names its table with no schema, and two hold one."""

        root = a_warehouse(tmp_path, [
            "CREATE SCHEMA analytics",
            "CREATE SCHEMA staging",
            "CREATE TABLE analytics.fact_orders AS SELECT i AS order_id FROM range(1, 11) t(i)",
            "CREATE TABLE staging.fact_orders AS SELECT i AS order_id FROM range(1, 11) t(i)",
        ])
        assets = [_metadata_asset("fact_orders", table="fact_orders")]
        checks = build_declaration_checks(
            project_of(assets, unique_on("order_id", "fact_orders")), asset_keys(assets), repo_root=root
        )

        results, _ = run(checks)

        assert "fact_orders" in unmeasured(results["fact_orders"])


#: The value a failing cast is made to quote. It must not reach any result.
ROW_VALUE = "row_value_never_carried"
#: The first engine whose warehouse adapters mask a value a refusal quotes,
#: and what they put in its place (read in exmergo-dex-core 1.17.5, #189).
VALUE_MASKED_FROM = (1, 17, 5)
VALUE_WITHHELD = "<value withheld>"
#: DuckDB's refusal of a failed cast, in the words 1.17.4's verify passes on.
DUCKDB_REFUSAL = (
    f"Conversion Error: Could not convert string '{ROW_VALUE}' to INT32 "
    "when casting from source column x"
)


def _quoting_warning() -> Any:
    from exmergo_dex_core.maintain.results import VerifyResult

    warnings = [
        "the grain could not be measured for fact_orders: the warehouse "
        f"refused the distinct-count statement ({DUCKDB_REFUSAL})"
    ]
    if carries_grain_coverage():
        # From 1.17.5 the key's record is what leaves it unjudged, and the
        # note is carried into the reason, where the cut still applies.
        return proven_except([record("fact_orders", "unchecked", "not_measured")], warnings=warnings)
    return VerifyResult(warnings=warnings)


def _quoting_error() -> Any:
    from exmergo_dex_core import WarehouseQueryError

    return WarehouseQueryError(DUCKDB_REFUSAL)


class TestNoRowValueIsCarried:
    """No result carries a value the warehouse's message quotes.

    From 1.17.5 dex-core masks that value itself, before any text reaches this
    package, so a real warehouse no longer shows the cut in `dex.py` doing
    anything. The stand-in case is what does: its engine quotes the value at
    every version, so only the cut keeps it out of the result. The warehouse
    case is kept for what only it reads, dex-core's real wording reaching the
    cut, with a control that knows which of the two texts to expect.
    """

    @pytest.mark.usefixtures("engine_judges")
    @pytest.mark.parametrize("outcome", [_quoting_warning, _quoting_error], ids=["warning", "error"])
    def test_an_engine_text_quoting_a_row_value_is_cut_from_the_reason(self, outcome: Any) -> None:
        given = outcome()

        # The positive control: the value is in what the stand-in engine hands
        # the executor, unmasked, so it is there for the cut to remove. For the
        # error this reads dex-core's own `str`, which would show a constructor
        # that began masking. That the cut is what removes it is shown by
        # mutating the cut, which turns both arms red (#189's pull request).
        said = str(given) if isinstance(given, BaseException) else " ".join(given.warnings)
        assert ROW_VALUE in said and VALUE_WITHHELD not in said

        checks = build_declaration_checks(
            project_of(PLACED_ASSETS), asset_keys(PLACED_ASSETS), open_engine=StandInEngine(given)
        )
        results, _ = run(checks)

        reason = unmeasured(results["fact_orders"])
        assert "the warehouse refused" in reason and "not carried" in reason
        for result in results.values():
            assert ROW_VALUE not in f"{result.description} {result.metadata}"

    def test_a_warehouse_message_quoting_a_row_value_is_cut_from_the_reason(self, tmp_path: Any) -> None:
        """`fact_orders` is a view whose cast fails on a row, so the warehouse
        refuses verify's statement and its message quotes the value. 1.12.5
        raises the refusal and 1.17.4 notes it; either way the reason stops
        where dex starts quoting the warehouse. From 1.17.5 dex-core masks the
        value before it is noted, so here the cut has nothing left to remove,
        and the stand-in case above is what shows it removes it."""

        from exmergo_dex_core import DexEngine, WarehouseQueryError

        root = a_warehouse(tmp_path, [
            "CREATE SCHEMA analytics",
            f"CREATE TABLE analytics.raw AS SELECT * FROM (VALUES ('7'), ('{ROW_VALUE}')) t(x)",
            "CREATE VIEW analytics.fact_orders AS SELECT CAST(x AS INTEGER) AS order_id FROM analytics.raw",
        ])
        assets = [_metadata_asset("fact_orders", table="analytics.fact_orders")]
        project = project_of(assets, unique_on("order_id", "fact_orders"))

        # The positive control: dex-core's own text says the warehouse refused
        # and gives its words, the value or (from 1.17.5) its mask, so what is
        # absent below is not a warehouse that said nothing.
        try:
            with DexEngine.from_repo(str(root), project_format=bridge.DexProject(project)) as engine:
                raw = " ".join(engine.verify(["fact_orders"]).warnings)
        except WarehouseQueryError as exc:
            raw = str(exc)
        assert "the warehouse refused" in raw and "Could not convert string" in raw
        if _engine_version() < VALUE_MASKED_FROM:
            assert ROW_VALUE in raw
        else:
            assert VALUE_WITHHELD in raw and ROW_VALUE not in raw

        results, _ = run(build_declaration_checks(project, asset_keys(assets), repo_root=root))

        reason = unmeasured(results["fact_orders"])
        assert "the warehouse refused" in reason and "not carried" in reason
        assert ROW_VALUE not in f"{reason} {results['fact_orders'].metadata}"


@pytest.mark.usefixtures("engine_judges")
class TestEveryEngineErrorIsAResult:
    def test_an_engine_error_outside_the_cost_gate_is_not_measured_rather_than_no_result(self) -> None:
        import exmergo_dex_core

        checks = build_declaration_checks(
            project_of(PLACED_ASSETS),
            asset_keys(PLACED_ASSETS),
            open_engine=StandInEngine(exmergo_dex_core.ConnectorError("the connection dropped")),
        )

        results, _ = run(checks)

        assert len(results) == 3
        assert all("ConnectorError" in unmeasured(result) for result in results.values())

    def test_an_error_that_is_not_the_engines_still_raises(self) -> None:
        """The quiet arm: a defect is not dressed up as a reason."""

        checks = build_declaration_checks(
            project_of(PLACED_ASSETS), asset_keys(PLACED_ASSETS), open_engine=StandInEngine(KeyError("a bug"))
        )

        with pytest.raises(KeyError):
            run(checks)

    def test_no_claims_asks_nothing(self) -> None:
        """An empty `objects` is every model to verify, so nothing is asked."""

        StandInEngine.opened = 0

        assert bridge.verify_declared_keys([], StandInEngine(None)) == ()
        assert StandInEngine.opened == 0


# --- #194: from 1.17.5, a pass only on a proven grain_coverage record ---------


def carries_grain_coverage() -> bool:
    """Does the installed engine's verify result carry ``grain_coverage``?"""

    from exmergo_dex_core.maintain.results import VerifyResult

    return "grain_coverage" in VerifyResult.model_fields


@pytest.fixture
def records() -> None:
    """Skip unless the installed engine's verify result carries the records.

    Below 1.12.5 the version gate's tests run instead; the note path, which
    1.12.5 to 1.17.4 take, is `TestTheNotePathStays`.
    """

    if _engine_version() < VERIFY_SEAM_FROM or not carries_grain_coverage():
        pytest.skip("this engine's verify result carries no grain_coverage")


#: #179's three keys, by model: (columns, source), as `grain_plan` labels them.
KEYS = {
    "dim_date": (["date_key"], "unique_test"),
    "dim_store": (["region", "store_code"], "unique_test_composite"),
    "fact_orders": (["order_id"], "unique_test"),
}


def record(model: str, status: str, reason: str | None = None, **counts: int) -> dict[str, Any]:
    """One `grain_coverage` record, built by dex-core's own `grain_record`."""

    from exmergo_dex_core.maintain.verify import GrainCandidate, grain_record

    columns, source = KEYS[model]
    candidate = GrainCandidate(columns=columns, source=source)
    return dict(grain_record(model, candidate, status, reason, **counts))


def proven_except(fact_orders: list[dict[str, Any]], **fields: Any) -> Any:
    """A verify result whose records prove `dim_date` and `dim_store`, with
    the records given for `fact_orders`."""

    from exmergo_dex_core.maintain.results import VerifyResult

    coverage = [
        record("dim_date", "proven", rows=10, distinct=10),
        record("dim_store", "proven", rows=10, distinct=10),
        *fact_orders,
    ]
    return VerifyResult(grain_coverage=coverage, **fields)


def judged(result: Any) -> dict[str, Any]:
    checks = build_declaration_checks(
        project_of(PLACED_ASSETS), asset_keys(PLACED_ASSETS), open_engine=StandInEngine(result)
    )
    results, _ = run(checks)
    return results


#: A note of verify's on the grain of `fact_orders`, reworded so it no longer
#: names the model: the issue's violating case. The executor before #194 finds
#: no note naming `fact_orders`, so it reads the key as held.
PLANTED_NOTE = "the grain could not be measured for one relation: its scan was refused"


@pytest.mark.usefixtures("records")
class TestAPassNeedsAProvenRecord:
    def test_a_planted_note_that_no_longer_names_the_model_is_not_a_pass(self) -> None:
        """#194's test. `fact_orders` was not measured, its record says so,
        and the only note about it has stopped naming it."""

        assert not bridge._names_model(PLANTED_NOTE, "fact_orders")
        result = proven_except([record("fact_orders", "unchecked", "scan")], warnings=[PLANTED_NOTE])

        results = judged(result)

        assert "unchecked (scan)" in unmeasured(results["fact_orders"])
        assert state(results["dim_date"]) == (True, True)

    def test_a_proven_record_passes(self) -> None:
        results = judged(proven_except([record("fact_orders", "proven", rows=10, distinct=10)]))

        assert {model: state(result) for model, result in results.items()} == {
            "dim_date": (True, True),
            "dim_store": (True, True),
            "fact_orders": (True, True),
        }

    @pytest.mark.parametrize(
        ("status", "reason"),
        [
            ("not_applicable", "empty_relation"),
            ("unchecked", "not_measured"),
            ("not_planned", "priority"),
            ("measured", None),
        ],
        ids=["not_applicable", "unchecked", "not_planned", "a-status-not-known-here"],
    )
    def test_a_record_in_any_other_state_is_not_a_pass(self, status: str, reason: str | None) -> None:
        counts = {"rows": 0, "distinct": 0} if status == "not_applicable" else {}
        results = judged(proven_except([record("fact_orders", status, reason, **counts)]))

        said = unmeasured(results["fact_orders"])
        assert f"record is {status} ({reason or 'no reason code'})" in said
        assert "fact_orders (order_id)" in said

    def test_a_broken_record_is_a_measured_failure_with_its_count(self) -> None:
        broken = record("fact_orders", "broken", rows=10, distinct=8)

        results = judged(proven_except([broken]))

        assert state(results["fact_orders"]) == (True, False)
        assert results["fact_orders"].metadata[DUPLICATE_COUNT] == 2

    def test_a_broken_record_takes_the_findings_words_where_there_is_one(self) -> None:
        from exmergo_dex_core.maintain.drift import DriftFinding

        finding = DriftFinding(
            axis="grain",
            code="grain_broken",
            identifier="fact_orders",
            detail="fact_orders repeats order_id",
            data={"model": "fact_orders", "columns": ["order_id"], "duplicate_count": 3, "source": "unique_test"},
        )
        broken = record("fact_orders", "broken", rows=10, distinct=7)

        results = judged(proven_except([broken], findings=[finding]))

        assert state(results["fact_orders"]) == (True, False)
        assert results["fact_orders"].description == "fact_orders repeats order_id"
        assert results["fact_orders"].metadata[DUPLICATE_COUNT] == 3

    @pytest.mark.parametrize(
        "changed",
        [None, {"source": "primary_entity"}, {"columns": ["order_ref"]}, {"model": "fact_order"}],
        ids=["none", "another-source", "other-columns", "another-model"],
    )
    def test_a_key_with_no_record_of_its_own_is_not_a_pass(self, changed: dict[str, Any] | None) -> None:
        others = [] if changed is None else [{**record("fact_orders", "proven", rows=10, distinct=10), **changed}]

        results = judged(proven_except(others))

        assert "holds no record for fact_orders (order_id)" in unmeasured(results["fact_orders"])

    def test_no_grain_coverage_at_all_is_not_a_pass(self) -> None:
        """`None` is what verify returns when its grain check did not run; an
        empty result built without records is no evidence any key held."""

        from exmergo_dex_core.maintain.results import VerifyResult

        results = judged(VerifyResult())

        assert all("returned no grain_coverage" in unmeasured(result) for result in results.values())

    def test_one_proven_record_beside_an_unchecked_one_is_not_a_pass(self) -> None:
        both = [record("fact_orders", "proven", rows=10, distinct=10), record("fact_orders", "unchecked", "scan")]

        assert "unchecked (scan)" in unmeasured(judged(proven_except(both))["fact_orders"])

    def test_a_note_naming_the_model_is_carried_into_the_reason_never_the_decision(self) -> None:
        note = "the grain could not be measured for fact_orders: two relations matched"
        proven = proven_except([record("fact_orders", "proven", rows=10, distinct=10)], warnings=[note])
        unchecked = proven_except([record("fact_orders", "unchecked", "ambiguous")], warnings=[note])

        assert state(judged(proven)["fact_orders"]) == (True, True)
        assert "two relations matched" in unmeasured(judged(unchecked)["fact_orders"])


class NoteEraResult:
    """A verify result shaped as 1.12.5 to 1.17.4 return it: no `grain_coverage`.

    The ceiling's own `VerifyResult` carries the field, so the note path is
    reached there only with a result that lacks it.
    """

    def __init__(self, *, warnings: list[str] | None = None) -> None:
        self.findings: list[Any] = []
        self.suppressed: dict[str, str] = {}
        self.warnings = list(warnings or [])
        self.notes: list[str] = []
        self.pending_confirmation = None
        self.pending_offer = None


@pytest.mark.usefixtures("engine_judges")
class TestTheNotePathStays:
    """Below 1.17.5 the executor reads verify's notes, as it did before #194."""

    @pytest.fixture(autouse=True)
    def _a_note_era_engine(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(bridge, "engine_release", lambda: "1.17.4")

    def test_a_clean_result_passes_every_key(self) -> None:
        assert all(state(result) == (True, True) for result in judged(NoteEraResult()).values())

    def test_a_note_naming_the_model_is_not_measured(self) -> None:
        results = judged(NoteEraResult(warnings=["the grain could not be measured for fact_orders"]))

        assert "fact_orders" in unmeasured(results["fact_orders"])
        assert state(results["dim_date"]) == (True, True)

    def test_the_residue_a_note_that_stops_naming_the_model_reads_as_a_pass(self) -> None:
        """Stated in the docstring and the README rather than left to be found:
        on this path the planted note is a pass. It is the path's one way open."""

        assert state(judged(NoteEraResult(warnings=[PLANTED_NOTE]))["fact_orders"]) == (True, True)

    def test_from_1_17_5_a_result_without_grain_coverage_passes_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The backstop: a field renamed upstream costs every pass rather than
        reopening the note path."""

        monkeypatch.setattr(bridge, "engine_release", lambda: "1.17.5")

        results = judged(NoteEraResult())

        assert all("without grain_coverage" in unmeasured(result) for result in results.values())


def test_the_backstop_and_this_file_name_one_version() -> None:
    assert bridge.GRAIN_COVERAGE_FROM == VALUE_MASKED_FROM == (1, 17, 5)
