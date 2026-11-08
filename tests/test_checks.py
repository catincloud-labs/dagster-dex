# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""The spec layer: one Dagster asset check spec per declared key, none per join.

These are #180's *How we would know it worked* checks 1, 6 and 7, as the
owner's ruling on that issue amends them (keys only, joins named in a note):

1. the spec set equals the declared key set, derived from the YAML by a reader
   written here rather than by the package's parser, and moves with it when a
   declaration is removed or added;
2. no spec exists for a declared join, and each one is named in the note;
3. claim ids are equal across two reductions of one project, run in two
   processes, and differ after a declared column changes;
4. the package imports with Dagster and dex-core both absent.

**Engine-free and orchestrator-free, so this runs in the control step.**
``AssetCheckSpec`` is Dagster's type and the control does not install Dagster,
so the spec layer is handed a stand-in ``dagster`` module here. Its
``AssetCheckSpec`` takes the arguments the real one takes (its signature read
in dagster 1.13.29) and keeps what a reader reads back. The assertions read the
specs the layer returns, never a helper that feeds them. What the real Dagster
does with the specs is held by ``examples/reduce_asset_graph.py``, the CI step
that installs it.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import textwrap
import types
from pathlib import Path
from typing import Any

import pytest
import yaml

from dagster_dex import DagsterProject, DeclaredKey, ProjectDeclarations
from dagster_dex.checks import (
    CLAIM_ID,
    COLUMNS,
    MODEL,
    DeclarationCheckSpecs,
    claim_id,
    declaration_check_specs,
)

REPO = Path(__file__).resolve().parent.parent
TESTS = Path(__file__).resolve().parent

#: Dagster's name rule (``VALID_NAME_REGEX_STR``, read in dagster 1.13.29).
DAGSTER_NAME = re.compile(r"^[A-Za-z0-9_]+$")


# --- a stand-in for the orchestrator -----------------------------------------


class StandInAssetKey:
    def __init__(self, path: list[str]) -> None:
        self.path = path


class StandInAssetCheckSpec:
    """``dagster.AssetCheckSpec``'s signature, keeping what a reader reads back.

    Strict where the real one is lenient in a way this layer must not lean on:
    it takes the asset as a list of path segments only, since that is the one
    form whose meaning does not depend on how Dagster parses a string.
    """

    def __init__(
        self,
        name: str,
        *,
        asset: Any,
        description: str | None = None,
        additional_deps: Any = None,
        blocking: bool = False,
        metadata: Any = None,
        automation_condition: Any = None,
        partitions_def: Any = None,
    ) -> None:
        if not isinstance(asset, list) or not all(isinstance(s, str) for s in asset):
            raise TypeError(f"asset should be a list of path segments, got {asset!r}")
        self.name = name
        self.asset_key = StandInAssetKey(list(asset))
        self.description = description
        self.blocking = blocking
        self.metadata = dict(metadata or {})


def stand_in_dagster() -> types.ModuleType:
    module = types.ModuleType("dagster")
    setattr(module, "AssetCheckSpec", StandInAssetCheckSpec)
    setattr(module, "AssetKey", StandInAssetKey)
    return module


@pytest.fixture(autouse=True)
def _dagster(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "dagster", stand_in_dagster())


# --- a project ---------------------------------------------------------------


class _Key:
    def __init__(self, *path: str) -> None:
        self.path = path

    def __hash__(self) -> int:
        return hash(self.path)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _Key) and self.path == other.path


class _Definition:
    def __init__(self, keys: list[_Key]) -> None:
        self.keys = keys
        self.asset_deps: dict[Any, Any] = {}
        self.metadata_by_key: dict[Any, Any] = {}


#: Two of the three assets sit under a prefix, which is the case the asset keys
#: are taken for: the reduction names each model by its key's last segment.
ASSETS = [
    _Key("warehouse", "fact_orders"),
    _Key("warehouse", "dim_store"),
    _Key("dim_date"),
]

