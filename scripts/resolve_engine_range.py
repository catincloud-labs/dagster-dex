#!/usr/bin/env python3
# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""Resolve the ENDS of the engine range this package publishes, by asking a resolver.

Run it:

    python scripts/resolve_engine_range.py

CI pins `exmergo-dex-core` to one exact version, deliberately, and `AGENTS.md`
explains why that pin and the published `[dex]` range are allowed to disagree.
What nothing checked is the range itself. The extra promises a compatible-release
specifier; every test ran at one point inside it. A consumer resolving the floor
got a combination this repository had never executed.

**The obvious fix is a list of versions in the workflow, and it is wrong.** A
hand-written `[a, b, c]` is a registry making a claim about a moving set: the day
upstream publishes a new patch, the promise widens and the matrix does not, and
nothing goes red - the workflow simply keeps testing the versions it always did.
That is the same failure shape `tests/test_pin_coherence.py` avoids by holding no
version literal, and this file holds none either. It reads the specifier the
package actually publishes and asks a resolver what satisfies it, so the matrix
tracks the promise instead of restating it.

**Why a resolver rather than the package index.** The floor is not simply the
lowest version the index holds that matches the string: a resolver also applies
`requires-python` and any yanks. Asking the thing that will actually run at a
consumer's desk is the point - a floor computed by our own arithmetic would be a
second implementation of resolution, and the two would disagree exactly when it
mattered.

**`--resolution lowest-direct` cannot be pointed at `.[dex]`, and this is
measured rather than predicted.** It applies to every direct requirement, so it
drags `pyyaml` to its own declared floor (`6.0`), which does not build on a
current interpreter, and the run dies before resolving anything. So the specifier
is extracted and resolved ALONE, and callers pin only the engine, leaving
everything else at the resolver's default.

Prints one JSON array on stdout, sorted and de-duplicated, ready for a
`strategy.matrix` via `fromJSON`. Everything else goes to stderr, so the output
is usable in a pipeline while still being readable by a human.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

#: The distribution whose range is being resolved. Named once, here, and the
#: version is never named at all - that is the whole point of the file.
PACKAGE = "exmergo-dex-core"

#: The extra that carries the engine. `pyproject.toml` is the single source; a
#: second copy of the specifier anywhere would be one more thing to go stale.
EXTRA = "dex"

#: Strip any extras marker (`pkg[a,b]>=1`) when matching the requirement to the
#: package name, so a future requirement naming an extra still resolves.
#: No example is spelled out here: `tests/test_pin_coherence.py` reads any
#: `<package><operator><version>` string in a tracked file as a real pin, and it
#: is right to - an illustrative version in a comment goes stale exactly like a
#: real one, and this file's whole claim is that it holds no version literal.
#: It caught this file on its first CI run.
_REQUIREMENT = re.compile(
    r"^\s*" + re.escape(PACKAGE) + r"(?:\[[^\]]*\])?\s*(?P<spec>[^\s;]+)"
)


def specifier() -> str:
    """The requirement string this package publishes for the engine."""

    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    try:
        requirements = data["project"]["optional-dependencies"][EXTRA]
    except KeyError as exc:  # pragma: no cover - a structural change, not a bug
        raise SystemExit(
            f"pyproject.toml has no [project.optional-dependencies].{EXTRA}; "
            "the extra was renamed or removed, and this script's premise with it"
        ) from exc

    matches = [r for r in requirements if _REQUIREMENT.match(r)]
    if len(matches) != 1:
        # Zero means the engine left the extra; two means an ambiguity a resolver
        # would silently pick a winner for. Neither is something to guess at.
        raise SystemExit(
            f"expected exactly one {PACKAGE} requirement in the "
            f"[{EXTRA}] extra, found {len(matches)}: {matches}"
        )
    return matches[0].strip()


def resolve(requirement: str, strategy: str) -> str:
    """Ask uv what version satisfies `requirement` under `strategy`."""

    result = subprocess.run(
        [
            "uv", "run", "--no-project", "--quiet",
            "--resolution", strategy,
            "--with", requirement,
            "python", "-c",
            f"import importlib.metadata as m; print(m.version({PACKAGE!r}))",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SystemExit(
            f"could not resolve {requirement!r} at --resolution {strategy}:\n"
            f"{result.stdout}\n{result.stderr}"
        )
    version = result.stdout.strip().splitlines()[-1].strip()
    if not version:
        # An empty answer must not read as "no versions to test". A matrix built
        # from nothing runs nothing and reports green, which is the fail-open
        # shape this whole file exists to avoid.
        raise SystemExit(f"{strategy} resolved {requirement!r} to an empty version")
    return version


def main() -> int:
    requirement = specifier()
    print(f"published specifier : {requirement}", file=sys.stderr)

    floor = resolve(requirement, "lowest-direct")
    ceiling = resolve(requirement, "highest")
    print(f"floor               : {floor}", file=sys.stderr)
    print(f"ceiling             : {ceiling}", file=sys.stderr)

    # Sorted for a stable matrix order, de-duplicated because a range with one
    # release in it is a legitimate state and should run one job, not two.
    versions = sorted({floor, ceiling})
    if floor == ceiling:
        print(
            "note                : the range holds a single release, so the "
            "matrix is one job. That is correct, not a misconfiguration.",
            file=sys.stderr,
        )
    print(json.dumps(versions))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
