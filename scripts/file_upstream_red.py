#!/usr/bin/env python3
# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""Turn a red run against `exmergo/dex` main into ONE issue here, or into nothing.

Run by `.github/workflows/upstream-main.yml` after the two contract files have
failed against upstream `main`. Never by a green run: green is reported nowhere,
and this script is not reached.

    python scripts/file_upstream_red.py --junit junit.xml \\
        --upstream-sha <sha> --run-url <url> [--last-green-sha <sha>] [--dry-run]

**What the issue is keyed on, and why the test id alone is not enough.** The
coverage guard in `tests/test_upstream_contract.py`,
`test_every_contract_upstream_ships_is_mixed_in_or_explicitly_declined`, is ONE
test id that goes red on every new upstream contract: it fired for 1.9.0's
`SemanticCatalogContract` (#64) and for 1.11.0's `SemanticCatalogSourceContract`
(#86). Against a moving `main` it goes red the day a contract is added and stays
red until the contract is declined by name here. De-duplicated on the test id, a
second new contract arriving while the first's issue is open would be absorbed
into it silently - the news would be the parameter, and the key would not carry
it. So that guard's key is the test id PLUS the bracketed list its assertion
message names. Parametrised tests need no such table: pytest already writes the
parameter into the id (`test_x[b]`), so the id carries the news by itself.

**Fail closed.** A red step that produced no junit file, or a junit file with no
failing testcase, is not "nothing to report" - it is the install or the
collection breaking before pytest could judge anything, and that is the case a
red-only job most needs to surface. It is filed under its own key.

**What is de-duplicated against.** Every OPEN issue carrying the label, read by
the marker lines this script writes into each body. A closed issue stops
counting: a red that returns after its issue was closed is news again.

The `gh` calls live in `main` alone; everything above it is a pure function of
its inputs so `tests/test_file_upstream_red.py` can prove the keying, the
de-duplication and the fail-closed arm without a token.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

#: The repository under test. Named once; the compare and commit links below
#: are built from it.
UPSTREAM = "exmergo/dex"

#: The label every issue this script files carries, and the label it reads back
#: to find the open ones. Both directions use the same string on purpose.
LABEL = "upstream:dex"

#: The marker line that carries a key in an issue body. An HTML comment renders
#: as nothing, so a reader sees prose and `gh issue list --json body` sees keys.
KEY_MARKER = "upstream-main-key:"
_KEY_LINE = re.compile(r"<!--\s*" + re.escape(KEY_MARKER) + r"\s*(\S.*?)\s*-->")

#: Test names whose id is stable while the news is in the message, with the
#: pattern that extracts the news. One entry, argued in the module docstring.
#: Both arms of the coverage guard name a bracketed list, so one pattern reads
#: either arm.
_DETAIL: dict[str, re.Pattern[str]] = {
    "test_every_contract_upstream_ships_is_mixed_in_or_explicitly_declined": re.compile(
        r"(?:declines|no longer ships): (\[[^\]]*\])"
    ),
}

#: The key a red run gets when pytest left nothing to key on. Deliberately free
#: of the upstream sha, so a persistent install failure is one issue rather than
#: one per day.
NO_RESULTS_KEY = "run::failed-without-a-failing-test"

#: Issue titles take the commit form `type(scope): summary`, at most this long.
#: `scripts/check_pr_title.py` holds the same number for pull requests; the
#: test for this file judges the generated title with that checker rather than
#: trusting the two to agree.
_TITLE_MAX = 100

GhRunner = Callable[[Sequence[str]], str]


@dataclass(frozen=True)
class Red:
    """One failing or erroring testcase, or the run itself when there is none."""

    test_id: str
    kind: str
    message: str
    text: str

    @property
    def key(self) -> str:
        """The de-duplication key: the id, plus the news when the id hides it."""

        name = self.test_id.rsplit("::", 1)[-1]
        bare = name.split("[", 1)[0]
        pattern = _DETAIL.get(bare)
        if pattern is None:
            return self.test_id
        found = pattern.search(self.message)
        detail = found.group(1) if found else "<unparsed>"
        return f"{self.test_id}::{detail}"

    @property
    def short_name(self) -> str:
        return self.test_id.rsplit("::", 1)[-1]


@dataclass(frozen=True)
class Plan:
    """What a run's reds mean against the issues already open."""

    new: tuple[Red, ...]
    tracked: tuple[tuple[Red, int], ...]

    @property
    def files_an_issue(self) -> bool:
        return bool(self.new)


def parse_junit(path: Path) -> list[Red]:
    """Every failing or erroring testcase in a junit file, in document order.

    A missing file, an unparseable one, or one with nothing red in it yields the
    single fail-closed `Red` under `NO_RESULTS_KEY`: the step was red, so
    something has to be filed, and "pytest reported no failure" is the report.
    """

    if not path.is_file():
        return [_no_results(f"no junit file at {path}: pytest did not get as far as writing one")]
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        return [_no_results(f"junit file at {path} is not well-formed XML: {exc}")]

    reds: list[Red] = []
    for case in root.iter("testcase"):
        classname = case.get("classname", "")
        name = case.get("name", "")
        test_id = f"{classname}::{name}" if classname else name
        for kind in ("failure", "error"):
            node = case.find(kind)
            if node is not None:
                reds.append(
                    Red(test_id, kind, node.get("message", "") or "", (node.text or "").strip())
                )
    if not reds:
        return [_no_results("the step failed but no testcase in the junit file reports a failure or an error")]
    return reds


def _no_results(why: str) -> Red:
    return Red(NO_RESULTS_KEY, "run", why, "")


def open_issue_keys(issues: Sequence[dict[str, object]]) -> dict[str, int]:
    """Key -> issue number, read from the marker lines in every open body.

    The lowest issue number wins a key that appears in two bodies, so the
    tracked line points at the issue that was filed first.
    """

    keys: dict[str, int] = {}
    for issue in sorted(issues, key=lambda i: int(str(i.get("number", 0)))):
        number = int(str(issue.get("number", 0)))
        body = str(issue.get("body") or "")
        for found in _KEY_LINE.findall(body):
            keys.setdefault(found, number)
    return keys


def plan(reds: Sequence[Red], open_keys: dict[str, int]) -> Plan:
    new = tuple(r for r in reds if r.key not in open_keys)
    tracked = tuple((r, open_keys[r.key]) for r in reds if r.key in open_keys)
    return Plan(new, tracked)


def title(reds: Sequence[Red], upstream_sha: str) -> str:
    """`type(scope): summary`, at most `_TITLE_MAX` characters."""

    where = f"{UPSTREAM}@{upstream_sha[:7]}" if upstream_sha else f"{UPSTREAM}@main"
    first = reds[0]
    if first.kind == "run":
        summary = f"{where} failed before pytest reported a test"
    elif len(reds) == 1:
        summary = f"{where} fails {first.short_name}"
    else:
        summary = f"{where} fails {len(reds)} tests, first {first.short_name}"
    full = f"test(upstream): {summary}"
    # Cut, never elided: `...` reads as a trailing period to the title rule,
    # and the body carries the whole id anyway.
    return full[:_TITLE_MAX].rstrip(" .")


def _range_line(upstream_sha: str, last_green_sha: str) -> str:
    if not upstream_sha:
        return "- upstream commit: unknown (the resolve step did not produce one)"
    commit = f"- upstream commit: [`{upstream_sha[:7]}`](https://github.com/{UPSTREAM}/commit/{upstream_sha})"
    if not last_green_sha:
        return (
            commit
            + "\n- since last green: no green run of this workflow is on record, so the "
            "range cannot be named. Nothing is inferred in its place."
        )
    if last_green_sha == upstream_sha:
        return (
            commit
            + "\n- since last green: the SAME upstream commit was green on the last run. "
            "Upstream did not move; look at this tree and at the run environment first."
        )
    compare = f"https://github.com/{UPSTREAM}/compare/{last_green_sha}...{upstream_sha}"
    return commit + f"\n- since last green: [`{last_green_sha[:7]}...{upstream_sha[:7]}`]({compare})"


def body(the_plan: Plan, upstream_sha: str, last_green_sha: str, run_url: str) -> str:
    """The issue body: what failed, where upstream stands, and the keys."""

    lines = [
        "Red-only run of `tests/test_upstream_contract.py` and `tests/test_dex_bridge.py` "
        f"against `{UPSTREAM}` `main`. Filed by `scripts/file_upstream_red.py`; see #74.",
        "",
        _range_line(upstream_sha, last_green_sha),
        f"- run: {run_url}",
        "",
        "Whose red this is - a contract moved upstream, or this format leaned on an "
        "unpromised behaviour - is decided per red by the owner, not by this job.",
        "",
        "## Failing assertions",
    ]
    for red in the_plan.new:
        lines += _red_section(red)
    if the_plan.tracked:
        lines += ["", "## Already tracked", ""]
        for red, number in the_plan.tracked:
            lines.append(f"- `{red.test_id}` is open as #{number}")
            lines.append(f"<!-- {KEY_MARKER} {red.key} -->")
    return "\n".join(lines) + "\n"


def _red_section(red: Red) -> list[str]:
    if red.kind == "run":
        return ["", f"### the run itself ({red.message})", f"<!-- {KEY_MARKER} {red.key} -->"]
    section = ["", f"### `{red.test_id}` ({red.kind})", "", "```text", red.message.strip(), "```"]
    if red.text:
        section += ["", "<details><summary>full report</summary>", "", "```text", red.text, "```", "", "</details>"]
    section.append(f"<!-- {KEY_MARKER} {red.key} -->")
    return section


def _gh(argv: Sequence[str]) -> str:
    result = subprocess.run(["gh", *argv], capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f"gh {' '.join(argv)} failed ({result.returncode}):\n{result.stderr}")
    return result.stdout


def main(argv: Sequence[str] | None = None, gh: GhRunner = _gh) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--junit", required=True, type=Path)
    parser.add_argument("--upstream-sha", default="")
    parser.add_argument("--last-green-sha", default="")
    parser.add_argument("--run-url", required=True)
    parser.add_argument("--dry-run", action="store_true", help="render, file nothing")
    args = parser.parse_args(argv)

    reds = parse_junit(args.junit)
    open_issues = json.loads(
        gh(["issue", "list", "--state", "open", "--label", LABEL, "--limit", "200",
            "--json", "number,body"])
    )
    the_plan = plan(reds, open_issue_keys(open_issues))
    for red, number in the_plan.tracked:
        print(f"already tracked: {red.key} -> #{number}", file=sys.stderr)
    if not the_plan.files_an_issue:
        print("every red is already open; filing nothing", file=sys.stderr)
        return 0

    issue_title = title(reds, args.upstream_sha)
    issue_body = body(the_plan, args.upstream_sha, args.last_green_sha, args.run_url)
    if args.dry_run:
        print(issue_title)
        print(issue_body)
        return 0
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as handle:
        handle.write(issue_body)
        body_path = handle.name
    url = gh(["issue", "create", "--title", issue_title, "--label", LABEL, "--body-file", body_path])
    print(f"filed: {url.strip()}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
