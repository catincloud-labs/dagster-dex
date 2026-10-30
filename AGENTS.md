# AGENTS.md

Operating rules for AI coding agents, and for humans skimming for the sharp edges.

## What this is

One Python distribution: `dagster-dex`. A Dagster asset graph reduced to a neutral
project model, and bridged onto the `dex` engine's project seam through an entry
point. Stable from 1.0.0 - the seam follows semantic versioning, and a breaking
change to it waits for 2.0 (README, *Status*).

## The rule that matters most here

**The engine coupling is one file, and a CI step exists to prove it.**

`src/dagster_dex/dex.py` is the only module permitted to import
`exmergo_dex_core`. Everything else - the model, the protocol, the parser, and the
conformance suite - runs with dex-core **uninstalled**.

The engine-free control (the `python-floor` job in `checks.yml`, and the first
test step of `publish.yml`'s `build`) runs the suite with the engine absent.
**That step is a control, not a speed split.** Add an `exmergo_dex_core` import to
any other module and it goes red at collection. Merging it into the step below it
would delete the only thing checking the package's central claim.

`tests/test_dex_bridge.py` additionally walks `dex.py`'s AST to assert it imports
**public API only**, rather than trusting it. How both checks fail, and what the
AST check does not read:
[docs/design/verification.md, *The engine-absent control*](docs/design/verification.md#the-engine-absent-control).

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
  table name is used as the file stem rather than guessed through one. The stem
  is matched against the declarations **without regard to case** (#141), since
  Snowflake reports `DIM_DATE` for a `dim_date.yml`, under `.yml` and `.yaml`
  alike. Two files the table could name, differing by case or by suffix, make
  `SCHEMA_YML` `None` for that table: neither is evidence for one over the
  other.
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
      the layer, and the guard has been shown to fire
      ([docs/design/verification.md, *Notes asserted on the layer*](docs/design/verification.md#notes-asserted-on-the-layer)).
      A new test would be a second copy of a working one.
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

Plus the following checks, which are not pytest. They do not share a CI job:
the type check, the two `examples/` commands and the README excerpt check that
reads the second one's output run in `suite`, and the two
power-of-ten commands run in `power of ten` (both are the literal `name:` of a
job in `checks.yml`). Until 2026-09-07 this line read "Plus two checks that are
not pytest, and both run in the same CI job", while the block beneath it held
five commands across two jobs - both halves were false (#83).

```bash
# the py.typed claim, actually checked -- at the FLOOR, not the newest interpreter.
# The type checker's version is read from the manifest Dependabot moves, never
# typed here (ADR-0042 in constellation, rule 10: a pin with no mover is frozen)
uv run --no-project --with-editable . \
  --with-requirements scripts/power_of_ten_requirements.txt --with types-PyYAML \
  python -m mypy

# the coding standard, read at class A over `src` -- strict typing, ceiling 10 --
# by the vendored checker; its self-test first, then the check. Same manifest.
uv run --no-project --python 3.10 \
  --with-requirements scripts/power_of_ten_requirements.txt \
  python scripts/test_check_power_of_ten.py
uv run --no-project --python 3.10 \
  --with-requirements scripts/power_of_ten_requirements.txt \
  python scripts/check_power_of_ten.py --tree . --class-a src

# the reduction against REAL dagster objects -- no other step installs it
uv run --no-project --with-editable . --with 'dagster>=1.13' \
  python examples/reduce_asset_graph.py

# the WHOLE loop against a real (DuckDB) warehouse -- the only command that
# installs the orchestrator, the engine and a warehouse at once -- and the
# README's quote of its output, held to what this run printed
uv run --no-project --with-editable . --with 'dagster>=1.13' \
  --with exmergo-dex-core==1.8.0 --with sqlglot==30.13.0 --with duckdb \
  python examples/walk_the_whole_loop.py | tee whole-loop.txt
python scripts/check_readme_excerpt.py whole-loop.txt
```

The second line used to end `python -c "..."`, with the ellipsis standing in for
a script. **That is a command that runs, exits 0, and checks nothing** -
`...` is a bare `Ellipsis`, so Python evaluates it and succeeds. A reader
copying it saw the same exit code CI produces and had installed an orchestrator
to evaluate a constant. => **An elided command is worse than a missing one: it
returns the answer you were looking for.** Every command in this file is
runnable verbatim now, which was checked by running all of them. What
`tests/test_documented_commands.py` holds every documented command to is in
[docs/design/verification.md, *Documented commands*](docs/design/verification.md#documented-commands).

**The Dagster step exists because everything else uses fakes.** The suite must
run without an orchestrator, so the `examples/` steps in `suite` are the only
checks against real Dagster objects. The `[dagster]` extra was declared and installed
by nothing until that step existed.

**The README quotes the whole loop's output, and CI holds the quote to the
run.** Change a leg's printed line and the README excerpt moves in the same
change. How the quote is held, and where the checker is shown to go red:
[docs/design/verification.md, *The README's output excerpt*](docs/design/verification.md#the-readmes-output-excerpt).

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

**Keep both, though the conformance contracts now catch every planted defect
on record.** At both ends of the published range, dex-core's `EditableProjectContract` and
`PlacingProjectContract` fail on each defect planted so far, the ones that got
past them at 1.6.6 included. The drivers' claim is the route a host takes, the
built wheel, the entry-point scan and dex's own reconcile, plan and apply,
which no contract takes. The measurement, the engine each half of it ran
against, and what each driver's legs assert:
[docs/design/verification.md, *What the shipped contracts catch, and what the drivers add*](docs/design/verification.md#what-the-shipped-contracts-catch-and-what-the-drivers-add).

Run either by hand:

```bash
uv run --no-project --with-editable . \
  --with exmergo-dex-core==1.8.0 --with sqlglot==30.13.0 \
  python scripts/drive_the_write_path_against_the_wheel.py
```

**The write-path driver bails after leg 1 when the tier is not reached**, on
purpose: do not remove the bail. It runs the round trip twice, legs 1-6 on the
live-graph path and legs 7-15 on the artifact transport, and the second half is
not a copy to be deleted.

**The bail bounds what calibration can prove.** A mutation can only be shown to
fire the earliest leg it breaks, so scope a calibration mutation to one route,
or it proves nothing about the other. Leg 11's pin assertion is a backstop no
mutation reaches. => **An assertion written for a defect is not evidence the
defect is caught there.** Why, leg by leg:
[docs/design/verification.md, *What the drivers add*](docs/design/verification.md#what-the-drivers-add).

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
desk, wrong in CI, where an unrun file and a passing file look identical. The
guards beside it, for a skipped criterion and for a contract nobody declined:
[docs/design/verification.md, *When upstream's contract is missing, skipped or grown*](docs/design/verification.md#when-upstreams-contract-is-missing-skipped-or-grown).

**These three used to be described as "matching CI exactly", and since
2026-08-18 they do not.** CI runs engine axes these three commands do not
([docs/design/verification.md, *The engine axes*](docs/design/verification.md#the-engine-axes)).
The three above are still the right thing to run at a desk - they are the
fastest path to the same failures - but a green local run is now a weaker claim
than a green pipeline, which is the opposite of what the old sentence implied.

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
What each job proves, and how it fails:
[docs/design/verification.md, *The engine axes*](docs/design/verification.md#the-engine-axes).

- **`python-floor`** runs the engine-free control on 3.10, 3.11, 3.12 and 3.13.
  The list is written out on purpose: `>=3.10` is open-ended, so there is nothing
  to resolve, and adding an interpreter is a decision about what is claimed.
- **`engine-ends`** runs the boundary suite and the upstream contract at the
  floor and the ceiling of the published range, **resolved rather than listed**
  by `scripts/resolve_engine_range.py`. Never replace it with a hand-written
  list: that is a registry making a claim about a moving set, and when upstream
  publishes a patch the promise widens, the matrix does not, and nothing goes
  red.
- **`suite`** keeps the exactly-pinned steps. It is not folded into
  `engine-ends`, because the exact pin and the published range are two different
  claims - see the two-pins section below. Folding them would delete one.
  It also keeps the literal `exmergo-dex-core==` strings where
  `test_pin_coherence.py` can see them; a `${{ matrix.version }}` expression is
  not a pin, so templating those steps would have shrunk that guard's corpus by
  two sites with no count changing to show it.

- **`upstream main`** (its own file, `.github/workflows/upstream-main.yml`) runs
  the boundary file and the upstream contract against `exmergo/dex` **`main`**,
  daily, **red-only**: green is reported nowhere, and red opens one issue here
  labelled `upstream:dex`. It lives outside `checks.yml` so a moving `main` can
  never redden a pull request; do not move it in. Its de-duplication key, its
  fail-closed arm and its two forced reds:
  [docs/design/verification.md, *The unreleased head*](docs/design/verification.md#the-unreleased-head-red-only-and-it-files).
  Reproduce the axis at a desk:

  ```bash
  DEX_UPSTREAM_CONTRACT_REQUIRED=1 uv run --no-project --with-editable . \
    --with pytest==8.4.1 --with sqlglot==30.13.0 \
    --with 'exmergo-dex-core @ git+https://github.com/exmergo/dex@main#subdirectory=packages/dex-core' \
    python -m pytest tests/test_upstream_contract.py tests/test_dex_bridge.py -p no:cacheprovider
  ```

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
  - **It is the demonstrated pin, and one of three engine axes, not the only
    version the package runs against.** `engine-ends` runs the boundary suite
    and the upstream contract at the resolved floor and ceiling of the published
    range on every push, and `upstream main` runs them daily against the
    unreleased head. A grep for version literals sees only this axis, because
    the other two hold no literal by design (a matrix expression and a git URL).
    Reading such a grep as the whole matrix is how #89 came to say the package
    was tested nowhere above this version, on a day the ceiling cell had already
    caught 1.11.0 (#86). The pin moves when the floor moves, and the floor moves
    when the package needs something the newer engine ships.

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
- **A `v*` tag is signed by the owner (`git tag -s`), and the first step after
  checkout in `build` refuses one that does not verify against
  `.github/allowed_signers`, or whose own name is not the ref's** (#112).
  Commits are not signed. Tags up to `v0.6.2` stay unsigned because a
  signature added now would vouch after the fact. **The reason #112 first
  gave is dead, so do not re-derive it:** re-cutting would NOT change what
  their attestations name, which is the ref and the commit, never the tag
  object (read off the 0.6.2 wheel's certificate). Two things in that step
  look like gaps and are not, so do not "fix" them; the step's comment gives the reasons. It has
  **no `git fetch` of the tag**, because checkout already delivers the signed
  tag object bound to `github.sha` and a forced re-fetch would undo that. And
  the file is **not the trust anchor**, because it comes from the tagged
  commit just as the workflow does; a stranger anchors on the account's key on
  GitHub (README, *Verifying a release*). A key rotation edits that file in
  the same change, the way its header says.
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

## Verification method

A control observed only to pass has not been shown to be a control. Four
moves stand behind that rule, each paid for in this organisation:

- **Calibrate on both arms first.** Before reading an instrument's answer about
  the subject, show it report the defect on a case you built to have it, and
  report clean on a case you built not to, in the shape of the defect it is
  for. A refusal on a day when nothing could have passed is not a calibration.
- **A count is not an attribution.** Before a number names a cause, map it to
  the identities it counts, and ask what else produces the same reading. The
  count that matches the prediction is the one least likely to be checked.
- **Independence lives in the premise, not the author.** A second check that
  shares the first one's assumption agrees with it for the same reason. Vary
  the method: parse a different way, or enumerate a superset and subtract.
- **Empty and blind are the same input.** An empty list, a zero or a missing
  line is also what an unauthorised, filtered or never-run read returns. Run a
  positive control, a query that must return something, before reading
  absence as a fact.

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
  - Passing the guard is not the convention. The owner reads the title, so it
    is clear and concise, not a thesis: it says what was done to what, in plain
    words and the diff's own nouns, with no contrast clause, no *no X*
    phrasing, no identifier the change itself introduces in the lead, and no
    imperative the owner could take as addressed to them. A title about an
    agent rule names the artifact and the actor. A `fix:` title names the
    process that misbehaves today, its actor, and what it does after the
    change. An `argument:` title is *whether X*, X being the decision in the
    governing document's words. A filing in a repository outside the
    organisation keeps this form as closely as that repository allows. A pull
    request is retitled rather than a pushed commit amended. Ruled by the owner
    from 2026-10-08 to 2026-10-10. In practice titles run about 70 characters,
    and measuring the length before creating one catches a title over the cap.
- **A pull request carries exactly one `deploy:` label.** It says what merging
  does to a box, which is a fact about the change. Merging deploys nothing
  here: publication runs on a `v*` tag (`publish.yml`), never on a merge, so
  `deploy:none` is the usual value, and a pull request that owes a tag after
  it merges is `deploy:by-hand`.
  None is unclassified and reads red; two is two claims about one merge and
  reads red. The `review:` clock is applied by hand and read by no guard.
  - Guarded by `scripts/check_deploy_label.py` in the `pr-hygiene` job, its
    self-test first. It is a **vendored copy**, byte-compared from the private
    side like the checks above. **Never edit it here.** Run it by hand with
    `python scripts/check_deploy_label.py --labels-json '["deploy:none"]'`.
  - The remedy for a red is to apply the label: the job listens for `labeled`
    and `unlabeled`, so it re-runs by itself. The red run stays on the commit
    beside the green one; read the latest run of the job.
  - Advisory, not ruleset-required: count the required contexts with
    `gh api repos/catincloud-labs/dagster-dex/rules/branches/main` before
    assuming a red here blocks a merge.
  - Dependabot is exempt by author, and the exemption prints its closing
    condition at every firing: a `labels:` key in `.github/dependabot.yml`.
  - **The template's label line is the estate's shared line with its link
    sentence cut, and nothing else changed.** The shared line is identical in
    every estate template by ruling and links a private issue, so here, the
    one public repository that carries a template, it ends after its first
    sentence (#108). Ruled 2026-10-03 on the private side (constellation #214,
    comment 5973354633), as an exception to "the identical line yields to
    nobody". The line beneath it is this
    repository's own: the two values above, and what a contributor from a fork
    should expect. Do not re-add the link, and do not merge the two lines: the
    first stays a byte-identical prefix of the shared one.
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
- **The estate's coding standard is read here at class A** - ADR-0042 in
  `catincloud-labs/constellation`: `src` is class A because a failure there
  reaches a stranger, the consumer of a published wheel. Cyclomatic ceiling 10,
  strict typing, no recursion, no `while True`, no `global`, no blind `except`.
  `tests/`, `scripts/` and `examples/` are class C at ceiling 15. The checker
  is vendored the way the two guards above are (public repository, private
  action): `scripts/check_power_of_ten.py`, `scripts/test_check_power_of_ten.py`
  and `scripts/power_of_ten_requirements.txt` are byte-compared against
  `workbench` from the private side, and the `power of ten` job in `checks.yml`
  runs them, advisory rather than ruleset-required. **Never edit them here.**
  The manifest is the one place `ruff` and `mypy` are pinned, for the suite's
  type-check step too, and `.github/dependabot.yml`'s `pip` entry moves it.
  - The check is the **one reader of suppressions**: a deviation is a `noqa`
    or a `type: ignore[code]` that names the rule with its reason on the same
    line; one that is unused or gives no reason is red, and under strict typing
    an unused `type: ignore` is red too. No `predates ADR-0042` marker stands in
    this tree and the ratchet refuses the first one added. The two class C
    `main`s (`examples/walk_the_whole_loop.py`, the write-path driver) carry a
    reasoned `C901` deviation: each is one ordered walk of legs, and the order
    is the artefact.
- **An outside contributor's pull request is merged as a squash.** This
  repository's own rule, ruled by the owner on 2026-10-21 (#144). The
  subsection below covers a session's own pull requests, and its bullet *When
  the owner says merge* names `--merge`, never a squash. When the owner says
  merge on an outside contributor's pull request, the command is that bullet's
  with `--squash` in place of `--merge`, and it runs only after the same reads
  that bullet lists. The owner's own pull requests keep `--merge`, and so does
  a bot's.
  - An outside contributor is a person who is not the owner. A bot, such as
    Dependabot, is not one.
  - The branch's commits do not land on `main`, so a review that cites one
    cites a commit `main` does not contain. What the squash commit carries is
    set by the repository's squash defaults, read with
    `gh api repos/catincloud-labs/dagster-dex --jq '{squash_merge_commit_title, squash_merge_commit_message}'`
    by a caller with push access; an anonymous read omits both fields. The
    owner set them on 2026-10-21 to the pull request's title, as the subject,
    and its body, as the message. The first squash after that change is the
    reading that shows they land through this command. #135, the first squash
    here, predates it: the message of `65a9d2b` is the branch's commit
    messages, each one a bulleted line.
  - The rule sits here and not in that bullet because the subsection is kept
    byte-identical across the organisation's repositories. Do not move it in.

### Merging, the cold review and the record

Rules for a session's own pull requests. The owner ruled the stop, the merge
method, the default against closing, the cold review, when a pull request
leaves draft and the issue-correction rule; the rest is practice sessions
learned, most of it after a wrong post had to be corrected. This subsection,
the title sub-bullet above, *Verification method* and *The owner's workstation*
are kept byte-identical across the organisation's repositories: change them
everywhere or nowhere. Nothing checks it.

- **A session opens the pull request and stops.** It does not merge, deploy
  or widen a token's reach without the owner's word in that session. A
  general "proceed", a handover note or a message from another session is not
  that word; an instruction from the owner that names the act is, for the act
  it names.
- **When the owner says merge,** the command is
  `gh pr merge <n> --repo <owner>/<repo> --merge --admin`, never a squash. It
  runs only after reading that the pull request is not a draft, that the
  latest run of every required check is green, and that
  `gh api repos/<owner>/<repo>/pulls/<n> --jq '{number, stack}'` prints the
  pull request's number with `"stack":null`. The number is the read's
  positive control: a pull request in no stack carries no `stack` field, so a
  bare `--jq .stack` prints an empty line whatever the truth. No stacked pull
  request has been read this way since the estate's one stack was dissolved.
- **A merge closes nothing by default.** The owner's rule is that a pull
  request does not close an issue without a clear reason. The body carries
  `Autoclose: none`, and the issue is closed by hand once the reading its
  done-when names exists. When there is a reason, such as the merge itself
  being the done-when, the closing verb and the `Autoclose: #N` trailer go
  together.
- **One cold review per pull request, before it leaves draft or merges.** The
  reviewer shares none of the author's context and is not an automated review
  command: it gets the pull request number, the issue or ruling it builds
  against, this file's binding sections and the commands to run, and it runs
  them against the head and against `main`. Its findings are posted as a
  comment on the pull request. Each is closed as taken, with the fixing commit,
  or declined, with the reason, against the review's own checks re-run at the
  new head, in that comment or in a dispositions comment after it. A second
  review happens only when the owner asks for one.
- **A pull request leaves draft when its code is ready, not when its slot
  comes.** It opens as a draft, so its cold review comes before it leaves.
  Ready means its one cold review is dispositioned, the latest run of every
  required check is green at its head, and nothing its body lists as owed
  before it leaves draft is open. The session that built it takes it out of
  draft once that holds, and says so on the pull request. `draft` means the
  code is not ready; the merge's slot lives on its day card and its row on the
  [estate board](https://github.com/orgs/catincloud-labs/projects/1), never in
  the draft flag. Leaving draft removes the last lock GitHub enforces against
  an `--admin` merge of a green pull request, so after it the guard is the
  owner's word to merge and the permission layer.
- **A reference to another repository's issue is qualified:** `owner/repo#N`
  or a full link. A bare `#N` links this repository's number, in a comment as
  in a body.
- **A claim a session posted on an issue, wrong when it was posted, is
  corrected by a follow-up comment** that cites the comment it corrects, not by
  editing it. A pull request body may be corrected in place, with a visible
  dated note saying what changed.
- **A ruling given in a session becomes a record once it is a comment on the
  issue it decides,** carrying the owner's words and posted before the pull
  request that cites it.
- **Read the thread before posting to it.** Re-fetch an issue's comments
  immediately before posting a proposal, a ruling or a question there, and
  quote a comment you cite, by its id, rather than a summary of it.
- **A return to another repository's issue carries the merge commit and its
  `mergedAt`.**
- **A branch with a pull request is brought up to `main` by merging `main`
  into it,** never by a rebase or a force-push: its body, its review and its
  comments cite its commits.

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

**No exemption, since 2026-09-07.** `scripts/check_verification_section.py` was
  exempt until then: a vendored copy compared **byte-for-byte** against
  `workbench` by CI, so reformatting it here would have traded a passing test
  for a failing pipeline. The closing-keyword guard and its self-test were
  exempt on the same argument until 2026-09-04. Each ended when its source was
  scrubbed to ASCII and re-vendored (#77, then #85), and the skip set in the
  test left with the last entry rather than staying empty: a byte copy is fixed
  at its source, so a non-ASCII byte arriving in a re-vendor is a defect at the
  source, and this test is the first to see it. An entry in that set could
  never again be the right fix, which is why there is no set.

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

## The owner's workstation

This repository is authored on the owner's Windows workstation, with Git Bash
and Windows PowerShell 5.1 side by side. Each trap below was read there on
2026-10-12 and has been paid for at least once; re-read one before relying on
it.

- **A command handed to the owner runs in either shell.** One command per
  block; paths as `C:/...`; no `&&`, `||`, `;` chains, `$VAR`, `$(...)`,
  heredocs, `2>/dev/null` or line continuations. A command that needs Git Bash
  says so on the line above it, or comes with its PowerShell twin. A Windows
  command with `/flag` arguments (`schtasks`, `reg`) is marked as PowerShell. A
  handed-over `gh` command names `--repo <owner>/<repo>`, and a handed-over
  `ssh` command reaches one host.
- **Never run `python -`,** which reads its program from standard input. Here
  it can hang until it is killed, with an empty heredoc or `</dev/null` as its
  input, or end silently having done nothing, and a script fed to it is
  decoded as cp1252. A Claude Code hook on the workstation refuses its plain
  spellings, including those with interpreter options before the `-`
  (`python -I -`, `python -X utf8 -`), which hang the same way. It misses
  others, such as one quoted inside another command (`bash -c 'python -'`) or
  one whose `-` is on a continued line. Write a script,
  a commit message or a pull request body to a file and use it by path
  (`python <file>`, `git commit -F <file>`, `gh pr create --body-file <file>`).
  A heredoc through an agent's shell can halve backslashes, so text that holds
  one goes through a file too.
- **Git Bash rewrites path-shaped arguments.** Set `MSYS_NO_PATHCONV=1` on the
  one command that passes a `rev:path`, a `/`-leading pattern or a `/flag`.
  Never export it: it breaks `/c/...` paths for the rest of the shell. A
  rewritten argument fails quietly, so a probe through it can print an empty
  answer that looks real.
- **Git Bash `grep` cannot see a carriage return,** so a CR count from it is
  wrong in either direction. Check line endings with `git ls-files --eol` or a
  byte count in Python, and have Python write LF explicitly: bytes, or
  `newline` set to a line feed.
- **`jq` is not installed** (read 2026-10-13: `jq --version` prints an error
  in either shell, where `python --version` prints a version; `command -v jq`
  is no check in PowerShell, which runs it as `Get-Command -Verb jq` and
  prints nothing whether or not the tool exists). `gh --jq` works
  because it is built into `gh`; everything else filters with `--jq`, `grep` or
  Python.
- **Python's default encoding here is cp1252,** so Python that prints
  non-ASCII runs as `python -X utf8`. A PowerShell 5.1 `Get-Content` and
  `Set-Content` round trip turns LF into CRLF, and mangles UTF-8 once either
  side names an encoding: never round-trip a tracked file through it.
- **An agent's permission layer may refuse an act** (a secret read, an `ssh`, a
  merge, a scheduled task). Do not retry it in another form: hand the owner the
  exact command, one per block, and read the result back after it runs.
