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
from .project import DagsterProject
from .protocol import EditableProject, FingerprintedProject, ProjectSource, tier_of

__version__ = "0.1.0"

__all__ = [
    "DagsterProject",
    "DeclaredJoin",
    "DeclaredKey",
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
    "SemanticField",
    "SemanticModel",
    "__version__",
    "tier_of",
]
