# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""A project, serialized - so the side that has the graph and the side that
reads it need not be the same process.

**Why this exists at all.** :meth:`~.project.DagsterProject.from_asset_graph`
reduces a live orchestrator graph, which means the process calling it must be
able to import that graph. That import builds every asset definition in the
code location, so it costs whole seconds where a file read costs milliseconds,
and none of it is the reduction: it is the orchestrator plus the code location,
so neither laziness nor caching reaches it (a host that builds a project per
command, as this seam's contract asks, never holds one long enough to amortize
it).

The split this module makes is the answer: **the side that already has the graph
reduces it once and writes the result down; the side that answers requests reads
that.** Construction on the read side becomes a file read and a YAML parse, which
is what the contract asked for in the first place.

**What it carries, and why so little.** :class:`~.project.DagsterProject` is
constructed from plain data - reduced models plus three mappings of declaration
*text*. So that is exactly what an artifact holds. It does **not** hold a
:class:`~.model.ProjectDeclarations`: parsing is cheap, and a project
rebuilt from its own inputs runs the same parsers, the same cross-checks and the
same notes as one built from a graph. An artifact of the *outputs* would instead
be a second implementation of the reduction, free to disagree with the first.

**Declarations are carried as TEXT, never as parsed structures.** They are
YAML, and ``SemanticModel.definition_sha`` is computed over a re-dump of the
parsed entry, so any round trip through another type system has to preserve
YAML's exactly. It does not: a bare ``2026-01-01`` parses to a date, becomes a
string in JSON, and comes back as a *quoted* scalar - a different digest for a
file nobody edited, reported as a definition change. Text has no such surface.
It is also what both existing readers already hand to the constructor, so the
artifact path and the directory path feed it byte-identical input.

**Absence is refused, not tolerated.** See :func:`loads`.

**This module is text, plus exactly one filesystem operation, and the asymmetry
is deliberate.** :func:`dump` takes a path; there is no ``load(path)``. Writing
needs the path because *atomicity is not expressible in text* - the swap has to
happen on a filesystem or it is not a swap. Reading does not, because what a
missing file *means* is a policy the caller owns and only the caller knows:
:mod:`~.dagster_dex.dex` refuses a missing artifact, because for dex a stale
drift report is worse than a loud failure, and a different host may reasonably
decide otherwise.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from collections.abc import Mapping, Sequence
from pathlib import Path

from .model import ProjectModel

__all__ = [
    "SCHEMA_VERSION",
    "ProjectArtifact",
    "ArtifactError",
    "dump",
    "dumps",
    "loads",
]

#: The version of the on-disk shape, written by :func:`dumps` and required by
#: :func:`loads`. Bump it when the shape changes in a way an older reader would
#: misread - never for an added field an older reader can ignore.
#:
#: The check is **equality, not a floor**. A reader meeting a version it does
#: not know cannot tell "newer, and compatible" from "newer, and reinterpreted";
#: guessing is how a field that changed meaning gets read with the old meaning
#: and reported as fact. The writer and reader ship in the same distribution, so
#: a mismatch means a half-finished deploy - which is worth a refusal.
SCHEMA_VERSION = 1


class ArtifactError(ValueError):
    """A project artifact could not be read.

    A ``ValueError`` because that is what this package's other refusals are, and
    what the engine boundary already turns into its own configuration error.
    """


@dataclass(frozen=True)
class ProjectArtifact:
    """A reduced project, as it travels between two processes.

    The fields are exactly :class:`~.project.DagsterProject`'s constructor
    arguments, plus provenance. That correspondence is deliberate: it is what
    keeps this a transport for the existing model rather than a second model
    that has to be kept in step with it.

    ``name`` is the graph's name, fixed by the writer. The reader refuses a
    ``name`` option beside an artifact rather than letting one override the
    other - see :func:`~.dex.project_from_context`.

    ``generated_at`` is the writer's own timestamp, carried because the reader
    cannot otherwise tell a project written minutes ago from one written before
    the last three deploys. Nothing in this module acts on it - an artifact is
    not refused for being old, because "old" is a judgment about a schedule this
    module cannot see. It is carried so a consumer that *does* know the schedule
    can make it.
    """

    name: str
    models: tuple[ProjectModel, ...]
    declaration_sources: Mapping[str, str]
    semantic_sources: Mapping[str, str]
    source_declarations: Mapping[str, str]
    generated_at: str
    schema_version: int = SCHEMA_VERSION


