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

Legs 7 to 15 run that same round trip a second time, over the ARTIFACT
transport, which is the shape production actually configures - and which could
not reach the write tier at all until `declarations:` was admitted beside
`artifact:` (dagster-dex #29).

  7. `artifact:` plus a `declarations:` directory reaches tier 3.
  8. The directory SUPERSEDES the declarations the artifact carries, both arms.
  9. And says so through `notes()`, which is where a dropped mapping is
     disclosed, asserted on the project rather than on what feeds it.
 10-12. Reconcile, plan, apply - as legs 2 to 4, over the other transport.
 13. THE DECIDING LEG. The written test is read back as a declared key with no
     artifact regenerated. #29 names this as the only evidence that separates a
     real fix from a plausible one.
 14. The human again. The pin now comes from a different place, so leg 6 is not
     evidence about this route.
 15. `artifact:` alone is still tier 2, and `semantics:` / `sources:` / `name:`
     are still refused beside it. One exception, still one.

Leg 8's fixture is deliberately MIXED. The artifact carries a bare-stem
`dim_date` declaring a column that is on no file; the directory carries a
`fact_orders` the artifact has never heard of. Without both halves, "the
directory superseded the artifact" and "the artifact was read as usual" are
equally consistent with a green run.

Leg 10 is the one that catches the design's own near miss, and it was expected to
be leg 11. An artifact keys declarations by a bare stem, a bare stem is inside no
editing surface, and an edit view built from those keys is EMPTY. Reconcile merges
into the text the view hands it, so an empty view yields NO EDIT rather than an
unpinned one - the defect arrives one leg earlier than the assertion written for
it. Leg 11's pin assertion is therefore a backstop no mutation reaches, which is
recorded on the leg itself rather than left to look like a control.

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
        --with exmergo-dex-core==1.8.0 --with sqlglot==30.13.0 \\
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

#: A second declaration, on disk and carried by NO artifact. Legs 7 onward need
#: the two sides to disagree in both directions, and this is the half only the
#: directory can produce: if it is declared, the directory was read.
SECOND_DECLARATION = (
    "models:\n"
    "  - name: fact_orders\n"
    "    columns:\n"
    "      - name: order_id\n"
    "        tests:\n"
    "          - unique\n"
)

#: The other half, and the tracer. Carried ONLY by the artifact, declaring a
#: column that exists on no file in the tree. It must be declared when the
#: artifact is read alone and gone when a declarations directory is named beside
#: it - which is what tells supersession apart from a project that parsed nothing.
STALE_DECLARATION = (
    "models:\n"
    "  - name: dim_date\n"
    "    columns:\n"
    "      - name: stale_only\n"
    "        tests:\n"
    "          - unique\n"
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
    from dagster_dex.artifact import dumps
    from dagster_dex.model import ProjectModel

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
        if not announce("leg 6 ok        : the refusal held and reported itself"):
            return report()

    # -- legs 7 to 15: the same round trip, on the ARTIFACT transport --------
    #
    # A fresh tree. Legs 1 to 6 leave a human's edit on disk, and this half has
    # to be able to say that nothing was declared for `dim_date` before it ran.
    #
    # The artifact and the directory are made to DISAGREE, and the disagreement
    # is the instrument. `stale_only` is carried only by the artifact and exists
    # on no file; `fact_orders` is carried only by the directory. So "the
    # directory superseded the artifact" and "the artifact was read as usual"
    # give different answers, instead of both being consistent with green.
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        directory = root / "declarations"
        directory.mkdir()
        target = directory / "dim_date.yml"
        target.write_text(DECLARATION, encoding="utf-8", newline="\n")
        (directory / "fact_orders.yml").write_text(
            SECOND_DECLARATION, encoding="utf-8", newline="\n"
        )

        # Bare-stem keyed, the way a real artifact is: `dumps` carries
        # `{name: text}`, and the writers feeding it key by the file's stem. That
        # is the fact that decides the whole design - a bare stem is inside no
        # editing surface, so an edit view built from these keys would be empty
        # and every edit would pin against a file it thought was absent.
        (root / "project").mkdir()
        (root / "project" / "demo.json").write_text(
            dumps(
                name="demo_project",
                models=[ProjectModel(name="dim_date", layer="gold")],
                generated_at="2026-01-01T00:00:00Z",
                declaration_sources={"dim_date": STALE_DECLARATION},
            ),
            encoding="utf-8",
        )

        snapshot_context = ProjectContext(
            repo_root=str(root),
            project_dir=None,
            options={"artifact": "project/demo.json"},
        )
        both_context = ProjectContext(
            repo_root=str(root),
            project_dir=None,
            options={
                "artifact": "project/demo.json",
                "declarations": "declarations",
            },
        )

        snapshot_only = construct_project("dagster", factory, snapshot_context)

        # -- leg 7: the artifact transport reaches the write tier -------------
        #
        # Caught, because on a tree that refuses the combination this RAISES
        # rather than returning a tier-2 project. An uncaught ValueError prints a
        # traceback instead of naming the leg, which is the defect leg 1's bail
        # exists to prevent - the same promise, one construction route over.
        try:
            project = construct_project("dagster", factory, both_context)
        except ValueError as exc:
            check(
                "leg 7: an artifact plus a declarations directory reaches the "
                "write tier",
                False,
                f"construction was refused: {exc}",
            )
            return report()

        check(
            "leg 7: the combination reaches tier 3",
            tier_of(project) == 3,
            f"tier_of said {tier_of(project)}",
        )
        check("leg 7: it satisfies EditableProject", isinstance(project, EditableProject))
        check("leg 7: it satisfies PlacingProject", isinstance(project, PlacingProject))
        if not announce(
            f"leg 7 ok        : tier {tier_of(project)} project from an artifact "
            f"plus a directory"
        ):
            return report()

        # -- leg 8: the directory supersedes the artifact's declarations ------
        #
        # Both arms, and the quiet one is what makes the loud one mean anything.
        # LOUD: the tracer the artifact carries is gone. QUIET: it is still there
        # when the artifact is read alone - so its absence above is supersession
        # rather than a project that parsed nothing at all.
        stale_columns = {k.column for k in snapshot_only.definitions().declared_keys}
        live_keys = {(k.model, k.column) for k in project.definitions().declared_keys}

        check(
            "leg 8: the artifact alone still declares what it carries",
            "stale_only" in stale_columns,
            f"the artifact declared {sorted(stale_columns)!r}",
        )
        check(
            "leg 8: naming the directory supersedes the artifact's text",
            not any(column == "stale_only" for _model, column in live_keys),
            f"declared {sorted(live_keys)!r}, which still carries the artifact's",
        )
        check(
            "leg 8: and the directory's own second file is declared",
            any(model == "fact_orders" for model, _column in live_keys),
            f"declared {sorted(live_keys)!r}",
        )
        check(
            "leg 8: nothing is declared for dim_date yet, which makes leg 13 a pair",
            not any(model == "dim_date" for model, _column in live_keys),
            f"declared {sorted(live_keys)!r}",
        )
        if not announce(
            f"leg 8 ok        : declares {len(live_keys)} key(s), none of them "
            f"the artifact's"
        ):
            return report()

        # -- leg 9: and it SAYS the artifact's declarations were superseded ---
        #
        # `notes` is this format's disclosure channel and it is load-bearing: a
        # mapping that drops something without saying so is the failure the
        # channel exists for. Asserted on the PROJECT rather than on whatever
        # feeds it, because a check that reads the source of a value cannot see
        # it failing to arrive at the destination.
        combined_notes = project.notes()
        snapshot_notes = snapshot_only.notes()

        check(
            "leg 9: the supersession is disclosed",
            any("superseded" in note for note in combined_notes),
            f"notes were {combined_notes!r}",
        )
        check(
            "leg 9: and is not claimed when there is nothing to supersede",
            not any("superseded" in note for note in snapshot_notes),
            f"the artifact alone disclosed {snapshot_notes!r}",
        )
        if not announce(
            f"leg 9 ok        : {len(combined_notes)} note(s), the supersession "
            f"among them"
        ):
            return report()

        # -- leg 10: a proposal that is NOT advisory, on this transport -------
        #
        # And this is where an edit view built from the wrong keyspace actually
        # surfaces, which is not where it was expected to. Reconcile MERGES into
        # the text the view hands it, so a view keyed by bare stems - the shape
        # the artifact carries - is empty, and an empty view produces no edit at
        # all rather than an unpinned one. Measured: keying the view by stem
        # fires this leg, not leg 11.
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
            "leg 10: reconcile produced a plan edit rather than only an advisory",
            bool(edits),
            f"no edits; warnings were {warnings!r}",
        )
        if edits:
            check(
                "leg 10: the edit landed at the key this format placed",
                edits[0].path == "declarations/dim_date.yml",
                f"placed at {edits[0].path!r}",
            )
            check(
                "leg 10: the content reconcile authored adds the unique test",
                "unique" in (edits[0].new_content or ""),
                f"content was {edits[0].new_content!r}",
            )
        if not announce(
            f"leg 10 ok       : {len(edits)} plan edit(s), "
            f"{len(proposals)} proposal(s)"
        ):
            return report()

        # -- leg 11: the plan store, through this format's surface -------------
        #
        # NO MUTATION REACHES THIS LEG'S PIN ASSERTION, and saying so is worth
        # more than the assertion. It was written believing it caught an edit
        # view built from the artifact's keyspace; leg 10 catches that first, and
        # the two other candidates tried - a wrong view root, and a view
        # reporting a hash of nothing - fire legs 12 and 4. So this is a backstop
        # mirroring leg 3, kept because it would discriminate if reconcile ever
        # stopped needing the view, and NOT a control that has been shown to
        # fire. Do not cite it as one.
        store = MemoryStore()
        plan, diffs, plan_warnings = plans.plan(
            "add the unique test the grain lost",
            edits,
            repo_root=root,
            store=store,
            project_format=project,
        )

        check("leg 11: the plan was stored", bool(plan.plan_id))
        check(
            "leg 11: the edit was pinned against the file on disk, not an empty view",
            plan.edits[0].old_content_hash is not None,
            "old_content_hash was None, so the declarations the artifact carries "
            "were used as the edit view and none of them is inside the surface",
        )
        check("leg 11: a reviewable diff came back", bool(diffs))
        if not announce(
            f"leg 11 ok       : plan {plan.plan_id} stored, {len(diffs)} diff(s)"
        ):
            return report()

        # -- leg 12: applied through THIS format's write path -----------------
        result = plans.apply(
            plan.plan_id, repo_root=root, store=store, project_format=project
        )

        check(
            "leg 12: the apply wrote the file",
            result.written == ["declarations/dim_date.yml"],
            f"written was {result.written!r}, conflicts {result.conflicts!r}",
        )
        check(
            "leg 12: and the unique test is in the file on disk",
            "unique" in target.read_text(encoding="utf-8"),
            f"the file holds {target.read_text(encoding='utf-8')!r}",
        )
        if not announce(f"leg 12 ok       : wrote {result.written}"):
            return report()

        # -- leg 13: THE DECIDING LEG ----------------------------------------
        #
        # A reconcile proposal has reached an artifact-transported project's
        # declarations and is read back as a declared key, with no artifact
        # regenerated. This is the artefact dagster-dex #29 named as the only
        # evidence that would tell a real fix from a plausible one.
        rebuilt = construct_project("dagster", factory, both_context)
        after = rebuilt.definitions()

        check(
            "leg 13: the written test is read back as a declared key",
            any(
                k.model == "dim_date" and k.column == "date" for k in after.declared_keys
            ),
            f"declared_keys was {after.declared_keys!r} after the write",
        )
        if not announce(
            f"leg 13 ok       : declares {len(after.declared_keys)} key(s) now, "
            f"over the artifact transport"
        ):
            return report()

        # -- leg 14: and a human, arriving during review ----------------------
        #
        # Repeated on this transport rather than assumed from leg 6. The refusal
        # is a property of the pinned hash, and the pin now comes from a
        # different place, so leg 6 is not evidence about this route.
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
            "leg 14: the apply wrote nothing over the human's edit",
            refused.written == [],
            f"written was {refused.written!r}",
        )
        check(
            "leg 14: and said why, so the divergence reaches a person",
            bool(refused.conflicts),
            "conflicts was empty, so the refusal reads as a clean no-op",
        )
        check(
            "leg 14: the human's edit is still on disk",
            target.read_text(encoding="utf-8") == by_hand,
            "the file was overwritten",
        )
        check(
            "leg 14: the plan is not recorded as applied",
            store.load_plan(second.plan_id).applied_at is None,
            "applied_at was set on a plan that wrote nothing",
        )
        if not announce("leg 14 ok       : the refusal held here too"):
            return report()

        # -- leg 15: the exception did not become a hole ----------------------
        #
        # One option was admitted beside `artifact:`, not three. Without this leg
        # the change is indistinguishable from having deleted the refusal, and an
        # artifact read as tier 3 with nowhere for an edit to land is the
        # original defect the split class exists to prevent.
        check(
            "leg 15: an artifact ALONE is still tier 2",
            tier_of(snapshot_only) == 2,
            f"tier_of said {tier_of(snapshot_only)}",
        )
        check(
            "leg 15: and claims neither write-tier protocol",
            not isinstance(snapshot_only, EditableProject)
            and not isinstance(snapshot_only, PlacingProject),
            "an artifact with no directory behind it claimed a tier it cannot honor",
        )
        for option in ("semantics", "sources", "name"):
            still_refused = False
            try:
                construct_project(
                    "dagster",
                    factory,
                    ProjectContext(
                        repo_root=str(root),
                        project_dir=None,
                        options={
                            "artifact": "project/demo.json",
                            option: "declarations",
                        },
                    ),
                )
            except ValueError:
                still_refused = True
            check(
                f"leg 15: {option!r} beside 'artifact' is still refused",
                still_refused,
                "it was accepted, so the one exception has become three",
            )
        announce("leg 15 ok       : one exception, and it is still one")

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
