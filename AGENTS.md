# AGENTS.md

Operating rules for AI coding agents, and for humans skimming for the sharp edges.

## What this is

One Python distribution: `dagster-dex`. A Dagster asset graph reduced to a neutral
project model, and bridged onto the `dex` engine's project seam through an entry
point. Alpha - the seam is a proposal, and the argument may still change it.

## The rule that matters most here

**The engine coupling is one file, and a CI step exists to prove it.**

`src/dagster_dex/dex.py` is the only module permitted to import
`exmergo_dex_core`. Everything else - the model, the protocol, the parser, and the
conformance suite - runs with dex-core **uninstalled**.

The first step of the `tests` job runs the whole suite with the engine absent.
**That step is a control, not a speed split.** Add an `exmergo_dex_core` import to
any other module and it goes red at collection. Merging it into the step below it
would delete the only thing checking the package's central claim.

`tests/test_dex_bridge.py` additionally walks `dex.py`'s AST to assert it imports
**public API only**, rather than trusting it.

## The names in `protocol.py` are OURS, and must not be "fixed" to match

| here | upstream (`adapters/project.py`) |
| --- | --- |
| `ProjectSource.declarations()` | `ExploreProject.definitions()` |
| `FingerprintedProject.fingerprint()` | `MaintainProject.transform_layer()` + `.semantic_layer()` |
| `EditableProject.propose_edits()` | `EditableProject.write_edits()` |

**This is not drift.** The package was designed on its own terms and owes nothing
to dex-core's model; `dex.py` is the bridge, which is exactly why the coupling is
one file. Upstream's tier-2 shape is two methods rather than one because their
`maintain snapshot` already exposed two - a correction that applies to *their*
tree, not this one.

**The word "tier" is theirs.** It was in their storage seam before it reached the
project seam. Never describe the tiering as this package's invention.

## Tier 3 is reached by ONE class, and the split is the design

`EditableDagsterProject` implements the write tier. `DagsterProject` does not,
and must not be given the method.

**It cannot be a flag or a runtime refusal.** `EditableProject` and
`PlacingProject` are both `runtime_checkable`, so they match on a method being
*present*. Put `propose_edits` on the shared class and every instance claims the
tier - including one built from an `artifact:`, which is a JSON file carrying
`{name: text}` with no directory behind it. That instance would have to refuse
every edit at call time, and a caller finding out by receiving an empty result
that looks like success is exactly what the tiers exist to prevent.

So `project_from_context` picks the class: a **`declarations:` directory** gets
the editable one, and everything else does not. `tests/test_dex_bridge.py` asserts
all four cases.

**This used to read "a live graph *plus* a `declarations:` directory", and the
live graph is no longer part of it.** A `declarations:` directory named beside an
`artifact:` reaches tier 3 too, which is what made the write tier reachable for
the deployment shape that had it and could not use it. The tier still turns on
having somewhere for an edit to land; what changed is that the graph is not the
only way to have one.

**Two directory contracts, stated because consumers build on them.** A missing
directory is refused by name and an EMPTY one is accepted at the full tier -
the asymmetry is deliberate (a provisioning order can create the directory
before its first content arrives; a missing directory means a wrong path, an
empty one a true state), and tightening the empty arm is a breaking change to
that order, not a tidier default. And the directory's PARENT is the project
root - keys are `<directory-name>/<file>` relative to it, downstream tooling
stores plans relative to it, so changing the derivation relocates every stored
plan's `project_dir`. Both are pinned in `tests/test_dex_bridge.py`; the pins
are the guarantee's home, so a change goes red here rather than in a consumer.

**The directory SUPERSEDES the declaration text the artifact carries, and it
has to. Do not "fix" this into the artifact keeping its declarations.** That was
proposed first and cannot be built:

- An artifact keys declarations by a **bare stem**, and must keep doing so - it
  has no directory to have come from, and inventing one is the fabricated
  provenance `ExternalSource.declared_in` exists to avoid.
- `_within` is segment-wise, so a bare stem is **inside no surface**.
- So an edit view built from the artifact's text is **empty**: every edit pins
  against a file it believes absent and every apply is a conflict on a file that
  plainly exists. Refused on every write, forever - worse than declining the tier.

The supersession is disclosed through `notes()`, with both arms: an artifact
carrying no declarations loses nothing, and claiming a loss that did not happen is
the same defect pointing the other way. And the cost argument never covered
declarations - `artifact:` exists to avoid importing a code location, and reading
YAML needs neither an import nor an orchestrator.

