# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""Declared keys, rendered as Dagster asset checks and run through dex-core.

Two of the three pieces of #180. :func:`declaration_check_specs` renders the
specs, engine-free. :func:`build_declaration_checks` is the executor: one
``multi_asset_check`` that runs the specs through dex-core's public
``DexEngine.verify``, so each check keeps one implementation, in dex-core. The
documents and example come after it.

**The executor never touches the engine here.** Everything that does is in
:mod:`.dex`, which is the one module allowed to: this module hands it the
claims and receives one plain verdict per claim back. Defaults the owner ruled
on #180 (comment 6715768229), each held by ``tests/test_executor.py``:

- **A claim the engine did not measure never reports as passed.** It is a WARN
  result with ``measured`` False and dex-core's reason in its metadata.
- **Nothing confirms a priced probe on a run's behalf.** A probe dex's cost
  gate refuses, or wants confirmed, leaves its checks not measured. Spending
  is an opt-in on the builder, and dex's ceilings bind either way.
- **WARN and non-blocking.** Blocking is an opt-in per claim id.
- **Metadata carries counts only**, never a row value. A reason is dex's
  text, cut where dex starts quoting the warehouse, whose message can quote one.
- **Run on a schedule, not on materialization.** The checks carry no
  automation condition; a job selecting them is the caller's to schedule.

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

import functools
import json
import os
import re
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .declarations import _key_identity
from .model import DeclaredJoin, DeclaredKey, ProjectDeclarations, definition_hash
from .protocol import ProjectSource

if TYPE_CHECKING:  # pragma: no cover - type-only imports
    from dagster import AssetCheckSpec, AssetChecksDefinition

    from .dex import KeyVerdict
    from .project import _AssetKey

__all__ = [
    "CLAIM_ID",
    "COLUMNS",
    "DUPLICATE_COUNT",
    "ENGINE",
    "MEASURED",
    "MODEL",
    "REASON",
    "DeclarationCheckSpecs",
    "build_declaration_checks",
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

#: On each result: did dex-core judge the claim? False is never a pass.
MEASURED = "dagster_dex/measured"
#: On a result that was not measured: why, in dex-core's words where it gave any.
REASON = "dagster_dex/reason"
#: On a measured failure: how many rows repeat the key. A count, never a value.
DUPLICATE_COUNT = "dagster_dex/duplicate_count"
#: On each result: the engine that answered, as ``exmergo-dex-core <version>``.
ENGINE = "dagster_dex/engine"

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
    *,
    blocking: Iterable[str] = (),
) -> DeclarationCheckSpecs:
    """One ``AssetCheckSpec`` per declared key, and notes for the rest.

    ``asset_keys`` are the keys of the assets the project was reduced from,
    such as ``[key for asset in assets for key in asset.keys]``: Dagster's
    ``AssetKey``, or any object whose ``path`` is a sequence of strings. A key
    passed twice counts once. Each spec attaches to the key whose last segment
    is the declared model.

    Each spec carries the claim id under :data:`CLAIM_ID`, and the declared
    model and columns under :data:`MODEL` and :data:`COLUMNS`. Its name is
    ``declared_key__<column>__<column>``, which carries every column. The
    columns are the claim id's: a composite's sorted and lowercased, so
    reordering one does not rename its check. A column holding a character a
    Dagster name cannot hold is written with ``_`` in its place, and the name
    then ends with ``__`` and the first 12 characters of the claim id, since
    the replacement can map two columns to one name. Two keys on one asset that
    would still share a name both take that suffix, and a key whose name is
    taken even so is named in the notes rather than rendered; see
    :func:`_names` for which one keeps it.

    A declared key repeating another's claim id is rendered once. Raises
    ``ImportError`` when Dagster is not installed.

    **Every spec is non-blocking unless its claim id is in ``blocking``**, the
    per-claim opt-in #180's ruling asks for. A claim id there that names no
    rendered spec is refused with ``ValueError``: an opt-in that silently
    attached to nothing reads exactly like one that took.
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
    named = _names(placed, notes)
    blocked = frozenset(blocking)
    unknown = sorted(blocked - {entry.claim for entry, _ in named})
    if unknown:
        raise ValueError(
            "blocking names claim ids no rendered check carries: " + ", ".join(unknown)
        )
    specs = tuple(
        AssetCheckSpec(
            name,
            asset=list(entry.path),
            description=(
                f"Declared key: {entry.key.model} is unique on "
                f"({', '.join(entry.key.columns)})."
            ),
            blocking=entry.claim in blocked,
            metadata={
                CLAIM_ID: entry.claim,
                MODEL: entry.key.model,
                COLUMNS: list(entry.key.columns),
            },
        )
        for entry, name in named
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


def _owns(entry: _Placed, name: str) -> bool:
    """Does ``name`` end in ``entry``'s own claim id?"""

    return name.endswith(_SEPARATOR + entry.claim[:_SUFFIX_LENGTH])


