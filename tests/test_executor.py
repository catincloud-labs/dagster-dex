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

        def never_asks(project: Any, claims: Any, open_engine: Any) -> tuple[Any, ...]:
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

        checks = build_declaration_checks(project, asset_keys(PLACED_ASSETS), open_engine=Unasked)
        results, _ = run(checks)

        assert all(state(result) == (True, True) for result in results.values())
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
            assert "order_ref" in reason
            assert "WarehouseQueryError" in unmeasured(order_id)
        else:
            assert "order_ref" in reason and "fact_orders" in reason
            assert state(order_id) == (True, not violated)


# --- the stand-in engine: what DuckDB cannot reach ----------------------------


class StandInEngine:
    """An engine whose ``verify`` raises, or returns, what it is given."""

    opened = 0

    def __init__(self, outcome: Any) -> None:
        self.outcome = outcome

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
            assert type(error).__name__ in reason and str(error) in reason

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
        checks = self._checks(VerifyResult(findings=broken), [fact_orders])

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
        [{"repo_root": "."}, {"connector": "duckdb"}, {"connection": object()}, {"confirm_spend": True}],
        ids=["repo_root", "connector", "connection", "confirm_spend"],
    )
    def test_open_engine_beside_an_engine_option_is_refused(self, options: dict[str, Any]) -> None:
        with pytest.raises(ValueError, match="cannot be combined with: " + next(iter(options))):
            build_declaration_checks(
                project_of(PLACED_ASSETS), asset_keys(PLACED_ASSETS), open_engine=StandInEngine(None), **options
            )

    def test_a_connector_beside_a_repo_root_is_refused(self, tmp_path: Any) -> None:
        with pytest.raises(ValueError, match="pass connector or repo_root, not both"):
            bridge.open_verify_engine(project_of(PLACED_ASSETS), repo_root=tmp_path, connector="duckdb")
