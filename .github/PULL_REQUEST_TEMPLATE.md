<!--
Delete any section that genuinely does not apply. An empty heading is worse
than no heading.
-->

## What changes

<!-- One paragraph. What is now true that was not true before. -->

## Why

<!-- The problem this resolves and how you know it is real. Link the issue. -->

## Verification

<!--
CI proves the checks passed. It cannot prove the checks test anything, and that
gap is where this estate's defects have actually lived. So:

- Paste output, do not paraphrase it, and run it in the session that writes it.
- A claim about another repository cites the file and says whether it was READ
  or RUN. Those are different claims and the difference matters.
- A claim about a decision cites the decision record, not a recollection of a
  conversation.
- A claim that a setting is in place says what BEHAVIOUR was observed. Reading
  a setting back proves it was stored, not that it does anything.
-->

**Dev:**

## Does the new control fire?

<!--
Required for any change adding a check, guard, gate, or test.

A control added without a case that violates it looks identical to a control
whose violation silently passes. Name the violating case and show it FAILING,
not just the correct one passing. Show it going quiet too - a guard that trips
on everything gets switched off, and a switched-off guard is the worse failure.

If this change adds no control, say "no new control" and move on.
-->

## What this costs

<!--
Every real change has a price: a dependency, a slower run, a foreclosed option,
work that now has to happen in a particular order. "None" is a valid answer and
an unusual one.
-->

## Issue references

<!--
A closing verb immediately followed by `#N` auto-closes that issue on merge,
whether or not you meant it, and backticks do not protect it - only adjacency
fires. "Part of #N" and "refs #N" are safe. Do not hunt for a gentler verb: the
words for fixing a bug are the reserved set, so a paraphrase lands on another
one. Break the adjacency instead.

When you DO mean to close something, list the exact set in `Autoclose:` so the
effect is stated rather than inferred.
-->

Part of #

Autoclose: none

## Checklist

- [ ] Conventional commit subject (`feat:`, `fix:`, `test:`, `docs:`, `chore:`)
- [ ] Branched off `main`, not committed to it directly
- [ ] No decision restated rather than cited
- [ ] Any new control ships with proof it can fire and proof it can go quiet
