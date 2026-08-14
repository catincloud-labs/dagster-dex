# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""The serialized project: what survives the trip, and what is refused.

**This file must stay engine-free.** It is collected by the first CI step,
which installs no dex-core, and that step is a control rather than a speed split
(see `AGENTS.md`). An `exmergo_dex_core` import here turns it red at collection,
which is the point.

The equivalence assertion is the one that matters: a project rebuilt from an
artifact must answer exactly what the project it was written from answered. A
round trip that only checks its own fields would pass while the reduction drifted
underneath it.
"""

from __future__ import annotations

import json

import pytest

from dagster_dex import DagsterProject, ProjectModel
from dagster_dex.artifact import (
    SCHEMA_VERSION,
    ArtifactError,
    dumps,
    loads,
)
from dagster_dex.conformance import (
    a_join_declaration,
    a_semantic_definition,
    a_single_key_declaration,
    a_source_declaration,
)

MODELS = (
    ProjectModel(name="dim_date", layer="silver"),
    ProjectModel(name="fact_orders", depends_on=("dim_date",), layer="gold"),
    ProjectModel(name="mart_revenue", depends_on=("fact_orders",), layer="platinum"),
)

GENERATED_AT = "2026-08-12T07:00:00Z"


def _sources():
    """The three declaration mappings, deliberately all non-empty.

    A fixture whose declaration halves are empty would round-trip perfectly while
    proving nothing about the channel that carries real content.
    """

    return {
        "declaration_sources": {
            "dim_date": a_single_key_declaration(),
            "fact_orders": a_join_declaration(),
        },
        "semantic_sources": {"mart_revenue": a_semantic_definition()},
        "source_declarations": {"orders_raw": a_source_declaration()},
    }


def _project(**overrides):
    payload = {"models": MODELS, "name": "demo_project", **_sources()}
    payload.update(overrides)
    models = payload.pop("models")
    return DagsterProject(models, **payload)


def _round_trip(**overrides):
    payload = {
        "name": "demo_project",
        "models": MODELS,
        "generated_at": GENERATED_AT,
        **_sources(),
    }
    payload.update(overrides)
    return loads(dumps(**payload))


class TestTheRoundTrip:
    def test_a_project_rebuilt_from_an_artifact_answers_identically(self):
        """The assertion the whole mechanism rests on.

        Compared on `declarations()` rather than on the artifact's own fields,
        because that is what dex reads. Two artifacts agreeing tells you the
        transport is consistent with itself; this tells you the transport did not
        change the project.
        """

        direct = _project()
        parsed = _round_trip()
        rebuilt = DagsterProject(
            parsed.models,
            name=parsed.name,
            declaration_sources=parsed.declaration_sources,
            semantic_sources=parsed.semantic_sources,
            source_declarations=parsed.source_declarations,
        )

        assert rebuilt.declarations() == direct.declarations()

    def test_the_fingerprint_survives_too(self):
        """Tier 2 is hashed over the models and their dependencies, so a
        depends_on or layer lost in transport would change it silently -- and a
        changed fingerprint IS the drift signal."""

        parsed = _round_trip()
        rebuilt = DagsterProject(parsed.models, name=parsed.name, **_sources())
        assert rebuilt.fingerprint() == _project().fingerprint()

    def test_the_declarations_are_not_empty(self):
        """The guard that keeps the two assertions above from passing vacuously:
        two empty projects compare equal."""

        declarations = _project().declarations()
        assert declarations.declared_keys
        assert declarations.declared_joins
        assert declarations.semantic_models
        assert declarations.sources

    def test_declaration_text_is_carried_byte_identically(self):
        """Text, never parsed structures.

        `SemanticModel.definition_sha` is computed over a re-dump of the parsed
        entry, so a round trip through another type system has to preserve YAML's
        exactly -- and it does not. A bare `2026-01-01` parses to a date, becomes
        a string in JSON, and returns as a QUOTED scalar: a different digest for
        a file nobody edited, reported as a definition change.
        """

        original = _sources()["declaration_sources"]["dim_date"]
        assert _round_trip().declaration_sources["dim_date"] == original

    def test_a_date_shaped_scalar_survives(self):
        """The specific hazard above, exercised rather than only described."""

        text = "version: 2\nmodels:\n  - name: dim_date\n    started: 2026-01-01\n"
        parsed = _round_trip(declaration_sources={"dim_date": text})
        assert parsed.declaration_sources["dim_date"] == text

    def test_it_is_byte_stable_across_runs(self):
        """Two runs over unchanged inputs must produce identical bytes, or a
        no-op regeneration reads as a change to anyone diffing the volume."""

        assert dumps(
            name="demo_project", models=MODELS, generated_at=GENERATED_AT, **_sources()
        ) == dumps(
            name="demo_project",
            models=tuple(reversed(MODELS)),
            generated_at=GENERATED_AT,
            **_sources(),
        )

    def test_provenance_survives(self):
        parsed = _round_trip()
        assert parsed.generated_at == GENERATED_AT
        assert parsed.name == "demo_project"
        assert parsed.schema_version == SCHEMA_VERSION


class TestWhatIsRefused:
    """Every arm here is a refusal, and that is deliberate.

    The tolerant alternative -- an unreadable artifact becoming an empty project
    -- is indistinguishable from a warehouse that genuinely declares nothing, so
    it would be reported as a clean result forever.
    """

    def test_a_future_schema_version_is_refused(self):
        document = json.loads(dumps(name="c", models=MODELS, generated_at=GENERATED_AT))
        document["schema_version"] = SCHEMA_VERSION + 1
        with pytest.raises(ArtifactError, match="schema_version"):
            loads(json.dumps(document))

    def test_an_older_schema_version_is_refused_too(self):
        """The check is equality, not a floor. A reader that accepted anything
        older would read a field whose meaning had changed with the old meaning
        and report the result as fact."""

        document = json.loads(dumps(name="c", models=MODELS, generated_at=GENERATED_AT))
        document["schema_version"] = SCHEMA_VERSION - 1
        with pytest.raises(ArtifactError, match="schema_version"):
            loads(json.dumps(document))

    def test_malformed_json_is_refused(self):
        with pytest.raises(ArtifactError, match="not valid JSON"):
            loads("{ not json")

    def test_a_non_object_document_is_refused(self):
        with pytest.raises(ArtifactError, match="top level"):
            loads("[]")

    @pytest.mark.parametrize("field", ["name", "generated_at", "models"])
    def test_a_missing_required_field_is_refused_by_name(self, field):
        document = json.loads(dumps(name="c", models=MODELS, generated_at=GENERATED_AT))
        del document[field]
        with pytest.raises(ArtifactError, match=field):
            loads(json.dumps(document))

    def test_a_nameless_model_is_refused(self):
        """Refused by ProjectModel's own __post_init__ rather than re-checked
        here, so the model stays the single authority on what a model needs."""

        document = json.loads(dumps(name="c", models=MODELS, generated_at=GENERATED_AT))
        document["models"][0]["name"] = ""
        with pytest.raises(ArtifactError, match="models\\[0\\]"):
            loads(json.dumps(document))

    def test_declarations_that_are_not_text_are_refused(self):
        """Checked rather than trusted because the failure is misdirecting: a
        non-text value reaches a YAML parser, which reports the DECLARATION as
        malformed and sends a reader to the wrong file."""

        document = json.loads(dumps(name="c", models=MODELS, generated_at=GENERATED_AT))
        document["declared"] = {"dim_date": {"parsed": "structure"}}
        with pytest.raises(ArtifactError, match="dim_date"):
            loads(json.dumps(document))
