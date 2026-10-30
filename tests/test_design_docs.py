# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""A design document names code, and nothing else checks that the code is there.

`docs/design/` describes how the package works and links every decision to
where it is made. Both halves rot quietly: a module is renamed and the
document still names the old one, a heading is reworded and the link to it
still renders, it just lands at the top of the page. Neither is an error
anywhere, so this file makes them one.

What it checks, per document (the directory's `README.md` describes the
convention and is not itself a document):

  - the header: Status, Describes and Reviewed, in that order, first after
    the title, with a Status of `living`, `frozen` or `dead`;
  - every backticked path on the Describes line exists in the tree;
  - every backticked `dagster_dex.<module>.<name>` resolves, by import and
    attribute lookup, rather than by a text search a stale name could pass;
  - every relative link reaches a file, and its anchor a heading there.

**What it cannot check is whether the prose is true.** A document whose named
paths and symbols all exist can still describe them wrongly; the Reviewed line
is the record of someone having read the two side by side.

Engine-free and orchestrator-free, so it runs in the control step: resolving
`dagster_dex.dex` imports nothing from the engine, because that module defers
every engine import to the call that needs it.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
DESIGN = REPO / "docs" / "design"

_STATUSES = frozenset({"living", "frozen", "dead"})
_LABELS = ["Status", "Describes", "Reviewed"]
_BULLET = re.compile(r"^- \*\*(\w+):\*\*\s*(.*)$")
_TICKED = re.compile(r"`([^`]+)`")
_SYMBOL = re.compile(r"`(dagster_dex(?:\.[A-Za-z_]\w*)+)`")
_LINK = re.compile(r"\]\(([^)\s]+)\)")
_FENCE = re.compile(r"^```.*?^```[ \t]*$", re.M | re.S)
_HEADING = re.compile(r"^#{1,6} (.+?)\s*$", re.M)


def _documents() -> list[Path]:
    return sorted(p for p in DESIGN.glob("*.md") if p.name != "README.md")


def _ids() -> list[str]:
    return [p.name for p in _documents()]


def _header(text: str) -> list[tuple[str, str]]:
    """The bullets between the title and the first blank line, continuations
    joined. Anything else in that position is returned too, so a header that
    does not come first reads as a wrong label rather than as no header."""

    lines = text.splitlines()
    assert lines and lines[0].startswith("# "), "the first line must be the title"
    body = lines[1:]
    while body and not body[0].strip():
        body = body[1:]
    bullets: list[tuple[str, str]] = []
    for line in body:
        if not line.strip():
            break
        match = _BULLET.match(line)
        if match:
            bullets.append((match.group(1), match.group(2)))
        elif line.startswith("  ") and bullets:
            label, value = bullets[-1]
            bullets[-1] = (label, f"{value} {line.strip()}")
        else:
            bullets.append(("<not a header bullet>", line))
    return bullets


def _slug(heading: str) -> str:
    """GitHub's anchor for a heading: lower case, punctuation other than `-` and
    `_` dropped, spaces to hyphens."""

    return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")


def _anchors(path: Path) -> set[str]:
    """Every heading anchor in a markdown file, fenced code excluded, so a
    `# comment` in a shell block is not mistaken for a heading. A repeated
    heading gets GitHub's `-1`, `-2` suffixes."""

    text = _FENCE.sub("", path.read_text(encoding="utf-8"))
    seen: dict[str, int] = {}
    anchors: set[str] = set()
    for heading in _HEADING.findall(text):
        slug = _slug(heading)
        count = seen.get(slug, 0)
        anchors.add(slug if count == 0 else f"{slug}-{count}")
        seen[slug] = count + 1
    return anchors


def _resolves(dotted: str) -> bool:
    """Import the longest module prefix of ``dotted``, then walk the rest as
    attributes. A module that is missing because the prefix is too long is the
    expected miss; any other missing module is a real failure and raises."""

    parts = dotted.split(".")
    for cut in range(len(parts), 0, -1):
        name = ".".join(parts[:cut])
        try:
            found: object = importlib.import_module(name)
        except ModuleNotFoundError as exc:
            if exc.name and (name == exc.name or name.startswith(exc.name + ".")):
                continue
            raise
        for attribute in parts[cut:]:
            if not hasattr(found, attribute):
                return False
            found = getattr(found, attribute)
        return True
    return False


def test_there_are_design_documents_to_check():
    """The floor. Every test below is parametrized over the documents, and an
    empty parameter set is a skip, not a failure."""

    assert "dagster-to-dex.md" in _ids()


@pytest.mark.parametrize("path", _documents(), ids=_ids())
def test_the_header_comes_first_and_names_a_known_status(path):
    bullets = _header(path.read_text(encoding="utf-8"))
    assert [label for label, _ in bullets] == _LABELS, (
        f"{path.name}: the header must be exactly the bullets {_LABELS}, first "
        f"after the title; found {bullets}"
    )
    values = dict(bullets)
    status = values["Status"].split()[0] if values["Status"].split() else ""
    assert status in _STATUSES, (
        f"{path.name}: Status {status!r} is not one of {sorted(_STATUSES)}"
    )
    assert re.search(r"\d{4}-\d{2}-\d{2}", values["Reviewed"]) and re.search(
        r"`[0-9a-f]{7,40}`", values["Reviewed"]
    ), f"{path.name}: Reviewed must give a date and a backticked commit sha"


@pytest.mark.parametrize("path", _documents(), ids=_ids())
def test_every_described_path_exists(path):
    values = dict(_header(path.read_text(encoding="utf-8")))
    named = _TICKED.findall(values.get("Describes", ""))
    assert named, f"{path.name}: the Describes line names no backticked path"
    missing = [token for token in named if not (REPO / token).exists()]
    assert not missing, f"{path.name}: Describes names paths not in the tree: {missing}"


@pytest.mark.parametrize("path", _documents(), ids=_ids())
def test_every_named_symbol_resolves(path):
    symbols = sorted(set(_SYMBOL.findall(path.read_text(encoding="utf-8"))))
    missing = [symbol for symbol in symbols if not _resolves(symbol)]
    assert not missing, f"{path.name}: names that do not resolve: {missing}"


@pytest.mark.parametrize("path", _documents(), ids=_ids())
def test_every_relative_link_reaches_its_target(path):
    text = _FENCE.sub("", path.read_text(encoding="utf-8"))
    broken: list[str] = []
    for link in _LINK.findall(text):
        if re.match(r"[a-z]+:", link):
            continue
        target, _, anchor = link.partition("#")
        resolved = (path.parent / target).resolve() if target else path
        if not resolved.exists():
            broken.append(f"{link} (no such file)")
        elif anchor and resolved.suffix == ".md" and anchor not in _anchors(resolved):
            broken.append(f"{link} (no such heading)")
    assert not broken, f"{path.name}: links that land nowhere: {broken}"


def test_the_symbol_check_reads_a_known_name_both_ways():
    """Calibration on the resolver itself, both arms, so a green run of the
    test above is not a resolver that accepts everything or nothing."""

    assert _resolves("dagster_dex.dex.EditableDexProject.edit_path")
    assert not _resolves("dagster_dex.dex.EditableDexProject.no_such_method")
    assert not _resolves("dagster_dex.no_such_module.anything")


def test_the_slug_matches_github_on_a_heading_with_code_and_quotes():
    """The one heading shape here most likely to slug wrongly."""

    heading = 'The names in `protocol.py` are OURS, and must not be "fixed" to match'
    assert _slug(heading) == "the-names-in-protocolpy-are-ours-and-must-not-be-fixed-to-match"