**What can receive an edit is the declarations, not the models.** A model is a
node in a running asset graph, regenerated on the next run. The declared keys
and joins are hand-written, version-controlled YAML in dbt's schema-test
spelling - which is what these files were already written in - so the `unique`
test `maintain reconcile` proposes lands where this package's own parser reads it
back as a declared key.

**Placement answers one kind and declines the rest.** `SCHEMA_YML` resolves;
every other `EditKind` is `None`, and that is a complete answer rather than a
partial implementation - upstream's protocol names this exact shape as what it
was built for. Two consequences worth knowing before changing anything here:

- `edit_path`'s `model` is the **warehouse table**, not our model name. There is
  no table-to-relation mapping here (`ProjectModel.relation` is `None`), so the
  table name is used as the file stem rather than guessed through one.
- Reconcile reads the model name out of the placed key's **stem**, so placement
  presumes **one model per declaration file**. A file declaring several gets a
  warning and no edit, which is upstream refusing to guess.

**Two dead reasons, so nobody re-derives them.** This section used to call the
decline structural, on the grounds that a reduction has no source of truth that
can receive an edit - retracted in the code on 2026-08-09 and left standing here
regardless. Then it stayed declined because dex could not route an edit to a
non-dbt format; both blockers this package filed (`exmergo/dex#257`, `#258`)
closed on 2026-08-11 under our own merged `exmergo/dex#263`.

## `load()` was required by two callers and declared by no protocol - fixed upstream, lesson kept

`transform.plans.plan` calls it to pin each edit against the file it would
change, and `maintain.commands` calls it before reconcile builds a proposal.
Until dex-core 1.7.0 neither `EditableProject` nor `PlacingProject` declared
it and no shipped conformance contract exercised it; this package filed that
as `exmergo/dex#328`, and 1.7.0 declared `load()` on `PlacingProject` (their
argument: both call sites reach it only for a placing format).

=> **The lesson stands even though the gap is closed: a format can pass every
assertion upstream ships and fail at the first real reconcile.**
`EditableDexProject.load()` predates the declaration - it exists because the
callers need it, not because the contract asked.

The suite asserts the read-only arm's decline **negatively** - `not
isinstance(project, EditableProject)` - so reaching tier 3 by accident is caught
rather than congratulated. `PlacingProject` is declined the same way on that arm
and separately, because it sits *beside* the tiers rather than inside them:
`tier_of() == 2` says nothing about it.

## Sharp edges

- **Sources are NOT graph dependencies.** `model_refs` is filtered to *built*
  models, because the engine's `model_refs` is the `ref()` graph. A dependency on
  something the project does not build is not a ref; what it might be instead is
  reported in `notes` rather than guessed at.
- **`notes` is the disclosure channel, and it is load-bearing.** Both layers
  carry it. A lossy mapping that cannot disclose itself is the failure it exists
  to prevent: an empty `files` compared against an empty `files` reads as "no file
  drift" rather than as "this cannot be checked here".
  - **Both halves need a loud arm and a quiet arm. This was got wrong once, and
    it is now guarded - do not undo the guard.** Dropping `notes=` from the
    `SemanticLayer` constructor once left an entire suite green, because every
    semantic assertion read the standalone `semantic_layer_notes()` function
    rather than the layer object the value is set on. => **Assert on the layer,
    not on the function that feeds it.** A test that reads the source of a value
    cannot see it failing to arrive at the destination.
    - Both layers now carry both arms in `tests/test_dex_bridge.py`, asserted on
      the layer. **Verified by mutation rather than by reading**: removing
      `notes=` from `to_semantic_layer` turns
      `test_an_unresolvable_field_arrives_as_none_and_is_disclosed` red on
      *"the pairing is the layer's job now, not the caller's"*. A new test would
      be a second copy of a working one.
- **`path` is `None`, never `""`.** The empty string was an undocumented
  sentinel, named as one by the release that made the field optional. A
  regression test guards it, because `""` validates fine and would go unnoticed.
  - It is no longer always `None`. `ExternalSource.declared_in` existed and was
    never set, so the mapping carried a field whose value was absent by
    construction; a source read out of a directory now names the file it came
    from. Text handed over in memory still gets `None`, and must: a bare model
    name is not a place.
- **A declaration key is `<directory>/<file>`, and it was the bare stem.** The
  three source mappings use it as an origin label in notes - except
  `parse_source_declarations`, which reads it as **the name of the model doing
  the reading**. That parser takes the key's stem, so a bare model name and a
  file key give the same answer. Widen the key without that and every source in a
  working project is attributed to a model the graph does not build.
- **The `exmergo_dex_core.projects` entry point is live as of dex-core 1.6.0**,
  and was inert before it for as long as nothing looked the group up. That is the
  origin of this repository's most-repeated lesson and the reason several tests
  exist that look redundant: they check the *resolution*, not the registration.

## Running the suite

Three steps. From the repository root:

```bash
# 1. the control -- no orchestrator, no engine
uv run --no-project --with-editable . --with pytest==8.4.1 \
  python -m pytest tests --ignore=tests/test_dex_bridge.py \
  --ignore=tests/test_upstream_contract.py

