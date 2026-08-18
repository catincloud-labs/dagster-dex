# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""A non-dbt project format, and the seam it would like to plug into.

Importing this package pulls in neither an orchestrator nor a query engine.
The model, the protocol, the artifact transport and the conformance suite are
dependency-free, and dex-core is needed only by :mod:`dagster_dex.dex`,
which imports it lazily at the point of use.

``DagsterProject.from_asset_graph`` does not import the orchestrator either: it
reads the asset definitions it is handed structurally, so a caller that already
has a graph can reduce one without this package depending on how it was built.

The same holds for the write tier. :class:`EditableDagsterProject` and the
:class:`ProposedEdit` / :class:`EditOutcome` vocabulary are stdlib-only: a host
can build, review and apply an edit set without dex-core installed, and the
engine is needed only to translate one onto dex's own seam in
:mod:`dagster_dex.dex`.
"""

from .artifact import ProjectArtifact
from .model import (
    DeclaredJoin,
    DeclaredKey,
    ExternalSource,
    Fingerprint,
    Freshness,
    Metric,
    ProjectDeclarations,
    ProjectModel,
    SemanticField,
    SemanticModel,
)
from .project import DagsterProject, EditableDagsterProject
from .protocol import (
    EditableProject,
    EditOutcome,
    FingerprintedProject,
    ProjectSource,
    ProposedEdit,
    tier_of,
)

__version__ = "0.2.0"

# What the write tier needs is here beside what the read tiers need. `tier_of`
# and `EditableProject` were already exported, so a consumer could ask whether a
# project reaches tier 3 from the top level and then had to reach into
# `dagster_dex.protocol` for the vocabulary to call it with. That asymmetry is
# the kind that reads as an oversight rather than a decision.
#
# `EditConflict`, `ProjectFile` and `ProjectFileView` are deliberately NOT here.
# They are values a caller receives and reads, never ones it constructs: the
# conflicts arrive inside an `EditOutcome` and the files inside a view. Exporting
# a type nobody needs to name is a promise with no consumer, and the seam is
# explicitly alpha.
__all__ = [
    "DagsterProject",
    "DeclaredJoin",
    "DeclaredKey",
    "EditOutcome",
    "EditableDagsterProject",
    "EditableProject",
    "ExternalSource",
    "Fingerprint",
    "FingerprintedProject",
    "Freshness",
    "Metric",
    "ProjectArtifact",
    "ProjectDeclarations",
    "ProjectModel",
    "ProjectSource",
    "ProposedEdit",
    "SemanticField",
    "SemanticModel",
    "__version__",
    "tier_of",
]
