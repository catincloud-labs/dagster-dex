# Contributing

Contributions are welcome. This is a small, one-maintainer project, so the most
useful thing to do first is **open an issue** - a design disagreement is worth
more here than a patch, and the seam follows semantic versioning, so a breaking
change to it waits for 2.0 (README, *Status*).

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

Every command the suite runs has one home, in `AGENTS.md`, and this file
links to it rather than carrying a copy:

- [*Running the suite*](AGENTS.md#running-the-suite): the three pytest steps,
  the control first, then the checks that are not pytest - the type check, the
  coding standard, and the `examples/` that run against real Dagster objects
  and a real warehouse.
- [*The two drivers*](AGENTS.md#the-two-drivers-and-why-passing-the-contracts-is-not-enough):
  the two end-to-end checks that drive dex through the built wheel, one for the
  read path and one for the write path.

Each command there runs verbatim from the repository root, and each one runs in
CI on every pull request. `tests/test_documented_commands.py` parses the
commands in every tracked markdown file and refuses a malformed one, or one
naming a script that does not exist.

This section carried its own copy of those commands until 2026-10-30, so each
had two homes, and the copy had fallen behind: it did not list
`examples/write_project_artifact.py`, which CI runs, or the coding-standard
check. Earlier still, it inlined an eight-line `python -c` script standing in
for `examples/reduce_asset_graph.py`. That script worked, which is why it
survived, and it was a second copy of a check that already had a home.

=> **A command in a document is a claim, and a second copy is a second claim
that nothing keeps in step with the first.**

**If you touch `from_asset_graph`, run the Dagster check**
(`examples/reduce_asset_graph.py`, in *Running the suite*). The suite uses
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

No file is exempt. `scripts/check_verification_section.py` was, until
2026-09-07: a vendored copy compared byte-for-byte against its source, which
could not be reformatted here without failing that comparison. Its source was
scrubbed to ASCII and re-vendored (#85), as the closing-keyword guard and its
self-test had been on 2026-09-04 (#77), and the skip set in
`tests/test_ascii_only.py` left with it: a non-ASCII byte arriving in a
re-vendor is a defect at the source, and that test is the first to see it.

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
- **From a fork, what happens next depends on whether you hold write access
  here.** Either way, `pr-hygiene`'s step `Exactly one deploy label` refuses a
  pull request carrying no `deploy:` label, and a label change re-runs the step
  with no push needed. The red run from before the label stays listed beside
  the green one, and the latest run is the one that counts.
  - **Without write access, that red is expected until the maintainer has
    looked at your pull request.** Applying a label takes triage access, so
    nothing on your side clears it: the maintainer applies a label at triage.
    Until a commit or pull request of yours has been merged here, every
    workflow run, that one included, also waits for approval from someone
    with write access here before it starts, because this repository requires
    approval for first-time contributors and GitHub counts you as one until
    that merge.
    While a run waits, its checks read as awaiting approval rather than red.
  - **As a collaborator, holding write access, you apply your own `deploy:`
    label and a `review:` clock** when you open the pull request. The
    template's checklist says which `deploy:` value applies here, and the
    clock is `review:this-week`, the default for a fix or small docs, unless
    the maintainer sets another. The label descriptions are written for
    several repositories, so take the values from here rather than from
    them. Your runs should start without
    approval: on #135, the first pull request here from a collaborator's fork,
    they started at once, before its author had anything merged here. GitHub's
    documentation of the approval setting names only a prior merge as the
    exemption, so that is one observation, not a documented rule.

  In both cases CI runs on the `pull_request` event: every workflow file in
  `.github/workflows` that runs on a pull request is triggered by it. From a
  fork, GitHub gives such a run a read-only token and no repository secret,
  whoever the author is, so write access changes who labels the pull request
  and whether a run waits, not what such a run can do. GitHub's CodeQL
  default setup also runs on pull requests here, as its own event with no
  file in that directory; it did not run on #135.
- **From a fork in your personal account, please tick the box that lets
  maintainers edit your branch** when you open the pull request. It lets
  anyone with write access here push to your branch, so a small fix a review
  asks for can land as a commit rather than a round trip through you. A fork
  of this repository carries its workflows, so GitHub labels the box *Allow
  edits and access to secrets by maintainers*, and warns that ticking it also
  lets them edit your fork's workflows, which can reveal that fork's secrets
  and give access to its other branches. GitHub offers the box only on a fork
  in a personal account: #135 came from a fork owned by an organization, so it
  had no such box, and a change its review asked for could be pushed only by
  someone with access to that fork.
- **Approval and merge are separate, and every merge into `main` is the
  maintainer's.** A pull request from anyone but the maintainer needs an
  approving review from a code owner of each file it changes.
  `.github/CODEOWNERS` names the maintainer on every path, and a second code
  owner beside the maintainer on the seam files: there, either one's approval
  counts, and any other path needs the maintainer's. Since 2026-10-20 a
  repository ruleset lets only the maintainer update `main`, so once your pull
  request is approved it waits for the maintainer to merge it, and write access
  does not change that. Anyone can read the two rules this rests on, with no
  account at `https://api.github.com/repos/catincloud-labs/dagster-dex/rules/branches/main`
  or signed in with `gh api repos/catincloud-labs/dagster-dex/rules/branches/main`:
  the review is the `pull_request` rule's `require_code_owner_review`, and the
  restriction is the `update` rule. That output does not say who is exempt from
  either rule (the maintainer's own pull requests merge without a review that
  way), and GitHub returns a ruleset's bypass list only to a reader who can
  edit the ruleset.
- **`scripts/check_closing_keywords.py` and `scripts/check_pr_title.py` are
  vendored copies** of shared guards - the first so the hook works offline, the
  second because a public repository cannot call the private shared action.
  Both are diffed against their sources from the private side, which fails on
  drift, so please do not edit either here.

## What review looks like

Review here re-runs your claims rather than reading them. From a clean
checkout of your pull request's head, the maintainer runs what its
*Verification* says you ran, and tries mutations of their own: small
deliberate breaks in the code or the test, to see whether the test goes red
on them.

A reading that cannot run from a clean checkout is welcome when it is listed
under the template's *Readings not reproducible from a clean checkout*, with
where it ran: a warehouse, a scratch harness, a credential. Listed there, it
tells the reviewer which claims rest on your word rather than on a re-run.
The dogfood runs in #135 were labelled this way.

Each requested change carries a priority:

- **P1:** the test can pass on a wrong result.
- **P2:** a statement that would be false, or permanent, once merged. Your
  pull request's title and body are each one: the maintainer merges your pull
  request as a squash, so its title, its number appended as `(#N)`, lands on
  `main` as the commit's subject and its body as the commit's message, as
  written. The commit subjects on your branch do not land on `main`.
- **P3:** clarity.

The changes come in two groups: what must change before approval, and what is
fine as follow-up issues, filed and linked from the pull request. Approval
follows the first group, and the merge stays the maintainer's, as the
*Approval and merge* bullet above says.
[The review of #135](https://github.com/catincloud-labs/dagster-dex/pull/135#issuecomment-6320793495)
is the model.

## What is likely to be accepted

- Bug fixes with a test that fails without them.
- A new leg in `examples/walk_the_whole_loop.py` for a case the loop does not
  reach yet. (This bullet used to say a runnable example was the clearest gap;
  every file in `examples/` is now executed by CI - and briefly said "two",
  a count the next example moved.) The README quotes some of the loop's
  output: if a leg it quotes changes what it prints, re-quote the README in
  the same change, or CI refuses it.
- Support for asset-graph shapes the reduction handles badly.
- Arguments, in an issue, about the tier boundaries. Where the write tier's
  scope sits - hand-written declarations can receive an edit, reduced models
  cannot - is a stated position, and positions are arguable.

## What to discuss first

- Anything that adds a runtime dependency. The core is deliberately
  near-dependency-free.
- Anything that changes the `ProjectSource` / `FingerprintedProject` /
  `EditableProject` protocols, or the conformance contract. Those are a public
  interface other formats are meant to implement against.
- Anything that widens what `dex.py` is allowed to reach for upstream.

## Code of conduct

By participating you agree to the [Code of Conduct](CODE_OF_CONDUCT.md).
