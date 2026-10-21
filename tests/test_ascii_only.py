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

There is no exemption, since 2026-09-07. Until then
`scripts/check_verification_section.py` was skipped here: a vendored copy
compared **byte-for-byte** against its source, so editing it to satisfy this
test would have traded a passing test for a failing pipeline. The closing-keyword
guard and its self-test were skipped on the same argument until 2026-09-04. Each
exemption ended the same way, with the source scrubbed to ASCII and re-vendored
(#77, then #85), and the skip set left with the last entry rather than staying
empty, because an entry in it can never again be the right fix: a byte copy is
fixed at its source, so a non-ASCII byte arriving in a re-vendor is a defect in
the source, and this test is the first thing to see it. An empty set kept for
that case would be a mechanism whose every future use is the wrong answer.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent


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
        if not f.lower().endswith(skip_suffixes)
    ]


def _offenders_in(name: str, path: pathlib.Path) -> list[str]:
    """Every line of one tracked file that is not ASCII, read as bytes.

    The file is split on LF and each line decoded on its own. A valid
    multi-byte UTF-8 sequence never contains 0x0A, so the split never cuts a
    character, and one undecodable line cannot hide another line.

    A line that decodes is reported by the characters it holds, `U+2014`. A
    line that does not is reported by each byte above 0x7F and that byte's
    offset in the file, counted from 0. Until #128 a file that did not decode
    was skipped whole, so the em dash as cp1252 writes it, a lone 0x97, passed
    the check written to refuse em dashes, and hid every valid one in the same
    file. A file that cannot be read is reported too: an unreadable file is not
    a clean one.
    """

    try:
        data = path.read_bytes()
    except OSError as exc:
        return [f"{name}: unreadable ({type(exc).__name__})"]
    offenders: list[str] = []
    start = 0
    for lineno, raw in enumerate(data.split(b"\n"), 1):
        try:
            line = raw.decode("utf-8")
        except UnicodeDecodeError:
            shown = ", ".join(
                f"0x{byte:02X} at byte {start + i}"
                for i, byte in enumerate(raw)
                if byte > 127
            )
            offenders.append(f"{name}:{lineno}: {shown} (not UTF-8)")
        else:
            bad = {c for c in line if ord(c) > 127}
            if bad:
                shown = ", ".join(f"U+{ord(c):04X}" for c in sorted(bad))
                offenders.append(f"{name}:{lineno}: {shown}")
        start += len(raw) + 1
    return offenders


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

    Each file is read as bytes, so one that is not UTF-8 is reported by line
    and byte offset rather than skipped; `_offenders_in` says why that matters.
    """

    offenders: list[str] = []
    for name in _text_files():
        offenders.extend(_offenders_in(name, REPO / name))

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


def _plant(count: int, planted: dict[int, bytes]) -> bytes:
    """`count` lines of 20 ASCII bytes each, with the numbered lines replaced.

    Twenty bytes a line is what lets an offset below be counted by hand.
    """

    return b"".join(
        planted.get(n, b"line %02d: plain text\n" % n) for n in range(1, count + 1)
    )


# The four arms of #128, each placing its bytes where that issue's reading put
# them. Bytes above 0x7F are written as escapes, so this file stays ASCII.
# Arm 3: fifteen lines of 20 bytes (300), then 14 bytes into line 16: byte 314.
# Arm 4: two lines (40), a 23-byte line 3 (63), 33 more lines (723), then 34
# bytes into line 37: byte 757.
_ARM_ASCII = _plant(20, {})
_ARM_VALID = _plant(20, {16: b"line 16: plain\xe2\x80\x94 text\n"})
_ARM_LONE = _plant(20, {16: b"line 16: plain\x97 text\n"})
_ARM_BOTH = _plant(
    40,
    {
        3: b"line 03: plain\xe2\x80\x94 text\n",
        37: b"line 37: plain text, then a byte: \x97\n",
    },
)


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        pytest.param(_ARM_ASCII, [], id="1-ascii"),
        pytest.param(_ARM_VALID, ["plant.txt:16: U+2014"], id="2-valid-u2014"),
        pytest.param(
            _ARM_LONE,
            ["plant.txt:16: 0x97 at byte 314 (not UTF-8)"],
            id="3-lone-0x97",
        ),
        pytest.param(
            _ARM_BOTH,
            [
                "plant.txt:3: U+2014",
                "plant.txt:37: 0x97 at byte 757 (not UTF-8)",
            ],
            id="4-valid-then-lone",
        ),
    ],
)
def test_the_file_check_reports_every_arm(tmp_path, data, expected):
    """Calibration of the file check, through the function the real test calls.

    `test_the_check_can_actually_fail` calibrates `str.isascii` on strings built
    in memory, so it never reaches a read and could not see the read skip a
    file. These arms write bytes to disk and go through `_offenders_in`, the
    same call the whole-repository test makes for each tracked file.

    Arm 3 is the em dash as cp1252 writes it, a lone 0x97, which is the
    likeliest way one reaches this tree from a Windows editor or clipboard.
    Arm 4 is why the check reads line by line: one undecodable line late in a
    file must not hide a valid U+2014 earlier in it.
    """

    path = tmp_path / "plant.txt"
    path.write_bytes(data)
    assert _offenders_in("plant.txt", path) == expected


def test_the_arms_put_each_byte_where_its_offset_says():
    """The offsets above are counted by hand, so count them a second way.

    The check finds a line and an offset by splitting on LF and summing line
    lengths. This finds them with `bytes.index` and a count of the LFs before
    the byte, so a fixture edited out from under its expected offset goes red
    here rather than having the expectation edited to match the check.
    """

    assert _ARM_ASCII.isascii()
    assert _ARM_VALID[: _ARM_VALID.index(b"\xe2\x80\x94")].count(b"\n") == 15
    assert _ARM_LONE.index(b"\x97") == 314
    assert _ARM_LONE[:314].count(b"\n") == 15
    assert _ARM_BOTH[: _ARM_BOTH.index(b"\xe2\x80\x94")].count(b"\n") == 2
    assert _ARM_BOTH.index(b"\x97") == 757
    assert _ARM_BOTH[:757].count(b"\n") == 36


def test_an_unreadable_tracked_file_is_an_offender(tmp_path):
    """A file the check cannot read is not a file the check found clean.

    `git ls-files` lists the index, so a tracked file deleted from the working
    tree and not yet staged with `git rm` is listed and cannot be read. That is
    a desk state, not a CI one, and the remedy is to stage the deletion.
    """

    gone = tmp_path / "gone.txt"
    assert _offenders_in("gone.txt", gone) == [
        "gone.txt: unreadable (FileNotFoundError)"
    ]