FACT_ORDERS = """\
version: 2
models:
  - name: fact_orders
    columns:
      - name: order_id
        data_tests:
          - unique
          - not_null
      - name: ship_date_key
        data_tests:
          - relationships:
              arguments:
                to: ref('dim_date')
                field: date_key
      - name: order_date_key
        data_tests:
          - relationships:
              to: ref('dim_date')
              field: date_key
"""

DIM_STORE = """\
version: 2
models:
  - name: dim_store
    data_tests:
      - dbt_utils.unique_combination_of_columns:
          arguments:
            combination_of_columns: [store_code, region]
"""

DIM_DATE = """\
version: 2
models:
  - name: dim_date
    columns:
      - name: date_key
        tests: [unique]
"""

SOURCES = {
    "declarations/fact_orders.yml": FACT_ORDERS,
    "declarations/dim_store.yml": DIM_STORE,
    "declarations/dim_date.yml": DIM_DATE,
}


def render(
    sources: dict[str, str], assets: list[_Key] | None = None
) -> DeclarationCheckSpecs:
    """Reduce the graph with ``sources`` as its declarations, and render it."""

    keys = ASSETS if assets is None else assets
    project = DagsterProject.from_asset_graph(
        [_Definition([key]) for key in keys], declaration_sources=sources
    )
    return declaration_check_specs(project.declarations(), keys)


def rendered(result: DeclarationCheckSpecs) -> set[tuple[tuple[str, ...], str, tuple[str, ...]]]:
    """What each spec says it checks: its asset, and the model and columns."""

    return {
        (tuple(spec.asset_key.path), spec.metadata[MODEL], tuple(spec.metadata[COLUMNS]))
        for spec in result.specs
    }


def _tests(entry: dict[str, Any]) -> list[Any]:
    return list(entry.get("tests") or []) + list(entry.get("data_tests") or [])


def read_yaml(
    sources: dict[str, str],
) -> tuple[set[tuple[str, tuple[str, ...]]], list[tuple[str, str, str, str]]]:
    """The declared keys and joins, read here rather than by the package.

    Reads the forms this file's fixtures use and nothing more: a bare
    ``unique``, a prefixed ``unique_combination_of_columns`` with or without
    ``arguments:``, and a ``relationships`` test to a ``ref()``.
    """

    keys: set[tuple[str, tuple[str, ...]]] = set()
    joins: list[tuple[str, str, str, str]] = []
    for text in sources.values():
        for model in yaml.safe_load(text).get("models") or []:
            for test in _tests(model):
                ((test_name, payload),) = test.items()
                if test_name.endswith("unique_combination_of_columns"):
                    arguments = payload.get("arguments", payload)
                    keys.add((model["name"], tuple(arguments["combination_of_columns"])))
            for column in model.get("columns") or []:
                for test in _tests(column):
                    if test == "unique":
                        keys.add((model["name"], (column["name"],)))
                    elif isinstance(test, dict) and "relationships" in test:
                        payload = test["relationships"]
                        arguments = payload.get("arguments", payload)
                        target = re.fullmatch(r"ref\('(\w+)'\)", arguments["to"])
                        assert target, arguments["to"]
                        joins.append(
                            (model["name"], column["name"], target.group(1), arguments["field"])
                        )
    return keys, joins


def expected(sources: dict[str, str]) -> set[tuple[tuple[str, ...], str, tuple[str, ...]]]:
    keys, _ = read_yaml(sources)
    asset_of = {key.path[-1]: tuple(key.path) for key in ASSETS}
    return {(asset_of[model], model, columns) for model, columns in keys}


def join_notes(result: DeclarationCheckSpecs) -> list[str]:
    return [note for note in result.notes if note.startswith("declared joins")]


# --- 1. the spec set is the declared key set ---------------------------------

REMOVED = {**SOURCES, "declarations/dim_date.yml": DIM_DATE.replace("tests: [unique]", "tests: [not_null]")}
ADDED = {
    **SOURCES,
    "declarations/fact_orders.yml": FACT_ORDERS.replace(
        "      - name: order_date_key\n",
        "      - name: order_number\n        data_tests: [unique]\n"
        "      - name: order_date_key\n",
    ),
}


