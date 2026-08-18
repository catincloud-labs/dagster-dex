# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""The boundary with dex-core. The only module here that knows it exists.

Everything else in this package is engine-free: the model, the protocol, the
reduction, and the conformance suite all run with dex-core uninstalled. This
module is the whole of the coupling, and keeping it to one file is deliberate -
it means the cost of the engine changing is bounded to something you can read
in a sitting, and it means the design above was not shaped by what the engine
happens to look like today.

**Public API only.** Nothing here imports an underscore-prefixed name. That is
the standard a second implementation should be held to, so this package holds
itself to it: if the mapping below needs a private helper, the right conclusion
is that the boundary is in the wrong place, not that the import is fine.

The import is lazy for the same reason: a host that never speaks to dex-core
should not pay for it, and a package that imports an optional dependency at
module scope is not really optional.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Mapping

from .model import Freshness, ProjectDeclarations
from .protocol import ProjectSource, ProposedEdit

if TYPE_CHECKING:  # pragma: no cover - a type-only import
    # Imported for the annotation alone. Every runtime import of `.project` in
    # this module stays deferred: a host that only ever reads an artifact should
    # not pay to import the reduction, and a module that eagerly imports what it
    # sometimes needs is not really deferring anything.
    from .project import EditableDagsterProject

__all__ = [
    "DexProject",
    "EditableDexProject",
    "ProjectContext",
    "project_from_context",
    "semantic_layer_notes",
    "to_project_definitions",
    "to_semantic_layer",
    "to_transform_layer",
    "transform_layer_notes",
]

#: Every option :func:`project_from_context` understands. Kept as an explicit set
#: because the factory REFUSES an option it cannot honor rather than ignoring it:
#: a silently dropped setting is indistinguishable from a working one until dex
#: is reading the wrong project, and a typo in a committed config file is the
#: likeliest way to produce one.
_KNOWN_OPTIONS = frozenset(
    {"artifact", "assets", "name", "declarations", "semantics", "sources"}
)

#: The two ways to say where the project comes from, and they are mutually
#: exclusive. ``assets`` reduces a live graph in this process; ``artifact`` reads
#: one already reduced. Exactly one is required - see :func:`project_from_context`
#: for why neither a default nor a precedence order is offered.
_SOURCE_OPTIONS = frozenset({"assets", "artifact"})

#: Options an artifact already answers for itself. Refused beside ``artifact``
#: rather than allowed to override it or to lose to it silently: the three
#: directory options would modify nothing while reading as the live source, and
#: ``name`` is written into the artifact by the side that knew the graph.
_ARTIFACT_INAPPLICABLE = frozenset({"declarations", "semantics", "sources", "name"})


@dataclass(frozen=True)
class ProjectContext:
    """What a project format gets to build itself from - a proposal.

    Two fields, because the formats disagree about what keys them and the
    disagreement does not resolve by picking whichever the first one used. A
    directory-backed project takes a path. A project reduced from a graph in
    memory has no path and no repository. A hosted one has service coordinates
    and neither.

    A construction contract shaped around the path-shaped case leaves the rest
    unbuildable, and widening it afterwards is a schema change with a
    deprecation attached - which is why this is worth settling before the second
    format exists rather than after.

    ``repo_root`` is where the engine was pointed, or ``None`` when there is no
    repository in the picture. A format is free to ignore it, and most
    non-filesystem ones will.

    ``options`` is the format's own non-secret coordinates, passed through
    verbatim. Refuse an option you cannot honor rather than accepting and
    ignoring it: a silently dropped setting is indistinguishable from a working
    one until something reads the wrong project.

    **No secret arrives here.** A format named in committed configuration is
    named in a committed file, so a credential in ``options`` would be a
    credential in version control.
    """

    repo_root: str | None = None
    options: Mapping[str, Any] = field(default_factory=dict)


def _model_refs(declarations: ProjectDeclarations) -> dict[str, list[str]]:
    """Each model's dependencies on other models this project builds.

    Filtered to built models on purpose: the engine's ``model_refs`` is the
    ``ref()`` graph, and a dependency on something the project does not build is
    not a ref. What it might be instead - an external source, or nothing we know
    about - is reported by :func:`transform_layer_notes` rather than guessed at
    here.
    """

    built = {m.name for m in declarations.models}
    refs: dict[str, list[str]] = {}
    for model in declarations.models:
        named = sorted(d for d in model.depends_on if d in built and d != model.name)
        if named:
            refs[model.name] = named
    return refs


