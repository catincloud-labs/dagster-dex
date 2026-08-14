# Contributing

Contributions are welcome. This is a small, alpha, one-maintainer project, so the
most useful thing to do first is **open an issue** - the seam is still a proposal,
and a design disagreement is worth more here than a patch to something that may
move.

## Licensing

**Inbound = outbound.** Contributions are accepted under the
[Apache License 2.0](LICENSE), the same licence this project ships under. You keep
copyright on what you write.

There is **no CLA and no DCO sign-off.** That matches the posture of the upstream
project this integrates with, and adding one unilaterally would be friction
nobody else in this ecosystem imposes.

## Before you change anything: step one of the suite is a control

The test suite runs in three steps, and the first one runs everything **with
`exmergo-dex-core` uninstalled.**

That is not a speed optimisation. It is the only thing enforcing this package's
central claim: **the engine coupling lives in exactly one file**,
`src/dagster_dex/dex.py`. Every other module - the model, the protocol, the
parser, the conformance suite - must work with dex-core absent, which is what
keeps the design from being shaped by whatever the engine happens to look like
today.

**An `exmergo_dex_core` import added to any other module destroys that
property, and the only thing that catches it is a step that looks like a redundant
re-run.** If you find yourself wanting one somewhere else, that is a design
conversation - please open an issue rather than working around the step.

## Running the tests

From the repository root:

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

Plus two checks that are not pytest:

```bash
# annotations must check clean -- this package ships a py.typed marker
uv run --no-project --with-editable . --with mypy==1.14.1 --with types-PyYAML \
  python -m mypy

# the reduction against real Dagster objects (everything above uses fakes)
uv run --no-project --with-editable . --with 'dagster>=1.13' python -c "
import dagster as dg
from dagster_dex import DagsterProject, tier_of

@dg.asset(metadata={'layer': 'silver'})
def dim_date(): ...

p = DagsterProject.from_asset_graph([dim_date], name='demo')
print(tier_of(p), [m.name for m in p.declarations().models])
"
```

All five run in CI on every pull request. `--with-editable` is not optional.

**If you touch `from_asset_graph`, run the Dagster check.** The suite uses
fakes so it can run without an orchestrator, which means it cannot see that
method breaking against the objects Dagster actually passes it.

## This repository is ASCII

**No em-dashes, no decorative emoji**, in code, comments, docs or commit
messages. `tests/test_ascii_only.py` enforces it over every tracked file, so a
violation fails CI rather than review.

It is not fussiness. The package summary once carried an em-dash; the metadata
was valid UTF-8 and PyPI rendered it correctly, but `pip show` on a Windows
console printed a replacement character instead. Exception messages have the same
problem and a worse blast radius, since they land in tracebacks people paste into
issues.

Use `-`, or restructure with a colon, a comma or parentheses. `=>` for arrows,
`...` for ellipses.

One file is exempt, and CI will fail if you "fix" it:
`scripts/check_closing_keywords.py` is a vendored copy compared byte-for-byte
against its source.

## Opening a pull request

- **Branch off `main`.** Please do not commit to `main` directly.
- **Conventional commit subjects** - `feat:`, `fix:`, `docs:`, `test:`, `chore:` -
  with a body explaining *why*, not what. The diff already says what.
- **Enable the commit hook once per clone.** It does not install itself:

  ```bash
  git config core.hooksPath .githooks
  ```

  It runs `scripts/check_closing_keywords.py`, which refuses a commit message
  where a `close`/`fix`/`resolve` verb sits immediately before `#N` unless that is
  deliberate. Only *adjacency* fires - "part of #N" and "refs #N" are safe.
  CI checks the same thing over the PR body, so forgetting the hook is caught,
  just later.
- **`scripts/check_closing_keywords.py` is a vendored copy** of a shared guard,
  present so the hook works offline. CI diffs it against its source and fails on
  drift, so please do not edit it here.

## What is likely to be accepted

- Bug fixes with a test that fails without them.
- A runnable example - there currently isn't one, and it is the clearest gap.
- Support for asset-graph shapes the reduction handles badly.
- Arguments, in an issue, about the tier boundaries. Tier 3 is declined for a
  stated reason, and the reason is arguable.

## What to discuss first

- Anything that adds a runtime dependency. The core is deliberately
  near-dependency-free.
- Anything that changes the `ProjectSource` / `FingerprintedProject` /
  `EditableProject` protocols, or the conformance contract. Those are a public
  interface other formats are meant to implement against.
- Anything that widens what `dex.py` is allowed to reach for upstream.

## Code of conduct

By participating you agree to the [Code of Conduct](CODE_OF_CONDUCT.md).
