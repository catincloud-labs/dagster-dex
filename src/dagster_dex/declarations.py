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
from pathlib import PurePosixPath
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
#: ``source('erp', 'calendar')``: the source's name, then its table's.
_SOURCE = re.compile(r"source\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]+)['\"]\s*\)")
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

    Read for a semantic model's ``model:``. A relationship's ``to:`` is read
    by :func:`_relationship_target`, which does not take a bare name.
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


def _relationship_target(text: object) -> str | None:
    """A ``relationships`` test's ``to:``: ``ref('dim_date')`` -> ``dim_date``,
    and ``source('erp', 'calendar')`` -> ``erp.calendar``.

    These two forms are read as exmergo-dex-core's schema-YAML reader reads
    them (``_parse_relation_ref`` in ``exmergo_dex_core/dbt_project.py``,
    read in 1.15.2), which the owner ruled on #131:

    - **A source is a target, named ``<source>.<table>``**, the name that
      reader gives it. So the join's ``to_model`` names a source, not a model
      the project builds. This read no join from one, and noted it as
      unresolvable.
    - **A bare name is not.** dbt keeps a bare ``to:`` as the string and draws
      no edge to it, and that reader reads no join from one. This read
      ``to: dim_date`` as a join to ``dim_date`` through
      :func:`_referenced_model`, which a semantic model's ``model:`` still
      uses.

    Anything else is ``None``, and the caller notes it. That includes a
    ``ref()`` with a second argument, ``ref('m', v=1)`` or
    ``ref('pkg', 'm')``: ``_REF`` wants a ``)`` after the first argument, and
    that reader does not, so it reads a join to the first argument. That
    difference is older than #131 and not among its rows.
    """

    if not isinstance(text, str):
        return None
    ref = _REF.search(text)
    if ref:
        return ref.group(1)
    source = _SOURCE.search(text)
    return f"{source.group(1)}.{source.group(2)}" if source else None


def _test_names(tests: Any, where: str, notes: list[str]) -> list[tuple[str, Any]]:
    """Normalize a dbt-style ``tests:`` list to ``(name, payload)`` pairs.

    Entries are a bare string (``unique``), a single-key mapping
    (``{relationships: {...}}``), or a mapping that names its test under
    ``test_name:``, whose payload is the whole mapping
    (``{name: ..., test_name: unique, arguments: {...}}``). dbt documents both
    mapping spellings, and exmergo-dex-core's schema-YAML reader names a test
    by ``test_name:`` from 1.13.1 (``_named_tests``), when it is a string.
    Anything else is skipped rather than guessed.

    **A mapping of more than one key with no string ``test_name:`` is skipped
    and noted** (#131), such as a test with its ``config:`` beside its name
    rather than inside it. dbt refuses the project over one. That reader reads
    the test among the keys, on purpose (exmergo/dex#566), and the owner kept
    the skip here while exmergo/dex is asked; the note is this module's rule
    for input it skips, and it was skipped with none.
    """

    pairs: list[tuple[str, Any]] = []
    if not isinstance(tests, list):
        return pairs
    for entry in tests:
        if isinstance(entry, str):
            pairs.append((entry, None))
        elif isinstance(entry, dict) and isinstance(entry.get("test_name"), str):
            pairs.append((entry["test_name"], entry))
        elif isinstance(entry, dict) and len(entry) == 1:
            (name, payload), = entry.items()
            pairs.append((str(name), payload))
        elif isinstance(entry, dict) and entry:
            keys = ", ".join(sorted(str(key) for key in entry))
            note = (
                f"{where} lists a test as a mapping of several keys ({keys}) with "
                "no string `test_name`, which dbt refuses; skipped"
            )
            if note not in notes:
                notes.append(note)
    return pairs


