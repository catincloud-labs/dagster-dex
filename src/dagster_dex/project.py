# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""A project whose source of truth is an orchestrated asset graph.

This implements tiers 1 and 2 and deliberately not tier 3. For the MODELS the
reason is structural rather than a preference: the source of truth is the Python
that builds the graph, so an edit written back into this project's reduction
would be an edit to something regenerated from elsewhere - overwritten on the
next run, and misleading in review in the meantime.

That reasoning does not extend to the declarations, and this docstring implied
it did until 2026-08-09. ``declaration_sources``, ``semantic_sources`` and
``source_declarations`` arrive as hand-written text that nothing regenerates, and
they are a real editable source of truth. The tier stayed declined because dex
could not route an edit to it, which is a different claim from being unable to
receive one.

**That reason expired on 2026-08-11.** Both upstream blockers are closed, and
the write path is open to a second format in the dex-core version this package
pins - see ``dex.DexProject``, which carries the detail and the two further
gates the fix uncovered. The tier is still declined, and the decline is now a
statement about work this package has not done rather than about a door dex
holds shut.

**The core takes plain data.** :class:`DagsterProject` is constructed from
models and declaration text, so it needs neither an orchestrator nor an engine
to build or to test. :meth:`DagsterProject.from_asset_graph` is the thin
convenience that reduces a live graph.

**This said `from_asset_graph` "is the only thing here that imports the
orchestrator - lazily" until 2026-08-12. Nothing here imports it at all.** That
method reads the definitions it is handed structurally - ``keys``,
``asset_deps``, ``metadata_by_key`` - so it never names the orchestrator, and
the ``[dagster]`` extra exists for a caller's convenience rather than for this
code. The distinction is load-bearing rather than pedantic: it is what lets the
artifact reader in :mod:`dagster_dex.artifact` serve a project from a
host that has no orchestrator installed, which is the point of that module.

That split is not tidiness. It is what makes the reduction testable against
fixtures rather than against a running deployment, and it is why the conformance
suite can be run by someone who has neither.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from .declarations import (
    parse_declarations,
    parse_semantics,
    parse_source_declarations,
)
from .model import (
    Fingerprint,
    Freshness,
    ProjectDeclarations,
    ProjectModel,
    definition_hash,
)
from .protocol import (
    EditConflict,
    EditOutcome,
    ProjectFile,
    ProjectFileView,
    ProposedEdit,
)

__all__ = ["DagsterProject", "EditableDagsterProject"]


class _AssetKey(Protocol):
    """Dagster's ``AssetKey``, named as a shape rather than imported.

    Only ``path`` is read, and only its last element - the model name.
    """

    @property
    def path(self) -> Sequence[str]: ...


class _AssetDefinition(Protocol):
    """What :meth:`DagsterProject.from_asset_graph` requires of a definition.

    This is the same move :mod:`dagster_dex.protocol` makes for the seam this
    package offers, applied to the side it consumes: three attributes, named
    structurally, so the reduction is type-checkable **without the orchestrator
    being installed or even importable.** Dagster's ``AssetsDefinition``
    satisfies it; nothing here has to say so.

    **Deliberately not exported.** It documents what this one method reads,
    not a contract this package asks anyone to implement. Widening it is a
    change to what `from_asset_graph` accepts and should be argued as one.
    """

    @property
    def keys(self) -> Iterable[_AssetKey]: ...

    @property
    def asset_deps(self) -> Mapping[_AssetKey, Iterable[_AssetKey]]: ...

    @property
    def metadata_by_key(self) -> Mapping[_AssetKey, Mapping[str, Any]]: ...