def _names(placed: list[_Placed], notes: list[str]) -> list[tuple[_Placed, str]]:
    """Each placed key's check name, unique on its asset, in declaration order.

    A name two keys on one asset share is suffixed for both. ``_`` is a name
    character and the separator is made of it, so ``(a__b, c)`` and
    ``(a, b__c)`` share a name before the suffix. A suffix is never added for
    a name shared across assets: a check's name is its identity on its own
    asset, and a key added to one asset must not rename another's check.

    A name still taken after that is noted, and that key is not rendered: two
    specs with one name on one asset are one check to Dagster, which accepts
    them without complaint (``Definitions.validate_loadable``, read in dagster
    1.13.29). **A name ending in its own key's claim id keeps it**, so which
    key goes unrendered does not turn on declaration order: the other key's
    name only happens to end in those characters. Between two names that both
    do, which needs 48 bits of two claim ids to agree, the first declared
    keeps it.
    """

    bases = [(entry, _base_name(entry)) for entry in placed]
    shared = Counter((entry.path, base) for entry, base in bases)
    wanted = [
        (entry, base + _SEPARATOR + entry.claim[:_SUFFIX_LENGTH])
        if shared[(entry.path, base)] > 1
        else (entry, base)
        for entry, base in bases
    ]
    holder: dict[tuple[tuple[str, ...], str], _Placed] = {}
    # `sorted` is stable, so declaration order breaks every tie.
    for entry, name in sorted(wanted, key=lambda pair: not _owns(*pair)):
        if (entry.path, name) in holder:
            notes.append(
                f"declared key {_label(entry.key)} renders to the check name "
                f"{name!r}, which another declared key on {'/'.join(entry.path)} "
                "already has; it is not rendered"
            )
            continue
        holder[(entry.path, name)] = entry
    return [(entry, name) for entry, name in wanted if holder[(entry.path, name)] is entry]


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


# --- the executor ------------------------------------------------------------


