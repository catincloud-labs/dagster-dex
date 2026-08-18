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

## Tier 3 is declined, and the reason is not the one this section used to give

`propose_edits(edits) -> object` is deliberately vague. Declining is checked
rather than claimed: `tier_of()` checks by `isinstance`, so a format cannot
claim a tier it does not implement.

**This section used to call the decline structural**, on the grounds that a
project reduced from a running graph has no source of truth that can receive an
edit. **That reason was retracted in the code on 2026-08-09 and stood here
anyway**, in the file an agent reads first. The models are a reduction and
cannot receive an edit; the declared keys, joins, semantics and sources are
hand-written YAML that nothing regenerates, and they can. See `dex.DexProject`'s
docstring, which is where the correction landed.

**The second reason has expired too.** The tier stayed declined because dex
could not route an edit to a non-dbt format. Both blockers this package filed
(`exmergo/dex#257`, `#258`) closed on 2026-08-11, resolved by our own merged
`exmergo/dex#263`, which shipped `PlacingProject` in dex-core 1.6.4. This
package pins 1.6.6.

=> **What is left is work, not a blocker.** Do not re-derive either dead reason
from the assertions below: they assert the current state, not why it holds.

The conformance suite asserts the decline **negatively** - `not isinstance(project,
EditableProject)` - so reaching tier 3 by accident is caught rather than
congratulated. `PlacingProject` is declined the same way and separately, because
it sits *beside* the tiers rather than inside them: `tier_of() == 2` says nothing
about it.

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
- **The `exmergo_dex_core.projects` entry point is live as of dex-core 1.6.0**,
  and was inert before it for as long as nothing looked the group up. That is the
  origin of this repository's most-repeated lesson and the reason several tests
  exist that look redundant: they check the *resolution*, not the registration.

## Running the suite

Three steps, matching CI exactly. From the repository root:

```bash
# 1. the control -- no orchestrator, no engine
uv run --no-project --with-editable . --with pytest==8.4.1 \
  python -m pytest tests --ignore=tests/test_dex_bridge.py \
  --ignore=tests/test_upstream_contract.py

# 2. the boundary, against the real engine
uv run --no-project --with-editable . --with pytest==8.4.1 \
  --with exmergo-dex-core==1.6.6 --with sqlglot==30.13.0 \
  python -m pytest tests --ignore=tests/test_upstream_contract.py

# 3. dex-core's own project contract
DEX_UPSTREAM_CONTRACT_REQUIRED=1 uv run --no-project --with-editable . \
  --with pytest==8.4.1 --with exmergo-dex-core==1.6.6 --with sqlglot==30.13.0 \
  python -m pytest tests/test_upstream_contract.py -p no:cacheprovider
```

Plus two checks that are not pytest, and both run in the same CI job:

```bash
# the py.typed claim, actually checked -- at the FLOOR, not the newest interpreter
uv run --no-project --with-editable . --with mypy==1.14.1 --with types-PyYAML \
  python -m mypy

# the reduction against REAL dagster objects -- no other step installs it
uv run --no-project --with-editable . --with 'dagster>=1.13' python -c "..."
```

**The Dagster step exists because everything else uses fakes.** That is
deliberate - the suite must run without an orchestrator - but it means nothing
else here would notice `from_asset_graph` breaking against the objects Dagster
actually hands it. The `[dagster]` extra was declared and installed by nothing
until that step existed.

`--with-editable` is not optional - without it every test errors at collection
on `No module named 'dagster_dex'`. Never `uv run --python X` without
`--no-project`; it recreates a `.venv` here.

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

## The dependency pin, and why there are two of them

- **Published** (`pyproject.toml`, the `[dex]` extra): `exmergo-dex-core~=1.6.4`,
  i.e. `>=1.6.4, ==1.6.*`. Patches move, the minor boundary does not.
- **Tested** (CI and the commands above): `exmergo-dex-core==1.6.6`, exactly.
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

**One exemption, and it is not stylistic.** `scripts/check_closing_keywords.py`
  is a vendored copy compared **byte-for-byte** against `workbench` by CI.
  Reformatting it to satisfy this rule trades a passing test for a failing
  pipeline. The guard skips exactly that path and says why.

## Conventions

- Line endings are LF everywhere, enforced by `.gitattributes`.
- Every source file carries `# Copyright 2026 David Anaya` and
  `# SPDX-License-Identifier: Apache-2.0`.
- Markdown is linted in CI with a shared config. Two rules are off deliberately:
  `MD013` (line length) and `MD041` (first line must be a top-level heading) -
  `MD041` because the GitHub templates under `.github/` correctly do not start
  with an H1.
- **Never put a number in a document that something else can change.** A test
  count, an export count, a timing - cite the command instead.
