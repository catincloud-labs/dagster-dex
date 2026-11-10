# Dagster to dex: how an asset graph becomes a project dex can read

- **Status:** living
- **Describes:** `src/dagster_dex/project.py`, `src/dagster_dex/declarations.py`,
  `src/dagster_dex/model.py`, `src/dagster_dex/dex.py`,
  `src/dagster_dex/artifact.py`, `src/dagster_dex/protocol.py`,
  `src/dagster_dex/checks.py`
- **Reviewed:** 2026-10-30 at `c4e8231`; the asset-check section written
  2026-11-10 against `993f479`

This page describes how the translation works today. It decides nothing: each
decision it touches is linked where it is made, and a change to one is made
there, not here. The header convention is in [README.md](README.md).

## The translation, in three steps

```mermaid
flowchart LR
    G["Dagster asset definitions"]
    Y["Hand-written YAML: declarations, semantics, sources"]
    A["Artifact JSON, written by artifact.dump"]
    P["DagsterProject: models plus YAML text"]
    D["ProjectDeclarations: the neutral model"]
    PD["dex-core ProjectDefinitions"]
    TL["dex-core TransformLayer"]
    SL["dex-core SemanticLayer"]

    G -->|"step 1, reduce: keys, asset_deps, metadata_by_key"| P
    Y -->|"read as text"| P
    A -->|"artifact.loads"| P
    P -->|"step 2, parse: declarations()"| D
    D -->|"step 3, map: to_project_definitions"| PD
    D -->|"step 3, map: to_transform_layer"| TL
    D -->|"step 3, map: to_semantic_layer"| SL
```

1. **Reduce.** The Dagster objects become plain data: a sorted tuple of
   `dagster_dex.model.ProjectModel`, held by a `dagster_dex.project.DagsterProject`
   beside the declaration YAML as unparsed text.
2. **Parse.** `dagster_dex.project.DagsterProject.declarations` runs three
   parsers over that text, cross-checks what they find against the models, and
   returns one `dagster_dex.model.ProjectDeclarations`: the neutral model.
3. **Map.** `src/dagster_dex/dex.py` maps that value onto the three types
   dex-core's project seam asks for.