def build_declaration_checks(
    project: ProjectSource,
    asset_keys: Iterable[_AssetKey],
    *,
    name: str = "declared_keys",
    blocking: Iterable[str] = (),
    repo_root: str | os.PathLike[str] | None = None,
    connection: Any = None,
    connector: str | None = None,
    confirm_spend: bool = False,
    open_engine: Callable[[], Any] | None = None,
) -> AssetChecksDefinition:
    """One ``multi_asset_check`` running every declared key through dex-core.

    The checks are :func:`declaration_check_specs`'s, over
    ``project.declarations()`` and ``asset_keys``, and the spec layer's notes
    (each declared join, each key no asset carries) are logged as warnings on
    every run, so a run's log names what goes unchecked. Each run opens ONE
    engine, calls ``DexEngine.verify`` once for the models of the selected
    checks, and yields one result per selected check:

    - **passed** when verify judged the key and found it held;
    - **failed** when verify found it broken, with :data:`DUPLICATE_COUNT`;
    - **not measured** otherwise: ``passed`` False, severity WARN,
      :data:`MEASURED` False and :data:`REASON` set. Never a pass.

    Every result carries :data:`CLAIM_ID`, :data:`MEASURED` and :data:`ENGINE`.
    Severity is WARN, except a measured failure of a claim in ``blocking``,
    which is ERROR on a blocking check. An unmeasured blocking claim still
    warns rather than blocks: a key nobody measured is not evidence it broke.

    The engine is :func:`~.dex.open_verify_engine` over ``project``, with
    ``repo_root``, ``connection`` (dex-core's ``ConnectionSource``), ``connector``
    and ``confirm_spend`` passed through; see it for what each binds.
    ``confirm_spend`` defaults to False, so nothing confirms a priced probe on a
    scheduled run's behalf. ``open_engine`` replaces the whole of that with a
    zero-argument callable returning an engine to use as a context manager,
    and is refused beside any of those four, which it would silently override.

    **Schedule a job selecting these checks**, such as one over
    ``AssetSelection.checks(...)``. They carry no automation condition, so
    nothing runs them on materialization unless a run selects them.

    Raises ``ImportError`` without Dagster or without exmergo-dex-core, and
    ``ValueError`` when no declared key renders to a check.
    """

    try:
        from dagster import multi_asset_check  # noqa: PLC0415 - optional dependency
    except ImportError as exc:
        raise ImportError(
            "build_declaration_checks() needs dagster installed; "
            "install this package with the [dagster] extra"
        ) from exc

    from . import dex  # noqa: PLC0415 - the engine boundary, imported when used

    release = dex.engine_release()
    declarations = project.declarations()
    rendered = declaration_check_specs(declarations, asset_keys, blocking=blocking)
    if not rendered.specs:
        raise ValueError(
            "no declared key renders to a check: " + ("; ".join(rendered.notes) or "none is declared")
        )
    opener = _opener(
        project,
        open_engine,
        repo_root=repo_root,
        connection=connection,
        connector=connector,
        confirm_spend=confirm_spend,
    )
    keys = {claim_id(key): key for key in declarations.declared_keys}
    specs = {_check_id(spec): spec for spec in rendered.specs}

    # `context` is unannotated because Dagster refuses every annotation on it
    # but its own context classes, and refuses those too as the strings this
    # module's `from __future__ import annotations` makes them.
    def _declared_keys(context) -> Iterator[Any]:  # type: ignore[no-untyped-def]  # Dagster refuses any annotation on context it cannot match to its own class
        for note in rendered.notes:
            context.log.warning(note)
        selected = [specs[_check_id(key)] for key in context.selected_asset_check_keys]
        selected.sort(key=_check_id)
        claims = [(spec.metadata[CLAIM_ID], keys[spec.metadata[CLAIM_ID]]) for spec in selected]
        verdicts = dex.verify_declared_keys(claims, opener)
        for spec, verdict in zip(selected, verdicts, strict=True):
            yield _result(spec, verdict, release)

    # Called rather than applied with `@`: Dagster is an optional import that
    # the type check cannot see, and a decorator it cannot see would leave the
    # function untyped.
    definition: AssetChecksDefinition = multi_asset_check(
        specs=list(rendered.specs),
        name=name,
        can_subset=True,
        description="Declared keys, judged by dex-core's maintain verify.",
    )(_declared_keys)
    return definition


def _check_id(check: Any) -> tuple[tuple[str, ...], str]:
    """A spec or a selected check key, as (asset path, check name)."""

    return tuple(check.asset_key.path), str(check.name)


def _opener(
    project: ProjectSource,
    open_engine: Callable[[], Any] | None,
    **engine_options: Any,
) -> Callable[[], Any]:
    """``open_engine``, or :func:`~.dex.open_verify_engine` over the options."""

    from . import dex  # noqa: PLC0415 - the engine boundary, imported when used

    if open_engine is None:
        return functools.partial(dex.open_verify_engine, project, **engine_options)
    given = sorted(
        option
        for option, value in engine_options.items()
        if value is not None and value is not False
    )
    if given:
        raise ValueError(
            "open_engine replaces how the engine is opened, so it cannot be "
            "combined with: " + ", ".join(given)
        )
    return open_engine


def _result(spec: Any, verdict: KeyVerdict, release: str) -> Any:
    """One ``AssetCheckResult`` for one verdict. Counts and reasons only."""

    from dagster import (  # noqa: PLC0415 - optional dependency
        AssetCheckResult,
        AssetCheckSeverity,
    )

    metadata: dict[str, Any] = {
        CLAIM_ID: verdict.claim,
        MEASURED: verdict.measured,
        ENGINE: f"exmergo-dex-core {release}",
    }
    if not verdict.measured and verdict.reason is not None:
        metadata[REASON] = verdict.reason
    if verdict.duplicate_count is not None:
        metadata[DUPLICATE_COUNT] = verdict.duplicate_count
    blocks = verdict.measured and not verdict.passed and spec.blocking
    return AssetCheckResult(
        asset_key=spec.asset_key,
        check_name=spec.name,
        passed=verdict.passed,
        severity=AssetCheckSeverity.ERROR if blocks else AssetCheckSeverity.WARN,
        metadata=metadata,
        description=verdict.reason,
    )
