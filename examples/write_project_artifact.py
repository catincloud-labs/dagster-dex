# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""The README's scheduled-artifact sketch, executed.

Run it:

    uv run --no-project --with-editable . --with 'dagster>=1.13' \\
        python examples/write_project_artifact.py

The README's "Writing one, from the side that has the graph" section shows a
Dagster op, a job and a schedule around `dagster_dex.artifact.dump`. That
sketch is user code with placeholders - your project, your path, your cron -
and for a while it was prose nothing ran, a cost the README stated outright.
This file is the sketch's mechanics made concrete and executed by CI: the same
op body against a real (small) graph, the job run in process, the artifact
read back the way the serving side reads it, and the schedule object built.

What stays the reader's on purpose is the schedule VALUES. Scheduling is a
decision, and a library that made it for you would be wrong in every
deployment that differs. Everything up to that decision is proved here:

- the op body works against real Dagster objects, path supplied as op config
  the way a deployment would supply it;
- `dump` writes an artifact `loads` accepts, and the round trip preserves the
  project: a `DagsterProject` rebuilt from the artifact's own fields
  fingerprints identically to the one reduced from the live graph;
- declaration text crosses byte-identically - it is TEXT in the artifact, so
  no type system re-quotes a scalar behind the author's back;
- the schedule object constructs, so a cron typo fails here rather than at
  deploy;
- and the stated refusal holds: a path whose parent does not exist is an
  error, not a silently created tree nobody reads.

Same constraints as `reduce_asset_graph.py`, for the same reasons: no pytest
(the CI step that installs Dagster installs no test runner - plain asserts
and a nonzero exit), and not shipped in the sdist.
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path

import dagster as dg

from dagster_dex import DagsterProject
from dagster_dex.artifact import dump, loads

#: Hand-written declaration text, exactly as a repository would hold it. Kept
#: as one file of TEXT because that is what the artifact carries - see the
#: byte-identity assertion below for why that is load-bearing rather than lazy.
DECLARATIONS = {
    "dim_date.yml": """\
models:
  - name: dim_date
    columns:
      - name: date_key
        tests:
          - unique
          - not_null
""",
}


@dg.asset(metadata={"layer": "silver"})
def dim_date() -> None:
    """The one asset this demonstration needs."""


all_assets = [dim_date]


@dg.op(config_schema={"path": str})
def write_project_artifact(context) -> int:
    """The README sketch's op body, with the path as op config.

    The README defers the asset import into the op body to avoid a module
    cycle with a real project's `definitions.py`; here graph and op share a
    file, so there is no cycle to avoid and the module attribute is read
    directly. The path arrives as config because that is what it is in a
    deployment - a property of where this runs, not of the code.
    """

    project = DagsterProject.from_asset_graph(all_assets, name="demo_project")
    declarations = project.declarations()
    dump(
        context.op_config["path"],
        name="demo_project",
        models=declarations.models,
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        declaration_sources=DECLARATIONS,
    )
    context.log.info("wrote %s models", len(declarations.models))
    return len(declarations.models)


@dg.job
def write_project_artifact_job() -> None:
    write_project_artifact()


#: The schedule from the sketch, constructed so a cron typo fails in CI. The
#: VALUES are the reader's decision; nothing here runs the scheduler.
write_project_artifact_schedule = dg.ScheduleDefinition(
    job=write_project_artifact_job,
    cron_schedule="0 6 * * *",
    execution_timezone="UTC",
    default_status=dg.DefaultScheduleStatus.RUNNING,
)


def main() -> None:
    print(f"dagster           : {dg.__version__}")

    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "project" / "demo_project.json"
        target.parent.mkdir()  # dump refuses to - asserted below

        result = write_project_artifact_job.execute_in_process(
            run_config={
                "ops": {"write_project_artifact": {"config": {"path": str(target)}}}
            }
        )
        assert result.success, "the job did not succeed"
        assert result.output_for_node("write_project_artifact") == 1
        print("job ran           : 1 model written through the op")

        # Read it back the way the serving side does: text in, refusals loud.
        artifact = loads(target.read_text(encoding="utf-8"))
        assert [m.name for m in artifact.models] == ["dim_date"]

        # The declaration text crossed byte-identically. This is the artifact
        # module's central design claim - declarations travel as TEXT so no
        # round trip through another type system can re-quote a scalar and
        # change a definition hash for a file nobody edited.
        assert artifact.declaration_sources == DECLARATIONS
        print("read back         : 1 model, declaration text byte-identical")

        # The round trip preserves the PROJECT, asserted at the strongest
        # public surface there is: a project rebuilt from the artifact's own
        # fields fingerprints identically to one reduced from the live graph.
        from_graph = DagsterProject.from_asset_graph(
            all_assets, name="demo_project", declaration_sources=DECLARATIONS
        )
        from_artifact = DagsterProject(
            artifact.models,
            name=artifact.name,
            declaration_sources=artifact.declaration_sources,
            semantic_sources=artifact.semantic_sources,
            source_declarations=artifact.source_declarations,
        )
        assert from_graph.fingerprint() == from_artifact.fingerprint(), (
            "the artifact round trip changed the project"
        )
        print("fingerprint       : graph-built == artifact-rebuilt")

        # The stated refusal: a missing parent is a configuration mistake, and
        # creating it would write the artifact somewhere nobody reads.
        try:
            dump(
                Path(tmp) / "nowhere" / "demo_project.json",
                name="demo_project",
                models=artifact.models,
                generated_at="2026-01-01T00:00:00+00:00",
            )
        except OSError as refusal:
            print(f"missing parent    : refused ({type(refusal).__name__})")
        else:
            raise AssertionError("a missing parent directory was not refused")

    print()
    print("OK - the scheduled-artifact sketch's mechanics all execute; the")
    print("     schedule values remain the deployment's own decision.")


if __name__ == "__main__":
    main()