# 2. the boundary, against the real engine
uv run --no-project --with-editable . --with pytest==8.4.1 \
  --with exmergo-dex-core==1.8.0 --with sqlglot==30.13.0 \
  python -m pytest tests --ignore=tests/test_upstream_contract.py

# 3. dex-core's own project contract
DEX_UPSTREAM_CONTRACT_REQUIRED=1 uv run --no-project --with-editable . \
  --with pytest==8.4.1 --with exmergo-dex-core==1.8.0 --with sqlglot==30.13.0 \
  python -m pytest tests/test_upstream_contract.py -p no:cacheprovider
```

Plus two checks that are not pytest, and both run in the same CI job:

```bash
# the py.typed claim, actually checked -- at the FLOOR, not the newest interpreter
uv run --no-project --with-editable . --with mypy==1.14.1 --with types-PyYAML \
  python -m mypy

# the reduction against REAL dagster objects -- no other step installs it
uv run --no-project --with-editable . --with 'dagster>=1.13' \
  python examples/reduce_asset_graph.py

# the WHOLE loop against a real (DuckDB) warehouse -- the only command that
# installs the orchestrator, the engine and a warehouse at once
uv run --no-project --with-editable . --with 'dagster>=1.13' \
  --with exmergo-dex-core==1.8.0 --with sqlglot==30.13.0 --with duckdb \
  python examples/walk_the_whole_loop.py
```

The second line used to end `python -c "..."`, with the ellipsis standing in for
a script. **That is a command that runs, exits 0, and checks nothing** -
`...` is a bare `Ellipsis`, so Python evaluates it and succeeds. A reader
copying it saw the same exit code CI produces and had installed an orchestrator
to evaluate a constant. => **An elided command is worse than a missing one: it
returns the answer you were looking for.** Every command in this file is
runnable verbatim now, which was checked by running all of them.

**The Dagster step exists because everything else uses fakes.** That is
deliberate - the suite must run without an orchestrator - but it means nothing
else here would notice `from_asset_graph` breaking against the objects Dagster
actually hands it. The `[dagster]` extra was declared and installed by nothing
until that step existed.

`--with-editable` is not optional - without it every test errors at collection
on `No module named 'dagster_dex'`. Never `uv run --python X` without
`--no-project`; it recreates a `.venv` here.

## The two drivers, and why passing the contracts is not enough

`scripts/drive_dex_against_the_wheel.py` proves dex can READ a project through
the published distribution. `scripts/drive_the_write_path_against_the_wheel.py`
proves a `maintain reconcile` proposal reaches the write path, becomes a stored
plan, is written through this format, changes what the project declares, and is
REFUSED when a human edited the file behind a second plan. Both run in
`publish.yml`'s `build` job, which runs on every pull request.

**Neither is redundant with the conformance contracts.** Measured, not
assumed: five defects were introduced one at a time into `propose_edits`, and
dex-core's `EditableProjectContract` and `PlacingProjectContract` caught **two**.
All-or-nothing, a create whose pin is `None`, and segment-wise containment all
pass the shipped contracts in full. They are honest about being behavioural
rather than exhaustive; treating them as proof is the caller's mistake.

Run either by hand:

```bash
uv run --no-project --with-editable . \
  --with exmergo-dex-core==1.8.0 --with sqlglot==30.13.0 \
  python scripts/drive_the_write_path_against_the_wheel.py