def to_transform_layer(declarations: ProjectDeclarations) -> Any:
    """Map the neutral model onto dex-core's ``TransformLayer`` - the tier-2
    Maintain channel.

    Returns dex-core's type, so the caller needs dex-core installed. Never
    raises on project content: this is a read path, and the states worth
    reporting are reported by :func:`transform_layer_notes`.

    Three asymmetries, and unlike tier 1's they do not all have somewhere to go:

    **``files`` is left empty, and that is the honest answer.** It maps a path
    to a content hash, and this project has no files - its source of truth is
    the code that builds the graph. Fabricating entries keyed by model name
    would produce a mapping whose keys are not paths, handed to a field whose
    contract says they are. The field defaults to empty, so declining it is
    something the engine's own model already permits, and its only real
    consumers are on the write path this format does not implement.

    **``path`` is optional on every source, and we pass what we honestly have.**
    Since 1.6.0 ``SourceTable.path`` is ``str | None`` defaulting to ``None``, so
    a project with no files states that natively. This package passed ``""``
    until then - an undocumented sentinel, named as one by the release that
    removed the requirement (``exmergo/dex#193``, which this package's own
    reduction prompted). The field is read in exactly one place, as the
    ``declared_in`` provenance shown to an analyst on a ``dangling_source``
    finding, and that finding omits the key entirely rather than showing a blank
    one.

    **This said "and we pass ``None``" until 2026-08-18, and it was true because
    nothing ever set ``declared_in``.** The provenance was in the reader's hand
    and discarded one line later, so the field existed, the mapping carried it,
    and the value was always absent - a limitation this package's own parser
    created, which is a shape recorded elsewhere in this file. A source read out
    of a directory now names the file it was declared in; one handed over as text
    still passes ``None``, because a bare model name is not a place and inventing
    one is the fabricated evidence the original reasoning refused.

    **The disclosure has a home now.** ``TransformLayer.notes`` arrived in the
    same release, so a lossy tier-2 mapping can disclose itself in its own
    return value - the thing :func:`to_project_definitions` could always do via
    ``ProjectDefinitions.notes`` and this channel could not.
    :func:`transform_layer_notes` remains public, because a host that wants the
    caveats without building a layer still needs somewhere to get them, but the
    layer returned here carries them and the ``maintain`` commands fold them
    into their warnings.
    """

    try:
        from exmergo_dex_core.maintain.snapshot import (  # noqa: PLC0415 - optional dependency
            SourceTable,
            TransformLayer,
        )
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise ImportError(
            "to_transform_layer() needs exmergo-dex-core installed; "
            "install this package with the [dex] extra"
        ) from exc

    sources = [
        SourceTable(
            source_name=source.system,
            schema_name=source.schema_name,
            table=source.table,
            columns=list(source.columns),
            path=source.declared_in or None,
        )
        for source in declarations.sources
    ]

    model_sources: dict[str, list[str]] = {}
    for source in declarations.sources:
        for reader in source.read_by:
            model_sources.setdefault(reader, []).append(source.identifier)
    for reader in model_sources:
        model_sources[reader] = sorted(set(model_sources[reader]))

    return TransformLayer(
        files={},
        models=sorted(declarations.model_names()),
        sources=sources,
        model_sources=model_sources,
        model_refs=_model_refs(declarations),
        notes=list(transform_layer_notes(declarations)),
    )


def transform_layer_notes(declarations: ProjectDeclarations) -> tuple[str, ...]:
    """What :func:`to_transform_layer` could not carry across, in words.

    Since 1.6.0 these are also set on the returned layer's ``notes``; this stays
    public for a host that wants the caveats without building a layer, and it is
    the one place they are computed. A host that surfaces a snapshot to a human
    should surface these beside it; one that only compares fingerprints can
    ignore them.

    Empty only for a project with nothing in it. Any project this format
    actually reduces reports at least the absent file hashes, because that
    absence is a real limit on what a snapshot taken from it can detect - and an
    empty ``files`` compared against an empty ``files`` yields "no change",
    which reads as "no file drift" rather than "this cannot be checked here".
    The same distinction ``Freshness.NOT_APPLICABLE`` exists to make.
    """

    notes: list[str] = []

    if declarations.models:
        notes.append(
            "file hashes are absent: this project has no files, so drift on the "
            "transform layer is detectable through models, refs and sources but "
            "not through file content"
        )

    # A pathless-source note lived here until 1.6.0, when `SourceTable.path`
    # became `str | None`. It existed to disclose a sentinel: the field was
    # required, we had nothing true to put in it, and `""` needed explaining.
    # `None` explains itself, and `dangling_source` now omits `declared_in`
    # rather than showing it blank, so the note would restate what the data
    # already says. Removed rather than reworded - a note whose limitation is
    # gone is not a smaller note.

    built = {m.name for m in declarations.models}
    sourced = {s.table for s in declarations.sources} | {
        s.identifier for s in declarations.sources
    }
    unresolved = sorted(
        {
            dependency
            for model in declarations.models
            for dependency in model.depends_on
            if dependency not in built and dependency not in sourced
        }
    )
    if unresolved:
        notes.append(
            "dependencies on neither a built model nor a declared source, "
            "omitted from model_refs: " + ", ".join(unresolved)
        )

    return tuple(notes)