class TestTheSpecSetIsTheDeclaredKeySet:
    @pytest.mark.parametrize("sources", [SOURCES, REMOVED, ADDED], ids=["as-declared", "one-removed", "one-added"])
    def test_one_spec_per_declared_key_on_the_asset_it_names(self, sources):
        result = render(sources)
        assert expected(sources), "the reader found no keys, so the comparison would prove nothing"
        assert rendered(result) == expected(sources)
        assert len(result.specs) == len(rendered(result)), "a key was rendered twice"

    def test_removing_a_declaration_removes_its_check(self):
        before, after = rendered(render(SOURCES)), rendered(render(REMOVED))
        assert before - after == {(("dim_date",), "dim_date", ("date_key",))}
        assert after - before == set()

    def test_adding_a_declaration_adds_a_check(self):
        before, after = rendered(render(SOURCES)), rendered(render(ADDED))
        assert after - before == {(("warehouse", "fact_orders"), "fact_orders", ("order_number",))}
        assert before - after == set()

    def test_a_prefixed_asset_gets_the_spec_on_its_whole_key(self):
        paths = {spec.metadata[MODEL]: spec.asset_key.path for spec in render(SOURCES).specs}
        assert paths["fact_orders"] == ["warehouse", "fact_orders"]
        assert paths["dim_date"] == ["dim_date"]

    def test_a_key_on_a_model_no_asset_key_ends_in_is_named_not_dropped(self):
        sources = {**SOURCES, "declarations/fact_returns.yml": DIM_DATE.replace("dim_date", "fact_returns").replace("date_key", "return_id")}
        result = render(sources)
        assert "fact_returns" not in {spec.metadata[MODEL] for spec in result.specs}
        assert [n for n in result.notes if "fact_returns(return_id)" in n and "no asset key ends in" in n]

    def test_a_key_on_a_model_two_asset_keys_end_in_is_named_not_guessed(self):
        project = DagsterProject.from_asset_graph(
            [_Definition([key]) for key in ASSETS], declaration_sources=SOURCES
        )
        keys = ASSETS + [_Key("staging", "dim_date")]
        result = declaration_check_specs(project.declarations(), keys)
        assert "dim_date" not in {spec.metadata[MODEL] for spec in result.specs}
        assert [n for n in result.notes if "dim_date(date_key) [dim_date, staging/dim_date]" in n]

    def test_a_project_whose_keys_all_land_says_nothing_about_them(self):
        """The quiet arm: a note claiming a loss that did not happen is the
        same defect pointing the other way."""

        assert render(SOURCES).notes == tuple(join_notes(render(SOURCES)))

    def test_a_claim_written_twice_is_one_check(self):
        key = DeclaredKey("dim_date", ("date_key",))
        declarations = ProjectDeclarations(format="dagster", name="x", declared_keys=(key, key))
        assert len(declaration_check_specs(declarations, ASSETS).specs) == 1


# --- 2. no check for a declared join -----------------------------------------


class TestJoinsGetNoCheck:
    def test_no_spec_exists_for_a_declared_join_and_each_is_named(self):
        result = render(SOURCES)
        _, joins = read_yaml(SOURCES)
        assert len(joins) == 2, "the fixture should declare two joins between one pair"
        from_sides = {(model, (column,)) for model, column, _, _ in joins}
        assert not {(model, columns) for _, model, columns in rendered(result)} & from_sides
        (note,) = join_notes(result)
        for model, column, target, field in joins:
            assert f"{model}({column}) -> {target}({field})" in note

    def test_a_project_declaring_only_joins_renders_no_spec(self):
        result = render({"declarations/fact_orders.yml": FACT_ORDERS.replace("          - unique\n", "")})
        assert result.specs == ()
        (note,) = join_notes(result)
        assert "fact_orders(ship_date_key) -> dim_date(date_key)" in note
        assert "fact_orders(order_date_key) -> dim_date(date_key)" in note

    def test_a_project_declaring_no_join_has_no_join_note(self):
        sources = {k: v for k, v in SOURCES.items() if not k.endswith("fact_orders.yml")}
        assert join_notes(render(sources)) == []


