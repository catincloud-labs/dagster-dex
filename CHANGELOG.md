# Changelog

What changed between releases, and what it costs a consumer to move.

This file starts at `0.3.0` and describes the two releases before it from the
git history rather than from notes nobody wrote at the time. `0.1.0` and `0.2.0`
shipped without one, which is why their entries are shorter than they deserve:
what is here was recovered, and a recovered entry cannot say what the author was
thinking.

**The seam is alpha and may still move.** Entries name breaking changes
explicitly, because that is the reason a consumer opens this file. Pin the minor
if you depend on the contract.

## 0.6.0 - unreleased

The engine floor moves to the release that closed the grain axis's own blind
spot, and the whole-loop example gains the two legs that demonstrate what it
shipped. The seam did not move; the floor did, which is why this is a minor
and not a patch (the same reasoning as 0.5.0, one release later).

**Changed.**

- **The `[dex]` extra is `~=1.8`, from `~=1.7`.** dex-core 1.8.0 shipped the
  fix for exmergo/dex#337 -- our filing: a reconcile against a composite-grain
  declaration now declines with the combination named, where it silently
  discarded the edit before -- and `maintain grain` now verifies grains the
  project *declares* (`declared_grain_not_unique`), reading exactly the
  `declared_composite_keys` this package has supplied since 0.1.0 -- a field
  the engine read for nothing until now. The old range admitted 1.8.0 already;
  the floor bump makes the demonstration below honest, per the coherence
  guard's minor-alignment rule.
- **The tested pin is 1.8.0** at every site the coherence guard scans.

**Added.**

- **Whole-loop legs 13 and 14** (`examples/walk_the_whole_loop.py`), the first
  demonstrations of 1.8.0's arrivals against a real warehouse. Leg 13: a
  declared composite grain the data violates FIRES
  (`declared_grain_not_unique`, no baseline needed) while one the data
  satisfies is SILENT in the same call -- and the composite-wins-over-single
  authoring conflict is read off `ProjectDefinitions.notes`, where this format
  discloses it. Leg 14: `--infer-by-overlap` proposes a join between columns
  no name connects, and a column that is only a composite-grain member --
  equally contained in the same parent -- is NOT proposed. Both legs were run
  red first against 1.7.0 (leg 13 fails with zero declared findings there),
  so they demonstrably test the new engine rather than the harness. The
  reference tree carried no composite grain at all before this: the composite
  case lived only in the conformance builder, which is a fixture, not a
  demonstration.

**Cost to a consumer.** None at the seam. **The engine floor rises to 1.8.0**:
a consumer on 1.7.x stays on 0.5.0, which is exactly as tested; one already on
1.8.0 loses nothing and gains a range whose floor matches what was verified.
That floor is the breaking half and the reason for the minor.

## 0.5.0 - 2026-08-25

The range moves to the release that fixed our contract gap, and the strongest
of its new assertions is given the oracle it asks for. The seam did not move;
the engine floor did, which is why this is a minor and not a patch.

**Changed.**

- **The `[dex]` extra is `~=1.7`, from `~=1.6.4`.** dex-core 1.7.0 shipped
  the fix for exmergo/dex#328 -- the issue this package's write tier prompted --
  in exmergo/dex#336: `load()` declared on `PlacingProject`,
  six mutants from that report now failing in the shipped conformance suite,
  containment re-checked at apply. `~=1.6.4` meant `==1.6.*` and refused the
  resolver that release; the whole suite passes against it with
  `DEX_UPSTREAM_CONTRACT_REQUIRED=1` (zero contract skips), so the range was
  the only thing saying otherwise. Still a compatible-release range, per the
  *two pins* rule -- and `~=1.7`, not `~=1.6`: the latter would publish a floor
  of 1.6.0, three releases below the `PlacingProject` this write tier needs,
  so the range resolver would test a floor the package never claimed.
- **The tested pin is 1.7.0** at every site the coherence guard scans.

**Added.**

- **`a_clean_edit` on the write-tier contract class.** Upstream's optional
  hook. Without it `test_a_refused_apply_leaves_every_target_alone` checks what
  `write_edits` *reported*; with it the clean target is read directly, so a
  writer that lands half a mixed edit set while reporting nothing written is
  caught by the shipped contract rather than only by this repository's own
  six-leg driver. A create inside the surface, pinned to absence.

**Cost to a consumer.** None at the seam. **The engine floor rises to 1.7.0**:
a consumer on 1.6.x stays on 0.4.0, which is exactly as tested; one on 1.7.0
can now install `dagster-dex[dex]` at all. That floor is the breaking half and
the reason for the minor.

## 0.4.0 - 2026-08-18