class DagsterProject:
    """An asset graph, read as a project.

    Reaches tier 2 (:class:`~.protocol.FingerprintedProject`) and stops there.
    ``propose_edits`` is absent rather than present-and-refusing, so
    ``isinstance(project, EditableProject)`` is False and a caller finds out by
    asking rather than by receiving an empty result that looks like success.

    **One instance is meant to live for one command**, which is what makes
    :meth:`declarations`' memo safe to hold. Everything an instance answers from is
    fixed at construction: the reduced models and the three source mappings are
    copied in ``__init__`` and never written again, so a memo cannot go stale
    against its own inputs. Re-reading a changed declaration file means building a
    new instance, which is what ``project_from_context`` does per command anyway.
    """

    format = "dagster"

    def __init__(
        self,
        models: Sequence[ProjectModel],
        *,
        name: str = "asset_graph",
        declaration_sources: Mapping[str, str] | None = None,
        semantic_sources: Mapping[str, str] | None = None,
        source_declarations: Mapping[str, str] | None = None,
    ) -> None:
        self._models = tuple(sorted(models, key=lambda m: m.name))
        self._name = name
        self._declaration_sources = dict(declaration_sources or {})
        self._semantic_sources = dict(semantic_sources or {})
        # Keyed by the model that reads the declared tables, not by file path -
        # see parse_source_declarations. A graph cannot supply this: a model
        # that reads a warehouse table in its own SQL draws no edge, so the
        # read is invisible to the orchestrator and has to be declared.
        self._source_declarations = dict(source_declarations or {})
        # `declarations()`'s memo. See that method for why it is held.
        self._declarations: ProjectDeclarations | None = None

    # -- tier 1 ---------------------------------------------------------------

    def declarations(self) -> ProjectDeclarations:
        """What the graph and its hand-written declarations state.

        Never raises. A malformed declaration file becomes a note and is
        skipped; an empty project returns empty declarations. Both are ordinary
        states on a read path, and turning either into an exception would make a
        warehouse with no project unexplorable.

        Declarations naming a model the graph does not build are kept, with a
        note. They are a real statement by the author, and dropping them here
        would hide the far more likely cause - a renamed or removed asset - by
        making the declaration silently disappear along with it.

        **Memoized, once per instance**, the same way dex-core's own
        ``DbtProject.load()`` is and for the same reason: the tier-2 accessors each
        need it and a single command needs several of them. ``DexProject``'s
        ``definitions()``, ``transform_layer()`` and ``semantic_layer()`` call this
        separately, and ``notes()`` calls it again, so one ``maintain snapshot``
        re-parsed every declaration file three or four times. Measured on the real
        project before adding the memo: **21.0 ms** per call (50 warm calls, min
        20.1, max 26.2), so about 63 ms of repeated parsing per command.

        Safe to hold because the result is a pure function of state fixed at
        construction: the models and the three source mappings are copied in
        ``__init__`` and never written again, and ``ProjectDeclarations`` is a
        frozen dataclass of tuples, so a caller cannot mutate what it is handed and
        reach the next caller. The memo's lifetime is the instance's, which is why
        the class docstring says how long an instance is meant to live.
        """

        if self._declarations is not None:
            return self._declarations

        keys, joins, notes = parse_declarations(self._declaration_sources)
        semantic_models, metrics, semantic_notes = parse_semantics(self._semantic_sources)
        notes.extend(semantic_notes)
        sources, source_notes = parse_source_declarations(self._source_declarations)
        notes.extend(source_notes)

        known = {m.name for m in self._models}
        dangling = sorted(
            {k.model for k in keys if k.model not in known}
            | {j.from_model for j in joins if j.from_model not in known}
        )
        if dangling:
            notes.append(
                "declared for models the graph does not build: "
                + ", ".join(dangling)
            )

        # A source attributed to a model that does not exist is kept for the
        # same reason a dangling key is: the table is still a real dependency of
        # this project on the warehouse, and dropping it would take a live
        # contract out of the picture along with the stale attribution. Named
        # separately from the keys above because the cause differs - a renamed
        # reader, not a renamed subject.
        unread = sorted(
            {reader for s in sources for reader in s.read_by if reader not in known}
        )
        if unread:
            notes.append(
                "sources declared as read by models the graph does not build: "
                + ", ".join(unread)
            )

        self._declarations = ProjectDeclarations(
            format=self.format,
            name=self._name,
            models=self._models,
            sources=tuple(sources),
            declared_keys=tuple(keys),
            declared_joins=tuple(joins),
            semantic_models=tuple(semantic_models),
            metrics=tuple(metrics),
            # There is no compiled artifact between the graph and this
            # reduction, so there is nothing that can fall out of date with it.
            # Reporting FRESH here would be a claim nobody checked.
            freshness=Freshness.NOT_APPLICABLE,
            notes=tuple(notes),
        )
        return self._declarations

    # -- tier 2 ---------------------------------------------------------------

    def fingerprint(self) -> Fingerprint:
        """Hash each layer over the models it contains and their dependencies.

        Dependencies are part of the hash because a rewiring that moves no model
        between layers still changes what the layer computes, and a fingerprint
        that missed it would call a real change no change.

        Models with no layer are grouped under ``"unassigned"`` rather than
        dropped: a model outside every layer is exactly the kind of thing a
        drift report should surface, and silently excluding it from the hash
        would make it invisible in both directions.

        **External sources hash under ``"sources"``, and only when there are
        any.** They belong in the fingerprint because gaining or losing one is a
        change in what the project depends on, and a drift report that missed it
        would call a new warehouse dependency no change. The entry is omitted
        entirely when no sources are declared, so a project that never had them
        fingerprints exactly as it did before this existed - an added field
        should not read as drift on every project that ignores it.

        ``"sources"`` and ``"unassigned"`` are both names a real layer could
        collide with. The keys are the format's own to choose, so this is a
        naming convention rather than a guarantee; a graph that labels a layer
        either of those merges the two hashes.
        """

        by_layer: dict[str, list[ProjectModel]] = {}
        for model in self._models:
            by_layer.setdefault(model.layer or "unassigned", []).append(model)

        layers = {
            layer: definition_hash(
                "\n".join(
                    f"{m.name}({','.join(m.depends_on)})"
                    for m in sorted(members, key=lambda m: m.name)
                )
            )
            for layer, members in by_layer.items()
        }

        sources, _ = parse_source_declarations(self._source_declarations)
        if sources:
            # Schema included: the same table name in a different dataset is a
            # different warehouse object, and a hash that ignored the schema
            # would call a repointed source unchanged.
            layers["sources"] = definition_hash(
                "\n".join(
                    f"{s.system}.{s.schema_name or ''}.{s.table}"
                    for s in sorted(sources, key=lambda s: (s.system, s.table))
                )
            )

        return Fingerprint(layers=layers, models=tuple(m.name for m in self._models))

    # -- construction ---------------------------------------------------------

    @classmethod
    def from_asset_graph(
        cls,
        assets: Iterable[_AssetDefinition],
        *,
        name: str = "asset_graph",
        declaration_sources: Mapping[str, str] | None = None,
        semantic_sources: Mapping[str, str] | None = None,
        source_declarations: Mapping[str, str] | None = None,
    ) -> DagsterProject:
        """Reduce a live Dagster asset graph to a project.

        Reads only the orchestrator's public surface - ``keys``, ``asset_deps``,
        ``metadata_by_key`` - so nothing here depends on an internal module path
        that can move between releases. Held to the same standard this package
        asks of its own consumers.

        **Duplicates are detected against the raw definitions, never a built
        graph.** ``AssetGraph.from_assets`` collapses two definitions sharing a
        key into one node without complaint, so by the time a graph exists the
        collision is already invisible and a check against it can never fire.

        The comparison is case-folded because downstream consumers key models by
        name, and two names differing only in case collide the moment anything
        writes them to a case-insensitive filesystem - silently dropping one.

        A duplicate is an error rather than a note: one of the two models is
        about to disappear, and every declaration keyed by that name would then
        attach to whichever happened to survive.

        ``source_declarations`` is passed through untouched. Nothing about it
        can be read off ``assets`` - a model that reads a warehouse table in its
        own SQL has no dependency edge to find - so the reduction neither
        derives it nor validates it against the graph beyond noting a reader it
        does not build.
        """

        return cls(
            _reduce_asset_graph(assets),
            name=name,
            declaration_sources=declaration_sources,
            semantic_sources=semantic_sources,
            source_declarations=source_declarations,
        )