def _test_arguments(payload: Any) -> dict[str, Any]:
    """A test's inputs, read beside its name and under ``arguments:``.

    dbt asks for a generic test's inputs under ``arguments:``, and merges that
    mapping over the keys beside the test's name, ``arguments`` winning.
    exmergo-dex-core's schema-YAML reader does the same from 1.13.1
    (``_test_arguments``, ``exmergo/dex#565``), and this matches it, so
    ``declarations()`` and its reader agree about a model's grain and joins.
    An ``arguments:`` that is not a mapping is ignored, as it is there, and a
    payload that is not a mapping has no inputs.
    """

    if not isinstance(payload, dict):
        return {}
    arguments = payload.get("arguments")
    return {**payload, **arguments} if isinstance(arguments, dict) else payload


#: The two keys dbt reads an entry's tests under. `data_tests` is its current
#: spelling and `tests` the older alias for it.
_TEST_KEYS = ("tests", "data_tests")


def _entry_tests(entry: dict[str, Any], where: str, notes: list[str]) -> list[tuple[str, Any]]:
    """An entry's tests, read under ``tests:`` and ``data_tests:`` both.

    Reading ``tests:`` alone read every ``data_tests:`` list as nothing, and
    said nothing, whoever wrote it. Reconcile writes that spelling itself: from
    exmergo-dex-core 1.10.0 it follows a file's or a list's ``data_tests``
    spelling, and from 1.12.7 (``exmergo/dex#513``) it writes ``data_tests:``
    where the file has no spelling to follow.

    A key holding something other than a list or nothing is noted and ignored.
    An entry declaring both keys is read as the union, ``tests`` first, with an
    identical entry under both read once, and noted with the remedy: dbt
    refuses such an entry when ``tests`` lists anything, and dex-core 1.12.7
    refuses to edit a file that carries one. Refusing it here instead would
    break the rule at the head of this module.
    """

    for key in _TEST_KEYS:
        value = entry.get(key)
        if value is not None and not isinstance(value, list):
            notes.append(f"{where} declares `{key}` as something other than a list; ignored")
    if all(key in entry for key in _TEST_KEYS):
        notes.append(
            f"{where} declares both `tests` and `data_tests`; what each lists is read "
            "here, but dbt and dex-core can refuse an entry declaring both, so keep one key"
        )
    first = _test_names(entry.get("tests"), where, notes)
    second = _test_names(entry.get("data_tests"), where, notes)
    return first + [pair for pair in second if pair not in first]


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

            composites = _composite_keys(model, entry, notes)
            singles = _single_column_keys(model, entry, joins, notes)

            # A model-level combination and a column-level uniqueness claim are
            # two different statements of the same grain, and when both appear
            # they can disagree. Prefer the combination - it is the only one of
            # the two that can express a multi-column key - but say so, because
            # silently dropping the other would hide a real authoring conflict.
            # A model declaring two combinations keeps both.
            if composites:
                keys.extend(composites)
                if singles:
                    dropped = ", ".join(sorted({k.columns[0] for k in singles}))
                    notes.append(
                        f"{model!r} declares a composite grain and also a "
                        f"column-level unique on {dropped}; the composite wins"
                    )
            else:
                keys.extend(singles)

    return _once(keys), joins, notes


def _once(keys: list[DeclaredKey]) -> list[DeclaredKey]:
    """``keys`` with each key once per model, the first kept, in order.

    **One claim, however often it is written** (#131). A column's ``unique``
    written twice, by either spelling, on a column listed twice, or in a second
    entry or file declaring the model, read as two keys on one column; so did a
    composite key written twice. exmergo-dex-core's schema-YAML reader keeps
    one key per model and column, compared as written, and one composite per
    model and set of columns, compared without order or case, across every
    file it reads, keeping the first. This compares the same way. A key on one
    column cannot match a composite, which has two or more.
    """

    found: dict[tuple[str, tuple[str, ...]], DeclaredKey] = {}
    for key in keys:
        columns: tuple[str, ...] = key.columns
        if len(columns) > 1:
            columns = tuple(sorted(c.lower() for c in columns))
        found.setdefault((key.model, columns), key)
    return list(found.values())


