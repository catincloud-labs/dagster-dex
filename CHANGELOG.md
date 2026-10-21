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

## Unreleased

### Added

- **A reconcile splice is pinned to lose only the comments on the lines it
  replaces** (`tests/test_dex_bridge.py`, #88). The test #94 added for #88
  covers `key_lost_uniqueness`, an insertion, which loses nothing, so it could
  not tell a splice from a reprint that happened to keep the comments. The new
  class covers the three schema codes upstream splices since exmergo-dex-core
  1.10.0 (`column_added`, `column_dropped`, `nullability_changed`) and names
  the comment, if any, each case is expected to lose, which is the falsifier
  #88 asked for. Each case also asserts that its edit landed: the column is
  added or dropped, or its `not_null` is removed or added. Below 1.10.0 each
  case is asserted advisory with the file unchanged. Both arms are chosen by
  installed engine minor with no skip, the same shape as #94. This change touches that test file and this changelog and
  nothing else, so the package, its seam, its engine floor and the tested pin
  do not change.

## 0.6.6 - 2026-10-21

Six fixes to the declaration parser (#131), and two to tests (#128, #136),
which reach the sdist's `tests/` but neither the wheel nor an installed copy.
Every entry is a fix. Under `src/`, only `declarations.py`, the docstring of
`DeclaredJoin` in `model.py` and the version string changed, every name added
or removed in `declarations.py` is private, and `pyproject.toml` moved only its
version, so the seam and the engine floor are where 0.6.5 left them. That was
measured at the bump, and anyone can re-run it as `git diff v0.6.5..v0.6.6 --
src/ pyproject.toml`. The tested pin is written outside both, and is where
0.6.5 left it too: `git diff v0.6.5..v0.6.6 -G 'core==[0-9]' --name-only`
prints nothing. A patch exists because an installed copy sees a fix only as a
new version. No public name, signature or dataclass field changed, but five of
the parser fixes change the keys or joins a project reports and the sixth adds
a note, and each entry says so in bold.

**One change argues for a minor, and does not decide it.** A join's
`to_model` can now name a source, as `<source>.<table>`, where 0.6.5 read a
`relationships` test whose `to:` is a `source()` as no join (that test's entry
below). A consumer that took `to_model` to name a model now meets one naming a
table the project does not build, which `DeclaredJoin`'s docstring now says.
It is not a minor here. The field is a string as it was. The new value is
reached only from a declaration 0.6.5 already noted as naming no resolvable
model and column. It is the name exmergo-dex-core's own schema-YAML reader
gives the same declaration, read at 1.8.0 and at 1.15.2 for this bump. And
this release does neither thing that made an earlier release a minor: 0.5.0
and 0.6.0 raised the engine floor, and 0.2.0 to 0.4.0, on an unchanged floor,
added to the public surface. It is a patch as 0.6.4 and 0.6.5 were, whose
fixes also changed which keys and joins a project reports.

Of the three disagreements with exmergo-dex-core's reader that 0.6.5's lead
names, two now read as that reader reads them: a bare model name in `to:`, and
a column's `unique` written twice. Of the third, a `combination_of_columns` of
`[a, 1]` or `[a, b, 1]` now reads as that reader reads it, and `[a]` still
reads as a key on `a`, kept while exmergo/dex is asked (exmergo/dex#768). A
test entry dbt refuses for its keys, which that reader reads, is still
skipped, now with a note, kept the same way (exmergo/dex#767). Those are not
the only differences 0.6.6 ships: `[a, b, '']`, which the first composite
entry below names, still reads as a key on `(a, b)` where that reader reads
`(a, b, '')`, and is not ruled.

### Fixed

- **The ASCII test passed a tracked file that did not decode as UTF-8**
  (`tests/test_ascii_only.py`, #128). It skipped the file whole, so a lone
  `0x97`, which is how cp1252 writes an em dash, passed the test written to
  refuse em dashes, and also hid any valid U+2014 elsewhere in the same file.
  The test now reads each tracked file as bytes and decodes it a line at a
  time. A line that does not decode is reported by each byte above `0x7F`
  and its offset in the file, and a tracked file that cannot be read is
  reported rather than passed. It lists files with `git ls-files -z`, so a
  file whose name git would quote, such as one holding a byte above `0x7F`,
  is read rather than skipped. The issue's four arms are now self-tests that
  go through the function the test calls, with a fifth for a line holding
  both kinds of byte. This change touches that test and this changelog and
  nothing else, so the installed package, its seam, its engine floor and the
  tested pin do not change.
- **A composite key listing something other than a column name was read as a
  key on its names alone** (#131). A `combination_of_columns` of `[a, 1]`
  read as a key on `a`, and one of `[a, b, 1]` as a key on `(a, b)`: a key on
  fewer columns than the test checks, which claims more than the test does.
  That held beside the test's name, and since 0.6.5 under `arguments:` and
  beside a `test_name:` too. exmergo-dex-core's schema-YAML reader takes a
  composite only from a list of two or more columns that are all strings, so
  it reads no key from either. Such a list now reads as no key here, and is
  noted. **A project with such a list will now report one key fewer, and a
  note it did not carry**, through `declarations()` and on to dex's
  `definitions()`. A list of one name, `[a]`, still reads as a key on `a`,
  where that reader reads none: the owner kept it here while exmergo/dex is
  asked. A list holding an empty string is not covered, because an empty
  string is a string: `[a, b, '']` still reads as a key on `(a, b)`, where
  that reader reads `(a, b, '')`. That is not ruled.
- **A `relationships` test whose `to:` is a bare model name was read as a
  join to that model** (#131). `to: customers` read as a join to `customers`,
  beside the test's name, and since 0.6.5 under `arguments:` and beside a
  `test_name:` too. dbt keeps a bare `to:` as the string and draws no edge to
  it, and exmergo-dex-core's schema-YAML reader takes `to:` only as a `ref()`
  or a `source()`, so it reads no join. Such a test now reads as no join here,
  with the note every other unread target gets: that the relationship names
  no resolvable model and column. **A project whose `to:` names a model bare
  will now report one join fewer, and that note**, through `declarations()`
  and on to dex's `definitions()`. A semantic model's `model:` is read as it
  was, a bare name included.
- **A `relationships` test whose `to:` is a `source()` was read as no join**
  (#131), and noted as naming no resolvable model and column. exmergo-dex-core's
  schema-YAML reader reads `to: source('s', 't')` as a join to `s.t`, the
  source and its table joined by a dot: beside the test's name at every
  release #131 measured, and under `arguments:` from 1.13.1 (exmergo/dex#566).
  dbt makes the test depend on that source. The same join is now read here, in
  each form this parser reads, so a join's `to_model` can name a source rather
  than a model the project builds, and `DeclaredJoin`'s docstring says so.
  **A project whose `to:` names a source will now report a join it did not
  report before, and one note fewer**, through `declarations()` and on to
  dex's `definitions()`.
- **A model declaring two composite keys was read as declaring the first
  alone** (#131). dbt runs both tests, and exmergo-dex-core's schema-YAML
  reader reads both. `maintain reconcile` reads the grain through
  `definitions()`, so with the second unread it would propose a column-level
  `unique` on one of its columns, a key the project never declared, where it
  declines that edit when the grain is read; #117's entry under 0.6.4 is the
  same defect for the prefixed spelling. Every composite key on a model is
  now read, in order. One set of columns is read once, compared without
  order or case as that reader compares them, whether it is written again in
  the same entry or in another entry or file that declares the model, as
  that reader reads across files. A column-level `unique` in the same entry
  is still dropped with the note that the composite wins. **A project
  with a model declaring two composite keys will now report a key it did not
  report before**, through `declarations()` and on to dex's `definitions()`.
- **A column's `unique` written twice was read as two keys on that column**
  (#131). Written bare twice, it was read so in 0.6.4 too, on a file dbt
  refuses. Written once bare and once by `test_name:`, or twice by
  `test_name:`, it was read so since 0.6.5, on a file dbt parses into two
  tests. exmergo-dex-core's schema-YAML reader reads one key per model and
  column, and 0.6.4 already read a `unique` written under both `tests:` and
  `data_tests:` once. A column's `unique` is now one key however often it is
  written: on a column listed twice, or in another entry or file that
  declares the model, included. **A project that writes a
  column's `unique` twice will now report one key where it reported two**,
  through `declarations()` and on to dex's `definitions()`.
- **A test entry dbt refuses for its shape was skipped with no note** (#131).
  A test written as a mapping of two or more keys with no string
  `test_name:` naming it, such as a test with its `config:` beside its name
  rather than inside it, or a `test_name:` that is not a string beside the
  test's own key, makes dbt refuse the project. The parser skipped it silently, against this
  module's rule that input it skips is noted. exmergo-dex-core's schema-YAML
  reader reads the test among the keys, on purpose (exmergo/dex#566), so the
  two still disagree here: the owner kept the skip while exmergo/dex is
  asked. The entry is still skipped, and now noted once with its keys. A
  mapping of one key, or an empty one, reads as it did. **Nothing
  a project declares changes; it gains a note for each such entry, one for
  entries alike in their keys and where they sit**, through
  `declarations()` and on to dex's `definitions()`, where `maintain
  reconcile` carries notes into its warnings.
- **The changelog test passed a version heading the release job cannot find**
  (`tests/test_packaging.py`, #136). It asserted the substring
  `## <version>`, where the `release` job in `publish.yml` greps for a line
  that starts with `## <version>` and has one space after the version, and
  runs after the upload. So a heading with no date, `## 0.6.5`, passed the test
  before the upload and gave that grep nothing after it. The test now reads
  the heading as the release job does, matching the version literally, and a
  failure names the heading it wanted. The file is read with its line
  endings as written, as grep reads it. The issue's three arms, a dated
  heading, one with no date and `## Unreleased`, are self-tests that go
  through the function the test calls, with two more that pin the line start
  and the literal version, and two that pin the line endings. This change
  touches that test and this changelog and nothing else, so nothing the
  wheel ships changes.

## 0.6.5 - 2026-10-20

One fix to the declaration parser (#119), and a re-vendored dev-tool manifest
(#129) that reaches neither the wheel nor a consumer. Under `src/`, only
`declarations.py` and the version string changed, every name added there is
private, and `pyproject.toml` moved only its version, so the seam, the engine
floor and the tested pin are where 0.6.4 left them. That was measured at the
bump, and anyone can re-run it as `git diff v0.6.4..v0.6.5 -- src/
pyproject.toml`. A patch exists because an installed copy sees a fix only as a
new version. No public name or signature changed, but the fix changes what a
project reports, and its entry says so in bold: keys and joins written under
`arguments:` or named by `test_name:`, which 0.6.4 did not read, are now read.

**Reading those two forms also reaches three older rules of this parser, so
0.6.5 ships three disagreements with exmergo-dex-core's reader that 0.6.4 did
not have** (#131). The same three rules already disagreed with the reader in
0.6.4 on the flat forms it read: `[a]`, a bare `to:`, and `unique` written
twice. What is new is the shapes below, written under `arguments:` or in a test
named by `test_name:`, where 0.6.4 agreed with every engine #131 measured
(1.8.0, 1.13.0 and 1.15.1), because it read neither form. A
`combination_of_columns` of `[a]` or `[a, 1]` now reads as a key on `a`, and
one of `[a, b, 1]` as a key on `(a, b)`, where every engine reads none. A bare
model name in a `relationships` test's `to:` now reads as a join to that model,
where every engine reads none. A column's `unique` written once bare and once
by `test_name:` now reads as two keys on that column, where every engine reads
one. #131 asks whether to align each with the reader.

### Changed

- **The vendored `scripts/power_of_ten_requirements.txt` had its header
  sentence rewritten and its `ruff` and `mypy` pins moved.** This change
  touches that file and this changelog and nothing else, so the package, its
  seam, its engine floor and the tested pin do not change. The file is the
  dev-tool manifest that the `power of ten` job and the suite's type check
  install their tools from. It sits outside the package, and it is re-copied
  byte-for-byte from the canonical copy it is vendored from rather than edited
  here. The pins moved from ruff 0.16.9 and mypy 2.3.1 to ruff 0.17.1 and
  mypy 2.4.0. The header sentence that was replaced read, verbatim:

  > Both versions are the ones the record's readings were taken with, so the
  > day-one counts it prices are the counts this action reports.

  It held while the pins were the ones the file was vendored with in #80 on
  2026-09-06, ruff 0.16.6 and mypy 2.3.1. Its ruff half stopped being true on
  2026-10-01, when #106 moved ruff to 0.16.9 and left the sentence as it was.
  Its mypy half held until this change, read on 2026-10-18 against `main` at
  `e08df43`. The two sentences that replace it name no version, so a later
  bump of the pins cannot make them false.

### Fixed

- **A test's inputs under `arguments:`, and a test named by `test_name:`,
  were read as no key and no join** (#119). dbt asks for a generic test's
  inputs under `arguments:`, the form dbt-utils' README shows for
  `unique_combination_of_columns`, and merges that mapping over the keys
  beside the test's name, `arguments` winning. A test can also be named by a
  `test_name:` key beside the rest of its mapping. The declaration parser
  read inputs only beside the test's name, and a test only by its single
  key, so a composite key or a `relationships` join written either way, or a
  column-level `unique` named by `test_name:`, was read as nothing; where an
  input was written in both places, it read the one beside the name. It now reads both forms, with
  `arguments` winning, which is the rule exmergo-dex-core's schema-YAML
  reader follows from 1.13.1 (exmergo/dex#565). **A project that writes its
  tests' inputs under `arguments:`, or names its tests with `test_name:`,
  will now report keys and joins it did not report before**, through
  `declarations()` and on to dex's `definitions()`. On the eighteen cases
  #119's readings measure, the same YAML read as an uncompiled dbt project,
  this package now agrees with exmergo-dex-core's own reader from 1.13.1,
  read at every release through 1.15.1. It stops agreeing with that reader
  from 1.8.0 to 1.13.0, which the `[dex]` extra still admits and which reads
  neither form, on the eleven of those cases that use either form. 0.6.4's
  note for a composite key nested under `arguments:`, "a form not read yet",
  is retired with the form now read. An entry with no columns in either
  place keeps the note that it declares none.

## 0.6.4 - 2026-10-12

Three fixes to the declaration parser (#115, #117, #119), in four entries
because #115's takes two. Under `src/`, only `declarations.py` and the version
string changed, every name added there is private, and `pyproject.toml` moved
only its version, so the seam, the engine floor and the tested pin are where
0.6.3 left them. That was measured at the bump, and anyone can re-run it as
`git diff v0.6.3..v0.6.4 -- src/ pyproject.toml`. A patch exists because an
installed copy sees a fix only as a new version. No public name or signature
changed, but two of the fixes change what a project reports, and each says so
in bold below: keys and joins a project declared and this package did not
read are now read, and #115's also adds two notes. The third changes one
note's text.

### Fixed

- **Every `data_tests:` list was read as nothing, with no note** (#115). dbt
  reads an entry's tests under `tests:` or `data_tests:`, its current
  spelling. The declaration parser read `tests:` alone, at every engine and
  whoever wrote the list. `maintain reconcile` writes that spelling itself.
  From exmergo-dex-core 1.10.0 it follows a file's `data_tests:` spelling and
  appends to an existing `data_tests:` list. From 1.12.7 (exmergo/dex#513) it
  also writes `data_tests:` into a file with no spelling to follow, where
  1.12.6 wrote `tests:`. Each such proposal was written and applied through
  the write tier, and the project went on describing itself as if the key
  were not declared. The parser now reads both keys, on a model and on a
  column. **A project that spells its lists `data_tests:` will now report
  keys and joins it did not report before**, through `declarations()` and on
  to dex's `definitions()`.
- **An entry declaring both `tests:` and `data_tests:` is read as the union,
  and noted with the remedy, rather than refused.** `tests` comes first, and
  an identical entry under both is read once. The note says to keep one key,
  because dbt refuses such an entry when `tests` lists anything, and dex-core
  1.12.7 refuses to edit a file that carries one. Reconcile can create one: at
  1.8.0, a `unique` added to a column with a `data_tests:` list lands in a
  separate `tests:` list beside it. A test key holding something other than a
  list or nothing is now noted and ignored, where it was ignored silently.
- **A composite key spelled `dbt_utils.unique_combination_of_columns` was
  read as no key, with no note** (#117). The declaration parser read a
  model-level composite key under the bare test name alone, under `tests:`
  and `data_tests:` both, and the prefixed name is the spelling dbt-utils
  documents for its own test. It now reads the bare name or any name ending
  in `.unique_combination_of_columns`, which is exmergo-dex-core's own rule
  for schema YAML (`exmergo_dex_core/dbt_project.py` in 1.12.7), so a prefix
  naming another package is read too. `maintain reconcile` reads the grain
  through `definitions()`, so with the key unread, at 1.8.0 and at 1.12.7, it
  proposed a column-level `unique` on a column of that grain, a key the
  project never declared, where the bare spelling declines the edit and says
  why. **A project that spells its composite keys with a package prefix will
  now report keys it did not report before**, through `declarations()` and on
  to dex's `definitions()`. The form dbt-utils' README documents, with the
  columns nested under `arguments:`, is still not read, under either spelling
  of the test name and in `tests:` or `data_tests:`. The next entry says how
  it is noted.
- **A composite key with its columns nested under `arguments:` was noted as
  declaring no columns** (#119). That is the form dbt-utils' README shows,
  and the columns are there, one level down. It still reads as no key, under
  either spelling of the test name and in `tests:` or `data_tests:`, because
  exmergo-dex-core does not read it either: its schema-YAML reader takes
  `combination_of_columns` from directly under the test
  (`exmergo_dex_core/dbt_project.py` in 1.12.7). Reading it here alone would
  make `declarations()` and dex's `definitions()` disagree about the model's
  grain. The note now says the columns are nested under `arguments`, a form
  not read yet. An entry with no columns anywhere keeps the old note,
  including one whose `arguments:` lists none. **Nothing a project declares
  changes; only that note's text does.**

## 0.6.3 - 2026-10-09

Documentation and the release path. Nothing under `src/` changed but the
version string, and `pyproject.toml` moved only its version and a comment.
That was measured at the bump with the command the second correction below
names, not carried forward, and anyone can re-run it as `git diff
v0.6.2..v0.6.3 -- src/ pyproject.toml`. The seam did not move and nothing
here is breaking. A patch exists for two reasons: an index is immutable, so
the README rewrite below reaches the package's page on PyPI only as a new
version; and this is the first release whose tag is signed (#112).

**Added.**

- **A release tag is signed by the maintainer, and the release refuses one
  that is not** (#112). The chain a stranger could check ran from the wheel to
  its PEP 740 attestation to `publish.yml` at the tag, and stopped at a tag
  object with no signature. `.github/allowed_signers` names the maintainer's
  public signing key. On a tag push, the first step after checkout in
  `publish.yml`'s `build` job runs `git verify-tag` against it and compares
  the name inside the signed tag with the ref. So an unsigned tag, a
  lightweight one, one signed by any other key, or a signed tag moved from
  another name stops the run before a test, a build or the `pypi` reviewer.
  The README's new *Verifying a release* section is the same check from a
  fresh clone. 0.6.3 is the first signed release. 0.6.2 and every tag before
  it stay unsigned, because a signature added now would vouch for them after
  the fact, not at their release. Nothing changes at install time, and commits
  are not signed.

**Changed.**

- **The README opens with what the package does for a Dagster user, and
  shows it** (#109). It is also the package's page on PyPI, so its first
  screen is the package's first screen. The first sentence is the repository's
  About line rather than a description of the format, and after the install
  comes a short excerpt of what `examples/walk_the_whole_loop.py` prints
  against a local DuckDB warehouse, with the command that prints it. The
  excerpt is a copy of output, so it is held to the run: the CI step that runs
  the example captures its output, and `scripts/check_readme_excerpt.py`
  refuses any quoted line the run did not print.
- **The README's `## Status` says only what is true now**, and the history it
  narrated is recorded here (#109). Four passages there described what earlier
  text had said. Three predate the first tag, since the repository's first
  commit already carried them, so no release made those changes; the fourth
  was made in 0.2.0. A released entry is history and is not rewritten, so all
  of it lands in this section:
  - **The entry point was inert, then registered wrong**, before the first
    tag. Status once ended *"nothing resolves it today, and an entry point
    nobody looks up is inert."* dex-core 1.6.0 added resolution for the
    `exmergo_dex_core.projects` group on 2026-08-08, through
    exmergo/dex#171, which this package's constraint shaped: a host reaching
    dex as a subprocess cannot hand an object in, so name resolution was the
    only door that worked. The paragraph announcing it then ended *"what is
    left between here and a resolvable format is packaging, not design"*,
    written before anyone had run it. Resolution found the entry point and
    refused: it named the class, and dex-core's `ProjectFactory` calls what it
    resolves with a `ProjectContext`, so the context bound to `models`. Behind
    that, a bare `DagsterProject` was refused as *"missing name, definitions"*,
    because this package says `format`/`declarations()` where the seam says
    `name`/`definitions()`. Both were fixed by registering
    `dex:project_from_context`, which wraps the project. The lesson the
    passage carried: a declared-but-unresolved extension point is not
    evidence that registration works, because there is no moment before the
    first lookup at which it can fail.
  - **A hand-counted end-to-end result**, before the first tag. Status gave a
    model count, a source count, semantic models and metrics from dex driven
    as a subprocess against a private asset graph. True where it was written,
    unverifiable anywhere else, and four numbers in a document. It was
    replaced by the table of what CI verifies on every commit, which anyone
    can re-run.
  - **An import-time figure from a private project**, removed in 0.2.0
    (#18) from the section on the two ways to name a project, the same
    defect as the hand count left standing a screen below it. What replaced
    it is where to take the number so it is true: time
    `dagster definitions list` against your own code location.

**Corrected.**

- **The 0.1.0 entry dates the entry-point fix to 0.2.0, and the published
  0.1.0 already carried it.** Read 2026-10-03 at the tag the wheel was built
  from: `git show v0.1.0:pyproject.toml` registers
  `dagster_dex.dex:project_from_context`, under a comment dating the
  correction 2026-08-08, and `git show v0.1.0:README.md` already says both
  gaps are fixed. The wheel on the index agrees: installed from PyPI, 0.1.0's
  `exmergo_dex_core.projects` entry point is
  `dagster_dex.dex:project_from_context`. The class-named registration that
  failed on first contact predates this repository's first commit (`1e414db`,
  which already registers `project_from_context`), so it was in no tagged
  tree and no wheel, and the "0.1.0" the entry says it was inert from is a
  version string that predates publication. Found while moving the README's account of the same history into the entry
  above. Dated here rather than edited there, for the reason the next
  correction gives.
- **The 0.6.2 entry's first claim - that no code path in the package changed -
  was false on the day it was written, and it shipped.** Measured after the
  release (2026-09-14): `git diff --stat v0.6.1..v0.6.2 -- src/` is five files,
  +177/-121, from two changes. The 2026-09-06 power-of-ten pass at class A
  (#80) split two functions so each reads under the ceiling, `_models_of` out
  of `artifact.loads` and `_absorb_source_tables` out of
  `declarations.parse_source_declarations`, each keeping its refusals and
  notes in the same words; the same pass typed every method of the
  conformance contracts, gave `FingerprintedProjectContract` its own
  `make_project` signature narrowed to tier 2, and put a reason on each
  `type: ignore`. The 2026-09-06 docstring change (#84, for #83) removed the
  private figure the entry does describe. `protocol.py` is byte-identical
  between the tags and no public name moved, so the sentence the entry needed
  was "no behaviour changed": the suite is green at both ends and the
  defect-injection floor was re-measured at 5/5 on the post-#80 tree (#95).
  The claim was written into this section on 2026-09-09 (#92), three days
  after #80 had moved the code, and the cut on 2026-09-14 (#97) carried it
  forward without running the diff it asserts. A released entry is history,
  so the correction is dated here rather than edited there, the same shape as
  the 0.6.1 correction in the entry below. The check that would have caught
  both is one command, run before the version bump: `git diff --stat <last
  tag>..HEAD -- src/`.

## 0.6.2 - 2026-09-14

Documentation, one docstring and a scheduled workflow; no code path in the
package changed, the seam did not move, and nothing here is breaking. A patch
exists for two reasons: an index is immutable, so the docstring correction
below reaches an installed copy only as a new version; and this is the first
cut through the release job (#62), which has to produce its GitHub Release
with no step outside bump-and-tag before that issue can close.

**Added.**

- **The two contract files now run against `exmergo/dex` `main` daily, red-only**
  (`.github/workflows/upstream-main.yml`, #74). Green is reported nowhere; red
  opens one issue labelled `upstream:dex`, de-duplicated on the failing test id
  plus, for the coverage guard, the contract it names, quoting the assertion and
  the upstream commit range since the workflow's last green run. A consumer sees
  nothing of this in the wheel: it changes when a breaking upstream change is
  discovered here, from bump day to the morning after it merges.

- **A boundary test pins what a reconcile plan does to a hand-written
  declaration** (`tests/test_dex_bridge.py`, #88). Below dex-core 1.10.0 the
  plan content is a whole-document reprint and every comment in the file is
  lost on apply - reproduced on the wheel, which is the reason groundstation's
  harvest runbook carries its warning. From 1.10.0 the content is a splice into
  the original bytes and nothing is lost. Both arms are asserted, by engine
  version, with no skip, and the spliced `unique` test is read back as the same
  declared key as the reprinted one. Nothing under `src/` changed.

**Corrected.**

- **The 0.6.1 entry's first claim - that the shipped docstrings no longer quote
  private measurements - was false on the day it was written** (read
  2026-09-07). `src/dagster_dex/project.py` carried a timing taken against a
  deployment nobody outside this project can reach, in the `declarations()`
  docstring, since before 0.6.1; the change that entry describes edited the
  same file and left it (#52, #83). The figure is removed in this change. The
  design reason it illustrated stays, without a number: memoising the result
  avoids re-parsing the declaration files several times per command.
- **The same 0.6.1 entry restates a removed figure in the sentence announcing
  its removal.** A released entry is history and is not rewritten, so both
  corrections are dated here rather than edited there. The property alone was
  the claim worth publishing; the number belongs where it was taken (#83).

## 0.6.1 - 2026-08-27

Documentation only: no code path changed, the seam did not move, and nothing
here is breaking. A patch exists because an index is immutable - the
corrections below landed on `main` the day after 0.6.0 shipped, and an
installed copy only sees them as a new version.

**Changed.**

- **The shipped docstrings no longer quote private measurements.** `artifact.py`
  and `dex.py` carried ~2.6 s timings taken against a deployment nobody outside
  this project can reach. The figures are replaced by the property they
  illustrated - a live-graph reduction costs an import, whole seconds against a
  file read's milliseconds - and by where to take the number so it is true:
  time `dagster definitions list` against your own code location. The README
  had already made this move; the docstrings had not.
- **The distribution stopped describing the write tier as declined by
  design.** The write path shipped in 0.4.0; docstrings and the comment
  justifying the Alpha classifier in `pyproject.toml` still carried the older
  claim. Each site is retired in place with a date rather than deleted
  (#52, #60). The decline that remains - the artifact-only, read-only arm -
  is real and documented as exactly that.
- **The README states the format's boundary up front** - one orchestrated
  asset graph, never a sibling project in another format; where two projects
  meet, the warehouse is the join - and documents two contracts of the
  `artifact:` + `declarations:` combination: an empty declarations directory
  is accepted, because a consumer's provisioning order can create it before
  its first content, and the directory's parent becoming the project root is
  a guarantee, stable at least until 1.0.
- **The artifact-writer sketch in the README is executed by CI**
  (`examples/write_project_artifact.py` runs the same op body), so its old
  disclosure that "nothing runs it" is retired along with the gap it
  described. The schedule *values* stay placeholders on purpose: scheduling
  is a decision, and a library that made it for you would be wrong in every
  deployment that differs.

## 0.6.0 - 2026-08-26

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