# --- 3. claim ids ------------------------------------------------------------

_TWO_PROCESSES = textwrap.dedent(
    """
    import json, sys
    sys.path.insert(0, {tests!r})
    import test_checks as t
    sys.modules["dagster"] = t.stand_in_dagster()
    result = t.render(t.SOURCES)
    print(json.dumps({{
        "probe": hash("dagster-dex"),
        "claims": {{
            "/".join(s.asset_key.path) + ":" + s.name: s.metadata[t.CLAIM_ID]
            for s in result.specs
        }},
    }}))
    """
)


def _claims_in_a_process(seed: str) -> dict[str, Any]:
    done = subprocess.run(
        [sys.executable, "-c", _TWO_PROCESSES.format(tests=str(TESTS))],
        capture_output=True, text=True, cwd=REPO, timeout=120,
        env={**os.environ, "PYTHONHASHSEED": seed},
    )
    assert done.returncode == 0, done.stderr
    return dict(json.loads(done.stdout))


def _claims(result: DeclarationCheckSpecs) -> dict[str, str]:
    return {spec.metadata[MODEL]: spec.metadata[CLAIM_ID] for spec in result.specs}


class TestClaimIds:
    def test_two_reductions_in_two_processes_give_the_same_claim_ids(self):
        first, second = _claims_in_a_process("1"), _claims_in_a_process("2")
        # The positive control: the two processes hash a string differently,
        # so an id built on `hash()` would differ here.
        assert first["probe"] != second["probe"]
        assert len(first["claims"]) == 3
        assert first["claims"] == second["claims"]

    def test_a_changed_column_changes_that_claim_id_only(self):
        before = _claims(render(SOURCES))
        renamed = {**SOURCES, "declarations/fact_orders.yml": FACT_ORDERS.replace("order_id", "order_key")}
        after = _claims(render(renamed))
        assert after["fact_orders"] != before["fact_orders"]
        assert {k: v for k, v in after.items() if k != "fact_orders"} == {
            k: v for k, v in before.items() if k != "fact_orders"
        }

    def test_a_changed_composite_column_changes_its_claim_id(self):
        before = _claims(render(SOURCES))
        changed = {**SOURCES, "declarations/dim_store.yml": DIM_STORE.replace("region", "area")}
        assert _claims(render(changed))["dim_store"] != before["dim_store"]

    def test_reordering_a_composite_keeps_its_claim_id_and_its_name(self):
        """The parser reads the two orders as one claim, so they are one id."""

        reordered = {**SOURCES, "declarations/dim_store.yml": DIM_STORE.replace("[store_code, region]", "[region, store_code]")}
        names = {s.metadata[CLAIM_ID]: s.name for s in render(SOURCES).specs}
        assert {s.metadata[CLAIM_ID]: s.name for s in render(reordered).specs} == names

    def test_each_claim_has_its_own_id_and_the_spec_carries_claim_id(self):
        result = render(SOURCES)
        claims = [spec.metadata[CLAIM_ID] for spec in result.specs]
        assert len(set(claims)) == len(claims)
        for spec in result.specs:
            key = DeclaredKey(spec.metadata[MODEL], tuple(spec.metadata[COLUMNS]))
            assert spec.metadata[CLAIM_ID] == claim_id(key)


# --- check names -------------------------------------------------------------


def _on_one_asset(*keys: DeclaredKey) -> DeclarationCheckSpecs:
    declarations = ProjectDeclarations(format="dagster", name="x", declared_keys=keys)
    return declaration_check_specs(declarations, [_Key("warehouse", "m")])