#: The test that declares a model-level composite grain.
_COMPOSITE_TEST = "unique_combination_of_columns"


def _composite_keys(model: str, entry: dict[str, Any], notes: list[str]) -> list[DeclaredKey]:
    """Each model-level ``unique_combination_of_columns`` that is sane.

    **Every one is read, in order** (#131). This read the first alone, so a
    second composite on the model was unread, and ``maintain reconcile``,
    which reads the grain through ``definitions()``, would propose a
    column-level ``unique`` on one of its columns: a key the project never
    declared. dbt runs every one, and exmergo-dex-core's schema-YAML reader
    reads every one. One written twice is read once by :func:`_once`, across
    every entry for the model.

    The test is read bare or under any package prefix: the bare name, or any
    name ending in ``.unique_combination_of_columns``. That is
    exmergo-dex-core's own rule for schema YAML, read from
    ``exmergo_dex_core/dbt_project.py`` in its 1.13.1 wheel, and it is matched
    rather than narrowed to ``dbt_utils.``. Comparing the bare name alone read
    ``dbt_utils.unique_combination_of_columns``, the spelling dbt-utils
    documents for its own test, as no key, with no note.

    **The columns are read beside the test's name or under ``arguments:``**
    (:func:`_test_arguments`), and a test named by ``test_name:`` is read too
    (:func:`_test_names`). ``arguments:`` is the form dbt-utils' README shows.
    Up to 1.13.0 the same reader took ``combination_of_columns`` from directly
    under the test alone, and this one matched it, so a key written the way
    dbt asks was read as none. An entry with no columns in either place is
    noted as declaring none.

    **A list holding something other than a column name reads as no key, and
    is noted** (#131). Reading its names alone read ``[a, b, 1]`` as a key on
    ``(a, b)``, fewer columns than the test checks, which claims more than the
    test does. exmergo-dex-core's reader takes a composite only from a list
    whose columns are all strings, and reads none from this one. A single
    name, ``[a]``, is still read as a key on that column, where that reader
    reads none: the owner kept it here while exmergo/dex is asked. An empty
    string is a string, so this check passes it, and ``named`` drops it:
    ``[a, b, '']`` reads as ``(a, b)``, where that reader reads
    ``(a, b, '')``. That is not ruled.
    """

    found: list[DeclaredKey] = []
    for name, payload in _entry_tests(entry, repr(model), notes):
        if name != _COMPOSITE_TEST and not name.endswith(f".{_COMPOSITE_TEST}"):
            continue
        columns = _test_arguments(payload).get("combination_of_columns")
        if not isinstance(columns, list) or not columns:
            notes.append(f"{model!r} declares a composite grain with no columns; ignored")
            continue
        named = tuple(str(c) for c in columns if isinstance(c, str) and c)
        if not named:
            notes.append(f"{model!r} declares a composite grain with no usable columns; ignored")
            continue
        if not all(isinstance(c, str) for c in columns):
            notes.append(
                f"{model!r} declares a composite grain listing something other "
                "than a column name; ignored"
            )
            continue
        found.append(DeclaredKey(model=model, columns=named, source="combination"))
    return found


def _single_column_keys(
    model: str, entry: dict[str, Any], joins: list[DeclaredJoin], notes: list[str]
) -> list[DeclaredKey]:
    """Column-level ``unique`` keys, collecting ``relationships`` joins en route.

    Joins are appended rather than returned because they are found here but do
    not belong to the key result; threading them back through a second return
    value would make both callers unpack something they do not use. A
    relationship's ``to`` and ``field`` are read beside the test's name or
    under ``arguments:`` (:func:`_test_arguments`).

    A ``unique`` written twice is read once by :func:`_once`, across every
    entry for the model.
    """

    found: list[DeclaredKey] = []
    for column_entry in entry.get("columns") or []:
        if not isinstance(column_entry, dict):
            continue
        column = column_entry.get("name")
        if not isinstance(column, str) or not column:
            continue
        for name, payload in _entry_tests(column_entry, f"{model}.{column}", notes):
            if name == "unique":
                found.append(DeclaredKey(model=model, columns=(column,), source="unique"))
            elif name == "relationships" and isinstance(payload, dict):
                inputs = _test_arguments(payload)
                target = _relationship_target(inputs.get("to"))
                field = inputs.get("field")
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


