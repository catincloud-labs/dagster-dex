# Design documents

A document here describes how part of this package works today, and decides
nothing. Each decision it touches links to where the decision is made (the
top-level `README.md`, `AGENTS.md`, a module docstring, `CHANGELOG.md`), so a
rule has one home and a change to it is made there.

## The header

Three bullets come first after the title:

```markdown
- **Status:** living
- **Describes:** `src/dagster_dex/project.py`, `src/dagster_dex/dex.py`
- **Reviewed:** 2026-10-30 at `c4e8231`
```

- **Status** is `living`, `frozen` or `dead`, as the first word. A `living`
  document is kept true as the code moves. A `frozen` one is a record of a
  moment, and a `dead` one names what replaced it.
- **Describes** names, in backticks and from the repository root, the files
  the document is about. A change to one of them is the moment to re-read the
  document.
- **Reviewed** is the date and the commit the document was last checked
  against.

A bullet may run on to lines indented two spaces. When a document goes out of
date it is rewritten to state the present, and the text it replaces moves to
`CHANGELOG.md`; old text is not kept beside new text.

## What is checked

`tests/test_design_docs.py` reads every document in this directory except this
one. It requires the three bullets and a known Status, that every path on the
Describes line exists, that every backticked `dagster_dex.<module>.<name>` the
document mentions resolves to an attribute of that module, and that every
relative link reaches a file and, where it names one, a heading. It cannot
check that the prose is true; re-reading against the code is what the
Reviewed line records.