def to_semantic_layer(declarations: ProjectDeclarations) -> Any:
    """Map the neutral model onto dex-core's ``SemanticLayer`` - the other half of
    the tier-2 Maintain channel.

    Returns dex-core's type, so the caller needs dex-core installed.

    **The mapping that makes this worth having is name to physical column.**
    ``SemanticModelDef`` keys every entity, dimension and measure to the warehouse
    column behind it, and drift resolves those columns against what the warehouse
    currently has: a column that has gone away raises ``dangling_reference`` at
    high severity. A layer whose columns are all ``None`` still validates and still
    compares clean, so the check simply never runs. That is the whole reason
    :class:`~.model.SemanticField` carries ``column``.

    Three asymmetries, and they are all disclosed by :func:`semantic_layer_notes`
    rather than papered over:

    **``path`` is optional since 1.6.0 and we pass ``None``**, for the same reason
    a source's is: the field is provenance shown to a human, and ``None`` reads as
    "no provenance" where a synthesized path reads as evidence. It was ``""`` while
    the field was required.

    **``entities`` is left empty** because we declare none. It defaults to ``{}``,
    so this is a field the engine's own model permits us to decline.

    **``Metric.kind`` has nowhere to go.** ``MetricDef`` carries
    ``input_measures`` and ``input_metrics``, which describe what a metric is
    computed *from*, not how. A simple metric and an average over the same measure
    map identically here.
    """

    try:
        from exmergo_dex_core.maintain.snapshot import (  # noqa: PLC0415 - optional dependency
            MetricDef,
            SemanticLayer,
            SemanticModelDef,
        )
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise ImportError(
            "to_semantic_layer() needs exmergo-dex-core installed; "
            "install this package with the [dex] extra"
        ) from exc

    semantic_models = [
        SemanticModelDef(
            name=model.name,
            path=None,
            content_sha256=model.definition_sha,
            model_ref=model.model or None,
            entities={},
            dimensions={f.name: f.column for f in model.dimensions},
            # Values here are required `str`, unlike `dimensions`, so a field with
            # no resolvable column is absent rather than present-and-None. Being
            # absent is what stops it being read as a mapping to nothing.
            categorical_dimensions={
                f.name: f.column
                for f in model.dimensions
                if f.categorical and f.column is not None
            },
            measures={f.name: f.column for f in model.measures},
        )
        for model in declarations.semantic_models
    ]

    metrics = [
        MetricDef(
            name=metric.name,
            path=None,
            content_sha256=metric.definition_sha,
            input_measures=[metric.measure] if metric.measure else [],
            input_metrics=[],
        )
        for metric in declarations.metrics
    ]

    return SemanticLayer(
        semantic_models=semantic_models,
        metrics=metrics,
        notes=list(semantic_layer_notes(declarations)),
    )


def semantic_layer_notes(declarations: ProjectDeclarations) -> tuple[str, ...]:
    """What :func:`to_semantic_layer` could not carry across, in words.

    Set on the returned layer's ``notes`` since 1.6.0, and public for the same
    reason :func:`transform_layer_notes` is: a host may want the caveats without
    building a layer.

    Empty for a project that declares no semantics. Otherwise it reports the
    unmapped columns, because that is the difference between a layer dex checks and
    one it merely stores, and nothing in the returned object distinguishes them.
    """

    notes: list[str] = []
    if not declarations.semantic_models and not declarations.metrics:
        return ()

    unmapped = [
        f"{model.name}.{field.name}"
        for model in declarations.semantic_models
        for field in (*model.dimensions, *model.measures)
        if field.column is None
    ]
    if unmapped:
        notes.append(
            f"{len(unmapped)} semantic field(s) resolve to no warehouse column, so "
            "drift cannot check them and their absence is indistinguishable from "
            "agreement: " + ", ".join(sorted(unmapped))
        )

    if declarations.semantic_models:
        notes.append(
            "entities are absent: this format declares none, so entity-level "
            "reference checks have nothing to run against"
        )

    kinds = sorted({m.kind for m in declarations.metrics if m.kind and m.kind != "simple"})
    if kinds:
        notes.append(
            "metric kind has no field on MetricDef, so these arrive "
            "indistinguishable from simple metrics: " + ", ".join(kinds)
        )

    return tuple(notes)


