# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""Our format against **dex-core's own** project contract, not ours.

This file is the acceptance criterion from `exmergo/dex#144`, run rather than
asserted: *a format implemented in a separate package, depending only on the
published wheel, passes the conformance suite without importing anything private.*
Every import below is public, and this distribution is not theirs.

`tests/test_conformance.py` runs OUR contract against the same format. The two are
not redundant. Ours checks that the neutral model says what we meant; theirs checks
that dex-core can safely read us. A format can satisfy either one alone.

Skipped wholesale when dex-core is absent, exactly as `test_dex_bridge.py` is, so
the engine-free claim stays testable. The CI step that proves that claim `--ignore`s
this file rather than relying on the skip, because a skip is not a signal.

**But a skip is exactly what would hide this file failing to do its job.** So the
skip is for developers only: set ``DEX_UPSTREAM_CONTRACT_REQUIRED=1`` and the import
becomes hard, turning "the contract went missing or got renamed" from a green skip
into a collection error. CI sets it. Without that, a dex-core that stopped providing
`adapters.conformance` would leave this whole file quietly unrun and the job green.

That hazard did NOT retire with the branch install. It used to read "a fork branch
that stopped providing it", because until 2026-08-07 this ran against a ref on our own
fork; `adapters.conformance` now ships in **v1.5.2** and the pin is ordinary. A yank,
a revert or a bad bump reaches the same unrun-and-green state a rewritten branch did,
so the variable is load-bearing against a release too.

