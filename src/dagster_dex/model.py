# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""What a project declares, in a vocabulary that is not dbt's.

This is the neutral model. It exists because the alternative - reusing the
model a dbt-shaped engine already has - quietly imports dbt's accidents along
with its substance, and a second project format then has to answer questions
that only make sense for the first one.

Four decisions here are deliberate departures, each one earned:

**A key is always a tuple of columns.** Not a column with a composite variant
bolted on beside it. A single-column grain is the ``n == 1`` case, never a
different kind of thing. Modelling it the other way around is what makes a
composite grain inexpressible until someone widens the type, and widening it
later means every reader has two shapes to handle forever.

**There is no project directory.** A project is identified by its format and
its name. A path is one format's way of locating itself, not a property every
project has, and putting it in the shared model makes every path-free format
carry a field it can only ever leave empty - or worse, populate with something
misleading to keep a consumer happy.

**Freshness is a tri-state, not a boolean.** See :class:`Freshness`. This is the
one that cost the most to learn: a boolean cannot distinguish "current" from
"there is no such thing here", so a format with no compiled artifact reports
itself indistinguishable from one that just compiled.

**A required field is a refusal to invent.** :class:`ExternalSource` requires a
source system, because the consumer requires one; making it optional here would
only move the invention into the boundary code, where a fabricated value is
indistinguishable from a declared one. Where the consumer requires something a
project genuinely may not have - a file path - the field is optional here and
the loss is reported rather than filled in.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum

__all__ = [
    "DeclaredJoin",
    "DeclaredKey",
    "ExternalSource",
    "Fingerprint",
    "Freshness",
    "Metric",
    "ProjectDeclarations",
    "ProjectModel",
    "SemanticField",
    "SemanticModel",
    "definition_hash",
]


def definition_hash(text: str) -> str:
    """The content hash used throughout. Ours, so nothing here depends on a
    particular engine's hashing choice remaining what it is today."""

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Freshness(str, Enum):
    """Whether a derived artifact still describes the project it came from.

    ``NOT_APPLICABLE`` is the member that justifies this being an enum rather
    than a ``bool``. A format that compiles to an intermediate artifact can be
    ``FRESH`` or ``STALE``; a format that reduces its source graph directly has
    no such artifact and is neither. Collapsing that third case into ``False``
    makes "nothing to be stale about" report identically to "checked, and it is
    current" - which reads as an assurance nobody actually made.

    The same shape, in the other direction, is what makes a cache served past
    its window look like a healthy one.
    """

    FRESH = "fresh"
    STALE = "stale"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class ProjectModel:
    """One node the project builds, and what it reads to build it.

    ``relation`` is the physical table when the project knows it, and ``None``
    when it does not. Absence is honest here: a format that never resolves
    physical names should say so rather than guessing one from the model name,
    because a guessed relation is indistinguishable from a declared one at the
    point it is consumed.
    """

    name: str
    depends_on: tuple[str, ...] = ()
    relation: str | None = None
    layer: str | None = None

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("a model needs a name")


@dataclass(frozen=True)
class ExternalSource:
    """A warehouse object the project reads but does not build.

    The project's outer edge. Everything in ``models`` is something the project
    produces; this is the boundary where it stops and depends on something
    somebody else keeps honoring.

    **Why this cannot be derived from the graph.** An orchestrated graph knows
    its own nodes and the edges between them. A node that reads a warehouse
    table directly - in SQL inside its body, because the source system has no
    other interface - has no edge to draw, so the read is invisible to any
    amount of graph traversal. It is genuinely extra information, and it has to
    be declared. A format that inferred sources from dependencies would report
    none of them and look like it had checked.

    ``system`` is the source system this table belongs to, and it is
    **required**. That is a deliberate refusal: the consumer requires it too, so
    making it optional here would only move the moment of invention one layer
    down, into the boundary code, where it would be a fabricated value nobody
    could tell from a declared one. If a format does not know its source
    systems, the honest outcome is that it declares no sources.

    ``read_by`` names the models that read this table. It lives here rather than
    in a separate mapping so that two models declaring the same table converge
    on one source with two readers, instead of two sources that a downstream
    consumer would count - and report - twice.

    ``declared_in`` is optional provenance: where the declaration was written,
    when that is a place. It is optional precisely because a project need not
    have files, and requiring it would be the same mistake the paragraph above
    declines to make.
    """

    system: str
    table: str
    schema_name: str | None = None
    columns: tuple[str, ...] = ()
    read_by: tuple[str, ...] = ()
    declared_in: str | None = None

    def __post_init__(self) -> None:
        if not self.system:
            raise ValueError(f"external source {self.table!r} names no source system")
        if not self.table:
            raise ValueError("an external source needs a table name")

    @property
    def identifier(self) -> str:
        """``system.table`` - how a consumer names this source in a finding."""

        return f"{self.system}.{self.table}"


@dataclass(frozen=True)
class DeclaredKey:
    """The grain a model is declared to be unique at.

    ``columns`` is ordered and non-empty. Order is preserved because it is the
    author's statement of the key, and reordering it silently would make two
    declarations that a human wrote differently compare equal.
    """

    model: str
    columns: tuple[str, ...]
    source: str = "declaration"

    def __post_init__(self) -> None:
        if not self.columns:
            raise ValueError(f"declared key for {self.model!r} has no columns")

    @property
    def is_composite(self) -> bool:
        return len(self.columns) > 1


