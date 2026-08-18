# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""A command in a document is a claim, and nothing here checked the claims.

Every markdown file in this repository tells a reader to run something, and says
or implies that it is what CI runs. Those strings were unverified. Two defects
were sitting in them when this file was written, and they failed in opposite
directions:

  - `AGENTS.md` ended its Dagster check `python -c "..."`, with the ellipsis
    standing in for a script nobody wrote out. `...` is a bare `Ellipsis`, so
    that command RUNS, exits 0, and evaluates a constant. A reader copying it
    installed an orchestrator, saw the exit code CI produces, and checked
    nothing.
  - `CONTRIBUTING.md` carried a second, different copy of the same check as an
    inline eight-line script. That one worked, which is why it survived, and it
    still was not what CI runs.

=> **The runnable-but-wrong command is the expensive kind.** A broken one is
fixed by the first person who tries it. One that prints a plausible answer has
nothing pushing back on it, which is why the first defect outlived several
readings of the file it was in.

**This does not run the commands**, deliberately. Running them is re-running the
whole pipeline: the same suites, the same engine downloads, the same orchestrator
install, for a second time per pull request, and the parse is where these defects
live rather than the execution. What it asserts is that each command is
well-formed and points at something real - which is exactly what a reader needs
before they trust the output.

A sibling repository shipped three commands with a literal backslash-n where a
line continuation was meant, under a heading claiming they mirrored CI. Its guard
counted version pins per file and was green throughout, because counting pins
cannot see a broken command. That is the same shape as the ellipsis above and is
covered here too.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Fence labels that mean "this is an instruction". A `python` or `yaml` fence is
#: illustration; a shell fence is something a reader will copy, and this file is
#: about the ones a reader copies.
#:
#: **This is a scope list, and a scope list fails OPEN.** Relabelling a fence
#: takes every command inside it out of scope silently, and the guard goes green
#: rather than red - measured, by relabelling one and watching every other
#: assertion here still pass. That is what
#: `test_no_command_hides_in_a_fence_this_file_does_not_scan` exists to backstop.
#:
#: **One list, two readers.** `_FENCE` below is built from it rather than spelling
#: the labels a second time: two copies of a list is one list and one stale claim,
#: and the stale one here would be the copy that decides what goes unchecked.
_SHELL_LABELS = frozenset({"bash", "sh", "shell", "zsh", "console", "terminal"})

_FENCE = re.compile(
    r"```(?:%s)\n(.*?)```" % "|".join(sorted(_SHELL_LABELS)), re.S
)

#: A command this repository asks a reader to run. `DEX_UPSTREAM_CONTRACT_REQUIRED`
#: is here because the one command that needs it carries it as a prefix, and a
#: pattern anchored on `uv` alone would skip exactly the command whose whole point
#: is that a missing variable makes it meaningless.
_COMMAND = ("uv run", "DEX_UPSTREAM_CONTRACT_REQUIRED", "python scripts/", "npx ")

#: Markers standing in for content the writer did not fill in. Each one is
#: syntactically fine where it appears, which is the problem: `python -c "..."`
#: and `python -c "<your code>"` differ in that the first one SUCCEEDS.
_ELISIONS = ('"..."', "'...'", "<...>", "...>", "TODO", "FIXME", "your-", "YOUR_")


def _markdown_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "*.md"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def _commands() -> list[tuple[str, str]]:
    """Every documented command, with the file it came from.

    Continuations are joined first, so a command spanning four lines is one
    command here. That join is also what makes the literal-backslash-n defect
    visible: a real continuation disappears into the join, and a literal `\\n`
    survives it as two characters in the middle of a line.
    """

    found: list[tuple[str, str]] = []
    for name in _markdown_files():
        text = (REPO_ROOT / name).read_text(encoding="utf-8")
        for block in _FENCE.findall(text):
            for line in block.replace("\\\n", " ").splitlines():
                stripped = line.strip()
                if stripped.startswith(_COMMAND):
                    found.append((name, " ".join(stripped.split())))
    return found


def test_there_are_documented_commands_to_check():
    """The guard's own floor.

    Every assertion below iterates over what `_commands()` found, so a pattern
    that stopped matching would leave all of them vacuously true and this file
    green while checking nothing. That is the failure a scanner cannot see about
    itself.
    """

    commands = _commands()
    assert len(commands) >= 6, (
        f"only {len(commands)} documented commands found, which is fewer than this "
        "repository has. The fence or command patterns have probably stopped "
        "matching, and every assertion in this file is vacuous when they do"
    )
    assert {name for name, _ in commands} >= {"AGENTS.md", "CONTRIBUTING.md"}


