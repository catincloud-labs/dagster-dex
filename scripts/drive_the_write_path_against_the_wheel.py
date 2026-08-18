# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""Drive dex's WRITE path against the built wheel, the way reconcile reaches it.

The suite beside this one judges the write tier against dex-core's two shipped
conformance contracts, and both pass. That is not evidence that a proposal ever
reaches this format. It was measured, and the measurement is the reason this
file exists: of five defects introduced one at a time into the write path, those
contracts caught two. They are honest about being behavioural rather than
exhaustive; a format treating them as proof is the one making the mistake.

This package's own recorded lesson is the same shape one level down. Its entry
point was declared from 0.1.0 and inert until dex-core 1.6.0 began resolving the
group, at which point it failed on first contact - so there was no moment before
that at which it could have failed. "The contracts pass" is a claim of exactly
that kind about the write path.

WHAT THIS RUNS, AND WHY EACH LEG IS HERE

  1. `resolve_project_factory("dagster")` and `construct_project`, against a
     `declarations:` directory rather than an `artifact:`, which is the shape
     that reaches tier 3. Through dex-core's own entry-point scan, not an
     import of ours.
  2. `maintain.reconcile.build` with a `key_lost_uniqueness` finding, this
     format's view and this format's placement. It has to come back with a
     PLAN EDIT rather than an advisory: an advisory is what a format that
     declines the tier gets, and the two are told apart only here.
  3. `transform.plans.plan(..., project_format=...)`, which pins the edit
     against this format's view and checks its path against the surface this
     format declares. That gate refused a second format outright until
     dex-core 1.6.4.
  4. `transform.plans.apply(..., project_format=...)`, which routes the write
     through this format's own `write_edits` rather than dbt's.
  5. The file on disk is re-read through `definitions()`, and the key that was
     NOT declared before now is.
  6. The same path with a human in it: a second plan, the file edited behind it,
     and an apply that has to REFUSE.

Leg 5 is what makes this more than a plumbing test. A format can accept an edit,
write it, and be handed content its own parser cannot read - the edit lands, the
apply reports success, and the project means exactly what it did before. So the
before-and-after pair is asserted rather than the write alone.

Leg 6 exists because legs 1 to 5 are the happy path, and a `write_edits` that
reports every edit as written passes all five: the write really did happen, so
over-reporting costs nothing until something is refused. `transform apply` reads
`written` to decide whether to mark the plan applied, so a plan recorded as
applied while a human's edit stood is the failure that would follow. Measured, on
this file, before the leg existed.

DELIBERATELY NO WAREHOUSE, NO ORCHESTRATOR, AND NO CREDENTIAL

None of them is needed to answer the question this file asks, and requiring one
would make it unrunnable by a stranger from a clean checkout. The drift finding
is fabricated because the question is what dex does with one, not whether a
warehouse can produce one.

Run it by hand against an installed wheel:

    uv run --no-project --with "./dist/<wheel>" \\
        --with exmergo-dex-core==1.6.6 --with sqlglot==30.13.0 \\
        python scripts/drive_the_write_path_against_the_wheel.py

Exit 0 means a reconcile proposal became a stored plan, was written through this
format, and changed what the project declares. Anything else prints which leg
failed.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

FAILURES: list[str] = []

#: The declaration the write path is aimed at. The column carries NO `unique`
#: test, which is the whole point: reconcile's mechanical edit is to add one, and
#: a fixture that already had it would be skipped as "already alerting" and
#: produce no edit at all. It also means `declarations()` reports no declared key
#: before the write and one after, which is the pair leg 5 asserts.
DECLARATION = (
    "models:\n"
    "  - name: dim_date\n"
    "    columns:\n"
    "      - name: date\n"
)


def check(label: str, condition: bool, detail: str = "") -> None:
    if not condition:
        FAILURES.append(f"{label}{': ' + detail if detail else ''}")


def announce(line: str) -> bool:
    """Print a leg's result, and say whether it is safe to continue.

    Unconditional `print("leg N ok")` was the first shape of this and it was
    wrong in the way this repository keeps recording: run against the tree from
    before the write tier, the output read `leg 1 ok` and then listed three
    leg-1 failures underneath. A line that says "ok" above a FAILED block is
    worse than no line, because the eye takes the first one.
    """

    if FAILURES:
        return False
    print(line)
    return True