def _absorb_source_tables(
    entry: dict[str, Any],
    *,
    origin: str,
    reader: str,
    declared_in: str | None,
    found: dict[tuple[str, str | None, str], ExternalSource],
    notes: list[str],
) -> int:
    """Fold one ``sources[]`` entry's tables into ``found``, and count them.

    Split from :func:`parse_source_declarations` so each reads under the class A
    ceiling; the notes are the same ones, in the same words, and the merge rule
    for a table declared twice is stated where it is applied.
    """

    system = entry.get("name")
    if not isinstance(system, str) or not system:
        notes.append(f"source declaration {origin!r} has a source with no name; skipped")
        return 0
    schema = entry.get("schema")
    schema_name = schema if isinstance(schema, str) and schema else None

    declared = 0
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
        declared += 1
        found_key = (system, schema_name, table)
        columns = _named(table_entry.get("columns"))
        existing = found.get(found_key)
        if existing is None:
            found[found_key] = ExternalSource(
                system=system,
                table=table,
                schema_name=schema_name,
                columns=columns,
                read_by=(reader,),
                declared_in=declared_in,
            )
        else:
            merged = list(existing.columns)
            merged.extend(c for c in columns if c not in existing.columns)
            # The first declaration's provenance is kept when a second
            # reader joins. Two readers of one table were declared in two
            # places and the field holds one, so overwriting would make
            # which one survives depend on sort order; keeping the first
            # at least makes it stable and the `read_by` tuple says there
            # is more than one place to look.
            found[found_key] = ExternalSource(
                system=system,
                table=table,
                schema_name=schema_name,
                columns=tuple(merged),
                read_by=existing.read_by + (reader,),
                declared_in=existing.declared_in or declared_in,
            )
    return declared


def parse_source_declarations(
    sources: dict[str, str],
) -> tuple[list[ExternalSource], list[str]]:
    """Parse source-declaration YAML into external sources, and notes.

    ``sources`` is ``{origin: file text}``, and **the origin names the model that
    reads the declared tables**. Keying by the reader is what lets one input carry
    both halves a consumer needs - which tables the project depends on, and
    which model each one lands in - without a second mapping that could
    disagree with the first.

    **The origin may be a bare model name or a key naming a file**, and the
    reader is its stem either way. A caller holding text in memory - the
    conformance suite, a host, :func:`~.artifact.loads` - passes the model name
    and always has. A caller reading a directory passes
    ``sources/dim_date.yml``, and the stem of that is the same string the bare
    form would have been, which is why widening the key was not a change to what
    this returns.

    That is worth stating because this is **the one parser that reads its key as
    data rather than as a label**. The other two use it only in notes. Take the
    whole key as the reader and every source in a working project is attributed
    to a model the graph does not build, silently, with a note saying so.

    ``declared_in`` is set only when the origin names a place. A bare model name
    is not provenance, and putting one where a consumer expects a file would be
    the fabricated value :class:`~.model.ExternalSource` refuses elsewhere.

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
        # The reader is the stem, which is the whole origin when the caller
        # passed a bare model name. `declared_in` is the origin itself, and only
        # when it names somewhere.
        reader = PurePosixPath(origin).stem
        declared_in = origin if origin != reader else None
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
            declared_here += _absorb_source_tables(
                entry, origin=origin, reader=reader, declared_in=declared_in,
                found=found, notes=notes,
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
