#!/usr/bin/env python3
# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""Hold the README's output excerpt to what the whole loop actually printed.

Run it on a captured run of the example:

    python scripts/check_readme_excerpt.py whole-loop.txt

The README's first screen quotes lines `examples/walk_the_whole_loop.py`
prints (#109), because a reader should see what the package produces before
deciding to install it. **A quote of output is a copy, and a copy is the shape
this repository's documents keep going stale in**: the example's printed line
changes, the README does not, and nothing goes red. CI runs the example on every
pull request anyway, so its step captures the output and this file refuses any
excerpt line the run did not print, verbatim and as a whole line.

Whole lines, not substrings, because a substring match would pass a quote that
is only part of a printed line - for instance one left behind when the
example's line grew - and it would still read as checked. A line quoted twice
is refused too: it pads the excerpt without holding anything more.

What this does NOT hold: the prose beside the excerpt, which leg each quoted
line belongs to, and any fence the marker does not name. Those are read, not
checked.

The excerpt is found by its marker comment rather than by position, and EXACTLY
ONE marked block must exist. A guard that found no block would check nothing
and pass, which is indistinguishable from a README that agrees with its example,
so a missing or doubled marker is a refusal rather than a quiet pass.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

#: The comment that sits on the line above the excerpt's fence. Matched as a
#: line prefix, so the comment can say more after it without moving the anchor.
MARKER = "<!-- excerpt: examples/walk_the_whole_loop.py"

OPEN_FENCE = "```text"
CLOSE_FENCE = "```"


class ExcerptNotFound(Exception):
    """The README does not carry exactly one marked, non-empty excerpt."""


def excerpt(readme: str) -> list[str]:
    """The excerpt's lines, right-stripped, in order.

    Refuses rather than returning an empty list, because an empty excerpt
    would make every run agree with it.
    """
    lines = readme.splitlines()
    marks = [i for i, line in enumerate(lines) if line.startswith(MARKER)]
    if len(marks) != 1:
        raise ExcerptNotFound(
            "expected exactly one line starting %r in the README, found %d"
            % (MARKER, len(marks))
        )
    start = marks[0] + 1
    if start >= len(lines) or lines[start].strip() != OPEN_FENCE:
        raise ExcerptNotFound(
            "the marker must sit directly above a %r fence, so the block it "
            "names is not a matter of interpretation" % OPEN_FENCE
        )
    body: list[str] = []
    for line in lines[start + 1:]:
        if line.strip() == CLOSE_FENCE:
            break
        body.append(line.rstrip())
    else:
        raise ExcerptNotFound("the excerpt's fence is never closed")
    quoted = [line for line in body if line]
    if not quoted:
        raise ExcerptNotFound("the excerpt is empty, so it would agree with any run")
    repeated = sorted({line for line in quoted if quoted.count(line) > 1})
    if repeated:
        raise ExcerptNotFound("a line is quoted more than once: %s" % "; ".join(repeated))
    return quoted


def missing(quoted: list[str], output: str) -> list[str]:
    """Every quoted line the run did not print as a whole line."""
    printed = {line.rstrip() for line in output.splitlines()}
    return [line for line in quoted if line not in printed]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("output", type=Path, help="captured stdout of the whole loop")
    parser.add_argument("--readme", type=Path, default=REPO_ROOT / "README.md")
    args = parser.parse_args(argv)

    try:
        quoted = excerpt(args.readme.read_text(encoding="utf-8"))
    except ExcerptNotFound as exc:
        print("readme-excerpt CANNOT CHECK: %s" % exc, file=sys.stderr)
        return 1

    absent = missing(quoted, args.output.read_text(encoding="utf-8"))
    if absent:
        print(
            "readme-excerpt REFUSED: %d of %d quoted line(s) were not printed by "
            "this run of the whole loop:" % (len(absent), len(quoted)),
            file=sys.stderr,
        )
        for line in absent:
            print("  - %s" % line, file=sys.stderr)
        print(
            "Re-quote the README from a fresh run, in the same change that moved "
            "the example's output.",
            file=sys.stderr,
        )
        return 1
    print("readme-excerpt OK: all %d quoted line(s) were printed by the run" % len(quoted))
    return 0


if __name__ == "__main__":
    sys.exit(main())