The write tier becomes reachable over the artifact transport, which is the
deployment shape that had it and could not use it.

**Added.**

- **`declarations:` is admitted beside `artifact:`, and reaches tier 3.** A host
  on the artifact transport could not reach the write tier at all: `artifact:`
  returned a tier-2 project, and the four options an artifact answers for itself
  were refused beside it - so the two were mutually exclusive, and the transport
  exists precisely for hosts that cannot afford the live-graph path. One of those
  four is now admitted. `semantics:`, `sources:` and `name:` still are not.
- **`EditableDexProject` takes `extra_notes`**, appended by `notes()`. It carries
  disclosures about how a project was assembled, which the declarations cannot:
  `parse_declarations` never sees the text that lost, so it has no way to mention
  it.

**Changed.**

- **A `declarations:` directory named beside an `artifact:` SUPERSEDES the
  declaration text the artifact carries**, and the supersession is reported
  through `notes()`. The reading that would have been preferable - the artifact
  still declares, the directory only names a place - cannot be built: an artifact
  keys declarations by a bare stem, a bare stem is inside no editing surface, and
  an edit view built from those keys is empty, so every apply becomes a conflict
  on a file that plainly exists. The directory has to be read, which makes it the
  declarations. Nothing the artifact was protecting is lost - it exists to avoid
  importing a code location, and reading YAML needs no import.
- **Not breaking for any working configuration.** `artifact:` with
  `declarations:` raised a `ValueError` on every released version, so no
  deployment's behaviour moves.

**Fixed.**

- **The test guarding the refused-option set could not discriminate.** It matched
  the option's name against the whole refusal sentence, which contains the
  literal words "declarations" and "name" whichever option fired - so every arm
  passed on prose, and it stayed green for `declarations` on an unrelated error
  after the option was admitted. It now matches the phrase that names the option,
  and the set is pinned from outside instead of hand-copied into a parametrize.

**Verified.**

- `scripts/drive_the_write_path_against_the_wheel.py` runs the whole round trip a
  second time over the artifact transport - reconcile, plan, apply, and the
  written test read back as a declared key **with no artifact regenerated** -
  then requires the apply to refuse over a human's edit on that route too.
- **Calibrated by mutation, one at a time, rather than observed to pass.** Six
  defects were introduced into the finished implementation and each had to turn a
  named leg red; the table is in the pull request. One did not land where it was
  predicted to, and that is recorded on the leg rather than tidied away: keying
  the edit view by bare stem fires leg 10, not leg 11, because reconcile merges
  into the text the view hands it and an empty view yields no edit at all. Leg
  11's pin assertion is a backstop no mutation reaches.
- The artifact-built shape now reaches dex-core's own `EditableProjectContract`
  and `PlacingProjectContract`. It reached none of the three contract classes
  before: they build from in-memory text or from `assets:`, and the completeness
  gate counts contracts rather than shapes, so the hole was invisible to it.

**Known limits.**

- **This makes tier 3 reachable, not reached.** Nothing in production uses it
  yet: a deployment on the artifact transport has to mount its declarations
  directory where the reader can see it, which is a change on the deployment's
  side. "Shipped" and "exercised" are still different claims.

## 0.3.0 - 2026-08-18

The write tier. `maintain reconcile` can now propose an edit to a project in this
format, `transform apply` can write it, and a human's edit during review is
refused rather than overwritten.

### Added

- **`EditableDagsterProject`**, reaching tier 3 of this package's own seam. It
  writes into the hand-authored declaration YAML - never into the models, which
  are a reduction of a running asset graph and would be regenerated away.
- **`EditableDexProject`**, translating that onto dex-core's write tier and
  answering `PlacingProject`: `edit_path` places a `SCHEMA_YML` edit and declines
  every other kind, and `editing_surface` declares the region an edit may land
  in.
- **`ProposedEdit`, `EditOutcome`, `EditConflict`, `ProjectFile`,
  `ProjectFileView`** in `dagster_dex.protocol` - the vocabulary of the write
  path. `ProposedEdit`, `EditOutcome` and `EditableDagsterProject` are also
  importable from `dagster_dex` directly, because a caller names those to make a
  call. `EditConflict`, `ProjectFile` and `ProjectFileView` stay module-scoped: a
  caller receives them inside an outcome or a view rather than constructing them,
  and exporting a type with no consumer is a promise made for nothing.
- **`EditableProjectContract`** in `dagster_dex.conformance`, so a third format
  implementing this seam is held to the behaviour claimed here. It runs with
  dex-core uninstalled.
- **`ExternalSource.declared_in` is now populated** for a source read out of a
  directory, which means `SourceTable.path` finally carries the provenance an
  analyst sees beside a `dangling_source` finding. The field existed since
  sources landed and nothing ever assigned it.