def to_project_definitions(declarations: ProjectDeclarations) -> Any:
    """Map the neutral model onto dex-core's ``ProjectDefinitions``.

    Returns dex-core's type, so the caller needs dex-core installed. Raises
    ``ImportError`` with a usable message if it is not, rather than failing
    later at an attribute access.

    Two asymmetries are worth naming, because they are the interesting part of
    doing this at all:

    **A key splits in two on the way across.** This package models a grain as
    one tuple of columns, where ``n == 1`` is not a special case. dex-core
    models the single-column case as ``DeclaredKey`` and the multi-column case
    as ``DeclaredCompositeKey`` - two types with different multiplicity. The
    mapping is lossless in this direction, and the split happens here rather
    than in the model, which is the point: a format should not have to adopt
    another format's shape to be readable by it.

    **Freshness does not survive.** ``ProjectDefinitions`` carries
    ``manifest_loaded`` / ``manifest_stale``, both booleans, so
    ``NOT_APPLICABLE`` has nowhere to land and arrives as ``False`` - which
    reads as "there is a manifest and it is current" rather than "there is no
    such artifact here". This function leaves a note saying so, because a
    consumer reading ``manifest_stale=False`` would otherwise be reading an
    assurance nobody gave. It is the one place the neutral model says something
    the engine's model cannot hear.
    """

    try:
        from exmergo_dex_core.dbt_project import (  # noqa: PLC0415 - optional dependency
            DeclaredCompositeKey,
            DeclaredForeignKey,
            DeclaredKey,
            ProjectDefinitions,
        )
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise ImportError(
            "to_project_definitions() needs exmergo-dex-core installed; "
            "install this package with the [dex] extra"
        ) from exc

    keys = [
        DeclaredKey(
            model=key.model,
            column=key.columns[0],
            unique=True,
            not_null=False,
            source=key.source,
        )
        for key in declarations.declared_keys
        if len(key.columns) == 1
    ]
    composite = [
        DeclaredCompositeKey(
            model=key.model,
            columns=list(key.columns),
            source=key.source,
        )
        for key in declarations.declared_keys
        if len(key.columns) > 1
    ]
    foreign = [
        DeclaredForeignKey(
            model=join.from_model,
            column=join.from_columns[0],
            to_model=join.to_model,
            to_column=join.to_columns[0],
            source=join.source,
        )
        for join in declarations.declared_joins
        # A multi-column join has no single-column representation on the far
        # side. Dropping it silently would understate the declared graph, so it
        # is reported below instead of being quietly halved.
        if len(join.from_columns) == 1 and len(join.to_columns) == 1
    ]

    notes = list(declarations.notes)
    if declarations.freshness is Freshness.NOT_APPLICABLE:
        notes.append(
            "this project has no compiled artifact, so manifest_stale=False "
            "means 'not applicable' rather than 'current'"
        )
    widened = [
        j for j in declarations.declared_joins
        if len(j.from_columns) > 1 or len(j.to_columns) > 1
    ]
    if widened:
        listed = ", ".join(sorted(f"{j.from_model}->{j.to_model}" for j in widened))
        notes.append(
            f"{len(widened)} multi-column join(s) omitted, having no "
            f"single-column representation: {listed}"
        )

    return ProjectDefinitions(
        present=not declarations.is_empty,
        project_dir=None,
        manifest_loaded=False,
        manifest_stale=False,
        relationship_source="declaration",
        semantic_source="declaration",
        declared_keys=keys,
        declared_composite_keys=composite,
        foreign_keys=foreign,
        built_relation_names=sorted(n.lower() for n in declarations.model_names()),
        metric_models=sorted({m.model for m in declarations.semantic_models if m.model}),
        notes=notes,
    )


class DexProject:
    """One of our projects wearing dex-core's project seam.

    A wrapper rather than a change to :class:`~.project.DagsterProject`, and that
    is the whole point of this module existing: our format keeps its own
    vocabulary and its own model, and the adaptation to somebody else's protocol
    lives at the boundary where it can be read in one sitting.

    Two renames happen here, and neither is cosmetic:

    **``format`` becomes ``name``.** dex-core's seam calls the format identifier
    ``name``; we call it ``format``, because ``name`` on a project reads like the
    name of the instance and we had that ambiguity to avoid. Forwarded as a
    property rather than copied, so a second format of ours cannot drift from the
    value it reports.

    **``declarations()`` becomes ``definitions()``.** Ours returns our neutral
    :class:`~.model.ProjectDeclarations`; theirs returns dex-core's
    ``ProjectDefinitions``. :func:`to_project_definitions` is the mapping, and the
    asymmetries it cannot carry arrive as notes on the result.

    **This reaches dex-core's tier 2**: ``definitions()`` for the Explore
    channel, plus ``transform_layer()`` and ``semantic_layer()`` for Maintain, so
    ``tier_of()`` reports 2 and this format can be a drift baseline.

    **Tier 3 is declined, and the reason is narrower than it used to read.** The
    models cannot receive an edit: they are a reduction of a running asset graph,
    whose source of truth is the code that produced it, so writing into the
    reduction would edit something regenerated on the next run. That much stands.

    **What did not stand is the blanket version of that claim**, which this
    docstring made until 2026-08-09. Declared keys, joins, semantics and sources do
    NOT come from the graph. They come from hand-written, version-controlled YAML,
    read as INPUT and passed through verbatim rather than regenerated. That YAML is
    a genuine editable source of truth, and it is exactly
    the artifact ``reconcile``'s highest-value mechanical edit targets: adding a
    ``unique`` test to a column in schema YAML. => *An asset graph carries neither
    column names nor join keys, so a format over one always reads its declarations
    from somewhere else; check what that somewhere is before declining on the
    graph's behalf.*

    **So the tier was declined because dex could not route an edit here, not
    because we could not receive one.** That held until 2026-08-11 and no longer
    does. Two blockers were filed - ``exmergo/dex#257``, where ``maintain
    reconcile`` gated its write path on ``isinstance(editable, DbtProject)`` and
    downgraded every other format to advisory regardless of tier, and
    ``exmergo/dex#258``, where the proposed edit paths were hardcoded
    ``models/staging/stg_<table>.{sql,yml}`` literals naming files this project
    does not have. Both are closed, resolved together by ``exmergo/dex#263``,
    which shipped ``PlacingProject`` in dex-core **1.6.4**. This package pins
    1.6.6, so the door is open in the version it is tested against.

    **The two issues were one seam, and filing them as two is the part worth
    keeping.** The paths reconcile builds are not filesystem paths; they are keys
    into the view the format's own ``load()`` returned. So a format that can say
    where an edit of a given kind lands has answered *whether* as well as
    *where*, and the class check becomes "did the format place it". Building the
    fix also found two further gates neither issue described: plan-time
    containment validated every edit against dbt's ``model_paths`` whatever
    produced it, and ``transform apply`` wrote every plan through
    ``dbt_project.write_edits``. => *Two independent-looking blockers sharing a
    caller are usually one, and building the fix is what finds out.*

    **The tier is still declined here, and that is now a statement about this
    package rather than about dex.** Implementing the write path remains the
    work; what changed is that doing it would no longer satisfy the conformance
    contract and receive nothing, which is the lesson recorded against this
    package's own entry point in ``pyproject.toml``: an extension point declared
    before anything exercised it.

    **History worth keeping, because the mistake was nearly sent to the engine's
    authors.** This docstring once said we *could not* serve ``semantic_layer()``,
    and reported that as a finding about a tier bundling two channels a format might
    serve unevenly. Both halves were false: a ``SemanticLayer`` built from what we
    already held validated against dex-core, and the physical column we claimed to
    lack was declared as ``expr:`` in our own source files, discarded by our own
    parser. => *Before reporting a limitation of someone else's contract, check
    whether your own parser created it.*
    """

    def __init__(self, project: ProjectSource):
        self._project = project

    @property
    def name(self) -> str:
        return self._project.format

    def definitions(self) -> Any:
        """dex-core's ``ProjectDefinitions``. Must not raise, per their tier 1.

        Ours does not either: :meth:`~.protocol.ProjectSource.declarations` carries
        the same promise, so the guarantee composes rather than being re-argued.
        """

        return to_project_definitions(self._project.declarations())

    def transform_layer(self) -> Any:
        """dex-core's ``TransformLayer``. One of their two tier-2 methods."""

        return to_transform_layer(self._project.declarations())

    def semantic_layer(self) -> Any:
        """dex-core's ``SemanticLayer``. The other tier-2 method."""

        return to_semantic_layer(self._project.declarations())

    def notes(self) -> tuple[str, ...]:
        """What the two tier-2 layers could not carry, since neither has a field for it.

        Both halves, in one call: a caller surfacing a snapshot to a human wants the
        transform caveats and the semantic ones together, and neither
        ``TransformLayer`` nor ``SemanticLayer`` has anywhere to put them.
        """

        declarations = self._project.declarations()
        return (
            *transform_layer_notes(declarations),
            *semantic_layer_notes(declarations),
        )


