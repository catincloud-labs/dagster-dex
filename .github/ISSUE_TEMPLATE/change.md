---
name: Change or chore
about: Propose work - a feature, a refactor, a packaging or CI change
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

## TL;DR

<!-- What should change, and why it is worth doing now rather than later. -->

## Current state

<!--
Verbatim where you can: the code that ships, the output, the error. "Reads the
code that ships" is the standard here, because a plan derived from what the code
appears to intend has been wrong often enough to be a rule.
-->

## Proposed change

<!-- Concretely what you would do. A checklist is fine and usually better. -->

- [ ]
- [ ]

## How we would know it worked

<!--
The check, and how it could FAIL. A control added without a case that violates
it looks identical to a control whose violation silently passes - so name the
violating case, not only the passing one. If the verification needs something
not in this repository (a live warehouse, a billed query, a release of something
upstream), say so up front: that is a cost, and it changes the priority.
-->

## What it costs

<!--
A dependency, a slower test run, a foreclosed option, work that now has to
happen in a particular order. "None" is a valid answer and an unusual one.

Two costs specific to this package, worth checking before you propose:

- It is ASCII, and a test enforces that over every tracked file. A change
  introducing an em-dash or an emoji fails CI rather than being tidied later.
- Its public claims have to be reproducible from a clean checkout by someone who
  has none of our infrastructure. A measurement taken against a private
  warehouse cannot ship, though the mechanism that took it can.
-->

## Explicitly out of scope

<!--
The adjacent thing you are NOT proposing, so the next reader does not assume it
was missed.
-->
