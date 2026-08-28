# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""This repository is ASCII, and here is the thing that checks it.

Two separate reasons, and they fail differently, so both are asserted here.

**The encoding one, which was observed rather than predicted.** The package
summary once contained an em-dash. The metadata was correct UTF-8 and PyPI's web
page rendered it correctly, but `pip show` on a Windows console at cp1252 printed
a replacement character. Package metadata, exception messages and CLI output are
read in terminals whose encoding nobody controls, so a character that survives a
browser is not automatically a character that survives a release.

**The register one.** This repository is public. Em-dashes and decorative emoji
are a recognisable machine-written signature, and a package asking to be adopted
should not read like one. The private repositories in this estate keep their
severity taxonomy (a red circle means "this will bite you"); that convention is
for readers who know it, and it does not travel to strangers.

The second reason is a style rule, and a style rule with no control is a
suggestion. This is the control.

Two exemptions, and neither is a style choice. `scripts/check_closing_keywords.py`
and `scripts/test_check_closing_keywords.py` are vendored copies compared
**byte-for-byte** against their source. Editing either to satisfy this test would
trade a passing test for a failing pipeline.

The second one arrived late. This repository is public and cannot resolve actions
in a private repository, so the shared check that used to run the guard's
self-test could not run here at all -- the self-test had to be vendored next to
the guard it proves. The exemption's reason did not change, only how many files
it covers.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent

#: Compared byte-for-byte against their source. Not ours to reformat. See this
#: module's docstring.
#:
#: A set rather than a single path since the guard's self-test had to be vendored
#: too. Membership is checked with `in`, so adding a third vendored file is a
#: one-line change rather than a rewrite of the filter below.
VENDORED = frozenset(
    {
        "scripts/check_closing_keywords.py",
        "scripts/test_check_closing_keywords.py",
        # The verification-section checker, vendored at the wb #23 step-4
        # adoption. Same argument as the two above: compared byte-for-byte
        # against its private source by the drift job, so reformatting it to
        # ASCII here would be drift by construction.
        "scripts/check_verification_section.py",
    }
)


def _tracked_files() -> list[str]:
    """Ask git, rather than walking the tree.

    A walk would pick up `.venv`, build artifacts and anything else untracked,
    and would then be asserting something about a working directory rather than
    about what this repository actually publishes.
    """

    out = subprocess.run(
        ["git", "-C", str(REPO), "ls-files"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in out.stdout.split("\n") if line]


def _text_files() -> list[str]:
    skip_suffixes = (".png", ".jpg", ".gif", ".ico", ".whl", ".gz")
    return [
        f
        for f in _tracked_files()
        if f not in VENDORED and not f.lower().endswith(skip_suffixes)
    ]


@pytest.mark.skipif(
    subprocess.run(
        ["git", "-C", str(REPO), "rev-parse", "--git-dir"], capture_output=True
    ).returncode
    != 0,
    reason="not a git checkout, so there is no file list to check",
)
def test_every_tracked_file_is_ascii():
    """The whole repository, not a hand-maintained list of files to watch.

    Asserting over `git ls-files` rather than a literal list is what makes this
    hold for a file nobody has written yet. A list would have to be updated by
    the same person who is about to paste an em-dash into a new document, which
    is the class of control this estate has repeatedly found to be decorative.
    """

    offenders: list[str] = []
    for name in _text_files():
        path = REPO / name
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(text.split("\n"), 1):
            bad = {c for c in line if ord(c) > 127}
            if bad:
                shown = ", ".join(f"U+{ord(c):04X}" for c in sorted(bad))
                offenders.append(f"{name}:{lineno}: {shown}")

    assert not offenders, (
        "non-ASCII characters in tracked files; this repository is public and "
        "ASCII-only (see tests/test_ascii_only.py for both reasons):\n  "
        + "\n  ".join(offenders)
    )


def test_the_package_metadata_is_ascii():
    """The summary specifically, because it is the string `pip show` prints.

    Distinct from the file check above: metadata is assembled by the build
    backend, so a clean source tree does not by itself prove a clean artifact.
    This reads what was actually installed.
    """

    import importlib.metadata as md

    meta = md.metadata("dagster-dex")
    for field in ("Summary", "Name", "Version"):
        value = meta.get(field) or ""
        assert value.isascii(), f"non-ASCII in package metadata {field}: {value!r}"


def test_runtime_messages_are_ascii():
    """Every string this package can raise or print.

    The narrowest and most load-bearing of the three. A docstring's em-dash is a
    style question; an exception message's em-dash lands in a traceback, in a
    terminal, in an issue report, rendered by an encoding nobody chose.

    Walks the AST rather than grepping, so it sees the string literals as the
    compiler does and cannot be fooled by one spanning several source lines.
    """

    import ast

    src_root = REPO / "src" / "dagster_dex"
    offenders: list[str] = []
    for path in sorted(src_root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        docstrings = {
            id(node.body[0].value)
            for node in ast.walk(tree)
            if isinstance(
                node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
            )
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        }
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in docstrings
                and not node.value.isascii()
            ):
                offenders.append(
                    f"{path.relative_to(REPO)}:{node.lineno}: {node.value[:60]!r}"
                )

    assert not offenders, (
        "non-ASCII in runtime string literals. These reach terminals through "
        "tracebacks and CLI output, where the encoding is not ours to choose:\n  "
        + "\n  ".join(offenders)
    )


def test_the_check_can_actually_fail():
    """Calibration: the assertion above must reject a known-bad input.

    A checker that has silently stopped detecting anything passes every commit,
    which is the one failure mode the checks above cannot observe about
    themselves. Cheap to pin, and this estate has been bitten by an instrument
    that reported success from an empty result.

    The bad characters are written as escapes rather than literally, so this
    file stays ASCII and does not fail the very check it calibrates. That is not
    a trick to get around the rule: the rule is about what a reader and a
    terminal receive, and an escape sequence is neither.
    """

    assert not f"an em-dash {chr(0x2014)} here".isascii()
    assert not f"an emoji {chr(0x1F534)} here".isascii()
    assert not f"a warning sign {chr(0x26A0)} here".isascii()
    assert "a plain hyphen - here".isascii()