def test_no_command_hides_in_a_fence_this_file_does_not_scan():
    """The scope list, checked against the corpus rather than trusted.

    `_FENCE` is a hand-maintained list of fence labels deciding what this file
    looks at, and **a scope list fails open**: a label it stops matching leaves no
    failure behind, only fewer assertions. Measured rather than feared -
    relabelling one ```bash fence took its commands out of scope and every other
    assertion here still passed.

    **Checked per fence, not per file**, and the difference is the whole value.
    The first version of this asked whether each file naming `uv run` yielded at
    least one command; relabelling a single fence in a file that has several left
    it green, because the other fences kept the file in the answer. A
    file-granular check on a fence-granular defect is an instrument narrower than
    its promise, which is this estate's most repeated defect shape and was worth
    hitting once here to see.

    So this reads every fence of every label, and refuses one that holds a command
    while sitting outside `_FENCE`. Widen the label list; do not move the command.
    """

    any_fence = re.compile(r"```([A-Za-z0-9_+-]*)\n(.*?)```", re.S)

    hidden: list[str] = []
    for name in _markdown_files():
        text = (REPO_ROOT / name).read_text(encoding="utf-8")
        for label, block in any_fence.findall(text):
            if label.lower() in _SHELL_LABELS:
                continue
            for line in block.replace("\\\n", " ").splitlines():
                if line.strip().startswith(_COMMAND):
                    hidden.append(f"{name}: ```{label or '(none)'} -> {line.strip()[:70]}")

    assert not hidden, (
        "these commands sit in fences this file does not scan, so nothing here "
        "checks them:\n  " + "\n  ".join(hidden) + "\n"
        "Relabel the fence to a shell label, or add the label to `_SHELL_LABELS` "
        "- which is the one list both this test and `_FENCE` read."
    )


@pytest.mark.parametrize("name, command", _commands(), ids=lambda v: v[:40])
def test_no_documented_command_is_an_elision(name: str, command: str):
    """A placeholder that runs is worse than one that does not.

    The case this was written for: `python -c "..."` succeeds. So does
    `python -c "<your code here>"` fail loudly, which is why that spelling was
    never the problem. The refusal is on the ones a shell accepts.
    """

    for marker in _ELISIONS:
        assert marker not in command, (
            f"{name} documents a command containing {marker!r}, which is a "
            f"placeholder rather than a command:\n  {command}\n"
            "If it is meant to be run, write it out. If it is meant to be "
            "illustration, move it out of a shell fence - a reader copies what "
            "is in one, and `python -c \"...\"` exits 0 having checked nothing."
        )


@pytest.mark.parametrize("name, command", _commands(), ids=lambda v: v[:40])
def test_no_documented_command_carries_a_literal_newline_escape(name: str, command: str):
    """A `\\n` where a continuation belonged, which is unrunnable and looks fine.

    Continuations are joined before this sees the command, so a real one is gone
    by now and a literal two-character `\\n` is still here. A sibling repository
    shipped three of these under a heading claiming they mirrored CI.
    """

    assert "\\n" not in command, (
        f"{name} documents a command containing a literal backslash-n, which is "
        f"almost certainly a line continuation that lost its newline:\n  {command}"
    )


@pytest.mark.parametrize("name, command", _commands(), ids=lambda v: v[:40])
def test_every_script_a_documented_command_names_exists(name: str, command: str):
    """The path half. A command can be well-formed and name a deleted file.

    This is the arm that catches a rename: the pin guard beside this one holds
    every command's engine version coherent and has nothing to say about whether
    the script the command runs is still there.
    """

    for token in command.split():
        # A path can arrive as a bare argument or as a flag's value
        # (`--ignore=tests/x.py`), so the flag is stripped before the path is
        # resolved. The first draft did not do this and reported
        # `--ignore=tests/test_dex_bridge.py` as a missing file, which is the
        # harness being wrong about a file that is right there - a false positive
        # in a guard whose whole subject is claims that do not hold up.
        candidate = token.split("=", 1)[-1]
        if candidate.endswith(".py") and "/" in candidate:
            assert (REPO_ROOT / candidate).is_file(), (
                f"{name} documents a command running {candidate!r}, which does "
                f"not exist:\n  {command}"
            )


@pytest.mark.parametrize("name, command", _commands(), ids=lambda v: v[:40])
def test_every_uv_run_documented_here_is_project_isolated(name: str, command: str):
    """`--no-project` is not style, and omitting it changes what gets tested.

    Without it `uv run` resolves this repository as a project and creates a
    `.venv` here, so the command runs against a different environment from the
    one it claims to reproduce - and CI, which has no `.venv`, keeps passing.
    Every `uv run` in this repository's own documents carries it.
    """

    if command.startswith("uv run") or " uv run" in command:
        assert "--no-project" in command, (
            f"{name} documents a `uv run` without `--no-project`:\n  {command}\n"
            "That resolves this repository as a project and builds a .venv, so "
            "the reader is not running what CI ran"
        )
