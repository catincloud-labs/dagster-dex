# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""The project seam, tiered - a proposal, expressed as something that runs.

A project format is read through channels with different consumers and
different requirements. A single-method seam cannot carry that whichever method
it names: pin it to the read view and the declared keys never arrive; pin it to
the declarations and the per-layer fingerprint has nowhere to come from.

So the seam is tiered, the way a storage protocol is tiered:

    ProjectSource        declarations()                    - what the project declares
    FingerprintedProject   + fingerprint()                 - what it looks like right now
    EditableProject        + propose_edits()               - what may be written back

Each tier is a superset of the one above. A format implements the tiers it can
serve and simply does not implement the rest.

**Why tiers rather than capability flags.** A flag is a claim the engine has to
interpret, trust, and branch on, and nothing stops a format from setting it
wrong. A tier is checkable: ``isinstance(project, EditableProject)`` is either
true or it is not, and a format that cannot receive edits cannot accidentally
claim it can. The declaration and the enforcement become the same object.

That matters most for the write path. A generated project is safe from having
edits written into it today only where some naming convention happens not to
match - safe by coincidence rather than by contract. Declining a tier makes it
structural.

**Non-goal: this does not describe how a project is constructed.** Locating and
building one is a separate contract, and deliberately so: the formats disagree
about what they are keyed by (a directory, a graph in memory, a service), and
that disagreement is not resolvable by picking whichever the first format used.
See ``ProjectContext`` in ``dex.py`` for the shape that question takes.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .model import ProjectDeclarations

__all__ = [
    "EditableProject",
    "FingerprintedProject",
    "ProjectFingerprint",
    "ProjectSource",
    "tier_of",
]


@runtime_checkable
class ProjectSource(Protocol):
    """Tier 1: a project that can state what it declares.

    ``format`` is a stable identifier for the project format, not for the
    instance - ``"dagster"``, ``"dbt"``. It is what a registry would resolve.
    """

    format: str

    def declarations(self) -> ProjectDeclarations:
        """What the project declares: models, keys, joins, semantics.

        **This must not raise.** A project that is absent, ambiguous, or
        unreadable returns empty declarations carrying a note that says why.
        Exploration runs against warehouses with no project at all, so absence
        is an ordinary state rather than an error, and a format that raises
        here turns a normal condition into an outage.

        This is the tier's real contract, and it is behavioural rather than
        structural - which is why a conformance suite that only checks shapes
        will not catch a format that gets it wrong.
        """
        ...


class ProjectFingerprint(Protocol):
    """The per-layer content fingerprint of a project at one moment.

    Deliberately minimal and format-neutral: a mapping from a layer name to a
    stable hash, plus the model names that layer covers. What counts as a layer
    is the format's business.
    """

    layers: dict[str, str]
    models: tuple[str, ...]


@runtime_checkable
class FingerprintedProject(ProjectSource, Protocol):
    """Tier 2: adds the snapshot channel.

    A fingerprint is what makes drift detectable: compare a vouched-for one
    against the current one and the difference is the change. A format reaching
    only tier 1 still contributes declared keys and joins; it simply cannot be
    a drift baseline.
    """

    def fingerprint(self) -> ProjectFingerprint:
        """The project's current content fingerprint. Must not raise."""
        ...


@runtime_checkable
class EditableProject(FingerprintedProject, Protocol):
    """Tier 3: the write path.

    Implemented only by formats whose source of truth can actually receive an
    edit. The clearest case that cannot is a project reduced from a running
    graph: its source of truth is the code that produced the graph, and writing
    to the reduction would edit an artifact regenerated from something else.

    The test is about the artifact an edit lands in, not about where the project
    came from. A format that reduces a graph for its models and reads its
    declarations from hand-authored files holds both kinds at once, and can
    honestly serve this tier for the second while refusing it for the first.

    Declining this tier is the honest answer for such a format, and the reason
    the tiers exist rather than a ``writeback`` flag.
    """

    def propose_edits(self, edits: object) -> object:
        """Propose edits as reviewable diffs. Never writes without review."""
        ...


def tier_of(project: object) -> int:
    """The highest tier ``project`` satisfies, or 0 for none.

    Checked structurally rather than declared, so a format cannot claim a tier
    it does not implement. Note the deliberate ordering: tiers are nested, so
    the test runs from the most specific down.
    """

    if isinstance(project, EditableProject):
        return 3
    if isinstance(project, FingerprintedProject):
        return 2
    if isinstance(project, ProjectSource):
        return 1
    return 0