```

**The write-path driver bails after leg 1 when the tier is not reached**, on
purpose. Every leg below it calls a method the write tier adds, so pressing on
against a tier-2 project reports an `AttributeError` traceback instead of naming
the leg. Found by running it against the tree from before the write tier
existed, which is also the run that proves the legs can fail at all.

**It runs the round trip twice: legs 1-6 on the live-graph path, legs 7-15 on the
artifact transport.** The second half is not a copy. It is a different
construction route with two keyspaces meeting, and leg 13 is the artefact that
decided the design - a reconcile proposal read back as a declared key over the
artifact transport, with no artifact regenerated.

**The bail has a cost, and it bounds what calibration can prove.** Once
anything fails, every later `announce` returns `False`, so a mutation can only be
shown to fire the **earliest** leg it breaks. Two consequences, both measured
rather than reasoned:

- A mutation that breaks both transports fires on the live-graph half and the
  artifact half is never reached. Scope such a mutation to one route, or it
  proves nothing about the other.
- **Leg 11's pin assertion is a backstop no mutation reaches**, and the leg says
  so. It was written believing it caught an edit view built from the artifact's
  keyspace; leg 10 catches that first, because reconcile *merges* into the text
  the view hands it and an empty view yields no edit at all. Two other candidates
  fired legs 12 and 4. => **An assertion written for a defect is not evidence the
  defect is caught there.**

## The Python floor

`requires-python = ">=3.10"`, matching Dagster's own supported range. Verified
rather than assumed: the core suite is green on 3.10, 3.11, 3.12 and 3.13.

**The `[dex]` extra cannot install on 3.10** - `exmergo-dex-core` requires
`>=3.11`. That is a supported configuration, not a hole: on 3.10 you get the
model, the reduction, the conformance contract and `artifact.dumps`, which is
enough to write a reduced project that a machine on 3.11+ reads with the engine.
The artifact transport exists for exactly that split, so **the floor is set by
the core rather than by the heaviest extra.** Do not raise it to match the extra.

**`DEX_UPSTREAM_CONTRACT_REQUIRED=1` is what makes step 3 a signal.** Without
it the file skips itself when the upstream contract is unimportable - right at a
desk, wrong in CI, where an unrun file and a passing file look identical.

**These three used to be described as "matching CI exactly", and since
2026-08-18 they do not.** CI runs two axes these three commands do not: the
engine-free control on every interpreter in `requires-python`, and the boundary
plus the upstream contract at both ENDS of the published `[dex]` range rather
than at the demonstrated pin alone. The three above are still the right thing to
run at a desk - they are the fastest path to the same failures - but a green
local run is now a weaker claim than a green pipeline, which is the opposite of
what the old sentence implied.

To reproduce an axis locally, resolve the ends the way CI does rather than typing
versions in, and substitute one into steps 2 and 3:

```bash
python scripts/resolve_engine_range.py
```

## What CI runs that these three do not

**Two promises were asserted in prose and measured only when somebody
remembered.** `requires-python = ">=3.10"` and the `[dex]` extra's
compatible-release range were both verified by a hand-run matrix at each
release. A step that has to be remembered is not a control, so both are now jobs.

- **`python-floor`** runs the engine-free control on 3.10, 3.11, 3.12 and 3.13.
  The list is written out on purpose: `>=3.10` is open-ended, so there is nothing
  to resolve, and adding an interpreter is a decision about what is claimed.
- **`engine-ends`** runs the boundary suite and the upstream contract at the
  floor and the ceiling of the published range, **resolved rather than listed**.
  A hand-written list of versions is a registry making a claim about a moving
  set: upstream publishes a patch, the promise widens, the matrix does not, and
  nothing goes red. `scripts/resolve_engine_range.py` reads the specifier out of
  `pyproject.toml` and asks a resolver, so it holds no version literal - the same
  argument `tests/test_pin_coherence.py` makes for itself.
- **`suite`** keeps the exactly-pinned steps. It is not folded into
  `engine-ends`, because the exact pin and the published range are two different
  claims - see the two-pins section below. Folding them would delete one.
  It also keeps the literal `exmergo-dex-core==` strings where
  `test_pin_coherence.py` can see them; a `${{ matrix.version }}` expression is
  not a pin, so templating those steps would have shrunk that guard's corpus by
  two sites with no count changing to show it.

**The cross-product is one named cell, not a matrix**: the engine axis runs on
the newest claimed interpreter (`--python` on its steps, moved together with
the `python-floor` list), so "the floor of the range on the newest
interpreter" - the cell this paragraph used to name as deliberately untested -
runs on every push. The rest of the product stays not run: the intermediate
interpreters never meet the engine here, stated rather than left for a green
matrix to imply.

**The job named `tests` is an aggregate, and the name is load-bearing.** It is a
required status check on an organisation ruleset, matched by context string. A
`strategy.matrix` on a job called `tests` renames its contexts to `tests (3.10)`
and so on, at which point the required context never reports - and a check that
never reports never blocks a merge. The gate would go quiet rather than red.
Renaming it means editing the organisation ruleset in the same change.

## The dependency pin, and why there are two of them

- **Published** (`pyproject.toml`, the `[dex]` extra): `exmergo-dex-core~=1.8`,
  i.e. `>=1.8, ==1.*`. Minors and patches move, the major boundary does not.
  **Was `~=1.6.4` until 0.5.0** (1.7.0 shipped the fix for our exmergo/dex#328
  and `==1.6.*` refused it) **and `~=1.7` until 0.6.0** (1.8.0 shipped the fix
  for our exmergo/dex#337, and the whole-loop legs that demonstrate it need
  the floor to admit nothing older). Each floor raise is why its release is a
  minor, not a patch -- a consumer on the older engine stays on the older
  package.
- **Tested** (CI and the commands above): `exmergo-dex-core==1.8.0`, exactly.
  - This line used to read ``==1.6.4``, naming the version without naming the
    package. That put it **outside** `tests/test_pin_coherence.py`, which
    matches on the package name - so the one sentence in this file that states
    the tested version was the one site nothing checked, and it would have gone
    stale at the first bump with nothing to catch it. Found by the bump. Fixed
    by making the sentence guardable rather than by loosening the guard, since a
    looser pattern would have to match a bare `==1.6.5` anywhere and would find
    versions of unrelated things.

**These disagree on purpose.** This package is a plugin whose host resolves it
through an entry point, so an `==` pin in published metadata would make every
dex-core release uninstallable alongside it until this package re-released. The
version the mapping was verified against belongs where demonstrations live, not
imposed on every consumer's resolver. Do not "fix" the mismatch by aligning them.

The floor is load-bearing: below dex-core 1.6.0 the `exmergo_dex_core.projects`
group is not resolved at all, so the package would install and silently never be
found.

## Packaging

- `Typing :: Typed` and `src/dagster_dex/py.typed` ship **together or not at all**.
  The classifier alone is a claim a type checker cannot act on; the marker alone is
  invisible on the project page. The release workflow asserts the marker is in the
  built wheel.
- `version` in `pyproject.toml` and `__version__` in `__init__.py` are two
  hand-maintained strings. A test asserts they agree, and the release workflow
  asserts both agree with the tag.
- The release is tag-gated on `v*`. Publishing is a deliberate act, not the tail of
  a merge, and the `pypi` environment holds the tag at a required reviewer before
  anything is uploaded.
- **`0.1.0` is published** (2026-08-15, from `v0.1.0`). That makes the version bump
  mandatory for every release after it: an index refuses a version it already
  holds, so a tag cut without one stops at the workflow's match gate.
- The rehearsal is the `rehearse` job in the same workflow: `workflow_dispatch`
  only, TestPyPI, with its **own** `testpypi` environment and publisher - a Trusted
  Publisher matches on environment name, so the two identities cannot share one. It
  stamps a `.dev<run number>` version, because an index refuses a filename it
  already holds and a rehearsal you can only run once is no use on the second
  attempt. **Run it for any change to the upload path**; a plain version bump does
  not need it. Read the preamble at the head of `.github/workflows/publish.yml`
  before changing any of this.
- **The upload step is `pypa/gh-action-pypi-publish`, and the build step is still
  uv.** That split is the whole reason for the action: uv does not generate PEP 740
  attestations, only uploads ones something else made. Provenance attaches AT
  UPLOAD and index files are immutable, so a release that ships without it cannot
  be repaired, only superseded. Both jobs read the provenance back off the index
  and assert it names this repository, `publish.yml`, and the environment they ran
  in - presence alone would pass an attestation signed by anyone.

## Change workflow

- **Branch per change** off `main`. Never commit to `main` directly.
- **Conventional commits** (`feat:`, `fix:`, `docs:`, `test:`, `chore:`) with a
  body explaining *why*.
- **A title is a git artifact. PR and issue titles take the commit form:**
  `type(scope): summary` - lowercase after the colon, one clause, at most 100
  characters, no trailing period. A PR title becomes the merge commit history
  cites as `#N`; the full sentence belongs in the body. Issues take the type
  their fix would take; an issue arguing a fork rather than naming work is
  `argument:`. Probe PRs say `probe:` - a type, not an exemption.
  - The estate's `pr-title` guard could not run here as a shared action (a
    public repository cannot resolve an action in a private one), so the rule
    was held by this text alone until 2026-08-27. It is now vendored the same
    way the other two checks crossed the boundary: `scripts/check_pr_title.py`
    plus the `pr title` job in `checks.yml`, byte-compared from the private
    side, advisory rather than ruleset-required. Do not edit the vendored copy
    here.