class TestCheckNames:
    def test_names_are_dagster_names_unique_per_asset_and_carry_every_column(self):
        specs = render(SOURCES).specs
        assert all(DAGSTER_NAME.match(spec.name) for spec in specs)
        on_asset = [(tuple(spec.asset_key.path), spec.name) for spec in specs]
        assert len(set(on_asset)) == len(on_asset)
        assert {spec.name for spec in specs} == {
            "declared_key__order_id",
            "declared_key__region__store_code",
            "declared_key__date_key",
        }

    def test_a_column_a_name_cannot_hold_is_replaced_and_the_name_suffixed(self):
        key = DeclaredKey("m", ("order id",))
        (spec,) = _on_one_asset(key).specs
        assert DAGSTER_NAME.match(spec.name)
        assert spec.name == f"declared_key__order_id__{claim_id(key)[:12]}"

    def test_two_keys_sharing_a_name_on_one_asset_are_both_suffixed(self):
        one, two = DeclaredKey("m", ("a__b", "c")), DeclaredKey("m", ("a", "b__c"))
        names = {spec.metadata[CLAIM_ID]: spec.name for spec in _on_one_asset(one, two).specs}
        assert names == {
            claim_id(one): f"declared_key__a__b__c__{claim_id(one)[:12]}",
            claim_id(two): f"declared_key__a__b__c__{claim_id(two)[:12]}",
        }

    def test_a_name_still_taken_after_the_suffix_is_named_not_rendered(self):
        one, two = DeclaredKey("m", ("a__b", "c")), DeclaredKey("m", ("a", "b__c"))
        # Its name, unsuffixed, is the name `one` takes once suffixed.
        three = DeclaredKey("m", ("a", "b", f"c__{claim_id(one)[:12]}"))
        result = _on_one_asset(one, two, three)
        names = [spec.name for spec in result.specs]
        assert len(names) == len(set(names)) == 2
        assert [n for n in result.notes if _label(three) in n and "is not rendered" in n]


def _label(key: DeclaredKey) -> str:
    return f"{key.model}({', '.join(key.columns)})"


# --- 4. the import -----------------------------------------------------------

_BLOCKED = textwrap.dedent(
    """
    import importlib, importlib.abc, json, pkgutil, sys

    BLOCKED = ("dagster", "exmergo_dex_core")

    class Block(importlib.abc.MetaPathFinder):
        def find_spec(self, name, path=None, target=None):
            if name.split(".")[0] in BLOCKED:
                raise ModuleNotFoundError(f"blocked: {name}", name=name)
            return None

    sys.meta_path.insert(0, Block())
    report = {}
    try:
        import dagster
        report["blocker"] = "dagster imported"
    except ModuleNotFoundError:
        report["blocker"] = "refused"

    import dagster_dex
    report["modules"] = sorted(
        info.name for info in pkgutil.iter_modules(dagster_dex.__path__)
    )
    for name in report["modules"]:
        importlib.import_module(f"dagster_dex.{name}")
    report["loaded"] = sorted(n for n in sys.modules if n.split(".")[0] in BLOCKED)

    from dagster_dex.checks import claim_id, declaration_check_specs
    report["claim_id"] = claim_id(dagster_dex.DeclaredKey("m", ("c",)))
    try:
        declaration_check_specs(dagster_dex.ProjectDeclarations(format="dagster", name="x"), [])
        report["specs"] = "built"
    except ImportError as exc:
        report["specs"] = str(exc)
    print(json.dumps(report))
    """
)


class TestTheImport:
    def test_the_package_imports_with_dagster_and_dex_core_absent(self):
        done = subprocess.run(
            [sys.executable, "-c", _BLOCKED],
            capture_output=True, text=True, cwd=REPO, timeout=120,
        )
        assert done.returncode == 0, done.stderr
        report = json.loads(done.stdout)
        # The positive control: the blocker refuses, so an import it let
        # through would not be reading as absent.
        assert report["blocker"] == "refused"
        assert "checks" in report["modules"] and "dex" in report["modules"]
        assert report["loaded"] == []
        assert report["claim_id"] == claim_id(DeclaredKey("m", ("c",)))
        assert "[dagster] extra" in report["specs"]