Needs a dex-core carrying `adapters.conformance` - v1.5.2 or later; see the package
README for the command.
"""

from __future__ import annotations

import os
import pathlib
import tempfile

import pytest

from dagster_dex import DagsterProject, ProjectModel
from dagster_dex.conformance import (
    a_composite_key_declaration,
    a_join_declaration,
    a_single_key_declaration,
    malformed_yaml,
)

if os.environ.get("DEX_UPSTREAM_CONTRACT_REQUIRED") == "1":
    import exmergo_dex_core.adapters.conformance as conformance
else:
    pytest.importorskip("exmergo_dex_core", reason="the [dex] extra is not installed")
    conformance = pytest.importorskip(
        "exmergo_dex_core.adapters.conformance",
        reason=(
            "this dex-core predates the project conformance contract "
            "(exmergo/dex#192, released in v1.5.2); set "
            "DEX_UPSTREAM_CONTRACT_REQUIRED=1 to make this a failure instead"
        ),
    )

from exmergo_dex_core.adapters.project import (  # noqa: E402
    MaintainProject,
    ProjectContext,
)

from dagster_dex.dex import DexProject, project_from_context  # noqa: E402

#: Every assertion in this file is upstream's to make, which is what the marker
#: says. `conftest.py` holds marked tests to ZERO skips whenever
#: `DEX_UPSTREAM_CONTRACT_REQUIRED=1`, because a skipped conformance assertion is
#: a criterion not met rather than one met quietly - upstream declines to judge a
#: format on assertions it cannot reach, and the skip reason says so out loud.
#:
#: Module scope on purpose: it propagates to every test inherited from an
#: upstream contract class, which is most of what runs here and none of what is
#: written here.
pytestmark = pytest.mark.criterion

MODELS = (
    ProjectModel(name="dim_date", layer="silver"),
    ProjectModel(name="fact_sessions", depends_on=("dim_date",), layer="gold"),
)

#: The semantic fixture for `SemanticProjectContract`, written here rather than taken
#: from `dagster_dex.conformance`, because upstream's hook wants ONE model
#: carrying both resolved and unresolved fields and our two builders deliberately keep
#: them apart: `a_semantic_definition` maps everything, `a_semantic_definition_without_
#: expr` maps nothing, and both name the same model, so concatenating them would
#: declare it twice.
#:
#: **Mixing them is the point rather than a convenience.** Upstream's hook asks for
#: at least one field mapping to `None` *if the format can produce one*, and ours can.
#: An all-resolved fixture would make
#: `test_a_categorical_dimension_maps_only_to_a_real_column` pass trivially: with no
#: unresolved categorical anywhere in the layer, it cannot separate a format that
#: correctly leaves one out of `categorical_dimensions` from one that invents a column
#: to keep it in. That is the equal-fixture-sides failure, in the one suite whose judge
#: is upstream rather than us.
#:
#: All three routes to `None` are here: `region` omits `expr` **and** is
#: `type: categorical`, which is the only unresolved state that can reach a *required*
#: value on the far side; `revenue_with_fee` declares an expression rather than a bare
#: column name.
_SEMANTIC_MODEL = "mart_revenue"
_SEMANTIC_DECLARATION = (
    "semantic_models:\n"
    f"  - name: {_SEMANTIC_MODEL}\n"
    f"    model: ref('{_SEMANTIC_MODEL}')\n"
    "    dimensions:\n"
    "      - name: date\n"
    "        type: time\n"
    "        expr: date\n"
    "      - name: provider\n"
    "        type: categorical\n"
    "        expr: provider\n"
    "      - name: region\n"
    "        type: categorical\n"
    "    measures:\n"
    "      - name: daily_revenue_net\n"
    "        agg: sum\n"
    "        expr: daily_revenue_net\n"
    "      - name: revenue_with_fee\n"
    "        agg: sum\n"
    "        expr: daily_revenue_net * 1.2\n"
)


def _wrapped(**sources) -> DexProject:
    """Our format, wearing their seam."""

    return DexProject(
        DagsterProject(
            MODELS,
            name="demo_project",
            declaration_sources=sources.get("declarations", {}),
            semantic_sources=sources.get("semantics", {}),
        )
    )


class TestDagsterProjectAgainstDexCore(
    conformance.DeclaringProjectContract,
    conformance.SemanticProjectContract,
    conformance.MaintainProjectContract,
):
    """Tier 2, plus the content mix-in. Inherits every tier-1 assertion.

    **This was `ExploreProjectContract` until the `expr` fix.** The narrower class was not a
    statement about their contract, it was our parser discarding the `expr:` that
    gives each measure its physical column. Widening it here is the assertion that
    the plumbing landed: if `semantic_layer()` regressed, this class stops
    satisfying the tier and the whole file fails rather than one test.
    """

    def make_project(self) -> DexProject:
        return _wrapped()

    def make_unreadable_project(self) -> DexProject:
        # Our format's real unparseable state: a declaration source that is not
        # YAML. Overridden rather than left to skip, because the never-raises
        # assertions are the ones worth the most and we can actually reach the
        # state they describe.
        return _wrapped(declarations={"broken.yml": malformed_yaml()})

    def a_project_declaring_a_unique_key(self) -> tuple[DexProject, str, str]:
        project = _wrapped(
            declarations={"keys.yml": a_single_key_declaration("dim_date", "date")}
        )
        return project, "dim_date", "date"

    def a_project_declaring_a_join(self) -> tuple[DexProject, str, str, str, str]:
        project = _wrapped(
            declarations={
                "joins.yml": a_join_declaration(
                    "fact_sessions", "date", "dim_date", "date"
                )
            }
        )
        return project, "fact_sessions", "date", "dim_date", "date"

    # -- the content hooks upstream added after the suite could not see them ----

    def a_project_declaring_a_composite_key(self):
        """Four columns, from our own builder rather than hand-rolled YAML.

        The model is `fact_orders`, which this test's two-model graph does not
        build, and that is deliberate rather than sloppy. The reference tree this
        format was developed against carries NO composite grains at
        all: dbt's `unique` test is column level, so declaring one member of a
        composite alone would be false rather than partial, and its generator says
        so. The composite case therefore lives only in our conformance builder, and
        this is the first thing that reads it through upstream's contract.

        A declaration naming a model the graph does not build is a supported state
        for us, kept with a note rather than dropped, so it costs a note here and
        nothing else.
        """

        project = _wrapped(
            declarations={"composite.yml": a_composite_key_declaration()}
        )
        return (
            project,
            "fact_orders",
            ("date", "provider", "product_id", "order_type"),
        )

    def a_project_declaring_a_join_with_differently_named_sides(self):
        """The mirroring case, which our own suite already had and theirs did not.

        `product_url -> canonical_url`, the same pair our `test_a_join_keeps_the_two_sides_
        apart_when_they_are_named_differently` uses, because that is the mutation it
        was written for: `to_columns=(field,)` mutated to `to_columns=(column,)`
        left our whole suite green until a differently-named case existed.
        """

        project = _wrapped(
            declarations={
                "asymmetric.yml": a_join_declaration(
                    from_model="fact_pageviews",
                    from_column="product_url",
                    to_model="dim_product",
                    to_column="canonical_url",
                )
            }
        )
        return project, "fact_pageviews", "product_url", "dim_product", "canonical_url"

    def a_project_declaring_a_semantic_model(self):
        """The O12 assertion, now owed to upstream's contract rather than only ours.

        The resolved fields carry `expr:`, which is what a COMPLETE declaration looks
        like in our vocabulary and is the half we used to throw away - the half that
        decides whether `dangling_reference` can run at all.

        The unresolved ones are the honest answer rather than a gap, and upstream's
        hook asks for at least one: an expression is not a column name, and neither is
        an absent `expr`. Handing a consumer that resolves column names an invented one
        manufactures a reference that cannot resolve. Both are disclosed through
        `semantic_layer_notes()`.

        **This fixture is mixed on purpose; see `_SEMANTIC_DECLARATION`.** An
        all-resolved one would let
        `test_a_categorical_dimension_maps_only_to_a_real_column` pass without ever
        exercising what it checks, because `region` - categorical *and* unresolved -
        is the only shape that can tell a correct exclusion from an invented column.
        """

        project = _wrapped(semantics={"semantic.yml": _SEMANTIC_DECLARATION})
        return (
            project,
            _SEMANTIC_MODEL,
            {"date": "date", "provider": "provider", "region": None},
            {"daily_revenue_net": "daily_revenue_net", "revenue_with_fee": None},
        )


class _FactoryKey:
    def __init__(self, name: str) -> None:
        self.path = (name,)


class _FactoryDefinition:
    """The three public attributes `from_asset_graph` reads. No orchestrator.

    Mirrors the fake in `test_dex_bridge.py` rather than importing it: one test
    module reaching into another couples their collection order, and the surface
    being faked is three attributes.
    """

    def __init__(self, keys, deps=None, metadata=None) -> None:
        self.keys = keys
        self.asset_deps = deps or {}
        self.metadata_by_key = metadata or {}


_DIM_DATE = _FactoryKey("dim_date")
_FACT = _FactoryKey("fact_sessions")

#: Module level so the factory reaches it by dotted path exactly as it would reach
#: a real code location, which makes `empty_context()` a genuine round trip through
#: `importlib` rather than a stub handed in.
#:
#: Deliberately the same two models as `MODELS` above, because upstream's contract
#: asks that `empty_context()` return the context reaching the project
#: `make_project()` returns. The two classes below then describe one project built
#: two ways, and a divergence between them is a real finding rather than an
#: artifact of two different fixtures.
UPSTREAM_FACTORY_ASSETS = [
    _FactoryDefinition([_DIM_DATE], metadata={_DIM_DATE: {"layer": "silver"}}),
    _FactoryDefinition(
        [_FACT],
        deps={_FACT: [_DIM_DATE]},
        metadata={_FACT: {"layer": "gold"}},
    ),
]

#: A declarations directory holding YAML that will not parse, for
#: `make_unreadable_project()` below. Built at import and held for the process:
#: `project_from_context` reads declarations off the filesystem, and the hook it
#: feeds takes no pytest fixtures.
_BROKEN_DECLARATIONS = tempfile.TemporaryDirectory()
(pathlib.Path(_BROKEN_DECLARATIONS.name) / "broken.yml").write_text(
    malformed_yaml(), encoding="utf-8"
)


class TestDagsterProjectBuiltFromContext(
    conformance.ProjectFactoryContract,
    conformance.MaintainProjectContract,
):
    """The same tier-2 contract, against a project **dex built** rather than one
    handed over.

    Separate from the class above rather than folded into it, and both are worth
    running. That one proves the format is correct when a host constructs it; this
    one proves it is reachable from `.dex/config.yml`, which is the only door open
    to a host that reaches dex as a subprocess. A format can pass the first and fail
    the second, and this package has done exactly that: the behavioural suite was
    green for months while the registered entry point could not build anything at
    all.

    `ProjectFactoryContract` goes first so its `make_project()` supplies every
    inherited assertion below with a factory-built project. That is the whole point
    of mixing it in front: without it these would run against a hand-built instance
    again and the construction path would stay unexercised.

    **What this does not prove.** The assets are fakes, so a green run here says
    the factory, the dotted-path resolution and the reduction agree; it says nothing
    about real `dagster` objects. An end-to-end `maintain snapshot` against a live
    asset graph is what covers that, and it does not run in CI.
    """

    tier = MaintainProject

    def build(self, context) -> DexProject:
        return project_from_context(context)

    def empty_context(self):
        # No `repo_root`: this format is keyed by an importable module, and the
        # context is built the way a real configuration entry would produce it.
        return ProjectContext(
            options={"assets": f"{__name__}:UPSTREAM_FACTORY_ASSETS", "name": "demo_project"}
        )

    def make_unreadable_project(self) -> DexProject:
        # Overridden rather than left to skip, for the reason the class above
        # overrides it: the never-raises assertions are the ones worth the most,
        # and this format can actually reach the state they describe. An absolute
        # path so no `repo_root` is needed to resolve it.
        return self.build(
            ProjectContext(
                options={
                    "assets": f"{__name__}:UPSTREAM_FACTORY_ASSETS",
                    "declarations": _BROKEN_DECLARATIONS.name,
                }
            )
        )


def test_the_tier_we_reach_is_two_and_three_is_declined():
    """The tier boundary is asserted, so moving it stays a decision.

    Both directions matter. Reaching tier 2 is what lets this format be a drift
    baseline, and losing either layer method would silently drop it back to tier 1
    where `maintain` stops asking. Declining tier 3 is a live decision rather than a
    permanent one: the models cannot receive an edit, but the declarations are
    hand-written files that can, and the tier stays declined only because dex cannot
    route an edit to them yet. See `dex.DexProject` for the two upstream blockers.
    When they move, this assertion is the one that has to change deliberately.

    This assertion previously read `== 1` and was named
    `..._and_that_is_deliberate`, describing the gap as a finding about a tier
    bundling two channels. That was wrong twice, and the history is kept in
    `DexProject`'s docstring; "deliberate" was doing the work of "unfinished".
    """

    from exmergo_dex_core.adapters.project import (
        EditableProject,
        MaintainProject,
        PlacingProject,
        tier_of,
    )

    project = _wrapped()

    assert tier_of(project) == 2
    assert isinstance(project, MaintainProject)
    assert not isinstance(project, EditableProject)
    # `PlacingProject` (dex-core 1.6.4, exmergo/dex#263) sits BESIDE the tiers
    # rather than inside them, so `tier_of() == 2` says nothing about it and the
    # line above does not imply this one. Upstream's write gate reads the
    # capability directly, which makes this the assertion that actually keeps
    # reconcile's proposals advisory for our format.
    assert not isinstance(project, PlacingProject)


def test_the_format_name_is_forwarded_not_duplicated():
    """`name` is their word for what we call `format`, and it must not drift.

    Copying the string would let the two disagree the moment either changes; a
    property cannot.
    """

    project = _wrapped()

    assert project.name == "dagster"
    assert project.name == project._project.format


#: Contracts upstream ships that this format deliberately does NOT mix in, with
#: the reason each one is declined. The value is prose because it is the whole
#: point: a decline that cannot say why is indistinguishable from an oversight.
_DECLINED = {
    "EditableProjectContract": (
        "tier 3 is declined structurally - a project reduced from a running "
        "graph has no source of truth that can receive an edit, so the method "
        "is absent rather than present and empty"
    ),
    "PlacingProjectContract": (
        "placement is declined for the same reason: an edit path into a "
        "reduction would name a file regenerated from something else"
    ),
}


def test_every_contract_upstream_ships_is_mixed_in_or_explicitly_declined():
    """The half a skip count cannot reach: upstream ADDING a contract.

    dex-core 1.6.4 added `PlacingProjectContract`. Nothing in this package went
    red, because a contract nobody mixes in runs no assertions - it is invisible
    to a suite that only counts what ran. Someone noticed by hand and wrote a
    paragraph explaining why the number had not moved, which is a control made
    of attention.

    Both directions are asserted, and the second is the one that rots:

    - A contract upstream ships that is neither mixed in nor declined is a gap
      in what this format is judged on, and it arrives silently at a bump.
    - A decline naming a contract upstream no longer ships is an allowance that
      outlived its reason, which is a gate with a hole in it.
    """

    shipped = {
        name
        for name in dir(conformance)
        if name.endswith("Contract") and isinstance(getattr(conformance, name), type)
    }

    mixed_in = {
        base.__name__
        for cls in (TestDagsterProjectAgainstDexCore, TestDagsterProjectBuiltFromContext)
        for base in cls.__mro__
    }

    unconsidered = shipped - mixed_in - set(_DECLINED)
    assert not unconsidered, (
        "dex-core ships conformance contracts this format neither implements nor "
        f"declines: {sorted(unconsidered)}. Mix one in, or add it to _DECLINED "
        "with the reason. An unconsidered contract is an assertion nobody made."
    )

    stale = set(_DECLINED) - shipped
    assert not stale, (
        f"_DECLINED names contracts dex-core no longer ships: {sorted(stale)}. "
        "A decline that outlived its contract is an allowance with nothing "
        "behind it; delete the entry."
    )