- **Never put a `close` / `fix` / `resolve` verb immediately before `#N`** in a
  commit message or PR body unless you mean it - including inside backticks, and
  including in a sentence warning against it. Only *adjacency* fires, so "part of
  #N" and "refs #N" are safe.
  - Guarded by `scripts/check_closing_keywords.py`, as a `commit-msg` hook and
    again in CI. **Enable the hook per clone - it does not install itself:**
    `git config core.hooksPath .githooks`
  - Check a draft before pushing: `python scripts/check_closing_keywords.py <file>`
- `scripts/check_closing_keywords.py` is a **vendored copy**, present so the
  hook works offline. CI diffs it against its source and fails on drift. **Never
  edit it here.**

## This repository is ASCII

**No em-dashes. No decorative emoji. Anywhere in tracked files.** Guarded by
`tests/test_ascii_only.py`, which runs in the control step and checks every file
`git ls-files` reports, so it holds for files nobody has written yet.

Two reasons, and they fail differently:

- **Encoding, observed rather than predicted.** The package summary once carried
  an em-dash. The metadata was valid UTF-8 and PyPI's web page rendered it, but
  `pip show` on a Windows console at cp1252 printed a replacement character.
  Metadata, exception messages and CLI output are read in terminals whose
  encoding nobody controls.