def main() -> int:
    from exmergo_dex_core.adapters.project import (
        EditableProject,
        PlacingProject,
        ProjectContext,
        tier_of,
    )
    from exmergo_dex_core.adapters.project_resolver import (
        construct_project,
        resolve_project_factory,
    )
    from exmergo_dex_core.maintain import reconcile
    from exmergo_dex_core.maintain.drift import DriftFinding
    from exmergo_dex_core.maintain.snapshot import Snapshot
    from exmergo_dex_core.storage.memory import MemoryStore
    from exmergo_dex_core.transform import plans

    import dagster_dex

    print(f"dagster_dex     : {dagster_dex.__version__} from {dagster_dex.__file__}")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        directory = root / "declarations"
        directory.mkdir()
        target = directory / "dim_date.yml"
        target.write_text(DECLARATION, encoding="utf-8", newline="\n")

        # -- leg 1: their scan, their factory, a directory-backed project ----
        factory = resolve_project_factory("dagster")
        context = ProjectContext(
            repo_root=str(root),
            project_dir=None,
            # Relative, which is the form a real `.dex/config.yml` carries.
            options={
                "assets": f"{__name__}:ASSETS",
                "name": "demo_project",
                "declarations": "declarations",
            },
        )
        project = construct_project("dagster", factory, context)

        check(
            "leg 1: a declarations directory reaches the write tier",
            tier_of(project) == 3,
            f"tier_of said {tier_of(project)}",
        )
        check("leg 1: it satisfies EditableProject", isinstance(project, EditableProject))
        check("leg 1: it satisfies PlacingProject", isinstance(project, PlacingProject))

        # Bail rather than press on. Every leg below calls a method the write
        # tier adds, so continuing against a tier-2 project reports an
        # AttributeError traceback instead of naming the leg that failed - and
        # this file promises the opposite. Found by running it against the tree
        # from before the write tier existed, which is the run that proves these
        # legs can fail at all.
        if not announce(
            f"leg 1 ok        : tier {tier_of(project)} project built from a directory"
        ):
            return report()

        before = project.definitions()
        check(
            "leg 1: nothing is declared yet, which is what makes leg 5 a pair",
            not before.declared_keys,
            f"declared_keys was already {before.declared_keys!r}",
        )

        # -- leg 2: a proposal that is NOT advisory -------------------------
        finding = DriftFinding(
            axis="grain",
            code="key_lost_uniqueness",
            identifier="warehouse.analytics.dim_date",
            column="date",
            detail="the declared grain no longer holds",
        )
        proposals, edits, warnings = reconcile.build(
            [finding],
            Snapshot(created_at="2026-01-01T00:00:00Z"),
            None,
            project.load(),
            placement=project,
        )

        check(
            "leg 2: reconcile produced a plan edit rather than only an advisory",
            bool(edits),
            f"no edits; warnings were {warnings!r}",
        )
        if edits:
            check(
                "leg 2: the edit landed at the key this format placed",
                edits[0].path == "declarations/dim_date.yml",
                f"placed at {edits[0].path!r}",
            )
            check(
                "leg 2: the content reconcile authored adds the unique test",
                "unique" in (edits[0].new_content or ""),
                f"content was {edits[0].new_content!r}",
            )
        if not announce(
            f"leg 2 ok        : {len(edits)} plan edit(s), "
            f"{len(proposals)} proposal(s)"
        ):
            return report()

        # -- leg 3: the plan store, through this format's surface ------------
        #
        # This is the gate that refused a second format outright until dex-core
        # 1.6.4: containment validated every edit against DBT's model paths
        # whatever produced it. It reads `editing_surface()` now.
        store = MemoryStore()
        plan, diffs, plan_warnings = plans.plan(
            "add the unique test the grain lost",
            edits,
            repo_root=root,
            store=store,
            project_format=project,
        )

        check("leg 3: the plan was stored", bool(plan.plan_id))
        check(
            "leg 3: the edit was pinned against THIS format's view, not an empty one",
            plan.edits[0].old_content_hash is not None,
            "old_content_hash was None, so an existing file was hashed as absent "
            "and the diff renders a one-line change as a whole-file create",
        )
        check("leg 3: a reviewable diff came back", bool(diffs))
        if not announce(
            f"leg 3 ok        : plan {plan.plan_id} stored, {len(diffs)} diff(s)"
        ):
            return report()

        # -- leg 4: applied through THIS format's write path -----------------
        result = plans.apply(
            plan.plan_id, repo_root=root, store=store, project_format=project
        )

        check(
            "leg 4: the apply wrote the file",
            result.written == ["declarations/dim_date.yml"],
            f"written was {result.written!r}, conflicts {result.conflicts!r}",
        )
        if not announce(f"leg 4 ok        : wrote {result.written}"):
            return report()

        # -- leg 5: it changed what the project DECLARES ---------------------
        #
        # The leg that makes this more than plumbing. An edit can land, be
        # reported as applied, and mean nothing to the format it landed in.
        rebuilt = construct_project("dagster", factory, context)
        after = rebuilt.definitions()

        check(
            "leg 5: the written test is read back as a declared key",
            bool(after.declared_keys),
            f"declared_keys was still {after.declared_keys!r} after the write",
        )
        if after.declared_keys:
            check(
                "leg 5: it is the key the finding was about",
                any(
                    k.model == "dim_date" and k.column == "date"
                    for k in after.declared_keys
                ),
                f"declared_keys was {after.declared_keys!r}",
            )
        if not announce(
            f"leg 5 ok        : declares {len(after.declared_keys)} key(s) now"
        ):
            return report()

        # -- leg 6: and a human, arriving during review ----------------------
        #
        # The refusal is the property the write tier exists for, and it is the
        # one no happy path can see.
        second, _diffs, _warnings = plans.plan(
            "a second edit, planned before a human touched the file",
            [
                type(edits[0])(
                    path="declarations/dim_date.yml",
                    kind=edits[0].kind,
                    new_content=DECLARATION,
                )
            ],
            repo_root=root,
            store=store,
            project_format=rebuilt,
        )

        by_hand = "models:\n  - name: dim_date\n    columns:\n      - name: edited_by_a_human\n"
        target.write_text(by_hand, encoding="utf-8", newline="\n")

        refused = plans.apply(
            second.plan_id, repo_root=root, store=store, project_format=rebuilt
        )

        check(
            "leg 6: the apply wrote nothing over the human's edit",
            refused.written == [],
            f"written was {refused.written!r}",
        )
        check(
            "leg 6: and said why, so the divergence reaches a person",
            bool(refused.conflicts),
            "conflicts was empty, so the refusal reads as a clean no-op",
        )
        check(
            "leg 6: the human's edit is still on disk",
            target.read_text(encoding="utf-8") == by_hand,
            "the file was overwritten",
        )
        check(
            "leg 6: the plan is not recorded as applied",
            store.load_plan(second.plan_id).applied_at is None,
            "applied_at was set on a plan that wrote nothing",
        )
        announce("leg 6 ok        : the refusal held and reported itself")

    return report()


def report() -> int:
    if FAILURES:
        print("\nFAILED:")
        for failure in FAILURES:
            print(f"  - {failure}")
        return 1
    print("\nOK - a reconcile proposal reached this format's write path end to end.")
    return 0


class _Key:
    """Dagster's `AssetKey`, as the two attributes the reduction reads."""

    def __init__(self, name: str) -> None:
        self.path = [name]

    def __hash__(self) -> int:
        return hash(tuple(self.path))

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _Key) and other.path == self.path


class _Definition:
    """An `AssetsDefinition`, as the three attributes the reduction reads.

    A fake, and it has to be: this file is about the write path, and installing
    an orchestrator to produce two nodes would make it unrunnable in the job that
    installs the engine. The reduction against real Dagster objects is asserted
    in its own step, which is where that claim belongs.
    """

    def __init__(self, keys: list[_Key]) -> None:
        self.keys = keys
        self.asset_deps = {key: [] for key in keys}
        self.metadata_by_key = {key: {} for key in keys}


#: Resolved by dotted path through the factory, which is what a real
#: `.dex/config.yml` names. It has to be importable by the process dex runs in,
#: and here that process is this one.
ASSETS = [_Definition([_Key("dim_date")])]


if __name__ == "__main__":
    sys.exit(main())
