# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""Declared keys, rendered as Dagster asset check specs.

The first of three pieces of #180: the specs alone. Nothing here runs a check.
The executor that runs them through dex-core, and the documents and example,
come after it.

**Keys only.** The owner ruled on #180 that a declared join gets no check while
dex-core judges no declared join for this project format. A check that could
only ever report "not measured" was declined; each declared join is named in
:attr:`DeclarationCheckSpecs.notes` instead, so a reader can see it goes
unchecked.

**The asset keys come in beside the declarations.** The reduction keeps only an
asset key's last segment as the model name (``_reduce_asset_graph`` in
:mod:`.project`), so a declaration says ``fact_orders`` where Dagster knows
``warehouse/fact_orders``. A spec built from the declarations alone could only
attach to an asset with no prefix. So :func:`declaration_check_specs` takes the
asset keys too, and attaches each spec to the one key whose last segment is the
declared model. A declared key with no such asset, or with several, is named in
the notes and gets no spec: dropping it would hide the likelier cause, a renamed
asset, and picking one of several would be a guess.

**Dagster is imported at the point of use**, the way :mod:`.dex` imports
dex-core. ``import dagster_dex.checks`` works with neither installed, and so
does :func:`claim_id`. Only building a spec needs Dagster, because
``AssetCheckSpec`` is its type.

**The claim id is the declaration's content, hashed:** its kind, its model and
its columns, read the way the parser reads two declarations as one claim. So
two reductions of one project give one id per key, and renaming a declared
column gives a new one. The asset key, the check name and the file the key was
written in are not part of it: moving a declaration between files, or an asset
under a new prefix, does not make it a different claim.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .declarations import _key_identity
from .model import DeclaredJoin, DeclaredKey, ProjectDeclarations, definition_hash

if TYPE_CHECKING:  # pragma: no cover - type-only imports
    from dagster import AssetCheckSpec

    from .project import _AssetKey

__all__ = [
    "CLAIM_ID",
    "COLUMNS",
    "MODEL",
    "DeclarationCheckSpecs",
    "claim_id",
    "declaration_check_specs",
]

#: The metadata key each spec carries its claim id under. Namespaced the way
#: Dagster namespaces its own (``dagster/row_count``), so it cannot collide with
#: a key the project sets.
CLAIM_ID = "dagster_dex/claim_id"
#: The declared model, as the declaration names it.
MODEL = "dagster_dex/model"
#: The declared columns, in the order and case the author wrote them.
COLUMNS = "dagster_dex/columns"

#: Every check name starts with this, so a key check is told apart from a
#: project's own checks on the same asset, and from a join check if one comes.
_PREFIX = "declared_key"
_SEPARATOR = "__"
#: What a Dagster name may hold (``^[A-Za-z0-9_]+$``, read in dagster 1.13.29).
#: ``AssetCheckSpec`` accepts any string; the refusal comes later, when a
#: definition built from the spec is loaded.
_NAME_CHARACTERS = re.compile(r"[A-Za-z0-9_]+")
_NOT_NAME_CHARACTERS = re.compile(r"[^A-Za-z0-9_]+")
#: How much of the claim id a name carries when it needs one. 48 bits.
_SUFFIX_LENGTH = 12


def claim_id(key: DeclaredKey) -> str:
    """The id of the claim ``key`` makes: a hash of its kind, model and columns.

    The columns are read as :func:`~.declarations._once` compares them: a single
    column as written, a composite sorted and lowercased. Two declarations the
    parser reads as one claim therefore get one id, and the id changes when a
    declared column does. It is ``sha256`` over a JSON array, so it is the same
    in every process; Python's ``hash()`` of a string is not.
    """

    model, columns = _key_identity(key)
    return definition_hash(json.dumps(["key", model, list(columns)]))


@dataclass(frozen=True)
class DeclarationCheckSpecs:
    """The specs, and what was declared and not rendered.

    ``notes`` is how this layer discloses what it leaves out: every declared
    join, and every declared key it could not attach to exactly one asset.
    """

    specs: tuple[AssetCheckSpec, ...] = ()
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class _Placed:
    """A declared key, the one asset it attaches to, and its claim id."""

    key: DeclaredKey
    path: tuple[str, ...]
    claim: str


