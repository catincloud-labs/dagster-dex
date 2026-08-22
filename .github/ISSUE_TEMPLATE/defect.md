---
name: Defect
about: Something behaves differently from what it says it does
title: ""
---

<!--
You do not need any access to this repository to help here. It is public: fork
it, push a branch to your fork, and open a pull request. A fork's branch gets
the full test suite. Filing an issue first is welcome but not required.

A bare `#NNN` means this repository.

Do not pair a close/fix/resolve verb directly with an issue reference unless you
mean to close it, since that fires from an issue body too. Write "part of" or
"refs" instead. Do not hunt for a gentler verb: the words for fixing a bug are
the reserved set, so a paraphrase lands on another one. Break the adjacency.
-->

## What you ran

<!--
Verbatim, please, including the command line. A retyped approximation of a
command is a different command, and the difference is usually the bug.
-->

```text

```

## What you expected, and what happened

<!--
Both halves. "It did not work" cannot be reproduced, and a stack trace without
the expectation cannot be judged - some tracebacks are the correct behaviour.
Paste the output rather than describing it.
-->

## Does it reproduce from a clean checkout?

<!--
Yes / no / did not try are all useful answers, and "did not try" is fine. If it
only reproduces against your own warehouse or your own project, say so - that
narrows the cause more than a clean repro would, and it tells us the bug is in
the seam rather than in the package.
-->

## Versions

<!--
`dagster-dex`, Python, and whichever of dex-core and Dagster your case touches.
`pip show dagster-dex exmergo-dex-core dagster` covers it in one command. Please
paste it rather than summarising: a version range is not a version.
-->

```text

```

## Where you think the boundary is, if you have a view

<!--
Optional, and useful even when wrong. This package adapts a project format for
an engine it does not own, so a defect can live in our adapter, in the engine,
or in the contract between them. A guess here is a pointer, not a commitment,
and saying "no idea" is a perfectly good answer.
-->
