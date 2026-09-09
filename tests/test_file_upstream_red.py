# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""The filer behind the red-only run against `exmergo/dex` main (#74).

Runs in the engine-free control: nothing here needs dex-core, pytest's junit
output is the input, and `gh` is a callable handed in. What is proved:

- the de-duplication key carries the news when the test id hides it, and only
  then (the coverage guard's contract name; a parametrised id already does);
- a run whose reds are all open files nothing, and one new key files once;
- the fail-closed arm: a red step with no junit, or a junit with no red in it,
  is filed rather than swallowed;
- the generated title passes the repository's own title rule, judged by the
  vendored checker rather than by a second copy of its numbers;
- both arms of the "since last green" line, because a range this job cannot
  name must say so rather than invent one.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # A frozen dataclass under `from __future__ import annotations` resolves
    # its field types through `sys.modules[cls.__module__]`; a module executed
    # from a spec without being registered there fails at class creation.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


filer = _load("file_upstream_red")
titles = _load("check_pr_title")

GUARD = "test_every_contract_upstream_ships_is_mixed_in_or_explicitly_declined"
SHA_A = "2be745c6f2e5a4b743b11fe14048c7601be669f2"
SHA_B = "0123456789abcdef0123456789abcdef01234567"

#: The shape pytest 8.4.1 writes under `-o junit_family=xunit2`, taken from a
#: real run rather than typed from memory: `message` carries the whole
#: assertion text, the element text carries the report.
_JUNIT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites name="pytest tests"><testsuite name="pytest" errors="0" failures="{failures}" tests="4">
{cases}
</testsuite></testsuites>
"""

_OK = '<testcase classname="tests.test_dex_bridge.TestX" name="test_ok" time="0.001" />'


def _guard_case(contracts: str) -> str:
    return (
        f'<testcase classname="tests.test_upstream_contract" name="{GUARD}" time="0.001">'
        '<failure message="AssertionError: dex-core ships conformance contracts this format '
        f"neither implements nor declines: {contracts}. Mix one in, or add it to _DECLINED "
        'with the reason.&#10;assert not [...]">E   AssertionError: ...</failure></testcase>'
    )


def _param_case(param: str) -> str:
    return (
        f'<testcase classname="tests.test_dex_bridge" name="test_param[{param}]" time="0.001">'
        f"<failure message=\"AssertionError: assert '{param}' == 'a'\">report</failure></testcase>"
    )


def _error_case() -> str:
    return (
        '<testcase classname="" name="test_dex_bridge" time="0.000">'
        '<error message="collection failure">ImportError while importing test module</error>'
        "</testcase>"
    )


def _write(tmp_path: Path, *cases: str) -> Path:
    path = tmp_path / "junit.xml"
    path.write_text(_JUNIT.format(failures=len(cases), cases="\n".join(cases)), encoding="utf-8")
    return path


class TestParsing:
    def test_failures_and_collection_errors_are_both_read(self, tmp_path):
        """A collection error interrupts the whole run and is the ONLY testcase
        pytest writes for it. Reading `failure` alone would see an empty run."""

        reds = filer.parse_junit(_write(tmp_path, _OK, _param_case("b"), _error_case()))
        assert [(r.test_id, r.kind) for r in reds] == [
            ("tests.test_dex_bridge::test_param[b]", "failure"),
            ("test_dex_bridge", "error"),
        ]

    def test_a_passing_case_is_not_a_red(self, tmp_path):
        reds = filer.parse_junit(_write(tmp_path, _OK, _param_case("b")))
        assert len(reds) == 1


class TestTheKey:
    def test_the_coverage_guard_key_carries_the_contract_name(self, tmp_path):
        """The collision #74's review measured: one id, two upstream events."""

        first = filer.parse_junit(_write(tmp_path, _guard_case("['SemanticCatalogContract']")))[0]
        second = filer.parse_junit(
            _write(tmp_path, _guard_case("['SemanticCatalogSourceContract']"))
        )[0]
        assert first.test_id == second.test_id, "same id is the premise"
        assert first.key != second.key
        assert first.key.endswith("::['SemanticCatalogContract']")

    def test_the_stale_arm_of_the_guard_is_read_too(self):
        red = filer.Red(
            f"tests.test_upstream_contract::{GUARD}",
            "failure",
            "AssertionError: _DECLINED names contracts dex-core no longer ships: ['Gone']. A "
            "decline that outlived its contract is an allowance with nothing behind it",
            "",
        )
        assert red.key.endswith("::['Gone']")

    def test_an_unparsed_guard_message_still_keys_rather_than_raising(self):
        red = filer.Red(f"x::{GUARD}", "failure", "something else entirely", "")
        assert red.key == f"x::{GUARD}::<unparsed>"

    def test_any_other_test_is_keyed_on_its_id_alone(self, tmp_path):
        """Parametrised ids already carry the parameter; adding a detail table
        entry for them would be a second copy of what pytest wrote."""

        red = filer.parse_junit(_write(tmp_path, _param_case("b")))[0]
        assert red.key == "tests.test_dex_bridge::test_param[b]"
        other = filer.parse_junit(_write(tmp_path, _param_case("c")))[0]
        assert other.key != red.key


class TestFailClosed:
    def test_a_missing_junit_file_is_filed_not_swallowed(self, tmp_path):
        reds = filer.parse_junit(tmp_path / "absent.xml")
        assert [r.key for r in reds] == [filer.NO_RESULTS_KEY]
        assert "absent.xml" in reds[0].message

    def test_a_junit_with_nothing_red_in_it_is_filed_too(self, tmp_path):
        """The step was red or this script would not run; a file saying
        "all green" is then a report about the step, not about the tests."""

        reds = filer.parse_junit(_write(tmp_path, _OK))
        assert [r.key for r in reds] == [filer.NO_RESULTS_KEY]

    def test_malformed_xml_is_filed(self, tmp_path):
        path = tmp_path / "junit.xml"
        path.write_text("<testsuites><unclosed", encoding="utf-8")
        assert filer.parse_junit(path)[0].key == filer.NO_RESULTS_KEY

    def test_the_no_results_key_holds_no_sha(self):
        """Keyed on the sha, a persistent install failure would file daily."""

        assert SHA_A[:7] not in filer.NO_RESULTS_KEY


def _issue(number: int, *keys: str) -> dict[str, object]:
    lines = [f"<!-- {filer.KEY_MARKER} {k} -->" for k in keys]
    return {"number": number, "body": "prose\n" + "\n".join(lines) + "\n"}


class TestDeDuplication:
    def test_open_bodies_are_read_back_by_marker(self):
        keys = filer.open_issue_keys([_issue(7, "a::b"), _issue(9, "c::d", "a::b")])
        assert keys == {"a::b": 7, "c::d": 9}, "the earliest issue owns a repeated key"

    def test_a_body_without_markers_tracks_nothing(self):
        assert filer.open_issue_keys([{"number": 3, "body": "hand-written, no keys"}]) == {}
        assert filer.open_issue_keys([{"number": 4, "body": None}]) == {}

    def test_all_reds_open_files_nothing(self, tmp_path):
        reds = filer.parse_junit(_write(tmp_path, _param_case("b")))
        the_plan = filer.plan(reds, {reds[0].key: 12})
        assert not the_plan.files_an_issue
        assert the_plan.tracked == ((reds[0], 12),)

    def test_one_new_key_files_once_and_names_the_tracked_ones(self, tmp_path):
        reds = filer.parse_junit(_write(tmp_path, _param_case("b"), _param_case("c")))
        the_plan = filer.plan(reds, {reds[0].key: 12})
        assert the_plan.files_an_issue
        assert the_plan.new == (reds[1],)
        text = filer.body(the_plan, SHA_A, "", "https://run")
        assert "is open as #12" in text
        # Every key of the run rides in the new body, tracked ones included, so
        # the red stays de-duplicated after the older issue closes.
        assert text.count(filer.KEY_MARKER) == 2


class TestTheRendering:
    @pytest.mark.parametrize(
        "cases",
        [
            (_guard_case("['SemanticCatalogSourceContract']"),),
            (_param_case("b"), _param_case("c")),
            (_error_case(),),
            (),
        ],
        ids=["guard", "two", "collection-error", "no-results"],
    )
    def test_the_title_passes_the_repository_title_rule(self, tmp_path, cases):
        """Judged by `scripts/check_pr_title.py`, whose cap and type list are the
        rule; a copy of those numbers here would be the stale one."""

        reds = filer.parse_junit(_write(tmp_path, *cases))
        text = filer.title(reds, SHA_A)
        assert titles.judge(text) == [], text
        assert text.startswith("test(upstream): exmergo/dex@2be745c")

    def test_a_long_test_name_is_trimmed_rather_than_refused(self):
        red = filer.Red("tests.x::" + "a" * 150, "failure", "m", "")
        text = filer.title([red], SHA_A)
        assert len(text) == 100
        assert titles.judge(text) == [], text

    def test_no_sha_names_the_branch_rather_than_a_blank(self):
        red = filer.Red("tests.x::test_y", "failure", "m", "")
        assert "exmergo/dex@main fails test_y" in filer.title([red], "")

    def test_the_body_quotes_the_assertion_and_links_the_commit(self, tmp_path):
        reds = filer.parse_junit(_write(tmp_path, _guard_case("['SemanticCatalogSourceContract']")))
        text = filer.body(filer.plan(reds, {}), SHA_A, "", "https://run/1")
        assert "neither implements nor declines: ['SemanticCatalogSourceContract']" in text
        assert f"https://github.com/exmergo/dex/commit/{SHA_A}" in text
        assert "https://run/1" in text
        assert f"<!-- {filer.KEY_MARKER} {reds[0].key} -->" in text

    def test_the_range_has_three_arms_and_none_of_them_guesses(self):
        empty = filer.plan([], {})
        unknown = filer.body(empty, SHA_A, "", "u")
        assert "no green run of this workflow is on record" in unknown
        assert "compare" not in unknown
        same = filer.body(empty, SHA_A, SHA_A, "u")
        assert "SAME upstream commit" in same
        moved = filer.body(empty, SHA_B, SHA_A, "u")
        assert f"https://github.com/exmergo/dex/compare/{SHA_A}...{SHA_B}" in moved

    def test_no_upstream_sha_is_said_rather_than_linked(self):
        text = filer.body(filer.plan([], {}), "", SHA_A, "u")
        assert "upstream commit: unknown" in text
        assert "github.com/exmergo/dex/commit/" not in text


class TestMain:
    """The thin layer: which `gh` calls happen, with what."""

    def _gh(self, open_issues: list[dict[str, object]]):
        calls: list[list[str]] = []

        def fake(argv):
            calls.append(list(argv))
            if argv[:2] == ["issue", "list"]:
                return json.dumps(open_issues)
            if argv[:2] == ["issue", "create"]:
                return "https://github.com/o/r/issues/99\n"
            raise AssertionError(f"unexpected gh call: {argv}")

        return fake, calls

    def test_a_new_red_creates_one_labelled_issue(self, tmp_path):
        junit = _write(tmp_path, _param_case("b"))
        fake, calls = self._gh([])
        rc = filer.main(["--junit", str(junit), "--upstream-sha", SHA_A, "--run-url", "u"], gh=fake)
        assert rc == 0
        create = [c for c in calls if c[:2] == ["issue", "create"]]
        assert len(create) == 1
        assert filer.LABEL in create[0]
        body_file = Path(create[0][create[0].index("--body-file") + 1])
        assert filer.KEY_MARKER in body_file.read_text(encoding="utf-8")

    def test_an_open_red_creates_nothing(self, tmp_path):
        junit = _write(tmp_path, _param_case("b"))
        key = filer.parse_junit(junit)[0].key
        fake, calls = self._gh([_issue(5, key)])
        rc = filer.main(["--junit", str(junit), "--upstream-sha", SHA_A, "--run-url", "u"], gh=fake)
        assert rc == 0
        assert [c[:2] for c in calls] == [["issue", "list"]]

    def test_the_list_reads_only_open_issues_with_the_label(self, tmp_path):
        """A closed issue must not absorb a returning red."""

        junit = _write(tmp_path, _param_case("b"))
        fake, calls = self._gh([])
        filer.main(["--junit", str(junit), "--run-url", "u", "--dry-run"], gh=fake)
        listing = calls[0]
        assert "--state" in listing and listing[listing.index("--state") + 1] == "open"
        assert listing[listing.index("--label") + 1] == filer.LABEL

    def test_dry_run_files_nothing(self, tmp_path, capsys):
        junit = _write(tmp_path, _param_case("b"))
        fake, calls = self._gh([])
        filer.main(["--junit", str(junit), "--run-url", "u", "--dry-run"], gh=fake)
        assert [c[:2] for c in calls] == [["issue", "list"]]
        assert "test(upstream):" in capsys.readouterr().out