def declaration_check_specs(
    declarations: ProjectDeclarations,
    asset_keys: Iterable[_AssetKey],
) -> DeclarationCheckSpecs:
    """One ``AssetCheckSpec`` per declared key, and notes for the rest.

    ``asset_keys`` are the keys of the assets the project was reduced from,
    such as ``[key for asset in assets for key in asset.keys]``. Each spec
    attaches to the key whose last segment is the declared model.

    Each spec carries the claim id under :data:`CLAIM_ID`, and the declared
    model and columns under :data:`MODEL` and :data:`COLUMNS`. Its name is
    ``declared_key__<column>__<column>``, which carries every column. The
    columns are the claim id's: a composite's sorted and lowercased, so
    reordering one does not rename its check. A column holding a character a
    Dagster name cannot hold is written with ``_`` in its place, and the name
    then ends with ``__`` and the first 12 characters of the claim id, since
    the replacement can map two columns to one name. Two keys on one asset that
    would still share a name both take that suffix, and a key whose name is
    taken even so is named in the notes rather than rendered.

    A declared key repeating another's claim id is rendered once. Raises
    ``ImportError`` when Dagster is not installed.
    """

    try:
        from dagster import AssetCheckSpec  # noqa: PLC0415 - optional dependency
    except ImportError as exc:
        raise ImportError(
            "declaration_check_specs() needs dagster installed; "
            "install this package with the [dagster] extra"
        ) from exc

    notes: list[str] = []
    placed = _place(declarations.declared_keys, asset_keys, notes)
    specs = tuple(
        AssetCheckSpec(
            name,
            asset=list(entry.path),
            description=(
                f"Declared key: {entry.key.model} is unique on "
                f"({', '.join(entry.key.columns)})."
            ),
            metadata={
                CLAIM_ID: entry.claim,
                MODEL: entry.key.model,
                COLUMNS: list(entry.key.columns),
            },
        )
        for entry, name in _names(placed, notes)
    )
    notes.extend(_join_notes(declarations.declared_joins))
    return DeclarationCheckSpecs(specs=specs, notes=tuple(notes))


def _label(key: DeclaredKey) -> str:
    return f"{key.model}({', '.join(key.columns)})"


def _paths_by_model(asset_keys: Iterable[_AssetKey]) -> dict[str, list[tuple[str, ...]]]:
    """Each distinct asset key's path, grouped by its last segment."""

    found: dict[str, list[tuple[str, ...]]] = {}
    for asset_key in asset_keys:
        path = tuple(asset_key.path)
        if path and path not in found.get(path[-1], []):
            found.setdefault(path[-1], []).append(path)
    return found


def _place(
    keys: Sequence[DeclaredKey], asset_keys: Iterable[_AssetKey], notes: list[str]
) -> list[_Placed]:
    """Each key's one asset, and a note naming every key that has none or several.

    The model is matched to the last segment exactly, as the reduction names a
    model and as ``declarations()`` decides a model is one the graph builds.
    """

    paths = _paths_by_model(asset_keys)
    placed: list[_Placed] = []
    claims: set[str] = set()
    unmatched: list[str] = []
    ambiguous: list[str] = []
    for key in keys:
        claim = claim_id(key)
        if claim in claims:
            continue
        claims.add(claim)
        candidates = sorted(paths.get(key.model, []))
        if len(candidates) == 1:
            placed.append(_Placed(key=key, path=candidates[0], claim=claim))
        elif candidates:
            found = ", ".join("/".join(path) for path in candidates)
            ambiguous.append(f"{_label(key)} [{found}]")
        else:
            unmatched.append(_label(key))
    if unmatched:
        notes.append(
            "declared keys on a model that no asset key ends in, so no check is "
            "rendered for them: " + "; ".join(unmatched)
        )
    if ambiguous:
        notes.append(
            "declared keys on a model that more than one asset key ends in, so no "
            "check is rendered rather than one attached to a guess: "
            + "; ".join(ambiguous)
        )
    return placed


def _base_name(entry: _Placed) -> str:
    """``declared_key__<column>__<column>``, suffixed when a column was rewritten."""

    _, columns = _key_identity(entry.key)
    segments = [_NOT_NAME_CHARACTERS.sub("_", column) for column in columns]
    name = _SEPARATOR.join([_PREFIX, *segments])
    if not all(_NAME_CHARACTERS.fullmatch(column) for column in columns):
        name += _SEPARATOR + entry.claim[:_SUFFIX_LENGTH]
    return name


def _names(placed: list[_Placed], notes: list[str]) -> list[tuple[_Placed, str]]:
    """Each placed key's check name, unique on its asset.

    A name two keys on one asset share is suffixed for both. ``_`` is a name
    character and the separator is made of it, so ``(a__b, c)`` and
    ``(a, b__c)`` share a name before the suffix. A name still taken after that
    is noted, and that key is not rendered: two specs with one name on one
    asset are one check to Dagster, which accepts them without complaint
    (``Definitions.validate_loadable``, read in dagster 1.13.29).
    """

    bases = [(entry, _base_name(entry)) for entry in placed]
    shared = Counter((entry.path, base) for entry, base in bases)
    named: list[tuple[_Placed, str]] = []
    taken: set[tuple[tuple[str, ...], str]] = set()
    for entry, base in bases:
        name = base
        if shared[(entry.path, base)] > 1:
            name = base + _SEPARATOR + entry.claim[:_SUFFIX_LENGTH]
        if (entry.path, name) in taken:
            notes.append(
                f"declared key {_label(entry.key)} renders to the check name "
                f"{name!r}, which another declared key on {'/'.join(entry.path)} "
                "already has; it is not rendered"
            )
            continue
        taken.add((entry.path, name))
        named.append((entry, name))
    return named


def _join_notes(joins: Sequence[DeclaredJoin]) -> list[str]:
    """One note naming every declared join, each once, in declaration order."""

    labels = list(
        dict.fromkeys(
            f"{join.from_model}({', '.join(join.from_columns)}) -> "
            f"{join.to_model}({', '.join(join.to_columns)})"
            for join in joins
        )
    )
    if not labels:
        return []
    return [
        "declared joins are not rendered as checks, since dex-core judges no "
        "declared join for this project format yet: " + "; ".join(labels)
    ]