class EditableDexProject(DexProject):
    """The write tier, and where a proposed edit lands, wearing dex-core's names.

    Two seams meet here and they are not the same seam. dex-core's tier 3 is
    ``write_edits(edits, project_dir, *, confirmed=False)`` returning something
    with ``written`` and ``conflicts``; beside it, and deliberately not on it,
    ``PlacingProject`` asks ``edit_path`` and ``editing_surface``. Ours is
    ``propose_edits`` over :class:`~.protocol.ProposedEdit`. The mechanism is on
    our side, in :class:`~.project.EditableDagsterProject`, where it is testable
    with the engine uninstalled; everything below is translation.

    **Placement answers one kind and declines the rest, and that asymmetry is the
    reason the seam exists.** ``MODEL_SQL`` is ``None``: a model here is a node
    in a running asset graph, and a file authored for it would be regenerated
    away. ``SCHEMA_YML`` resolves, because the declared keys are hand-written
    YAML in this format's own vocabulary - dbt's schema-test spelling, which is
    what these files were already written in - so a ``unique`` test reconcile
    proposes lands somewhere this format's own parser reads it back as a declared
    key. One ``None`` and one path is a complete answer, and upstream's protocol
    names exactly this shape as what it was built for.

    **``model`` is the warehouse table, not our model name**, which upstream
    names as the thing this method is most often gotten wrong on. This format
    has no table-to-relation mapping - ``ProjectModel.relation`` is ``None`` -
    so the table name is used as the file stem rather than translated through a
    guess. A project whose declaration file is not named after the table it
    declares gets no edit and a warning saying so, which is upstream refusing to
    guess rather than this format writing to the wrong file.

    **A project that packs several models into one declaration file gets a
    warning, not an edit.** Reconcile reads the model name out of the placed
    key's stem, so placement here presumes one model per file. That is a real
    limit on the convention rather than a defect to work around: the alternative
    is a format guessing which entry in a shared file a finding is about.
    """

    def __init__(
        self, project: EditableDagsterProject, *, declarations_prefix: str
    ) -> None:
        super().__init__(project)
        # Narrowed for the type checker, and named separately rather than by
        # re-annotating the base's attribute: `DexProject` genuinely holds a
        # tier-1 project and re-declaring the field would be this class telling
        # the base what it holds. The two always refer to the same object.
        self._editable = project
        self._declarations_prefix = declarations_prefix

    def load(self) -> Any:
        """The editable files and the place their keys are relative to.

        **Nothing in dex-core's project protocols declares this method**, and two
        of its callers require it: ``transform.plans.plan`` calls it to pin each
        edit against the file it would change, and ``maintain.commands`` calls it
        before reconcile builds a proposal. So a format can satisfy
        ``EditableProject`` and ``PlacingProject`` in full, pass both shipped
        conformance contracts, and fail at the first real reconcile. Implemented
        here because the callers need it, not because the contract asked.

        Returns our own :class:`~.protocol.ProjectFileView` rather than dex-core's
        ``DbtProjectView``, which is what routes both callers down their
        format-neutral branch: ``plans.plan`` asks the *view* whether dbt's
        checks apply rather than asking the class that produced it, so handing
        back a dbt view would opt this format into dbt's macro-path and
        root-manifest rules and have it refused by them.
        """

        return self._editable.editable_view()

    def edit_path(self, kind: Any, model: str) -> str | None:
        """Where an edit of ``kind`` for the warehouse table ``model`` lives."""

        from exmergo_dex_core.transform.plans import (  # noqa: PLC0415 - optional dependency
            EditKind,
        )

        if kind is not EditKind.SCHEMA_YML:
            return None
        return f"{self._declarations_prefix}/{model}.yml"

    def editing_surface(self) -> list[str]:
        """The prefixes this format admits its edits may land in."""

        return list(self._editable.editing_surface())

    def write_edits(
        self, edits: Any, project_dir: Any = None, *, confirmed: bool = False
    ) -> Any:
        """dex-core's write tier, translated onto :meth:`propose_edits`.

        ``project_dir`` is the directory the plan being applied was pinned
        against, and it wins over the one this instance was built from. That is
        not deference for its own sake: this instance points wherever the engine
        was configured when it was built, the plan points where its hashes came
        from, and the two agreeing is the common case rather than a guarantee.

        The pin does the rest of the work. A plan applied against the wrong
        directory finds different content, or no file where it expected one, and
        both are conflicts - so a configuration that has moved under a stored
        plan is refused rather than written through.

        Returns dex-core's ``ApplyResult`` because it is the shipped shape their
        own protocol points at, and a local lookalike would be a second copy of a
        contract that can move.
        """

        from exmergo_dex_core.dbt_project import (  # noqa: PLC0415 - optional dependency
            ApplyResult,
            Conflict,
            EditOp,
        )

        proposed = [
            ProposedEdit(
                key=edit.path,
                new_content=None if edit.op is EditOp.DELETE else edit.new_content,
                pinned_hash=edit.old_content_hash,
            )
            for edit in edits
        ]
        outcome = self._editable.propose_edits(
            proposed, root=project_dir, confirmed=confirmed
        )
        return ApplyResult(
            written=list(outcome.written),
            conflicts=[
                Conflict(
                    path=conflict.key,
                    expected_sha256=conflict.expected,
                    found_sha256=conflict.found,
                )
                for conflict in outcome.conflicts
            ],
        )