- **Register.** This repository is public. Em-dashes and severity emoji are a
  recognisable machine-written signature, and a package asking to be adopted
  should not read like one.

The private repositories in this estate keep their emoji taxonomy, deliberately.
A red circle meaning "this will bite you" is real signal for a reader who knows
the convention, and that convention does not travel to strangers. **The rule is
scoped to what is published, not to how the estate writes.**

Use `-` for an em-dash, or restructure: a colon, a comma, or parentheses usually
say it better. Use `=>` for an arrow and `...` for an ellipsis.

**One exemption, and it is not stylistic.** `scripts/check_verification_section.py`
  is a vendored copy compared **byte-for-byte** against `workbench` by CI.
  Reformatting it to satisfy this rule trades a passing test for a failing
  pipeline. The guard skips exactly that path and says why. The closing-keyword
  guard and its self-test shared the exemption until 2026-09-04, when their
  source was scrubbed; they are held to the rule now, so a non-ASCII byte
  arriving in a re-vendor of either is a defect at the source, and this test
  is the first to see it.

## Conventions

- Line endings are LF everywhere, enforced by `.gitattributes`.
- Every source file carries `# Copyright 2026 David Anaya` and
  `# SPDX-License-Identifier: Apache-2.0`.
- Markdown is linted in CI with a shared config. Two rules are off deliberately:
  `MD013` (line length) and `MD041` (first line must be a top-level heading) -
  `MD041` because the GitHub templates under `.github/` correctly do not start
  with an H1.
  - **`MD024` collided with a changelog until 2026-08-27, when the estate
    default paid it at the source.** `siblings_only` is now set in the shared
    config and in this vendored copy, so a second release section carrying
    `### Added` lints clean while the same heading twice under ONE parent
    still fires. The fix deliberately did not go through a local root
    `.markdownlint.json`: a local file **outranks** the shared one entirely,
    so it would have had to restate `MD013` and `MD041` too - two copies of a
    decision, which is why this sat as a known cost instead. Historical
    changelog sections keep their bold lead-ins (history does not change);
    new entries may use real sub-headings again.
- **Never put a number in a document that something else can change.** A test
  count, an export count, a timing - cite the command instead.