def dumps(
    *,
    name: str,
    models: Sequence[ProjectModel],
    generated_at: str,
    declaration_sources: Mapping[str, str] | None = None,
    semantic_sources: Mapping[str, str] | None = None,
    source_declarations: Mapping[str, str] | None = None,
) -> str:
    """Serialize a reduced project to JSON text.

    Keyword-only, and ``generated_at`` is required rather than defaulted to
    "now": this module has no clock of its own on purpose. A default would make
    every artifact look freshly written, including one produced by a replay or a
    test, and the timestamp's only job is to be trustworthy.

    Sorted keys and a trailing newline, so two runs over unchanged inputs
    produce byte-identical output. That is what lets a reviewer diff two
    artifacts, and what keeps a no-op regeneration from looking like a change.
    """

    document = {
        "schema_version": SCHEMA_VERSION,
        "name": name,
        "generated_at": generated_at,
        "models": [
            {
                "name": model.name,
                "depends_on": list(model.depends_on),
                "relation": model.relation,
                "layer": model.layer,
            }
            for model in sorted(models, key=lambda m: m.name)
        ],
        "declared": dict(declaration_sources or {}),
        "semantic": dict(semantic_sources or {}),
        "sources": dict(source_declarations or {}),
    }
    return json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def dump(
    path: str | os.PathLike[str],
    *,
    name: str,
    models: Sequence[ProjectModel],
    generated_at: str,
    declaration_sources: Mapping[str, str] | None = None,
    semantic_sources: Mapping[str, str] | None = None,
    source_declarations: Mapping[str, str] | None = None,
) -> None:
    """:func:`dumps`, plus a swap a reader cannot observe half of.

    **It takes a path rather than a file object, and that is forced rather than
    stylistic.** The staging file must be created in the *destination directory*,
    because ``os.replace`` is only atomic within a filesystem - and a caller
    handing over an open file has already chosen where it lives. A reader who
    knows ``json.dump`` will notice the divergence; this is the reason for it.

    **Why atomicity at all.** The consumer builds a project per command, so it
    reads this file at times the writer does not choose. A plain write is
    observable in three broken states: truncated, half-written, and
    zero-length - and the reader refuses all three, which is correct and means a
    regeneration would take the consumer down for its duration. ``os.replace`` is
    atomic on POSIX by definition, so a reader sees either the whole previous
    artifact or the whole new one.

    Each of the following was bought with a production failure, and none is
    tidiness:

    - **The temp file goes in the destination directory.** A cross-device rename
      raises ``OSError`` (EXDEV), and the destination is often a mounted volume
      that is not the writer's root filesystem. Seeing EXDEV from here means
      someone moved the staging location.
    - **flush + fsync before the replace.** Without them a hard reboot can leave
      a zero-length file that parses as nothing. The reader refuses it - loudly,
      and on every request until the next successful write. Microseconds on a
      file this size.
    - **An explicit 0644.** ``mkstemp`` creates 0600, and an artifact exists to
      be read by *another* process, frequently under another uid. There is no
      ``mode=`` parameter on purpose: it would let 0600 be passed back in and
      re-create the bug this line exists to prevent.
    - **The staging file is unlinked if anything fails.** A failed write must not
      take out the artifact the consumer is currently reading.

    **The parent directory is not created.** A path whose parent does not exist
    is a configuration mistake, and creating the tree would hide it by writing
    the artifact somewhere nobody reads. That is this module's *absence is
    refused, not tolerated* applied to the write side.

    **Errors are ``OSError`` and are left to propagate.** :class:`ArtifactError`
    is not reused: its docstring says *a project artifact could not be read*, and
    :mod:`~.dex` maps it to a configuration refusal on the read path, so a write
    failure arriving as one would be indistinguishable there. No new exception
    type is introduced either - a bespoke error invites a caller to catch and
    continue, and continuing is the failure this module refuses everywhere else.
    """

    destination = Path(path)
    text = dumps(
        name=name,
        models=models,
        generated_at=generated_at,
        declaration_sources=declaration_sources,
        semantic_sources=semantic_sources,
        source_declarations=source_declarations,
    )

    handle, staging = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=str(destination.parent)
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(staging, 0o644)
        os.replace(staging, destination)
    except BaseException:
        # BaseException, not Exception: a KeyboardInterrupt between the create
        # and the replace would otherwise leave the staging file behind, and the
        # cleanup is what keeps a failed write from accumulating litter in a
        # directory the consumer reads.
        try:
            os.unlink(staging)
        except OSError:
            pass
        raise


