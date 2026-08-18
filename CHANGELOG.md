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

## 0.3.0 (unreleased)

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
