# dagster-dex

A Dagster asset graph read as a **project format** for
[dex](https://github.com/exmergo/dex), and the tiered seam it proposes for
reading one.

Copyright 2026 David Anaya. Apache-2.0.

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

Once installed, dex can name this format directly:

```yaml
# .dex/config.yml
project:
  format: dagster
  options:
    assets: my_project.definitions:all_assets
```

**dex** reads a project's declared structure (keys, joins, sources, semantics)
and reports where the warehouse has drifted from it. It reads dbt projects
natively. This package makes a Dagster asset graph readable the same way,
without the graph having to pretend to be a dbt project first.

## What this is

A working sketch of a contract, not a finished integration. It exists to make a
design argument concrete enough to disagree with: an asset graph is a perfectly
good source of project truth, and reading one does not require it to pretend to
be a dbt project first.

## The seam, in three tiers

| Tier | Adds | A format implements it when |
| --- | --- | --- |
| `ProjectSource` | `declarations()` | it can say what it declares |
| `FingerprintedProject` | `fingerprint()` | it can be a drift baseline |
| `EditableProject` | `propose_edits()` | its source of truth can receive an edit |

`DagsterProject` implements tiers 1 and 2, and **not** tier 3 - not by setting a
flag, but by not having the method. `isinstance(project, EditableProject)` is
False, so a caller finds out by asking rather than by receiving an empty result
that looks like success. A generated project is safe from stray writes today
only where a naming convention happens not to match; declining a tier makes that
structural.

## Four model decisions worth arguing about

**A key is always a tuple of columns.** A single-column grain is the `n == 1`
case, not a different type. Modelling it the other way is what makes a composite
grain inexpressible until someone widens the type - and after widening, every
reader handles two shapes forever.

**There is no project directory.** A path is one format's way of locating
itself, not a property every project has.

**Freshness is a tri-state.** `FRESH` / `STALE` / `NOT_APPLICABLE`. A boolean
cannot tell "current" from "there is no such artifact here", so a format with
nothing to compile reports itself identically to one that just compiled.

**A required field is a refusal to invent.** `ExternalSource` requires a source
system because the consumer requires one; making it optional would only move the
moment of invention into the boundary code, where a fabricated value cannot be
told from a declared one. Where the consumer requires something a project may
genuinely lack, such as a file path, the field is optional here and the loss is
reported instead of filled in.

## External sources: the edge a graph cannot see

Everything in `models` is something the project builds. `ExternalSource` is
where it stops and depends on a warehouse object somebody else keeps honoring.

These **cannot be derived from the asset graph**. A model that reads a table in
its own SQL, because the source system offers no other interface, draws no
dependency edge, so the read is invisible to any amount of traversal. It is
genuinely extra information and has to be declared, keyed by the model that
reads it. A format that inferred sources from dependencies would find none and
look like it had checked.

They are not decorative on the consumer side either: they drive a
`dangling_source` finding and the set of tables a project is understood to
cover. A format that reports none silently narrows its own blast radius.

## Layout, and why the dependencies sit where they do

```text
model.py         the neutral model          stdlib only
protocol.py      the tiered seam            stdlib only
declarations.py  input parsing              + pyyaml
project.py       the Dagster reduction      + dagster, lazily
conformance.py   the importable contract    + pytest
dex.py           the dex-core boundary      + exmergo-dex-core, lazily
```

The engine coupling is one file. Everything else, including the conformance
suite, runs with dex-core uninstalled, which is what keeps the design from
being shaped by whatever the engine happens to look like today. `dex.py` imports
**public API only**; `tests/test_dex_bridge.py` asserts that with an AST walk
rather than trusting it.

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
    --with pytest==8.4.1 --with exmergo-dex-core==1.6.5 --with sqlglot==30.13.0 \
    python -m pytest tests \
    --ignore=tests/test_upstream_contract.py
```

`--with-editable` is not optional: without it the package is never installed and
every test errors at collection on `No module named 'dagster_dex'`. These
are the two commands CI runs, and the first is a **control**: it is what holds
the engine coupling to one file, so an `exmergo_dex_core` import anywhere else
turns it red at collection.

The engine is pinned to `==1.6.4` here and in CI, which is **not** what the
`[dex]` extra publishes. The extra is `~=1.6.4`, so consumers are not forced onto
one patch release; the exact pin is where the demonstration lives, because a
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
    --with pytest==8.4.1 --with exmergo-dex-core==1.6.5 --with sqlglot==30.13.0 \
    python -m pytest tests/test_upstream_contract.py
```

`DEX_UPSTREAM_CONTRACT_REQUIRED=1` is what makes it a signal, and the release did
not change that. Without the variable the file skips itself when the contract is
unimportable, which is right at a developer's desk and wrong in CI, where an unrun
file and a passing file look the same. With it, a missing contract is a collection
error - which still matters against a release, because a yank or a bad bump lands
in exactly the same place a rewritten branch used to.

## Using the contract on another format

```python
from dagster_dex.conformance import FingerprintedProjectContract

class TestMyFormat(FingerprintedProjectContract):
    def make_project(self, declarations, semantics, sources):
        return MyProject(declaration_sources=declarations,
                         semantic_sources=semantics,
                         source_declarations=sources)
```

The assertions that matter most are behavioural: `declarations()` must not raise
on an absent, empty, or malformed project. That is the property a second
implementation is most likely to get wrong, and a suite checking only shapes
will pass it.

`make_project` took two arguments before external sources landed. The third
is a **breaking change to this contract**, taken deliberately while the suite has
no outside implementers rather than carried forever as an optional hook that
could be skipped - and a skipped assertion is not a passing one.

## Status

**Alpha, and the contract may move before 1.0.** The tiered seam is a proposal,
not a settled interface: it exists to be argued with, and the argument may change
it. Pin the minor if you depend on it.

**The entry point stopped being inert on 2026-08-08.** This section used to end:
*"nothing resolves it today, and an entry point nobody looks up is inert."*
dex-core **1.6.0** added resolution for exactly the `exmergo_dex_core.projects`
group this package has declared since `0.1.0` - a format can now be named from
`.dex/config.yml`, from a dotted `mypkg.projects:my_project` path, or from that
entry-point group, with `--project-format` overriding on the CLI.

That arrived through [`exmergo/dex#171`](https://github.com/exmergo/dex/issues/171),
which this package's own constraint shaped: a host reaching dex as a subprocess
cannot hand an object in, so name resolution was the only door that worked.

**And it was registered wrong.** That paragraph originally ended *"what is left
between here and a resolvable format is packaging, not design"*, written before
anyone had run it. Resolution found the entry point immediately and then refused:
it named the **class**, and dex-core's `ProjectFactory` calls what it resolves
**with a `ProjectContext`**, so the context bound to `models`. A second gap sat
behind it: a bare `DagsterProject` is refused as *"missing name, definitions"*,
because this package says `format`/`declarations()` where the seam says
`name`/`definitions()`.

=> The lesson is worth more than the fix: **a declared-but-unresolved extension
point is not evidence that registration works.** It was inert from `0.1.0`, so
there was no moment before 2026-08-08 at which it could have failed.

Both are fixed. The entry point names `dex:project_from_context`, which takes a
context and returns a `DexProject`, and a regression test asserts the registration
*and* that it loads to the callable.

**This paragraph used to end with a hand-counted end-to-end result** - a model
count, a source count, semantic models and metrics, from dex driven as a
subprocess against a private asset graph. It was true where it was written and it
is unverifiable here: nobody outside can run it, and it was four numbers in a
document, which is the thing this project's own rules forbid. What replaces it is
smaller and checkable by anyone:

| Verified in CI, every commit | Where |
| --- | --- |
| The suite passes with the engine uninstalled | control step |
| The suite passes against the engine | boundary step |
| The format passes dex-core's own project contract | criterion step |
| The reduction works on real Dagster objects | reduction step |
| The annotations type-check at the floor | type check |
| The built wheel imports, declares its entry point, ships `py.typed` | release workflow |

Everything above runs from a clean checkout with two commands and no access to
anything private, which is the property the old sentence did not have.

### Two ways to name the project, and the reason there are two

`assets:` reduces a live asset graph in the calling process. That is the honest
form, and on a real project it costs **~2.6 s** - almost entirely the import of
the code location, which is not something laziness or caching can reach, because
a host that builds a project per command never holds one long enough to amortize
it.

`artifact:` is the answer for a host that cannot pay that: the side that already
has the graph reduces it once and writes the result down, and the side that
answers requests reads it back.

```yaml
project:
  format: dagster
  options:
    artifact: project/my_project.json   # written by dagster_dex.artifact.dumps
```

Exactly one of the two is required, and naming both is refused rather than
resolved: a snapshot and a live graph disagree by design. An artifact carries
its own declarations and its own name, so `declarations:`/`semantics:`/`sources:`
and `name:` are refused beside it rather than silently ignored.

**A missing artifact is refused, not read as an empty project.** An empty
project is a valid one, so the tolerant reading would report a broken deploy as a
warehouse with nothing declared, quietly, and for as long as it lasted.
