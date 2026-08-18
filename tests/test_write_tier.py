# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""The write tier's mechanism, with no engine installed.

This runs in the control step, which is deliberate and is most of the reason
`EditableDagsterProject` exists as its own class rather than as methods on the
dex boundary. The conflict handshake is the part of this package where getting it
wrong costs somebody their work rather than costing an inaccurate report, so it
is asserted where it can be asserted without an engine, a warehouse, or an
orchestrator in the picture.

Every assertion here is behavioural. A shape check cannot tell a `propose_edits`
that refuses correctly from one that never writes at all, which is why the
refusing and the writing arms appear in pairs throughout.
"""

from __future__ import annotations

import pytest

from dagster_dex import (
    DagsterProject,
    EditableProject,
    ProjectModel,
    tier_of,
)
from dagster_dex.conformance import a_single_key_declaration
from dagster_dex.model import definition_hash
from dagster_dex.project import EditableDagsterProject
from dagster_dex.protocol import ProposedEdit

MODELS = (
    ProjectModel(name="dim_date", layer="silver"),
    ProjectModel(name="fact_orders", depends_on=("dim_date",), layer="gold"),
)


def a_writable_project(tmp_path, files=None, surface=("declarations",)):
    """A project whose declarations are real files, because the write path reads them.

    Everything else in this package's suite runs against text held in memory, on
    purpose. This one cannot: `propose_edits` re-reads each target from disk to
    detect a change made after the edit was proposed, and a fixture that kept the
    text in memory would be asserting against the very copy the check exists to
    distrust.
    """

    directory = tmp_path / "declarations"
    directory.mkdir(exist_ok=True)
    files = {"dim_date.yml": a_single_key_declaration()} if files is None else files
    for name, text in files.items():
        (directory / name).write_text(text, encoding="utf-8", newline="\n")

    return EditableDagsterProject(
        MODELS,
        root=tmp_path,
        surface=surface,
        declaration_sources={f"declarations/{n}": t for n, t in files.items()},
    )


def an_edit(project, key="declarations/dim_date.yml", content="models: []\n"):
    """An edit pinned to what the project's own view says is there now."""

    current = project.editable_view().files.get(key)
    return ProposedEdit(
        key=key,
        new_content=content,
        pinned_hash=current.sha256 if current is not None else None,
    )


class TestTheTierIsPerClass:
    """The split is the design, so both halves are asserted and neither alone.

    `EditableProject` is `runtime_checkable`, which means it matches on a method
    being present. Put `propose_edits` on the base class and every instance
    claims the write tier, including one built from an artifact - a JSON file
    with no directory behind it - which would then have to refuse at call time.
    A caller finding out by receiving an empty result that looks like success is
    exactly what the tiers exist to prevent.
    """

    def test_the_editable_class_reaches_tier_three(self, tmp_path):
        assert tier_of(a_writable_project(tmp_path)) == 3

    def test_the_plain_class_still_does_not(self):
        """The half that rots. Adding a method to the base by accident is a
        one-line change that would otherwise leave this suite entirely green."""

        project = DagsterProject(MODELS)
        assert tier_of(project) == 2
        assert not isinstance(project, EditableProject)
        assert not hasattr(project, "propose_edits")
        assert not hasattr(project, "editing_surface")