# -- construction from configuration ------------------------------------------


def _load_yaml_dir(repo_root: str | None, option: str, value: object) -> dict[str, str]:
    """Read ``*.yml`` / ``*.yaml`` out of a directory into ``{key: text}``.

    Missing directory is an error rather than an empty mapping. A declaration
    directory that silently reads as empty produces a project with no declared
    keys, which is a *valid* project reporting nothing - indistinguishable from
    one that genuinely declares nothing, and it would quietly widen every grain
    finding dex makes.

    **The key is ``<directory name>/<file name>``, and it was the bare stem
    until 2026-08-18.** The stem threw away the directory and the suffix, which
    cost nothing while nothing wrote: the parsers use the key as an origin label
    in notes, and ``'orders'`` reads about as well as ``'declarations/orders.yml'``
    to a human - slightly worse, since it names something a reader then has to
    go looking for.

    It costs something the moment an edit has to land. dex asks a format where an
    edit of a given kind goes and checks the answer against the surface that
    format declares it owns, and both are keys into whatever the format's own
    view returned rather than filesystem paths. **A bare stem is inside no
    surface**, so a format keyed by one can name no honest region of itself: the
    only prefix admitting ``orders`` is one admitting everything.

    **Relative to the directory rather than to ``repo_root``**, deliberately.
    ``repo_root`` is nullable and the option may be absolute, so a key derived
    from it exists only sometimes - and a keyspace whose shape depends on how
    the caller was configured is one that cannot be reasoned about. The
    directory's own name is always there. This is the format's keyspace, not the
    filesystem's, which is the distinction upstream's placement seam is built
    on.

    One consequence, stated rather than discovered: two options pointed at
    directories sharing a name produce keys that look alike across two separate
    mappings. They cannot collide - each mapping comes from exactly one
    directory - but an edit placed by name alone would be ambiguous between them,
    which is a constraint on placement rather than on reading.
    """

    return _read_yaml_dir(_resolve_dir(repo_root, option, value))


def _resolve_dir(repo_root: str | None, option: str, value: object) -> Any:
    """The directory an option names, resolved and checked, as a ``Path``.

    Split out from :func:`_load_yaml_dir` because the factory needs the place as
    well as its contents: the keys are relative to the directory, so the
    directory is what a later write has to resolve them against. Reading the text
    and then re-deriving the path from a key would be a second answer to a
    question already answered, and the two can differ.
    """

    from pathlib import Path  # noqa: PLC0415 - stdlib, kept local for symmetry

    if not isinstance(value, str):
        raise ValueError(f"project option {option!r} must be a path string, got {type(value).__name__}")

    directory = Path(value)
    if not directory.is_absolute():
        if repo_root is None:
            raise ValueError(
                f"project option {option!r} is relative ({value!r}) and there is no "
                f"repo_root to resolve it against; give an absolute path or point "
                f"dex at a repository"
            )
        directory = Path(repo_root) / directory

    if not directory.is_dir():
        raise ValueError(f"project option {option!r} names {str(directory)!r}, which is not a directory")

    return directory