def _reduce_asset_graph(assets: Iterable[_AssetDefinition]) -> list[ProjectModel]:
    """The reduction itself, as a function two constructors can share.

    Extracted when a second project class needed it. Copying it into the second
    one would have been the duplication that produces the next gap: two
    near-identical readers of the orchestrator's surface, one of which stops
    being maintained.
    """

    definitions = list(assets)

    flat_keys = [key.path[-1] for d in definitions for key in d.keys]
    seen: dict[str, str] = {}
    for model_name in flat_keys:
        folded = model_name.casefold()
        if folded in seen:
            raise ValueError(
                f"two assets reduce to the same model name: "
                f"{seen[folded]!r} and {model_name!r}"
            )
        seen[folded] = model_name

    models: list[ProjectModel] = []
    for definition in definitions:
        deps_by_key = definition.asset_deps
        metadata_by_key = definition.metadata_by_key
        for key in definition.keys:
            layer = (metadata_by_key.get(key) or {}).get("layer")
            models.append(
                ProjectModel(
                    name=key.path[-1],
                    depends_on=tuple(
                        sorted(p.path[-1] for p in deps_by_key.get(key, ()))
                    ),
                    layer=str(layer).lower() if layer else None,
                )
            )

    return models


class EditableDagsterProject(DagsterProject):
    """The same project, plus the one channel that can receive an edit.

    **A separate class rather than a method on** :class:`DagsterProject`, and
    that is the whole design. :class:`~.protocol.EditableProject` is
    ``runtime_checkable``, so it matches on a method being *present*. Put
    ``propose_edits`` on the base and every instance claims the write tier -
    including one built from an artifact, which is a JSON file carrying
    ``{name: text}`` and no filesystem behind it at all. Such an instance would
    have to refuse at call time, which is the present-and-refusing shape this
    package argues against in :mod:`.protocol`: the caller finds out by being
    handed an empty result that looks like success, instead of by asking.

    Splitting it means ``isinstance(project, EditableProject)`` is the truth for
    every instance, and the factory decides which truth to build.

    **What can receive an edit is the declarations, not the models.** The models
    are a reduction of a running asset graph, whose source of truth is the code
    that produced it: writing into the reduction edits something regenerated on
    the next run. The declared keys, joins, semantics and sources are
    hand-written YAML that nothing regenerates, they are version-controlled, and
    they are exactly the artifact a mechanical ``unique`` test lands in. Those
    are different claims about different files, and collapsing them is what this
    package spent a release doing before it noticed.

    ``root`` is what the keys are relative to. ``surface`` is the region of that
    keyspace edits may touch, as directory names - see :meth:`editing_surface`.
    """

    def __init__(
        self,
        models: Sequence[ProjectModel],
        *,
        root: str | os.PathLike[str],
        surface: Sequence[str],
        name: str = "asset_graph",
        declaration_sources: Mapping[str, str] | None = None,
        semantic_sources: Mapping[str, str] | None = None,
        source_declarations: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(
            models,
            name=name,
            declaration_sources=declaration_sources,
            semantic_sources=semantic_sources,
            source_declarations=source_declarations,
        )
        self._root = Path(root)
        self._surface = tuple(surface)

    @classmethod
    def from_asset_graph(  # type: ignore[override]
        cls,
        assets: Iterable[_AssetDefinition],
        *,
        root: str | os.PathLike[str],
        surface: Sequence[str],
        name: str = "asset_graph",
        declaration_sources: Mapping[str, str] | None = None,
        semantic_sources: Mapping[str, str] | None = None,
        source_declarations: Mapping[str, str] | None = None,
    ) -> EditableDagsterProject:
        """The same reduction, plus the two coordinates the write tier needs.

        Overridden rather than inherited because the base classmethod builds
        ``cls(models, ...)`` and this class requires ``root`` and ``surface``
        besides. Giving them defaults would be the cheaper change and the wrong
        one: an editable project with no surface admits no edit anywhere, and it
        would be constructible by accident.
        """

        return cls(
            _reduce_asset_graph(assets),
            root=root,
            surface=surface,
            name=name,
            declaration_sources=declaration_sources,
            semantic_sources=semantic_sources,
            source_declarations=source_declarations,
        )

    # -- tier 3 ---------------------------------------------------------------

    def editing_surface(self) -> tuple[str, ...]:
        """The region of this project's keyspace an edit may land in.

        Directory names, matched by path segment: ``declarations`` admits
        ``declarations/orders.yml`` and does not admit
        ``declarations_backup/orders.yml``.

        **Containment is a safety property, not a lookup.** It is what keeps a
        mistaken or hostile key from reaching the rest of the repository, and it
        has to be declared by this format because only this format knows its own
        layout. An empty surface refuses every edit rather than admitting all of
        them, which is the same statement declining the tier makes and is why
        the factory does not build this class without at least one directory to
        name.
        """

        return self._surface

    def editable_view(self) -> ProjectFileView:
        """The editable files, keyed as this format keys them, with their hashes.

        Built from the text this instance was constructed with rather than from a
        fresh read, which is the point: the pin an edit is planned against and
        the surface it is checked against then come from **one** reading of the
        project. Two readings a moment apart can disagree, and the disagreement
        is silent - it renders an existing file as a create, and the write after
        it reports a conflict on a file nobody touched.

        Only files inside :meth:`editing_surface` appear. A directory configured
        somewhere else is still read, still parsed, and still contributes
        declarations; it is simply not somewhere this format claims it may write,
        and saying otherwise in the view would be claiming a surface the
        containment check would then refuse.
        """

        files: dict[str, ProjectFile] = {}
        for mapping in (
            self._declaration_sources,
            self._semantic_sources,
            self._source_declarations,
        ):
            for key, text in mapping.items():
                if _within(key, self._surface):
                    files[key] = ProjectFile(
                        key=key, content=text, sha256=definition_hash(text)
                    )
        return ProjectFileView(files=files, root=str(self._root))

    def propose_edits(
        self,
        edits: Sequence[ProposedEdit],
        *,
        root: str | os.PathLike[str] | None = None,
        confirmed: bool = False,
    ) -> EditOutcome:
        """Write the edits, hash-checked and all-or-nothing. See the protocol.

        ``root`` overrides the directory this instance was built against, and the
        caller's answer wins when it gives one. That is not a nicety: a caller
        applying a stored proposal holds the place the proposal was *pinned*
        against, and this instance holds whatever the engine was configured for
        when it was built. The two agreeing is the common case rather than a
        guarantee, and the disagreement is silent.

        **Every target is re-read from disk here**, which is a different moment
        from :meth:`editable_view` on purpose. The view is what the proposal was
        built from; this is what is there now, possibly in another process, days
        later, after a human read the diff and changed their mind about a line.

        **The all-or-nothing is "check every target, then write", not a
        transaction**, and the difference is worth stating rather than implying.
        A failure part way through the writing leaves some files changed. What
        this rules out is the far likelier and far quieter case: a conflict on
        one target while the others are written anyway, leaving a project in a
        state neither the proposal nor the human intended and no record of which
        half landed.
        """

        base = Path(root) if root is not None else self._root

        conflicts: list[EditConflict] = []
        planned: list[tuple[Path, ProposedEdit]] = []
        for edit in edits:
            target = _resolve_within(base, edit.key, self._surface)
            found = (
                definition_hash(target.read_text(encoding="utf-8"))
                if target.is_file()
                else None
            )
            if found != edit.pinned_hash:
                conflicts.append(
                    EditConflict(key=edit.key, expected=edit.pinned_hash, found=found)
                )
            planned.append((target, edit))

        if conflicts and not confirmed:
            return EditOutcome(conflicts=tuple(conflicts))

        written: list[str] = []
        for target, edit in planned:
            if edit.new_content is None:
                if target.is_file():
                    target.unlink()
                    written.append(edit.key)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(edit.new_content, encoding="utf-8", newline="\n")
            written.append(edit.key)

        return EditOutcome(written=tuple(written), conflicts=tuple(conflicts))


def _within(key: str, surface: Sequence[str]) -> bool:
    """Is ``key`` inside one of the declared prefixes, by path segment?

    Segment-wise rather than by string prefix, because ``declarations`` must not
    admit ``declarations_backup/orders.yml``. An escape - an absolute key, or one
    climbing out through ``..`` - is refused before the surface is consulted and
    is not a format's to permit.
    """

    candidate = PurePosixPath(key.replace("\\", "/"))
    if candidate.is_absolute() or ".." in candidate.parts:
        return False
    return any(
        candidate == PurePosixPath(prefix) or PurePosixPath(prefix) in candidate.parents
        for prefix in surface
    )


def _resolve_within(base: Path, key: str, surface: Sequence[str]) -> Path:
    """``base / key``, refusing anything the surface does not admit.

    Checked here as well as wherever the proposal was built, because this method
    is reachable directly and a containment check that only runs upstream is a
    check somebody can route around. It costs a string comparison.
    """

    if not _within(key, surface):
        listed = ", ".join(surface) or "nothing"
        raise ValueError(
            f"edit key {key!r} is outside the editing surface this project "
            f"declares ({listed}); this format writes only what it says it owns"
        )
    return base / PurePosixPath(key)