- `tests/test_documented_commands.py`, refusing a documented command that is
  elided, unrunnable, names a missing script, or would build a `.venv`.

### Changed

- **BREAKING, on this package's own seam: `propose_edits` narrows** from
  `(edits: object) -> object` to
  `(edits: Sequence[ProposedEdit], *, confirmed: bool = False) -> EditOutcome`.
  Nothing implemented the old signature - it was deliberately vague while the
  tier was believed unreachable - so this breaks no working code, and it is
  called out because it is a published protocol. Taken now rather than carried,
  while the suite has no outside implementers.
- **BREAKING for a caller reading `notes`: a declaration read from a directory is
  keyed `<directory>/<file>`** rather than by the file's bare stem. The keys
  appear in `ProjectDeclarations.notes` and are now what `edit_path` returns, so
  a bare stem could name no honest region of the project's editing surface. Text
  passed in memory, and every artifact, are unaffected: `parse_source_declarations`
  takes the reading model from the key's stem, which is identical for a bare name.
- **Which tier a project reaches now depends on how it was built.** A live graph
  with a `declarations:` directory reaches 3; a project built from `artifact:`,
  or from a graph with no declarations directory, stays at 2. It cannot be
  otherwise: both dex-core protocols are `runtime_checkable`, so a `write_edits`
  on the shared class would have every instance claim the tier and then refuse at
  call time.

### Verified

- The core suite is green on **3.10, 3.11, 3.12 and 3.13**.
- The full suite, dex-core's shipped project contract, and the end-to-end write
  path are green against **dex-core 1.6.4, 1.6.5 and 1.6.6** - the whole range
  the `[dex]` extra admits, rather than only the version CI pins.
- `scripts/drive_the_write_path_against_the_wheel.py` drives a reconcile proposal
  through plan, apply and back out to `definitions()` against the built wheel on
  every pull request, then requires the next apply to refuse over a human's edit.

### Known limits

- **Placement presumes one model per declaration file.** Reconcile reads the
  model name from the placed key's stem, so a file declaring several models gets
  a warning and no edit rather than a guess.
- **`edit_path` takes the warehouse table**, not a model name in this format's
  vocabulary. There is no table-to-relation mapping here to translate one into
  the other, so a declaration file not named after the table it declares is not
  found.
- **The write is all-or-nothing by checking every target before writing any**,
  not by a transaction. A failure part way through the writing leaves some files
  changed. What it rules out is a conflict on one target while the others are
  written anyway.

## 0.2.0 - 2026-08-15

Reconstructed from the git history; this release shipped without notes.

- **Added `dagster_dex.artifact.dump`**, an atomic writer for a reduced project,
  so the side that has the asset graph can write one down and a side with no
  orchestrator can serve it. `artifact:` became a way to name a project in
  `.dex/config.yml`, beside `assets:`.
- Added `examples/reduce_asset_graph.py`, executed by CI - the one runnable
  demonstration had been a `python -c` blob inside YAML.
- Added `scripts/drive_dex_against_the_wheel.py`, which reads a project through
  the built distribution rather than the working tree.
- The tested engine pin moved forward a patch; the published `[dex]` extra stayed
  a compatible-release range, which is the difference that matters to a consumer.
  The exact version CI tested against is deliberately not restated here - see the
  note at the foot of this file.

## 0.1.0 - 2026-08-15

The first publication. Reconstructed from the git history.

- The neutral project model, the tiered seam, the Dagster reduction, the
  importable conformance contract, and the dex-core boundary.
- Registered against the `exmergo_dex_core.projects` entry-point group.
  **Inert from `0.1.0` until dex-core 1.6.0 began resolving that group**, at
  which point it failed on first contact: it named the class, and dex-core's
  factory calls what it resolves with a `ProjectContext`. Fixed in `0.2.0`, and
  the reason this project's rules say a declared-but-unresolved extension point
  is not evidence that registration works.

## Why this file names no engine version

`tests/test_pin_coherence.py` holds every `exmergo-dex-core==` pin in this
repository to one version, and it scans every tracked file. A changelog entry is
history and must not change; that guard exists precisely to make an exact pin
change on every bump. The two rules disagree, and a historical entry restating a
version is the one that loses: it would either go stale, or force a future bump
to edit a record of the past.

So entries describe what moved and leave the version to the places that state it
as a live fact - `pyproject.toml` for the published range, the workflows and
`AGENTS.md` for the tested pin. The measured range under 0.3.0 above is a
different kind of claim: it names the versions a test was actually run against on
a date, which is a result rather than a pin, and no guard has to keep it current.