@dataclass(frozen=True)
class DeclaredJoin:
    """A declared relationship between two models.

    Both sides are column tuples for the same reason keys are: a join on a
    composite key is not a different kind of join.
    """

    from_model: str
    from_columns: tuple[str, ...]
    to_model: str
    to_columns: tuple[str, ...]
    source: str = "declaration"

    def __post_init__(self) -> None:
        if not self.from_columns or not self.to_columns:
            raise ValueError(f"join {self.from_model}->{self.to_model} is missing columns")
        if len(self.from_columns) != len(self.to_columns):
            raise ValueError(
                f"join {self.from_model}->{self.to_model} has "
                f"{len(self.from_columns)} columns on one side and "
                f"{len(self.to_columns)} on the other"
            )


@dataclass(frozen=True)
class SemanticField:
    """One dimension or measure, and the warehouse column behind it.

    ``name`` is what the semantic layer calls it; ``column`` is the physical column
    it reads, when we honestly have one. They are usually the same string and are
    not the same thing: a consumer checking whether a semantic definition still
    resolves has to check the **column** against the warehouse, and checking the
    name instead would pass on a model that no longer builds it.

    **``column`` stays ``None`` unless the declaration gives a bare column
    reference.** A semantic declaration may define a field as an expression
    (``cost_net * 1.2``, a ``CASE``), and an expression is not a column name.
    Putting one where a consumer expects a column produces a confident wrong
    answer -- a reference that "does not resolve" because it was never a
    reference -- and a fabricated high-severity finding costs more than the
    missing one it replaces. ``None`` means "we cannot say", which is the honest
    answer and the one consumers already have an affordance for.

    ``categorical`` carries the declared ``type: categorical``. It lives here
    rather than in a second mapping beside the field list, because it is a
    property of the dimension: two collections that must agree about the same set
    of names is how they stop agreeing.
    """

    name: str
    column: str | None = None
    categorical: bool = False

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("a semantic field needs a name")


@dataclass(frozen=True)
class SemanticModel:
    """A semantic model: the dimensions and measures declared over one model.

    ``dimensions`` and ``measures`` became tuples of :class:`SemanticField` when
    the physical column started being carried; they were tuples of bare names. The
    break was taken deliberately rather than adding a parallel name-to-column
    mapping, which would have been two collections to keep in sync.
    """

    name: str
    model: str
    dimensions: tuple[SemanticField, ...] = ()
    measures: tuple[SemanticField, ...] = ()
    definition_sha: str = ""

    def dimension_names(self) -> tuple[str, ...]:
        """Declared dimension names, in declaration order."""

        return tuple(f.name for f in self.dimensions)

    def measure_names(self) -> tuple[str, ...]:
        """Declared measure names, in declaration order."""

        return tuple(f.name for f in self.measures)


@dataclass(frozen=True)
class Metric:
    """A metric declared over a measure."""

    name: str
    measure: str | None = None
    kind: str = "simple"
    definition_sha: str = ""


@dataclass(frozen=True)
class Fingerprint:
    """A project's content fingerprint, per layer.

    ``layers`` maps a layer name to a hash over that layer's contents. What
    counts as a layer is the format's business - a medallion tier, a directory,
    a package - because the engine comparing two fingerprints only needs them
    to be computed the same way twice, not to agree with another format.

    Per layer rather than one hash for the whole project, because a single hash
    answers "did anything change" and nothing else, and the useful question on
    a drift report is which part.
    """

    layers: dict[str, str] = field(default_factory=dict)
    models: tuple[str, ...] = ()

    def changed_layers(self, other: Fingerprint) -> tuple[str, ...]:
        """Layers whose hash differs, including ones added or removed.

        A layer present on one side and absent on the other counts as changed:
        that is a real difference, and treating a missing layer as "unchanged"
        is how a deleted one disappears from a drift report entirely.
        """

        names = set(self.layers) | set(other.layers)
        return tuple(
            sorted(n for n in names if self.layers.get(n) != other.layers.get(n))
        )


@dataclass(frozen=True)
class ProjectDeclarations:
    """Everything a project declares about itself, in one value.

    ``notes`` carries analyst-readable caveats. It is the one piece of the
    dbt-shaped model worth keeping verbatim: a consumer that degrades quietly
    still owes the reader a reason, and a note is how the reason travels
    without becoming an exception.
    """

    format: str
    name: str
    models: tuple[ProjectModel, ...] = ()
    sources: tuple[ExternalSource, ...] = ()
    declared_keys: tuple[DeclaredKey, ...] = ()
    declared_joins: tuple[DeclaredJoin, ...] = ()
    semantic_models: tuple[SemanticModel, ...] = ()
    metrics: tuple[Metric, ...] = ()
    freshness: Freshness = Freshness.NOT_APPLICABLE
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_empty(self) -> bool:
        """No declarations of any kind. The state every consumer must tolerate.

        Sources count. A project that builds nothing but names the warehouse
        objects it reads has still said something, and calling that empty would
        discard the only statement it made.
        """

        return not (
            self.models
            or self.sources
            or self.declared_keys
            or self.declared_joins
            or self.semantic_models
            or self.metrics
        )

    def model_names(self) -> tuple[str, ...]:
        return tuple(m.name for m in self.models)