Steps 1 and 2 run with neither Dagster nor dex-core installed. Step 3 needs the
`[dex]` extra, and `dex.py` is the only module that imports dex-core
([AGENTS.md, *The rule that matters most here*](../../AGENTS.md#the-rule-that-matters-most-here)).
Why the neutral model exists at all, rather than reusing dex-core's, is the
module docstring of `src/dagster_dex/model.py` and README,
[*Four model decisions worth arguing about*](../../README.md#four-model-decisions-worth-arguing-about).

## Step 1: Dagster to plain data

`dagster_dex.project.DagsterProject.from_asset_graph` hands its definitions to
`dagster_dex.project._reduce_asset_graph`, which reads three attributes of each
one. They are named as a structural protocol,
`dagster_dex.project._AssetDefinition`, so nothing in the package imports
`dagster`; the `[dagster]` extra is a caller's convenience.

| Dagster attribute | What is read | Lands in |
| --- | --- | --- |
| `keys` | the last element of each key's `path` | `ProjectModel.name` |
| `asset_deps[key]` | the last element of each dependency's `path`, sorted | `ProjectModel.depends_on` |
| `metadata_by_key[key]` | the `layer` entry, lowercased, when present | `ProjectModel.layer` |
| `metadata_by_key[key]` | `dagster/table_name`, or `dagster/relation_identifier` when that key is absent, unwrapped and lowercased | `ProjectModel.relation`, or `None` when neither names a table |

The relation is read by key, the way Dagster's own
`TableMetadataSet.extract_normalized_table_name` reads it, because nothing here
imports the orchestrator; `dagster_dex.project._table_name` gives the rule,
and `examples/reduce_asset_graph.py` holds it equal to Dagster's against real
objects. A `relations:` project option then overrides it per model, and a name
there the project does not build is refused (`dagster_dex.project.DagsterProject`).

Nothing else on a definition is read: not its code, partitions, checks or IO
managers. Two consequences:

- **Only the last path element survives**, so a key prefix is dropped. Two
  definitions whose names collide after case folding raise `ValueError`,
  checked against the raw definitions. The reasons for both are in the
  `dagster_dex.project.DagsterProject.from_asset_graph` docstring.
- **A dependency is kept whatever it points at.** Filtering to built models
  happens at step 3, where dex-core's meaning of a ref applies, not here.

## Step 2: the declarations, and the neutral model

An asset graph carries no column names, keys or joins. They come from
hand-written YAML, handed to the project as three mappings of `{key: text}`:

| Constructor argument | Config option | Parser | Yields |
| --- | --- | --- | --- |
| `declaration_sources` | `declarations:` | `dagster_dex.declarations.parse_declarations` | `DeclaredKey`, `DeclaredJoin` |
| `semantic_sources` | `semantics:` | `dagster_dex.declarations.parse_semantics` | `SemanticModel`, `Metric` |
| `source_declarations` | `sources:` | `dagster_dex.declarations.parse_source_declarations` | `ExternalSource` |

The YAML is written in dbt's schema-test vocabulary (`unique`, `not_null`,
`relationships`), and that vocabulary is an input format, not the model:
everything lands in `src/dagster_dex/model.py` types, so changing the input
format touches `src/dagster_dex/declarations.py` alone (its module docstring).
No parser raises on bad input. A file that is not readable YAML becomes a
note and is skipped; one that parses to something other than a mapping is
skipped with no note.

- **Keys.** Read from a directory, a key is `<directory name>/<file name>`.
  Two parsers use it only as a label in notes. `parse_source_declarations`
  reads the key's stem as the model doing the reading, and sets
  `ExternalSource.declared_in` only when the key names a file
  ([AGENTS.md, *Sharp edges*](../../AGENTS.md#sharp-edges)).
- **Semantic columns.** `SemanticField.column` is set only when the field's
  `expr:` is a bare column name; an expression or a missing `expr:` leaves it
  `None`, with a note (the `dagster_dex.declarations._semantic_fields`
  docstring).
- **Sources are declared, never inferred** from the graph
  ([README, *External sources*](../../README.md#external-sources-the-edge-a-graph-cannot-see)).

`declarations()` then cross-checks. A key on, a join from, or a source read by
a model the graph does not build is kept, with a note naming the model. A
join's far side is not checked, because it may name a source (the
`dagster_dex.model.DeclaredJoin` docstring). `freshness` is always
`NOT_APPLICABLE`, because nothing compiled sits between the graph and the
reduction. The result is memoized for the instance's life, which is one command.

## Step 3: the neutral model to dex-core's types

`dagster_dex.dex.DexProject` wraps a project in dex-core's names: `format`
becomes `name`, and `declarations()` becomes `definitions()`, beside
`transform_layer()` and `semantic_layer()`. That is dex-core's tier 2. Why the
names differ is in
[AGENTS.md, *The names in `protocol.py` are OURS*](../../AGENTS.md#the-names-in-protocolpy-are-ours-and-must-not-be-fixed-to-match).

Each channel below is one function. A loss the target type cannot hold is
disclosed in that type's own `notes`, and each table's last column says which
note carries it. That both layers carry their notes, and why the tests assert
on the layer, is in [AGENTS.md, *Sharp edges*](../../AGENTS.md#sharp-edges).

### Explore: `dagster_dex.dex.to_project_definitions`

| Neutral model | `ProjectDefinitions` | Lost | Disclosed by |
| --- | --- | --- | --- |
| `DeclaredKey`, one column | `DeclaredKey`, `unique=True`, `not_null=False` | nothing | |
| `DeclaredKey`, several columns | `DeclaredCompositeKey` | nothing | |
| `DeclaredJoin`, one column a side | `DeclaredForeignKey` | nothing | |
| `DeclaredJoin`, several columns | omitted | the join | a note listing each omitted join |
| `freshness` of `NOT_APPLICABLE` | `manifest_loaded=False`, `manifest_stale=False` | the third state | a note that `False` means not applicable |
| `ProjectModel.relation` | `model_relations`, one entry per model that has one | the models with none | a note naming each model with no relation |
| model names | `built_relation_names`, lowercased | case | |
| each semantic model's `model` | `metric_models` | nothing | |
| no project directory | `project_dir=None` | nothing | |
| `is_empty` | `present`, negated | nothing | |
| `notes` | `notes`, first | nothing | |

`relationship_source` and `semantic_source` are both `"declaration"`.

### Maintain, transform half: `dagster_dex.dex.to_transform_layer`

| Neutral model | `TransformLayer` | Lost | Disclosed by |
| --- | --- | --- | --- |
| no files | `files={}` | file-content drift | a note that file hashes are absent, whenever there are models |
| model names | `models`, sorted | nothing | |
| `depends_on` | `model_refs`, built models only, self-references dropped | every other dependency | a note listing each dependency on neither a built model nor a declared source; one on a declared source is dropped unlisted |
| `ExternalSource` | `SourceTable`: `system` as `source_name`, `schema_name`, `table`, `columns` | nothing | |
| `ExternalSource.declared_in` | `SourceTable.path`, or `None` | a place, for text handed over in memory | none: `None` says it |
| `ExternalSource.read_by` | `model_sources`, each reader to sorted `system.table` identifiers | nothing | |

### Maintain, semantic half: `dagster_dex.dex.to_semantic_layer`

| Neutral model | `SemanticLayer` | Lost | Disclosed by |
| --- | --- | --- | --- |
| `SemanticModel` | `SemanticModelDef`, `path=None`, `model_ref` from `model` | nothing | |
| `definition_sha` | `content_sha256` | nothing | |
| dimensions and measures | `dimensions`, `measures`: name to column | the check, where a column is `None` | a note listing each field with no column |
| a categorical dimension with a column | `categorical_dimensions` | nothing | |
| a categorical dimension with no column | absent from `categorical_dimensions` | the flag | the same note |
| no entities | `entities={}` | entity checks | a note, whenever there are semantic models |
| `Metric.measure` | `MetricDef.input_measures`, `input_metrics=[]` | nothing | |
| `Metric.kind` | no field | the kind | a note listing each kind other than `simple` |

`dagster_dex.dex.DexProject.notes` returns the transform notes and then the
semantic notes in one call, and `dagster_dex.dex.transform_layer_notes` and
`dagster_dex.dex.semantic_layer_notes` stay public for a host that wants them
without building a layer.

## Write-back: the one edit that can land

Which class a configuration gets is decided in
`dagster_dex.dex.project_from_context`: a named `declarations:` directory builds
`dagster_dex.dex.EditableDexProject` over
`dagster_dex.project.EditableDagsterProject`, and anything else builds the
read-only pair. Why it is a class and not a flag, and which cases the tests
pin, are in
[AGENTS.md, *Tier 3 is reached by ONE class*](../../AGENTS.md#tier-3-is-reached-by-one-class-and-the-split-is-the-design)
and [README, *The seam, in three tiers*](../../README.md#the-seam-in-three-tiers).

- **Root.** The declarations directory's parent; every key is relative to it.
- **Surface.** The declarations directory's name. On the graph route a
  `semantics:` or `sources:` directory under the same parent joins it; on the
  artifact route it stands alone. `dagster_dex.project._within` checks a key
  against the surface by path segment, and again at write time.
- **Placement.** `dagster_dex.dex.EditableDexProject.edit_path` answers
  `SCHEMA_YML` and returns `None` for every other kind. Its `model` argument
  is the warehouse table, matched against the stems of the declaration files
  in the view without regard to case, under `.yml` or `.yaml`. One match is
  that file; two or more are `None`; none is `<directory>/<table>.yml` as the
  table spells it. Reconcile reads the model from the placed file's stem, so a
  file declaring several models gets a warning and no edit.

```mermaid
sequenceDiagram
    participant R as dex: maintain reconcile
    participant T as dex: transform apply
    participant E as EditableDexProject
    participant P as EditableDagsterProject
    participant F as declarations directory

    R->>E: load()
    E->>P: editable_view()
    P-->>E: ProjectFileView: keys, text, sha256
    E-->>R: the view
    R->>E: edit_path(SCHEMA_YML, table)
    E-->>R: declarations/dim_date.yml, or None
    R->>E: load() and editing_surface()
    Note over R: each edit is checked against the surface, then stored as a plan pinned to the file's hash
    T->>E: editing_surface()
    Note over T: an edit outside the surface is refused, confirmed or not
    T->>E: write_edits(edits, project_dir)
    E->>P: propose_edits(ProposedEdit list, root=project_dir)
    P->>F: re-read and hash every target
    alt a hash differs from its pin, and not confirmed
        P-->>E: EditOutcome: conflicts, nothing written
    else every pin holds, or confirmed
        P->>F: write every target
        P-->>E: EditOutcome: written, and any conflicts
    end
    E-->>T: ApplyResult: written, conflicts
```

- **`load()` and the write read different moments.** The view is built from
  the text the project was constructed with; `propose_edits` re-reads every
  target from disk. The reasons are in the docstrings of
  `dagster_dex.project.EditableDagsterProject.editable_view` and
  `dagster_dex.project.EditableDagsterProject.propose_edits`.
- **All-or-nothing means "check every target, then write"**, not a
  transaction (the `dagster_dex.project.EditableDagsterProject.propose_edits`
  docstring).
- **The plan's directory wins.** `write_edits` passes dex's `project_dir` as
  `root`, so a configuration that moved under a stored plan meets a pin that
  does not hold.
- **`load()` returns this package's `dagster_dex.protocol.ProjectFileView`**,
  not dex-core's dbt view, which keeps dex on its format-neutral path.

The directory contracts consumers build on (a missing directory refused, an
empty one admitted, the parent as root) are in
[AGENTS.md, *Tier 3 is reached by ONE class*](../../AGENTS.md#tier-3-is-reached-by-one-class-and-the-split-is-the-design).

## The artifact transport: the same inputs, carried as text

`artifact:` is the second construction route. The side that has the graph runs
step 1 and writes the result as JSON with `dagster_dex.artifact.dump`, which
takes the reduced models and the declaration text as keyword arguments. The
side that answers requests reads it with `dagster_dex.artifact.loads`, which
returns a `dagster_dex.artifact.ProjectArtifact`, and runs steps 2 and 3
itself.

```mermaid
flowchart LR
    W["Writer: from_asset_graph, then artifact.dump"] --> J["Artifact JSON"]
    J --> L["Reader: artifact.loads"]
    L --> P["DagsterProject, tier 2"]
    L --> E["EditableDagsterProject, tier 3"]
    D["declarations: directory, beside the artifact"] --> E
```

- **What it carries.** `DagsterProject`'s constructor arguments (the name,
  the reduced models with their relations, the three mappings of declaration
  text) plus `generated_at` and `schema_version`. `relations` is the one it
  does not carry: that override is the reading side's, from its own
  `.dex/config.yml`. It carries text, never parsed
  structures, so a project rebuilt from an artifact runs the same parsers and
  notes as one built from the graph (the `src/dagster_dex/artifact.py` module
  docstring).
- **What the reader checks.** `loads` requires `schema_version` to equal
  `dagster_dex.artifact.SCHEMA_VERSION`, and refuses anything it cannot read.
  `project_from_context` refuses a missing artifact, and refuses `semantics:`,
  `sources:` and `name:` beside one. It admits `relations:`, which corrects
  the relations the artifact carries without writing it again.
- **Which tier.** An artifact alone builds `DagsterProject`. A `declarations:`
  directory beside it builds the editable pair, and the directory supersedes
  the declaration text the artifact carries, disclosed in
  `dagster_dex.dex.EditableDexProject.notes`. Why it has to supersede is in
  [README, *Reaching the write tier over the artifact transport*](../../README.md#reaching-the-write-tier-over-the-artifact-transport).

When to use which route is in
[README, *Two ways to name the project*](../../README.md#two-ways-to-name-the-project-and-the-reason-there-are-two).

## Declared keys as Dagster asset checks

The declared keys of step 2 can also run inside Dagster, as asset checks that
dex-core judges (#180). `src/dagster_dex/checks.py` holds two layers: a spec
layer that needs neither Dagster nor the engine to import, and an executor
behind the `[dex]` extra. Neither generates SQL. Each check has one
implementation, dex-core's `maintain verify`, and everything that touches the
engine stays in `src/dagster_dex/dex.py`. Line numbers below are at `993f479`.

```mermaid
flowchart LR
    D["ProjectDeclarations: declared keys and joins"]
    K["the asset keys"]
    S["declaration_check_specs: one AssetCheckSpec per key, notes for the rest"]
    B["build_declaration_checks: one multi_asset_check"]
    J["a scheduled job over AssetSelection.checks"]
    V["dex.verify_declared_keys: one engine, one verify call"]
    R["one AssetCheckResult per selected check"]

    D --> S
    K --> S
    S --> B
    J -->|"each run"| B
    B --> V
    V -->|"a KeyVerdict per claim"| R
```

### Keys only

Each declared key gets one check. A declared join gets none: dex-core judges
no declared join for this project format, and a check that could only ever
report "not measured" was declined. Each join is named instead in
`dagster_dex.checks.DeclarationCheckSpecs` notes (`_join_notes`, `checks.py`
line 344), which the executor logs as a warning on every run (line 445), so a
run's log says what goes unchecked. The ruling is
[#180, comment 6715768229](https://github.com/catincloud-labs/dagster-dex/issues/180#issuecomment-6715768229);
the dex-core change join checks would wait on is filed as
[exmergo/dex#1197](https://github.com/exmergo/dex/issues/1197).

### The spec layer

`dagster_dex.checks.declaration_check_specs` (line 157) takes the
declarations and the asset keys, and returns one `AssetCheckSpec` per declared
key plus notes. It imports Dagster when it is called, the way `dex.py` imports
dex-core, so `import dagster_dex.checks` works with neither installed.

- **It attaches each spec to the one asset key whose last segment is the
  declared model**, because step 1 keeps only that segment as the model name.
  A key on a model that no asset key ends in, or that several do, gets a note
  and no spec, rather than being dropped or attached to a guess.
- **The claim id is the declaration's content, hashed.**
  `dagster_dex.checks.claim_id` (lines 122 to 133) is `sha256` over the
  key's kind, model and columns, read as the parser reads two declarations as
  one claim: a single column as written, a composite sorted and lowercased. So
  two reductions of one project give one id per key, and a changed declared
  column gives a new one. The asset key, the check name and the file a key
  was written in are not part of it.
- **Each spec carries the claim id, the model and the columns** in its
  metadata, under `dagster_dex.checks.CLAIM_ID`, `dagster_dex.checks.MODEL`
  and `dagster_dex.checks.COLUMNS`. Its name is `declared_key__` and the
  columns; the docstring gives the suffix rule for a column a Dagster name
  cannot hold and for two keys that would share a name.
- **Every spec is non-blocking unless its claim id is in `blocking`** (line
  217). A claim id there that names no rendered spec is refused (line 204),
  since an opt-in that attached to nothing would read like one that took.

### The executor

`dagster_dex.checks.build_declaration_checks` (line 365) needs Dagster and
the `[dex]` extra. It returns one `multi_asset_check` over the spec layer's
specs (line 456), which a run may subset. Each run:

1. logs the spec layer's notes as warnings;
2. opens ONE engine, `dagster_dex.dex.open_verify_engine` (`dex.py` line
   1457) unless the caller passes its own opener. The connection may be the
   project's own (dex-core's `ConnectionSource`), but the cost ceilings stay
   dex's, built from its own store;
3. calls `DexEngine.verify` ONCE, for the models of the selected checks,
   through `dagster_dex.dex.verify_declared_keys` (line 1510);
4. maps each result back to its claim by model, columns and source: a
   `grain_broken` finding under `unique_test` or `unique_test_composite`
   (`_broken`, line 1656; `_KEY_SOURCES`, line 1379);
5. yields one result per selected check.

What crosses back from `dex.py` is a `dagster_dex.dex.KeyVerdict` per claim
(line 1395): plain values, so the Dagster side never handles an engine type.

**A pass is read out of silence.** Verify reports a broken key and says
nothing about one that held, so a key is reported passed only once every
route to "not judged" is ruled out (`_judge`, line 1627; `_skip_reason`, line
1671). The routes, and the one way the note-reading fails open, are in the
`dagster_dex.dex.verify_declared_keys` docstring. The upstream field that
would replace that reading is asked for in
[exmergo/dex#1223](https://github.com/exmergo/dex/issues/1223).

### The defaults

Ruled on #180 in
[comment 6715768229](https://github.com/catincloud-labs/dagster-dex/issues/180#issuecomment-6715768229),
and held by `tests/test_executor.py`:

| Default | How it reads in a result | Where |
| --- | --- | --- |
| A claim the engine did not measure never reports as passed | `passed` false, severity WARN, `dagster_dex/measured` false, and the reason under `dagster_dex/reason` and as the description | `KeyVerdict` and `_unmeasured`, `dex.py` lines 1395 to 1413 |
| Nothing confirms a priced probe on a run's behalf | a probe the cost gate refuses or wants confirmed leaves every key in the call not measured, with dex's message; spending is the builder's `confirm_spend` opt-in, and dex's ceilings bind either way | `dex.py` lines 1576 to 1593 |
| WARN by default; blocking is an opt-in per claim | ERROR only for a measured failure of a claim in `blocking`; an unmeasured blocking claim still warns, since a key nobody measured is not evidence it broke | `checks.py` line 512 |
| Run on a schedule, not on materialization | the checks carry no automation condition; a job selecting them is the caller's to schedule | the `build_declaration_checks` docstring |
| Metadata carries counts only, never a row value | the claim id, `measured`, the engine's version, a reason when not measured, and a duplicate count on a failure; a reason is cut where dex starts quoting the warehouse | `_result`, `checks.py` lines 495 to 520; `_carried`, `dex.py` line 1416 |

The routes that leave a key not measured, each reported with its reason:

- the engine predates verify judging this format (next section);
- verify suppressed its grain check;
- the model is absent from `model_relations`, because no asset metadata or
  `relations:` entry names its table, or verify reports `no_relation` for it;
- verify's own grain plan leaves the key out: it checks a declared composite
  key only when the model declares no single-column unique key;
- one of verify's notes names the model;
- any `DexError` stops verify (the cost gate, the query firewall, the
  warehouse refusing a statement, a lost connection), or verify returns a
  probe to confirm.

### The engine floor

`maintain verify` judges a declared key on this format from exmergo-dex-core
1.12.5, measured on #179's DuckDB reproduction and returned on #180 in
[comment 6716240099](https://github.com/catincloud-labs/dagster-dex/issues/180#issuecomment-6716240099):
no verify before 1.9.2, and a refusal of the format from 1.9.2 to 1.12.4. The
floor is `dagster_dex.dex.VERIFY_JUDGES_FROM` (line 1371). Below it every
check reports not measured, with a reason naming the installed engine and the
floor, and the engine is not opened (line 1554). The `[dex]` range's own floor
is older than 1.12.5, so an install at that end runs the checks and judges
none of them; the version pins themselves are in
[AGENTS.md, *The dependency pin*](../../AGENTS.md#the-dependency-pin-and-why-there-are-two-of-them).

## What the translation does not do

- **It never edits a model.** `edit_path` returns `None` for `MODEL_SQL`;
  why only the declarations can receive an edit is in
  [AGENTS.md, *Tier 3 is reached by ONE class*](../../AGENTS.md#tier-3-is-reached-by-one-class-and-the-split-is-the-design).
- **It does not place an edit through a relation.** Placement uses the
  warehouse table's name as the file stem, and does not translate it through
  `ProjectModel.relation`; doing so would move where a write lands.
- **It reports no file-content drift.** `files` is empty, and the transform
  layer's note says so rather than letting two empty mappings read as no change.
- **It does not infer sources** from dependencies, for the reason step 2 links.
- **It does not absorb a sibling project** in another format
  ([README, *What this is*](../../README.md#what-this-is)).

## Seeing it run

`examples/walk_the_whole_loop.py` runs the graph route on this page against a
local DuckDB warehouse, write-back included; it does not use the artifact
transport, which `scripts/drive_the_write_path_against_the_wheel.py` drives.
From the root of a clone, as the README gives it:

```bash
uv run --no-project --with-editable . --with 'dagster>=1.13' \
  --with exmergo-dex-core==1.8.0 --with sqlglot==30.13.0 --with duckdb \
  python examples/walk_the_whole_loop.py
```

The README's [*What it finds*](../../README.md#what-it-finds) explains the lines
it prints.

`examples/run_declared_key_checks.py` runs the asset-check section: it builds
the checks, schedules a job over `AssetSelection.checks`, and runs the job in
process under real Dagster against a local DuckDB warehouse. On an engine from
1.12.5 it shows measured passes, measured failures and two keys a real engine
leaves not measured; below it, every check not measured with the floor's
reason. CI runs it at both ends of the published range, in `engine-ends`.
`examples/reduce_asset_graph.py` is the spec-only example: it renders the
specs and has Dagster load them, and needs no engine. With the newest engine
the `[dex]` range admits:

```bash
uv run --no-project --with-editable '.[dex]' --with 'dagster>=1.13' \
  --with sqlglot==30.13.0 --with duckdb \
  python examples/run_declared_key_checks.py
```
