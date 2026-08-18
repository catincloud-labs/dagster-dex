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

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from .model import ProjectDeclarations

__all__ = [
    "EditConflict",
    "EditOutcome",
    "EditableProject",
    "FingerprintedProject",
    "ProjectFile",
    "ProjectFileView",
    "ProjectFingerprint",
    "ProjectSource",
    "ProposedEdit",
    "tier_of",
]


@dataclass(frozen=True)
class ProposedEdit:
    """One proposed change, pinned to the content it was planned against.

    ``key`` addresses a file in the project's **own keyspace**, not the
    filesystem's. What that space looks like is the format's business; what
    matters is that the same key means the same thing to
    :meth:`EditableProject.propose_edits` as it did to whatever produced the edit.

    ``pinned_hash`` is the hash of the target *at the moment the edit was
    proposed*, and ``None`` means the target did not exist then - a create.
    Re-checking it at write time is the whole point of this field: the window
    between proposing an edit and applying it is a human review and can be long,
    and someone editing the target during it must not have their work replaced by
    a proposal written before it existed.

    ``new_content`` of ``None`` is a delete. It still carries ``pinned_hash``,
    so removing a file a human edited after the proposal is a conflict rather
    than a silent deletion.
    """

    key: str
    new_content: str | None = None
    pinned_hash: str | None = None


@dataclass(frozen=True)
class EditConflict:
    """A target that moved between the proposal and the write.

    Both hashes are carried because the pair is the diagnosis. ``found`` of
    ``None`` is a target that has since been deleted; ``expected`` of ``None`` is
    a create whose file now exists, which is the same class of surprise from the
    other side.
    """

    key: str
    expected: str | None = None
    found: str | None = None


@dataclass(frozen=True)
class EditOutcome:
    """What a write did, in the two facts a caller has to be able to separate.

    A caller applying a proposal reads ``written`` to decide whether it is now
    applied and ``conflicts`` to decide whether to show a human what diverged.
    Both readings fail closed on a result answering neither, and they fail in
    opposite directions: a proposal recorded as applied that wrote nothing, or a
    conflict that never reaches the person it was raised for. So this type has
    exactly those two fields and no success flag - a flag would be a third
    statement able to disagree with the two that are load-bearing.
    """

    written: tuple[str, ...] = ()
    conflicts: tuple[EditConflict, ...] = ()


@dataclass(frozen=True)
class ProjectFile:
    """One file in a project's editable keyspace, and its content hash.

    The hash travels with the content deliberately. A consumer that read the
    content and hashed it itself would be free to hash it differently from the
    format that will later check the pin, and the two disagreeing is a conflict
    on every apply rather than an error anybody can see.
    """

    key: str
    content: str
    sha256: str


@dataclass(frozen=True)
class ProjectFileView:
    """The editable files of a project at one moment, keyed as the format keys them.

    ``root`` is what the keys are relative to, for a format that has such a
    place. It is what lets a caller store a proposal now and resolve it later
    from somewhere else; a format with no filesystem behind it leaves it
    ``None``, and such a format should be declining the write tier anyway.

    **The pin and the surface come from one view.** A caller that hashes an edit
    against one reading of the project while checking the path against another
    can hash an existing file as absent, which renders a one-line change as a
    whole-file create and turns the next write into a conflict on a file nobody
    touched. That is not hypothetical: it is the defect dex-core found when it
    widened its own containment check to ask the format.
    """

    files: dict[str, ProjectFile] = field(default_factory=dict)
    root: str | None = None


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

    def propose_edits(
        self, edits: Sequence[ProposedEdit], *, confirmed: bool = False
    ) -> EditOutcome:
        """Write proposed edits into the project, hash-checked and all-or-nothing.

        **This signature used to be ``propose_edits(edits: object) -> object``,
        and the vagueness was downstream of a claim that has since been
        retracted.** It read as deliberate - no format could implement the tier,
        so nothing had to be nameable - but the reason given for that was that a
        project reduced from a running graph has no source of truth to receive an
        edit, and this package withdrew exactly that on 2026-08-09. A seam no
        implementer can write against is not a seam; it is a declined tier
        spelled as a method.

        **Every target is re-checked against ``pinned_hash`` before anything is
        written.** A target that moved is a conflict, and with ``confirmed``
        false a single conflict refuses the *whole* set and writes nothing. That
        is propose-don't-impose at the only layer able to enforce it: the review
        window is where a human edits the file the proposal was built from.

        **All-or-nothing matters as much as the check.** Writing the
        non-conflicting half leaves the project in a state neither the proposal
        nor the human intended, and no record of which half landed.

        ``confirmed=True`` overrides the conflicts, because somebody looked and
        said so. Without it the refusal above is satisfied by an implementation
        that never writes at all, which is why a conformance suite has to assert
        both arms.
        """
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
