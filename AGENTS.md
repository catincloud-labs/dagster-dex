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

## Running the suite

Three steps, matching CI exactly. From the repository root:

```bash
# 1. the control -- no orchestrator, no engine
uv run --no-project --with-editable . --with pytest==8.4.1 \
  python -m pytest tests --ignore=tests/test_dex_bridge.py \
  --ignore=tests/test_upstream_contract.py

# 2. the boundary, against the real engine
uv run --no-project --with-editable . --with pytest==8.4.1 \
  --with exmergo-dex-core==1.6.4 --with sqlglot==30.13.0 \
  python -m pytest tests --ignore=tests/test_upstream_contract.py

# 3. dex-core's own project contract
DEX_UPSTREAM_CONTRACT_REQUIRED=1 uv run --no-project --with-editable . \
  --with pytest==8.4.1 --with exmergo-dex-core==1.6.4 --with sqlglot==30.13.0 \
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
- **Tested** (CI and the commands above): `==1.6.4`, exactly.

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
- The release is tag-gated on `v*` and **no tag has been pushed**. Publishing is a
  deliberate act, not the tail of a merge.

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
