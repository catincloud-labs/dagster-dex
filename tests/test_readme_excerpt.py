# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""The checker that holds the README's output excerpt to the whole loop (#109).

The check itself runs in the `suite` job, against a real run of
`examples/walk_the_whole_loop.py`, because that is the only step that installs
the orchestrator, the engine and a warehouse together. This file runs in the
engine-free control and proves the checker can go red, which a green CI step on
the real output cannot show:

- the README carries exactly one marked excerpt, so the guard has something to
  check on every interpreter, not only where the example runs;
- a quoted line the run did not print is refused, and a run that printed every
  quoted line passes with its other output ignored;
- a run that printed a LONGER line is still a refusal, because a substring match
  would pass an excerpt left behind by a truncation;
- a README with no marker, two markers, an unclosed fence, an empty block or a
  line quoted twice cannot be checked, and says so rather than passing.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


guard = _load("check_readme_excerpt")

_LINES = ["leg 1 ok    : first", "leg 2 ok    : second"]


def _readme(*lines: str, marker: str = "") -> str:
    head = marker or guard.MARKER + ", in a test -->"
    return "\n".join(["# t", "", head, "```text", *lines, "```", "", "after"]) + "\n"


def test_the_readme_carries_one_marked_excerpt():
    quoted = guard.excerpt((REPO_ROOT / "README.md").read_text(encoding="utf-8"))
    assert quoted, "the README's excerpt is empty, so the CI step would check nothing"


def test_a_run_that_printed_every_quoted_line_passes():
    output = "dagster : 1.13\n" + "\n".join(_LINES) + "\n\nOK - done\n"
    assert guard.missing(guard.excerpt(_readme(*_LINES)), output) == []


def test_a_quoted_line_the_run_did_not_print_is_refused():
    output = _LINES[0] + "\nleg 2 ok    : second, reworded\n"
    assert guard.missing(guard.excerpt(_readme(*_LINES)), output) == [_LINES[1]]


def test_a_longer_printed_line_does_not_vouch_for_a_shorter_quote():
    output = "\n".join(line + " and more" for line in _LINES) + "\n"
    assert guard.missing(guard.excerpt(_readme(*_LINES)), output) == _LINES


@pytest.mark.parametrize(
    "readme, cause",
    [
        ("# t\n\n```text\nleg 1\n```\n", "found 0"),
        (_readme(*_LINES) + _readme(*_LINES), "found 2"),
        (guard.MARKER + " -->\n\n```text\nleg 1\n```\n", "directly above"),
        (guard.MARKER + " -->\n```text\nleg 1\n", "never closed"),
        (_readme(), "empty"),
        (_readme(_LINES[0], _LINES[1], _LINES[0]), "more than once"),
    ],
    ids=["no marker", "two markers", "marker not on the fence", "unclosed", "empty", "a line twice"],
)
def test_a_readme_the_checker_cannot_read_is_refused(readme: str, cause: str):
    with pytest.raises(guard.ExcerptNotFound, match=cause):
        guard.excerpt(readme)


def test_main_exits_red_and_names_the_line(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    readme = tmp_path / "README.md"
    readme.write_text(_readme(*_LINES), encoding="utf-8")
    output = tmp_path / "out.txt"

    output.write_text(_LINES[0] + "\n", encoding="utf-8")
    assert guard.main([str(output), "--readme", str(readme)]) == 1
    assert _LINES[1] in capsys.readouterr().err

    output.write_text("\n".join(_LINES) + "\n", encoding="utf-8")
    assert guard.main([str(output), "--readme", str(readme)]) == 0
