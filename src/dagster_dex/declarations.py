# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""Reading hand-written declarations into the neutral model.

The declaration files this parses are written in a schema-test vocabulary
(``unique``, ``not_null``, ``relationships``) because that is what they were
already written in, and rewriting eleven of them to prove a point would be
churn. The vocabulary is an *input format*, not the model: everything below
lands in :mod:`.model` types, and swapping the input format later touches only
this module.

**Nothing here raises on bad input.** A declaration file that cannot be read,
or that says something contradictory, produces a note and is skipped. The
alternative - refusing to describe a project because one file of eleven is
malformed - turns an authoring typo into an outage on a read path.
"""

from __future__ import annotations

import re
from typing import Any

import yaml

from .model import (
    DeclaredJoin,
    DeclaredKey,
    ExternalSource,
    Metric,
    SemanticField,
    SemanticModel,
    definition_hash,
)

__all__ = ["parse_declarations", "parse_semantics", "parse_source_declarations"]

_REF = re.compile(r"ref\(\s*['\"]([^'\"]+)['\"]\s*\)")
#: A bare column reference, and nothing looser. Anything with an operator, a call,
#: a dotted path or a quote is an expression, and an expression handed to a
#: consumer expecting a column name is a fabricated reference. See
#: `_semantic_fields`.
#:
#: **Anchored in the pattern, not only at the call site.** `fullmatch` below
#: already anchors it, so `\A`/`\Z` are redundant today - deliberately. The comment
#: above claims the pattern admits nothing looser, and that has to stay true of the
#: pattern itself: an unanchored one becomes permissive the moment somebody reaches
#: for `match` or `search`, and what it would let through is precisely the
#: fabricated column this guard exists to stop.
_IDENTIFIER = re.compile(r"\A[A-Za-z_][A-Za-z0-9_]*\Z")


def _referenced_model(text: object) -> str | None:
    """``ref('dim_date')`` -> ``dim_date``; a bare name passes through.

    Returns ``None`` for anything else, so a caller can note it rather than
    fabricating a target that would later look like a declared join.
    """

    if not isinstance(text, str) or not text.strip():
        return None
    match = _REF.search(text)
    if match:
        return match.group(1)
    # A bare model name is accepted; anything with punctuation is not, because
    # a half-parsed expression is worse here than an honest refusal.
    bare = text.strip()
    return bare if bare.replace("_", "").isalnum() else None


def _test_names(tests: Any) -> list[tuple[str, Any]]:
    """Normalize a dbt-style ``tests:`` list to ``(name, payload)`` pairs.

    Entries are either a bare string (``unique``) or a single-key mapping
    (``{relationships: {...}}``). Anything else is skipped rather than guessed.
    """

    pairs: list[tuple[str, Any]] = []
    if not isinstance(tests, list):
        return pairs
    for entry in tests:
        if isinstance(entry, str):
            pairs.append((entry, None))
        elif isinstance(entry, dict) and len(entry) == 1:
            (name, payload), = entry.items()
            pairs.append((str(name), payload))
    return pairs


def parse_declarations(
    sources: dict[str, str],
) -> tuple[list[DeclaredKey], list[DeclaredJoin], list[str]]:
    """Parse declaration YAML into keys, joins, and notes.

    ``sources`` is ``{name: file text}``. Returns the three in a fixed order so
    the caller never has to remember which came first.
    """

    keys: list[DeclaredKey] = []
    joins: list[DeclaredJoin] = []
    notes: list[str] = []

    for origin in sorted(sources):
        try:
            document = yaml.safe_load(sources[origin])
        except yaml.YAMLError as exc:
            notes.append(f"declaration {origin!r} is not readable YAML ({exc.__class__.__name__}); skipped")
            continue
        if not isinstance(document, dict):
            continue

        for entry in document.get("models") or []:
            if not isinstance(entry, dict):
                continue
            model = entry.get("name")
            if not isinstance(model, str) or not model:
                notes.append(f"declaration {origin!r} has a model with no name; skipped")
                continue

            composite = _composite_key(model, entry, notes)
            singles = _single_column_keys(model, entry, joins, notes)

            # A model-level combination and a column-level uniqueness claim are
            # two different statements of the same grain, and when both appear
            # they can disagree. Prefer the combination - it is the only one of
            # the two that can express a multi-column key - but say so, because
            # silently dropping the other would hide a real authoring conflict.
            if composite is not None:
                keys.append(composite)
                if singles:
                    dropped = ", ".join(sorted(k.columns[0] for k in singles))
                    notes.append(
                        f"{model!r} declares a composite grain and also a "
                        f"column-level unique on {dropped}; the composite wins"
                    )
            else:
                keys.extend(singles)

    return keys, joins, notes


def _composite_key(model: str, entry: dict, notes: list[str]) -> DeclaredKey | None:
    """A model-level ``unique_combination_of_columns``, when present and sane."""

    for name, payload in _test_names(entry.get("tests")):
        if name != "unique_combination_of_columns":
            continue
        columns = (payload or {}).get("combination_of_columns") if isinstance(payload, dict) else None
        if not isinstance(columns, list) or not columns:
            notes.append(f"{model!r} declares a composite grain with no columns; ignored")
            continue
        named = tuple(str(c) for c in columns if isinstance(c, str) and c)
        if not named:
            notes.append(f"{model!r} declares a composite grain with no usable columns; ignored")
            continue
        return DeclaredKey(model=model, columns=named, source="combination")
    return None


def _single_column_keys(
    model: str, entry: dict, joins: list[DeclaredJoin], notes: list[str]
) -> list[DeclaredKey]:
    """Column-level ``unique`` keys, collecting ``relationships`` joins en route.

    Joins are appended rather than returned because they are found here but do
    not belong to the key result; threading them back through a second return
    value would make both callers unpack something they do not use.
    """

    found: list[DeclaredKey] = []
    for column_entry in entry.get("columns") or []:
        if not isinstance(column_entry, dict):
            continue
        column = column_entry.get("name")
        if not isinstance(column, str) or not column:
            continue
        for name, payload in _test_names(column_entry.get("tests")):
            if name == "unique":
                found.append(DeclaredKey(model=model, columns=(column,), source="unique"))
            elif name == "relationships" and isinstance(payload, dict):
                target = _referenced_model(payload.get("to"))
                field = payload.get("field")
                if target is None or not isinstance(field, str) or not field:
                    notes.append(
                        f"{model}.{column} declares a relationship that names no "
                        "resolvable model and column; ignored"
                    )
                    continue
                joins.append(
                    DeclaredJoin(
                        from_model=model,
                        from_columns=(column,),
                        to_model=target,
                        to_columns=(field,),
                        source="relationships",
                    )
                )
    return found


def parse_source_declarations(
    sources: dict[str, str],
) -> tuple[list[ExternalSource], list[str]]:
    """Parse source-declaration YAML into external sources, and notes.

    ``sources`` is ``{reading model: file text}``: the key names the model that
    reads the declared tables. Keying by the reader is what lets one input carry
    both halves a consumer needs - which tables the project depends on, and
    which model each one lands in - without a second mapping that could
    disagree with the first.

    **Two models declaring the same table converge on one source with two
    readers.** Emitting it twice would be the more literal reading of the input
    and the wrong one: a downstream consumer treats each entry as a distinct
    contract with the warehouse, so a duplicate is reported as two findings
    about a single table.

    Columns are unioned across declarations of the same table, in first-seen
    order. A declaration that lists a subset of columns is making a narrower
    statement, not contradicting a wider one.
    """

    found: dict[tuple[str, str | None, str], ExternalSource] = {}
    notes: list[str] = []

    for origin in sorted(sources):
        try:
            document = yaml.safe_load(sources[origin])
        except yaml.YAMLError as exc:
            notes.append(
                f"source declaration {origin!r} is not readable YAML "
                f"({exc.__class__.__name__}); skipped"
            )
            continue
        if not isinstance(document, dict):
            continue

        declared_here = 0
        for entry in document.get("sources") or []:
            if not isinstance(entry, dict):
                continue
            system = entry.get("name")
            if not isinstance(system, str) or not system:
                notes.append(
                    f"source declaration {origin!r} has a source with no name; skipped"
                )
                continue
            schema = entry.get("schema")
            schema_name = schema if isinstance(schema, str) and schema else None

            for table_entry in entry.get("tables") or []:
                if not isinstance(table_entry, dict):
                    continue
                table = table_entry.get("name")
                if not isinstance(table, str) or not table:
                    notes.append(
                        f"source {system!r} in {origin!r} declares a table with "
                        "no name; skipped"
                    )
                    continue
                declared_here += 1
                found_key = (system, schema_name, table)
                columns = _named(table_entry.get("columns"))
                existing = found.get(found_key)
                if existing is None:
                    found[found_key] = ExternalSource(
                        system=system,
                        table=table,
                        schema_name=schema_name,
                        columns=columns,
                        read_by=(origin,),
                    )
                else:
                    merged = list(existing.columns)
                    merged.extend(c for c in columns if c not in existing.columns)
                    found[found_key] = ExternalSource(
                        system=system,
                        table=table,
                        schema_name=schema_name,
                        columns=tuple(merged),
                        read_by=existing.read_by + (origin,),
                    )

        # A file that parsed but declared nothing is the failure mode worth
        # naming: it reads as "this model has no external reads", which is a
        # claim, and it is indistinguishable from having no file at all.
        if declared_here == 0:
            notes.append(
                f"source declaration {origin!r} declares no source tables; "
                "expected sources[].tables[].name"
            )

    return [found[k] for k in sorted(found)], notes


def parse_semantics(
    sources: dict[str, str],
) -> tuple[list[SemanticModel], list[Metric], list[str]]:
    """Parse semantic YAML into semantic models, metrics, and notes."""

    models: list[SemanticModel] = []
    metrics: list[Metric] = []
    notes: list[str] = []

    for origin in sorted(sources):
        text = sources[origin]
        try:
            document = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            notes.append(f"semantic file {origin!r} is not readable YAML ({exc.__class__.__name__}); skipped")
            continue
        if not isinstance(document, dict):
            continue

        for entry in document.get("semantic_models") or []:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name")
            if not isinstance(name, str) or not name:
                continue
            target = _referenced_model(entry.get("model")) or ""
            dimensions = _semantic_fields(entry.get("dimensions"), name, "dimension", notes)
            measures = _semantic_fields(entry.get("measures"), name, "measure", notes)
            models.append(
                SemanticModel(
                    name=name,
                    model=target,
                    dimensions=dimensions,
                    measures=measures,
                    definition_sha=definition_hash(yaml.safe_dump(entry, sort_keys=True)),
                )
            )

        for entry in document.get("metrics") or []:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name")
            if not isinstance(name, str) or not name:
                continue
            params = entry.get("type_params")
            measure = params.get("measure") if isinstance(params, dict) else None
            metrics.append(
                Metric(
                    name=name,
                    measure=measure if isinstance(measure, str) else None,
                    kind=str(entry.get("type") or "simple"),
                    definition_sha=definition_hash(yaml.safe_dump(entry, sort_keys=True)),
                )
            )

    return models, metrics, notes


def _named(entries: Any) -> tuple[str, ...]:
    """The ``name`` of each mapping in a list, in declaration order.

    Still used for a source table's ``columns``, which are column names already and
    have no expression to resolve. Semantic dimensions and measures go through
    :func:`_semantic_fields` instead.
    """

    if not isinstance(entries, list):
        return ()
    return tuple(
        e["name"] for e in entries if isinstance(e, dict) and isinstance(e.get("name"), str)
    )


def _semantic_fields(
    entries: Any, model: str, role: str, notes: list[str]
) -> tuple[SemanticField, ...]:
    """Semantic dimensions or measures, each with the column behind it when known.

    ``expr`` is the declared source of a field's values. Where it is a **bare
    column reference** it is exactly what a consumer needs to check the definition
    against the warehouse, so it is carried. Where it is anything else it is
    deliberately dropped and reported:

    - **an expression** (``cost_net * 1.2``, a ``CASE``) is not a column name, and
      handing one to a consumer that resolves column names produces a reference
      that fails to resolve because it was never a reference. A fabricated
      high-severity finding is worse than the absent one it replaces;
    - **an absent ``expr``** could be defaulted to the field's own name, and is
      not. Some semantic dialects define that default, but applying it here would
      assert a column the author never wrote, and the failure mode is the same
      fabricated finding. The note says to add ``expr:``, which is a fix the author
      can make and we cannot guess.

    Both cases leave ``column=None``, which consumers already read as "cannot be
    checked here", so the loss is coverage rather than correctness.

    **Names are unique here, and that is a real guarantee rather than an
    assumption.** A consumer keyed by name (dex-core's ``SemanticModelDef`` maps
    ``{name: column}``) silently keeps whichever duplicate it saw last, so two
    fields declaring the same name would drop one with nothing said. The first
    declaration wins and the rest are reported, for the reason
    :class:`~.model.ExternalSource` converges two declarations of one table into
    one source: a lossy narrowing that nothing discloses is the failure mode this
    package exists to avoid, and "last one parsed" is not a rule anybody chose.
    """

    if not isinstance(entries, list):
        return ()

    fields: list[SemanticField] = []
    unresolved: list[str] = []
    duplicates: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not name:
            continue
        if name in seen:
            duplicates.append(name)
            continue
        seen.add(name)
        expr = entry.get("expr")
        column = expr if isinstance(expr, str) and _IDENTIFIER.fullmatch(expr) else None
        if column is None:
            unresolved.append(name)
        fields.append(
            SemanticField(
                name=name,
                column=column,
                categorical=entry.get("type") == "categorical",
            )
        )

    if unresolved:
        notes.append(
            f"semantic model {model!r}: {len(unresolved)} {role}(s) declare no bare "
            f"column in `expr`, so drift cannot check them against the warehouse: "
            + ", ".join(sorted(unresolved))
        )
    if duplicates:
        notes.append(
            f"semantic model {model!r}: {len(duplicates)} {role}(s) redeclare a name "
            "already used; the first declaration is kept and the rest dropped: "
            + ", ".join(sorted(set(duplicates)))
        )
    return tuple(fields)
