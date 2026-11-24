# dagster-dex

Let [dex](https://github.com/exmergo/dex) read your Dagster asset graph the way
it reads a dbt project: keys, joins, sources, semantics, drift.

**dex** reports where a warehouse has drifted from the structure a project
declares. It reads dbt projects natively. This package makes a Dagster asset
graph readable the same way, without the graph having to pretend to be a dbt
project first.

Copyright 2026 David Anaya. Apache-2.0.
Maintained by [CatInCloud Labs](https://catincloudlabs.com/gh).

```bash
pip install dagster-dex          # the core: no orchestrator, no engine
pip install 'dagster-dex[dex]'   # with the dex-core boundary
```

Or from source, for `main` ahead of the last release:

```bash
pip install 'git+https://github.com/catincloud-labs/dagster-dex'
pip install 'dagster-dex[dex] @ git+https://github.com/catincloud-labs/dagster-dex'
```

Python 3.10+, matching Dagster's own floor. The `[dex]` extra needs 3.11+,
because the engine does: on 3.10 you can still reduce a graph and write an
artifact for a machine that has the engine to read it.

## What it finds

`examples/walk_the_whole_loop.py` puts a small Dagster asset graph in front of a
local DuckDB warehouse, breaks the warehouse and one of the project's
definitions by hand, and lets dex find the drift through this package. It needs no cloud account, no credential and
nothing private. From the root of a clone of this repository:

```bash
uv run --no-project --with-editable . --with 'dagster>=1.13' \
  --with exmergo-dex-core==1.8.0 --with sqlglot==30.13.0 --with duckdb \
  python examples/walk_the_whole_loop.py
```

Some of the lines it prints:

<!-- excerpt: examples/walk_the_whole_loop.py, held to the run by scripts/check_readme_excerpt.py -->
```text
leg 5 ok          : 2 finding(s); dim_date impacts ['dim_date', 'fact_sales']
leg 7/8 ok        : wrote it, and the project gained [('dim_date', 'date_key')]
leg 11 ok         : dangling_source on raw.sales_events, declared_in sources/fact_sales.yml
leg 12 ok         : definition_changed, and sales.amount reported as uncheckable
```

- **Leg 5.** One duplicate row in each of `dim_date` and `fact_sales` breaks
  both keys, hence two findings, and the `dim_date` finding names `fact_sales`
  among the models it impacts. Nothing in the warehouse connects those two
  tables; the Dagster asset graph does.
- **Legs 7 and 8.** The `unique` test dex proposed for the broken key is written
  into the hand-written declaration YAML through this package, and reading the
  project back shows the key declared.
- **Leg 11.** A source table the project declares is dropped, and the finding
  names the file that declared it.
- **Leg 12.** A measure is redefined as `amount * 1.2`. dex reports
  `definition_changed`, which no inspection of the warehouse finds because
  nothing in the warehouse changed, and says the new expression no longer maps
  to a column it can check, rather than passing it.

CI runs this example on every pull request and refuses the change if any line
quoted above is not one the run printed.

## Pointing dex at your graph

Once the package is installed, name the format in dex's own config:

```yaml
# .dex/config.yml
project:
  format: dagster
  options:
    assets: my_project.definitions:all_assets
```

### Naming each model's table

dex places a model in the warehouse by its relation, and `maintain verify`
judges a declared key only on a model it can place. The format takes each
model's relation from the `dagster/table_name` key in its asset's metadata,
where Dagster itself keeps a table name. Where that is missing or wrong,
`relations:` corrects it per model, and wins:

```yaml
project:
  format: dagster
  options:
    assets: my_project.definitions:all_assets
    relations:
      fact_orders: analytics.orders_v2   # plain dotted parts, no quoting
```

A model with no table from either place is reported in a note, so a run that
could not judge it does not read as a clean one, and a name under `relations:`
that matches no built model is an error. `relations:` is also
admitted beside `artifact:`, where it corrects what the artifact carries
without writing it again.

## What this is

A contract for reading an asset graph as a project, and a bridge that puts dex
on it. It exists to make a design argument concrete enough to disagree with: an
asset graph is a perfectly good source of project truth, and reading one does
not require it to pretend to be a dbt project first.

One boundary, stated up front: this format describes **one orchestrated asset
graph**. It does not describe, and will not absorb, a sibling project in
another format - two formats each describing the same warehouse table is
exactly the duplication this package's design argument rejects. Where
two projects meet, the warehouse is the join: each describes what it builds,
and lineage across them is read from the tables, not from either project.

## The seam, in three tiers

| Tier | Adds | A format implements it when |
| --- | --- | --- |
| `ProjectSource` | `declarations()` | it can say what it declares |
| `FingerprintedProject` | `fingerprint()` | it can be a drift baseline |
| `EditableProject` | `propose_edits()` | its source of truth can receive an edit |

**Which tier you get depends on how the project was built, and that is the
point.** `DagsterProject` reaches tier 2. `EditableDagsterProject` reaches tier
3, and the factory returns one only when the project points at a declarations
directory on disk, which gives an edit a place to go. Read one from an `artifact:`
alone and you get tier 2, because an artifact is a JSON file with no directory
behind it.

**The graph is no longer the only way to have one.** A `declarations:` directory
named beside an `artifact:` reaches tier 3 as well; see
[Two ways to name the project](#two-ways-to-name-the-project-and-the-reason-there-are-two)
for what that directory supersedes and why it has to.

The split is a class, not a flag, so `isinstance(project, EditableProject)`
answers for each instance. What an edit lands in is the **declarations**, never
the models. Both are argued in
`help(dagster_dex.project.EditableDagsterProject)`.

## Four model decisions worth arguing about

The neutral model in `dagster_dex.model` departs from a dbt-shaped one in four
places, each argued in its module docstring (`help(dagster_dex.model)`):

- **Keys are tuples of columns,** with no separate single-column type.
- **No directory in the model.** Format and name identify a project.
- **Freshness has three states,** `FRESH`, `STALE` and `NOT_APPLICABLE`, not
  two.
- **Required fields are not filled in.** `ExternalSource` requires its source
  system. What a project may lack, such as a file path, is optional, and its
  absence is reported.

## External sources: the edge a graph cannot see

`ExternalSource` stands for a table the project depends on and someone else
builds.
Sources have to be **declared**, each under the model that reads it, because a
read inside a model's own SQL draws no edge in the asset graph; the argument
is in `help(dagster_dex.model.ExternalSource)`.

They are not decorative on the consumer side either: they drive a
`dangling_source` finding and the set of tables a project is understood to
cover. A format that reports none silently narrows its own blast radius.

## Layout, and why the dependencies sit where they do

```text
model.py         the neutral model          stdlib only
protocol.py      the tiered seam            stdlib only
declarations.py  input parsing              + pyyaml
project.py       the reduction, the writer  stdlib only
artifact.py      the artifact transport     stdlib only
checks.py        declared keys as checks    + dagster, lazily; its executor + [dex]
conformance.py   the importable contract    + pytest
planted.py       formats built to fail it   + pyyaml
dex.py           the dex-core boundary      + exmergo-dex-core, lazily
```

The engine coupling is one file. Everything else, including the conformance
suite and the whole write path, runs with dex-core uninstalled, so the design
is not shaped by the engine's present form. The one exception is the
declared-key executor in `checks.py`, which
reaches the engine through `dex.py`; the module imports without it. `dex.py` imports **public API only**; `tests/test_dex_bridge.py` asserts
that with an AST walk rather than trusting it.

The write path is in `project.py` rather than at the boundary for that reason,
and its conflict handshake is asserted in the step that runs with no engine
installed - `tests/test_write_tier.py`. Why the write tier is the part most
worth holding is in `help(dagster_dex.conformance.EditableProjectContract)`.

## Running it

From the repository root:

```bash
# the core: no orchestrator, no engine
uv run --no-project --with-editable . \
    --with pytest==8.4.1 \
    python -m pytest tests \
    --ignore=tests/test_dex_bridge.py \
    --ignore=tests/test_upstream_contract.py

# with the engine, to exercise the boundary
uv run --no-project --with-editable . \
    --with pytest==8.4.1 --with exmergo-dex-core==1.8.0 --with sqlglot==30.13.0 \
    python -m pytest tests \
    --ignore=tests/test_upstream_contract.py
```

`--with-editable` is not optional: without it the package is never installed and
every test errors at collection on `No module named 'dagster_dex'`. Both run
in CI, and the first is a **control**: it is what holds
the engine coupling to one file, so an `exmergo_dex_core` import anywhere else
turns it red at collection.

The engine is pinned to `exmergo-dex-core==1.8.0` here and in CI, which is
**not** what the `[dex]` extra publishes. The extra is
`exmergo-dex-core~=1.8`, so consumers are not forced onto
one release; the exact pin is where the demonstration lives, because a
claim about what passed should name the version it passed against.

### Against dex-core's own contract

`tests/test_upstream_contract.py` runs this format against the conformance suite
**dex-core ships**, which is upstream's acceptance criterion for a second project
format (`exmergo/dex#144`). That suite ships in **v1.5.2**, released 2026-08-05,
via [`exmergo/dex#192`](https://github.com/exmergo/dex/pull/192) - our own PR, so
the criterion is now judged by upstream's released code rather than by a branch:

```bash
DEX_UPSTREAM_CONTRACT_REQUIRED=1 \
uv run --no-project --with-editable . \
    --with pytest==8.4.1 --with exmergo-dex-core==1.8.0 --with sqlglot==30.13.0 \
    python -m pytest tests/test_upstream_contract.py
```

`DEX_UPSTREAM_CONTRACT_REQUIRED=1` is what makes it a signal, and the release did
not change that. Without the variable the file skips itself when the contract is
unimportable, which is right at a developer's desk and wrong in CI, where an unrun
file and a passing file look the same. With it, a missing contract is a collection
error - which still matters against a release, because a yank or a bad bump lands
in exactly the same place a rewritten branch used to.

## Using the contract on another format

`dagster_dex.conformance` ships the contract in the package, as pytest classes
a test module subclasses, one per tier. At tiers 1 and 2 a hook builds your
format from text the test hands it; at tier 3 a hook stages a conflict of its
own. The wiring, which assertion matters most and why, and what of the
contract is public surface are in its module docstring,
`help(dagster_dex.conformance)`.

To watch the contract refuse before trusting its green, wire one of the six
formats in `dagster_dex.planted` to its contract: two go to the tier-2
contract and four to the tier-3 one, and each fails exactly the tests its
docstring names (`help(dagster_dex.planted)`). The design guide's
[*Watching it refuse*](https://github.com/catincloud-labs/dagster-dex/blob/main/docs/design/implementing-a-format.md#watching-it-refuse)
lists them.

## Status

**Stable from 1.0.0, under semantic versioning.** A breaking change to the seam
waits for 2.0. Pin the major if you depend on it, as `dagster-dex~=1.0` does.

1.0.0 was cut on evidence rather than on a date: the three criteria recorded on
[#57](https://github.com/catincloud-labs/dagster-dex/issues/57) held. This package's seam held through a full minor cycle,
dex-core's project seam held across two consecutive engine minors, and the
defect-injection floor held at 5/5. The changelog's 1.0.0 entry links the
reading behind each one.

[CHANGELOG.md](https://github.com/catincloud-labs/dagster-dex/blob/main/CHANGELOG.md) names what changed between releases and which
changes were breaking, which is the question this section cannot answer for a
consumer already on an older version.

**dex finds this format by name.** From dex-core 1.6.0 the engine resolves the
`exmergo_dex_core.projects` entry-point group, which this package registers in,
so a format can be named from `.dex/config.yml`, from a dotted
`mypkg.projects:my_project` path, or from that group, with `--project-format`
overriding on the CLI. The entry point names `dex:project_from_context`, which
takes a context and returns a `DexProject`, and a regression test asserts the
registration *and* that it loads to the callable. How it came to be registered
that way is in the changelog.

| Verified in CI, every commit | Where |
| --- | --- |
| The suite passes with the engine uninstalled | control step |
| The suite passes against the engine | boundary step |
| The format passes dex-core's own project contract | criterion step |
| The reduction works on real Dagster objects | reduction step |
| The annotations type-check at the floor | type check |
| The built wheel imports, declares its entry point, ships `py.typed` | release workflow |
| A reconcile proposal becomes a plan, is written through this format, and changes what the project declares | release workflow |
| A second plan is refused over a human's edit rather than written | release workflow |
| The shipped contract, run from the built wheel, fails each planted format on exactly its own tests and passes this one | release workflow |

Every row runs from a clean checkout with no access to anything private:
[AGENTS.md, *Running the suite*](https://github.com/catincloud-labs/dagster-dex/blob/main/AGENTS.md#running-the-suite)
gives the commands, and the workflows under
`.github/workflows/` run the rest.

### Two ways to name the project, and the reason there are two

`assets:` reduces a live asset graph in the calling process, and its cost is
mostly **importing the code location**, not the reduction. How long that
import takes is a property of your project rather than of this package, so it
is the thing to measure before choosing between the two forms: time
`dagster definitions list` against your own code location and you have the
number, on your machine, where it is true.

`artifact:` reads a project reduced earlier by a process that held the graph,
and wrote it with `dagster_dex.artifact.dump`. Why the transport exists, and
why caching cannot stand in for it, is in `help(dagster_dex.artifact)`.

```yaml
project:
  format: dagster
  options:
    artifact: project/my_project.json   # written by dagster_dex.artifact.dump
```

Name exactly one of the two; a config with both, or with neither, is an error.
An artifact carries its own semantics, sources and name, so `semantics:`,
`sources:` and `name:` are errors beside it, and **an artifact path with no
file behind it is an error too**, never an empty project. The reasons for each
refusal are in `help(dagster_dex.dex.project_from_context)` and in the
docstring of `_project_from_artifact` in `src/dagster_dex/dex.py`.

#### Reaching the write tier over the artifact transport

`declarations:` is the one option admitted beside `artifact:`. Its directory
**replaces** the declarations the artifact holds, and is where edits land:

```yaml
project:
  format: dagster
  options:
    artifact: project/my_project.json
    declarations: declared            # the live source, and where edits land
```

Keeping the artifact's declarations and using the directory only as a place
for edits sounds simpler, and cannot be built; the argument is in the
`_project_from_artifact` docstring, and worth reading before proposing it
again. The artifact still supplies the graph. `notes()` says when the
artifact's own declaration text was set aside, and a `declarations:` path with
no directory behind it is an error.

**An empty directory is accepted, and the asymmetry is a contract rather than
an accident.** A consumer's provisioning order can legitimately create the
directory before its first content arrives, so first boot depends on empty
being admitted; the project reaches the write tier with an empty editing view,
and the view fills as files do. A missing directory means a wrong path; an
empty one means a true state. Tightening the empty arm into a refusal would be
a breaking change to that provisioning order, not a tidier default.

**The directory's parent becomes the project root, and that derivation is a
guarantee: changing it waits for 2.0.** Keys are `<directory-name>/<file>`,
relative to the parent, and downstream tooling stores plans relative to that
root - so a plan made against one checkout applies against another only
because both derive the same root from the same configured path. A change here
relocates every stored plan's `project_dir`; it is pinned by a test in this
repository so the rule goes red where it lives.

### Writing one, from the side that has the graph

`dagster_dex.artifact.dump` writes the file. It is deliberately
orchestrator-free - the reduction reads asset definitions structurally - so the
scheduling around it is yours. This is what that looks like in Dagster, and it is
**user code**: copy it, do not import it.

```python
from datetime import datetime, timezone

import dagster as dg
from dagster_dex import DagsterProject
from dagster_dex.artifact import dump

@dg.op
def write_project_artifact(context) -> int:
    from my_project.definitions import all_assets   # deferred: see below

    project = DagsterProject.from_asset_graph(all_assets, name="my_project")
    declarations = project.declarations()
    dump(
        "/shared/project/my_project.json",
        name="my_project",
        models=declarations.models,
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        declaration_sources=my_declaration_yaml,      # {filename: text}
    )
    context.log.info("wrote %s models", len(declarations.models))
    return len(declarations.models)

@dg.job
def write_project_artifact_job() -> None:
    write_project_artifact()

write_project_artifact_schedule = dg.ScheduleDefinition(
    job=write_project_artifact_job,
    cron_schedule="0 6 * * *",
    execution_timezone="UTC",
    default_status=dg.DefaultScheduleStatus.RUNNING,
)
```

Four things in that sketch are not incidental:

- **The asset import is deferred into the op body.** A module-scope import of
  the graph is a cycle if your `definitions.py` also imports this module, and a
  failure in it takes down the whole code location rather than one job.
- **`generated_at` is yours to supply.** The library has no clock, and why is
  in `help(dagster_dex.artifact.dumps)`.
- **The path's parent must already exist.** `dump` will not create it; why is
  in `help(dagster_dex.artifact.dump)`.
- **Schedule it.** An artifact that regenerates when someone remembers is a
  stale artifact, and a stale project is a wrong drift report rather than an
  absent one.

**The sketch's mechanics are executed by CI** -
`examples/write_project_artifact.py` runs the same op body against a real
graph, executes the job in process, reads the artifact back, and constructs
the schedule, so the code above cannot silently rot. What CI deliberately does
not decide is the schedule *values*: scheduling is a decision, and a library
that made it for you would be wrong in every deployment that differs - which
is why the sketch stays here, with placeholders, as user code.

## Verifying a release

Each file on PyPI carries a PEP 740 attestation, which PyPI checks and shows:
it names this repository's `publish.yml`, run at the release's `v*` tag. From
the first release after `v0.6.2`, that tag is also signed by the maintainer, so
the chain ends at a public key rather than at repository settings you cannot
read. `v0.6.2` and every tag before it are unsigned and stay that way: a
signature added now would vouch for them after the fact, not at their release.

To check one, with git 2.34 or newer and OpenSSH 8.8 or newer, put the version
you installed in place of `vX.Y.Z`:

```bash
git clone https://github.com/catincloud-labs/dagster-dex
cd dagster-dex
cat .github/allowed_signers
curl -s https://api.github.com/users/catincloudlabs/ssh_signing_keys
git -c gpg.ssh.allowedSignersFile=.github/allowed_signers tag -v vX.Y.Z
```

- **The key comes before the file.** Every key in
  [`.github/allowed_signers`](https://github.com/catincloud-labs/dagster-dex/blob/main/.github/allowed_signers)
  has to be one GitHub lists as a signing key of the maintainer's account,
  `catincloudlabs`, which is what `curl` prints. The file travels in the same
  repository as the tag it vouches for, so on its own it proves nothing.
- **Then the tag.** `tag -v` prints the tag, then `Good "git" signature for`
  the principal in that file, and exits 0. Anything else (`no signature
  found`, `No principal matched`) means the tag is not one the maintainer
  signed.
- **Then two lines of what it printed.** `tag` has to name the version you
  asked for: a signature covers the name written inside the tag, so a tag
  signed under another name still verifies wherever it is moved. `object` is
  the commit the release was built from, the same commit its PyPI attestation
  names.
- **The release workflow runs the same checks first.** Its `build` job
  verifies the tag, and the name inside it, before it runs a test or builds
  anything, and a tag that fails stops the release before anything is
  uploaded.