def _read_yaml_dir(directory: Any) -> dict[str, str]:
    """``{<directory name>/<file name>: text}`` for the YAML in one directory."""

    return {
        f"{directory.name}/{path.name}": path.read_text(encoding="utf-8")
        for path in sorted(directory.iterdir())
        if path.suffix in (".yml", ".yaml")
    }


def _project_from_artifact(repo_root: str | None, options: Mapping[str, Any]) -> DexProject:
    """Build from a serialized project rather than from a live graph.

    **A missing artifact is refused, not treated as an empty project.** The
    two are indistinguishable downstream - a project that declares nothing is
    perfectly valid - so tolerating absence would report "this warehouse has no
    declared joins" for what is actually a broken deploy or an unwritten volume,
    and would keep reporting it. The refusal names the path, which is the one
    thing that makes the cause findable.

    That is a deliberate difference from a directory-keyed format, where dex
    degrades to an empty view when no project is found. Degrading is right when
    "no project" is an ordinary state of the repository. It is wrong here: an
    artifact path is configured explicitly, so naming one that is not there is
    always a mistake somewhere, never a description of the warehouse.
    """

    from pathlib import Path  # noqa: PLC0415 - stdlib, kept local for symmetry

    from .artifact import ArtifactError, loads  # noqa: PLC0415 - deferred on purpose
    from .project import DagsterProject  # noqa: PLC0415 - deferred on purpose

    inapplicable = sorted(set(options) & _ARTIFACT_INAPPLICABLE)
    if inapplicable:
        raise ValueError(
            f"project format 'dagster' cannot honor {', '.join(inapplicable)} "
            f"alongside 'artifact': a serialized project carries its own "
            f"declarations and its own name, so these would either be read from "
            f"nowhere while looking like the live source, or lose to the file "
            f"without saying so. Remove them, or use 'assets' instead."
        )

    value = options["artifact"]
    if not isinstance(value, str):
        raise ValueError(
            f"project option 'artifact' must be a path string, got {type(value).__name__}"
        )

    path = Path(value)
    if not path.is_absolute():
        if repo_root is None:
            raise ValueError(
                f"project option 'artifact' is relative ({value!r}) and there is "
                f"no repo_root to resolve it against; give an absolute path or "
                f"point dex at a repository"
            )
        path = Path(repo_root) / path

    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ValueError(
            f"project option 'artifact' names {str(path)!r}, which does not "
            f"exist. Refused rather than read as an empty project, because a "
            f"project declaring nothing is valid and would be reported as a "
            f"warehouse with no declared keys or joins"
        ) from exc
    except OSError as exc:
        raise ValueError(
            f"project option 'artifact' names {str(path)!r}, which could not be "
            f"read: {exc}"
        ) from exc

    try:
        parsed = loads(text)
    except ArtifactError as exc:
        raise ValueError(f"project artifact {str(path)!r} is unusable: {exc}") from exc

    return DexProject(
        DagsterProject(
            parsed.models,
            name=parsed.name,
            declaration_sources=parsed.declaration_sources,
            semantic_sources=parsed.semantic_sources,
            source_declarations=parsed.source_declarations,
        )
    )


