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
import os

import pytest

from dagster_dex import DagsterProject, ProjectModel

# The MODULE as well as the names, because the writer tests monkeypatch
# `artifact.os.replace` to inject a mid-swap failure. Patching the module's own
# reference is what makes the injection reach the code under test rather than a
# copy of `os` this file happens to hold.
from dagster_dex import artifact
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


# --- the writer -----------------------------------------------------------
#
# `dump` is `dumps` plus a swap. These check the swap, because the serialization
# half is already covered above and re-testing it here would only prove the
# delegation compiles.


def test_dump_writes_exactly_what_dumps_returns(tmp_path):
    """The delegation, asserted rather than assumed.

    If these two ever diverge, every other test in this file is testing a
    function the writer does not use.
    """

    target = tmp_path / "project.json"
    kwargs = dict(
        name="demo",
        models=[ProjectModel(name="dim_date", layer="silver")],
        generated_at="2026-01-01T00:00:00Z",
        declaration_sources={"keys.yml": "models: []\n"},
    )

    artifact.dump(target, **kwargs)

    assert target.read_text(encoding="utf-8") == artifact.dumps(**kwargs)


def test_dump_and_dumps_take_the_same_arguments():
    """Two hand-maintained signatures with nothing tying them together.

    Same shape as the version-string pair in `test_packaging.py`: a parameter
    added to one and not the other is a silent divergence, and the failure would
    surface as a caller's TypeError rather than here.
    """

    import inspect

    writing = list(inspect.signature(artifact.dump).parameters)
    serializing = list(inspect.signature(artifact.dumps).parameters)

    assert writing[0] == "path", writing
    assert writing[1:] == serializing, (writing, serializing)


def test_dump_replaces_an_existing_artifact_rather_than_appending(tmp_path):
    target = tmp_path / "project.json"
    common = dict(generated_at="2026-01-01T00:00:00Z")

    artifact.dump(target, name="first", models=[ProjectModel(name="a")], **common)
    artifact.dump(target, name="second", models=[ProjectModel(name="b")], **common)

    reread = artifact.loads(target.read_text(encoding="utf-8"))
    assert reread.name == "second"
    assert [m.name for m in reread.models] == ["b"]


def test_dump_leaves_no_staging_file_behind(tmp_path):
    """The directory a consumer reads must not accumulate litter.

    The staging file lives in the DESTINATION directory - `os.replace` is only
    atomic within a filesystem - so anything left behind lands where the reader
    is looking.
    """

    target = tmp_path / "project.json"
    artifact.dump(
        target,
        name="demo",
        models=[ProjectModel(name="dim_date")],
        generated_at="2026-01-01T00:00:00Z",
    )

    assert [p.name for p in tmp_path.iterdir()] == ["project.json"]


def test_dump_is_readable_by_another_process(tmp_path):
    """0644, not mkstemp's 0600.

    An artifact exists to be read by a DIFFERENT process, often under another
    uid. `mkstemp` creates 0600, so without the explicit chmod the transport is
    silently unusable in exactly its intended deployment.

    Skipped on Windows, where the POSIX mode bits are not meaningful - and
    skipped with a reason rather than asserted loosely, because a weaker
    assertion that passes everywhere would stop testing the thing on the
    platform that has it.
    """

    if os.name == "nt":
        pytest.skip("POSIX mode bits are not meaningful on Windows")

    target = tmp_path / "project.json"
    artifact.dump(
        target,
        name="demo",
        models=[ProjectModel(name="dim_date")],
        generated_at="2026-01-01T00:00:00Z",
    )

    assert target.stat().st_mode & 0o777 == 0o644


def test_dump_refuses_a_missing_parent_rather_than_creating_it(tmp_path):
    """A path whose parent does not exist is a configuration mistake.

    Creating the tree would hide it by writing the artifact somewhere nobody
    reads - the module's "absence is refused, not tolerated" applied to the
    write side. `OSError` propagates; it is not wrapped in `ArtifactError`,
    which means "could not be READ" and is mapped to a configuration refusal on
    the read path.
    """

    target = tmp_path / "no_such_dir" / "project.json"

    with pytest.raises(OSError) as refusal:
        artifact.dump(
            target,
            name="demo",
            models=[ProjectModel(name="dim_date")],
            generated_at="2026-01-01T00:00:00Z",
        )

    assert not isinstance(refusal.value, artifact.ArtifactError)


def test_a_failed_write_leaves_the_previous_artifact_intact(tmp_path, monkeypatch):
    """The arm that matters most, and the one a happy-path test cannot reach.

    A regeneration that fails must not take out the project the consumer is
    currently reading. Injecting the failure at `os.replace` is deliberate: it
    is the last step, so everything before it has already happened and the
    staging file exists at the moment of failure.
    """

    target = tmp_path / "project.json"
    good = dict(
        name="good", models=[ProjectModel(name="a")], generated_at="2026-01-01T00:00:00Z"
    )
    artifact.dump(target, **good)
    before = target.read_text(encoding="utf-8")

    def boom(*_args, **_kwargs):
        raise OSError("disk went away mid-swap")

    monkeypatch.setattr(artifact.os, "replace", boom)

    with pytest.raises(OSError):
        artifact.dump(
            target, name="bad", models=[ProjectModel(name="b")], generated_at="2026-01-01T00:00:00Z"
        )

    assert target.read_text(encoding="utf-8") == before, "the previous artifact was damaged"
    assert [p.name for p in tmp_path.iterdir()] == ["project.json"], "staging file left behind"