def _text_mapping(document: Mapping[str, object], key: str) -> dict[str, str]:
    """One of the three declaration mappings, checked to be ``{str: str}``.

    Checked rather than trusted because the failure it prevents is quiet: a
    mapping whose values are not text reaches a YAML parser that reports the
    file as malformed, so the artifact's defect is reported as a defect in the
    declarations - sending a reader to the wrong file.
    """

    raw = document.get(key, {})
    if not isinstance(raw, dict):
        raise ArtifactError(f"{key!r} must be an object mapping names to YAML text")
    for stem, text in raw.items():
        if not isinstance(stem, str) or not isinstance(text, str):
            raise ArtifactError(
                f"{key}[{stem!r}] must be YAML text; got {type(text).__name__}"
            )
    return dict(raw)


def loads(text: str) -> ProjectArtifact:
    """Read an artifact, refusing anything it cannot vouch for.

    **Every failure here is a refusal, and that is the deliberate half.** The
    tempting alternative - an unreadable artifact yielding an empty project - is
    the one outcome that must not ship: a project with no declarations is
    *valid*, so it is indistinguishable from a project that genuinely declares
    nothing, and a consumer would report "no declared joins" rather than "the
    project could not be read". That failure is silent, permanent, and reads
    exactly like a clean result. A refusal is loud once.

    The caller is expected to refuse a **missing** file on the same reasoning.
    ``loads`` sees text only, deliberately, so it cannot make that decision
    itself - and there is no ``load(path)`` beside :func:`dump` for exactly that
    reason. **The asymmetry is the design, not an omission.** Atomicity is not
    expressible in text, so writing needs the path; what absence *means* is a
    policy the caller owns, and only the caller knows it. :func:`~.dex.
    project_from_context` refuses a missing artifact because a stale drift
    report is worse than a loud failure; a different host may reasonably differ.
    """

    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ArtifactError(f"not valid JSON: {exc}") from exc

    if not isinstance(document, dict):
        raise ArtifactError(
            f"expected a JSON object at the top level, got {type(document).__name__}"
        )

    version = document.get("schema_version")
    if version != SCHEMA_VERSION:
        raise ArtifactError(
            f"schema_version {version!r} cannot be read by this version, which "
            f"writes and requires {SCHEMA_VERSION}. The writer and reader ship "
            f"in the same distribution, so this means one side is a different "
            f"build than the other"
        )

    name = document.get("name")
    if not isinstance(name, str) or not name:
        raise ArtifactError("'name' is required and must be a non-empty string")

    generated_at = document.get("generated_at")
    if not isinstance(generated_at, str) or not generated_at:
        raise ArtifactError("'generated_at' is required and must be a non-empty string")

    raw_models = document.get("models")
    if not isinstance(raw_models, list):
        raise ArtifactError("'models' is required and must be a list")

    models = []
    for index, entry in enumerate(raw_models):
        if not isinstance(entry, dict):
            raise ArtifactError(f"models[{index}] must be an object")
        depends_on = entry.get("depends_on", [])
        if not isinstance(depends_on, list) or not all(
            isinstance(d, str) for d in depends_on
        ):
            raise ArtifactError(f"models[{index}].depends_on must be a list of strings")
        try:
            # ProjectModel's own __post_init__ is the name check, so a nameless
            # model is refused by the model rather than re-checked here.
            models.append(
                ProjectModel(
                    name=entry.get("name", ""),
                    depends_on=tuple(depends_on),
                    relation=entry.get("relation"),
                    layer=entry.get("layer"),
                )
            )
        except ValueError as exc:
            raise ArtifactError(f"models[{index}]: {exc}") from exc

    return ProjectArtifact(
        name=name,
        models=tuple(models),
        declaration_sources=_text_mapping(document, "declared"),
        semantic_sources=_text_mapping(document, "semantic"),
        source_declarations=_text_mapping(document, "sources"),
        generated_at=generated_at,
        schema_version=SCHEMA_VERSION,
    )