class TestTheConflictHandshake:
    """Propose-don't-impose, at the only layer able to enforce it.

    The window between proposing an edit and applying it is a human review and
    can be long. What the pin buys is that a person who edits the target during
    it does not have their work replaced by a proposal written before it existed.
    """

    def test_a_clean_write_lands(self, tmp_path):
        """The ordinary case, and it has to be here.

        Without it, the two assertions below are equally consistent with a
        `propose_edits` that writes under no circumstances whatsoever.
        """

        project = a_writable_project(tmp_path)
        outcome = project.propose_edits([an_edit(project)])

        assert outcome.written == ("declarations/dim_date.yml",)
        assert outcome.conflicts == ()
        assert (tmp_path / "declarations/dim_date.yml").read_text(
            encoding="utf-8"
        ) == "models: []\n"

    def test_an_unconfirmed_write_refuses_a_target_that_moved(self, tmp_path):
        project = a_writable_project(tmp_path)
        edit = an_edit(project)

        target = tmp_path / "declarations/dim_date.yml"
        target.write_text("models: [{name: edited_by_a_human}]\n", encoding="utf-8")
        before = target.read_text(encoding="utf-8")

        outcome = project.propose_edits([edit])

        assert target.read_text(encoding="utf-8") == before
        assert outcome.written == ()
        assert [c.key for c in outcome.conflicts] == ["declarations/dim_date.yml"]

    def test_a_confirmed_write_overrides_the_conflict(self, tmp_path):
        """`confirmed=True` is the human saying they read the diff and meant it."""

        project = a_writable_project(tmp_path)
        edit = an_edit(project)

        target = tmp_path / "declarations/dim_date.yml"
        target.write_text("models: [{name: edited_by_a_human}]\n", encoding="utf-8")

        outcome = project.propose_edits([edit], confirmed=True)

        assert target.read_text(encoding="utf-8") == "models: []\n"
        assert outcome.written == ("declarations/dim_date.yml",)
        # The conflict is still reported. It happened, and a caller that
        # overrode one is exactly the caller that wants to know which.
        assert [c.key for c in outcome.conflicts] == ["declarations/dim_date.yml"]

    def test_one_conflict_refuses_the_whole_set(self, tmp_path):
        """All-or-nothing, which is a separate claim from detecting the conflict.

        Writing the clean half leaves the project in a state neither the proposal
        nor the person who edited during review intended, and no record of which
        half landed. This is the assertion a per-edit implementation passes the
        two above and fails.
        """

        project = a_writable_project(
            tmp_path,
            files={
                "dim_date.yml": a_single_key_declaration(),
                "fact_orders.yml": a_single_key_declaration(model="fact_orders"),
            },
        )
        clean = an_edit(project, key="declarations/fact_orders.yml")
        doomed = an_edit(project, key="declarations/dim_date.yml")

        moved = tmp_path / "declarations/dim_date.yml"
        moved.write_text("models: [{name: edited_by_a_human}]\n", encoding="utf-8")
        untouched = (tmp_path / "declarations/fact_orders.yml").read_text(
            encoding="utf-8"
        )

        outcome = project.propose_edits([clean, doomed])

        assert outcome.written == ()
        assert (tmp_path / "declarations/fact_orders.yml").read_text(
            encoding="utf-8"
        ) == untouched

    def test_a_create_whose_file_now_exists_is_a_conflict(self, tmp_path):
        """The same surprise from the other side, and the easier one to miss.

        A create pins `None`. If the check only compared two hashes it would
        compare `None` against a real one and happen to be right; if it treated
        `None` as "no expectation" it would overwrite a file somebody added while
        the proposal sat in review.
        """

        project = a_writable_project(tmp_path)
        edit = ProposedEdit(
            key="declarations/mart_revenue.yml",
            new_content="models: []\n",
            pinned_hash=None,
        )

        appeared = tmp_path / "declarations/mart_revenue.yml"
        appeared.write_text("models: [{name: written_by_someone_else}]\n", encoding="utf-8")

        outcome = project.propose_edits([edit])

        assert outcome.written == ()
        assert appeared.read_text(encoding="utf-8").startswith(
            "models: [{name: written_by_someone_else}]"
        )

    def test_a_delete_is_pinned_like_anything_else(self, tmp_path):
        """A delete carries no content and still carries the pin, so removing a
        file a human edited after the proposal is a conflict rather than a silent
        deletion."""

        project = a_writable_project(tmp_path)
        target = tmp_path / "declarations/dim_date.yml"
        pinned = definition_hash(target.read_text(encoding="utf-8"))
        target.write_text("models: [{name: edited_by_a_human}]\n", encoding="utf-8")

        outcome = project.propose_edits(
            [ProposedEdit(key="declarations/dim_date.yml", pinned_hash=pinned)]
        )

        assert outcome.written == ()
        assert target.is_file()

    def test_a_pinned_delete_removes_the_file(self, tmp_path):
        """The quiet arm for the pair above."""

        project = a_writable_project(tmp_path)
        target = tmp_path / "declarations/dim_date.yml"

        outcome = project.propose_edits(
            [
                ProposedEdit(
                    key="declarations/dim_date.yml",
                    pinned_hash=definition_hash(target.read_text(encoding="utf-8")),
                )
            ]
        )

        assert outcome.written == ("declarations/dim_date.yml",)
        assert not target.exists()


class TestContainment:
    """A surface is a region of the project, not a way out of it.

    Checked here as well as wherever the proposal was built. A containment check
    that only runs upstream is one a caller reaching this method directly routes
    around, and it costs a string comparison.
    """

    def test_a_key_outside_the_declared_surface_is_refused(self, tmp_path):
        project = a_writable_project(tmp_path)
        with pytest.raises(ValueError, match="editing surface"):
            project.propose_edits(
                [ProposedEdit(key="secrets/creds.yml", new_content="x\n")]
            )

    def test_a_prefix_does_not_admit_a_sibling_that_merely_starts_with_it(
        self, tmp_path
    ):
        """`declarations` admits `declarations/orders.yml` and must not admit
        `declarations_backup/orders.yml`. A string `startswith` passes every
        other assertion in this class and fails this one."""

        project = a_writable_project(tmp_path)
        with pytest.raises(ValueError, match="editing surface"):
            project.propose_edits(
                [
                    ProposedEdit(
                        key="declarations_backup/dim_date.yml", new_content="x\n"
                    )
                ]
            )

    @pytest.mark.parametrize(
        "key",
        [
            "../outside.yml",
            "declarations/../../outside.yml",
            "/etc/passwd",
        ],
    )
    def test_an_escape_is_refused_whatever_the_surface_says(self, tmp_path, key):
        """Escapes are refused before the surface is consulted, so a format
        cannot permit one by declaring it."""

        project = a_writable_project(tmp_path, surface=("declarations", ".."))
        with pytest.raises(ValueError, match="editing surface"):
            project.propose_edits([ProposedEdit(key=key, new_content="x\n")])


class TestTheView:
    def test_it_carries_the_files_and_the_place_they_are_relative_to(self, tmp_path):
        project = a_writable_project(tmp_path)
        view = project.editable_view()

        assert set(view.files) == {"declarations/dim_date.yml"}
        assert view.root == str(tmp_path)
        entry = view.files["declarations/dim_date.yml"]
        assert entry.sha256 == definition_hash(entry.content)

    def test_a_directory_outside_the_surface_is_read_but_not_offered(self, tmp_path):
        """Two different claims, and the file is subject to both.

        A directory configured elsewhere still contributes declarations - it is
        real input and dropping it would narrow what dex checks. It is simply not
        somewhere this format says it may write, and putting it in the view would
        be claiming a surface the containment check then refuses, which reads as
        dex declining rather than as this format contradicting itself.
        """

        project = EditableDagsterProject(
            MODELS,
            root=tmp_path,
            surface=("declarations",),
            declaration_sources={"declarations/dim_date.yml": a_single_key_declaration()},
            semantic_sources={"elsewhere/rev.yml": "semantic_models: []\n"},
        )

        assert set(project.editable_view().files) == {"declarations/dim_date.yml"}
        assert project.declarations().declared_keys, "the outside file stopped being read"