def project_from_context(context: Any) -> DexProject:
    """Build this format from a :class:`ProjectContext` - a ``ProjectFactory``.

    This is what ``.dex/config.yml``'s ``project.format`` resolves to, and it is
    the reason the entry point exists. dex-core calls it with one context and
    expects a project back; the wrapper is not optional, because a bare
    :class:`~.project.DagsterProject` speaks *our* vocabulary (``format``,
    ``declarations()``) and dex's seam wants *theirs* (``name``,
    ``definitions()``). Returning the unwrapped project is refused by dex as
    "missing name, definitions", which is a good error and still an avoidable one.

    **Two ways in, and exactly one of them per configuration.** Either reduce a
    live graph in this process::

        project:
          format: dagster
          options:
            assets: my_project.definitions:all_assets
            name: my_project
            declarations: my_project/declared
            semantics: my_project/semantic
            sources: my_project/sources

    ...or read one that was already reduced, by a process that had the graph::

        project:
          format: dagster
          options:
            artifact: project/my_project.json

    ``assets`` is a dotted ``module:attribute`` naming an iterable of Dagster
    asset definitions - the same shape ``dagster`` itself loads. ``artifact`` is
    a path to what :func:`~.artifact.dumps` wrote. Both, and the three directory
    options, are resolved against ``repo_root`` when relative.

    **Neither is a default and there is no precedence between them.** A
    configuration naming both is refused rather than resolved, because the two
    disagree by design - the artifact is a snapshot and the graph is live, so
    silently preferring one would make a host read a project the operator did
    not ask for and could not see they had not asked for.

    **The three directory options are refused alongside ``artifact``.** An
    artifact carries its declarations, so a ``declarations:`` beside it modifies
    nothing while reading as though the files on disk were live. That is the
    ordinary shape of a config that is quietly a day out of date.

    **Unknown options are refused by name.** Upstream's own factory contract
    checks for this, and the reasoning is the same one that makes a declined tier
    honest: accepting a setting you do not implement is a claim you cannot keep.

    **Construction is cheap on the artifact path and expensive on the graph
    path**, and the contract asks that it be cheap. dex builds a project per
    command rather than holding one, because a stale read is a wrong drift
    report. Reading an artifact is a file read and a YAML parse. Reducing a graph
    means importing a code location, which builds every asset definition in it -
    measured at ~2.6 s on a real project, which is what ``artifact`` exists to
    avoid. The import is deferred to this call rather than to module scope.
    """

    options = dict(getattr(context, "options", None) or {})

    unknown = sorted(set(options) - _KNOWN_OPTIONS)
    if unknown:
        raise ValueError(
            f"project format 'dagster' cannot honor option(s): {', '.join(unknown)}. "
            f"Known options: {', '.join(sorted(_KNOWN_OPTIONS))}. Refused rather than "
            f"ignored, because a dropped setting reads exactly like a working one."
        )

    named = sorted(key for key in _SOURCE_OPTIONS if options.get(key))
    if len(named) > 1:
        raise ValueError(
            f"project format 'dagster' takes exactly one of "
            f"{', '.join(sorted(_SOURCE_OPTIONS))}, and got both: "
            f"{', '.join(named)}. They are two different projects - 'assets' "
            f"reduces the graph as it is now, 'artifact' reads one reduced "
            f"earlier - so preferring one would silently serve a project you did "
            f"not choose. Name the one you mean."
        )
    if not named:
        raise ValueError(
            "project format 'dagster' needs either an 'assets' option naming the "
            "asset graph to reduce, as 'module:attribute' (e.g. "
            "'my_project.definitions:all_assets'), or an 'artifact' option "
            "naming a serialized project to read. There is nothing to discover "
            "from a directory: this format's source of truth is code."
        )

    repo_root = getattr(context, "repo_root", None)

    if named == ["artifact"]:
        return _project_from_artifact(repo_root, options)

    target = options.get("assets")
    if not isinstance(target, str) or ":" not in target:
        raise ValueError(
            f"project option 'assets' must be 'module:attribute' with a colon "
            f"between them, got {target!r}"
        )

    module_name, _, attribute = target.partition(":")
    from importlib import import_module  # noqa: PLC0415 - deferred on purpose

    try:
        module = import_module(module_name)
    except ImportError as exc:
        raise ValueError(
            f"project option 'assets' names module {module_name!r}, which could not "
            f"be imported: {exc}. It has to be importable by the process dex runs in."
        ) from exc

    try:
        assets = getattr(module, attribute)
    except AttributeError as exc:
        raise ValueError(
            f"project option 'assets' names {attribute!r} in {module_name!r}, which "
            f"does not define it"
        ) from exc

    from .project import (  # noqa: PLC0415 - deferred on purpose
        DagsterProject,
        EditableDagsterProject,
    )

    directories = {
        option: _resolve_dir(repo_root, option, options[option])
        for option in ("declarations", "semantics", "sources")
        if option in options
    }
    text = {
        option: _read_yaml_dir(directory) for option, directory in directories.items()
    }

    name = str(options.get("name", "asset_graph"))
    declarations = text.get("declarations")
    semantics = text.get("semantics")
    sources = text.get("sources")

    # THE WRITE TIER IS PER INSTANCE, AND THIS IS WHERE IT IS DECIDED.
    #
    # `EditableProject` is `runtime_checkable` and matches on a method being
    # present, so the decision cannot be a flag or a refusal at call time - it
    # has to be which class gets built. A project with no `declarations`
    # directory has nowhere for the one kind of edit this format can place, and
    # `edit_path` answering None for every kind is upstream's own description of
    # a format that should be declining the tier instead.
    #
    # The artifact path never reaches here at all: it returns above, from
    # `_project_from_artifact`, and an artifact is a JSON file carrying
    # `{name: text}` with no directory behind it.
    if "declarations" not in directories:
        return DexProject(
            DagsterProject.from_asset_graph(
                assets,
                name=name,
                declaration_sources=declarations,
                semantic_sources=semantics,
                source_declarations=sources,
            )
        )

    root = directories["declarations"].parent
    # A directory configured somewhere else is still read and still contributes
    # declarations. It is left out of the surface because a surface is a claim
    # about a region of ONE keyspace, and a directory under a different parent is
    # not addressable by a key relative to this root. Claiming it would produce
    # placements the containment check then refuses, which reads as dex declining
    # rather than as this format contradicting itself.
    surface = sorted(
        {
            directory.name
            for directory in directories.values()
            if directory.parent == root
        }
    )

    return EditableDexProject(
        EditableDagsterProject.from_asset_graph(
            assets,
            root=root,
            surface=surface,
            name=name,
            declaration_sources=declarations,
            semantic_sources=semantics,
            source_declarations=sources,
        ),
        declarations_prefix=directories["declarations"].name,
    )
