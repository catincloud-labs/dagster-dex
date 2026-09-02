#!/usr/bin/env python3
"""A third-party action ref is a full commit with its version beside it, and the estate's pins are compared.

WHY THIS EXISTS (constellation's ADR-0040, ruled 2026-09-01). Every action
the estate did not write was referenced by a TAG - `actions/checkout@v4`,
`google-github-actions/auth@v3`, `tailscale/github-action@v4` holding the
tailnet credential. A tag is a mutable pointer owned by someone else: when it
moves, the code holding those secrets changes with no diff in the estate's
tree and no pull request. And with nobody owning the version, the estate ran
`actions/checkout` at `v4` in five repositories and `v7` in three, and
`astral-sh/setup-uv` at three versions across four, with nothing comparing
them. The estate's OWN actions had already been given both halves of this -
`pin-coherence` beside this file - and this is the other half: every
publisher the estate did not write.

TWO THINGS, ONE SCANNER

  The refusal (`--tree`), run in a caller's pull request against the tree it
  proposes. Every `uses:` site under `.github/` that names a third-party
  action must carry a forty-character commit AND a trailing comment naming
  the version, and the publisher must be one the record enumerates. A
  refusal names the file, the line, the ref and the publisher.

  The comparator (`--org` alone), run from `workbench` across the
  organisation. The population is DERIVED exactly the way `pin-coherence`
  derives it - the organisation's repository list, every
  `.github/**/*.yml|yaml` blob in each default branch, an unreadable
  repository a REFUSAL - by importing that module's readers rather than
  growing a second idea of what the estate is. The same refusal applies to
  every site it finds, which is what makes an unmigrated repository visible
  from here. Then the sites are grouped by action and by ref, and where one
  action sits at two refs the run says so, version labels side by side.

WHAT IS RED AND WHAT IS REPORTED - the one rule that differs from
`pin-coherence`, and deliberately:

  - An unpinned ref, a pin with no version comment, a publisher outside the
    enumerated set, a `uses:` this scanner cannot classify: RED. These are
    the record's constraint, and a guard that lets one through is decorative.
  - Zero third-party sites in a scanned surface: RED. Every workflow in this
    estate checks out, so an empty population means the matcher rotted or
    the scanner was pointed at the wrong directory - a finding either way.
  - Divergence - one action at two refs across repositories: REPORTED, as a
    `::warning::` annotation and a side-by-side table, exit 0. ADR-0040
    allows divergence and forbids silence about it; the mover is Dependabot
    grouped MONTHLY PER REPOSITORY, so two repositories at different commits
    for part of a cycle is the designed steady state, not a defect. A
    comparator red for that would be red most of the time, and a real
    refusal - a tag, a stranger's publisher - would arrive indistinguishable
    from the noise. The refusal keeps the exit code; the divergence keeps
    the annotation.

WHAT A GREEN HERE DOES NOT SAY. A pin proves the code does not change. It
does not say the code is benign, and it does not defend against a
compromised publisher at the pinned commit: the trusted-publisher set below
is the whole of that defence, and the record says so. Nor does it move a
pin. Dependabot does, per repository, and a pin without a mover is a frozen
vulnerability (ADR-0031).

THE PUBLISHER SET is enumerated in ADR-0040 from the estate's tree as read on
2026-09-01. Adding one is a decision: a dated line in constellation's
`docs/ORGANISATION.md` register, and then the line here that enforces it. The
register line is the argument and this set is the control; a publisher added
to one without the other is either a refusal with no record or a record with
no teeth, and both are visible - the first as a red run, the second in the
register's next reading.

The estate's own refs (`<org>/...`) are NOT this scanner's subject. They are
`pin-coherence`'s, which demands one commit estate-wide because its subject
is one guard the estate ships to itself. A local `./path` is not a ref at
all. Comment lines are not sites, and a trailing comment after a ref is where
the version lives.

Run bare, never through a pipe - the exit code is the product.

    python3 check_third_party_pins.py --org catincloud-labs --tree .
    GH_TOKEN="$(gh auth token)" python3 check_third_party_pins.py --org catincloud-labs
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Callable, Iterable, NamedTuple

# ADR-0040, Decision. From the estate's tree as read 2026-09-01. See the
# module docstring for what adding a name here requires.
TRUSTED_PUBLISHERS = frozenset(
    {
        "actions",
        "google-github-actions",
        "tailscale",
        "docker",
        "astral-sh",
        "aquasecurity",
        "hashicorp",
        "terraform-linters",
        "pypa",
    }
)

_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")

# A `uses:` line: optional list dash, the key, a value that may be quoted, and
# an optional trailing `# comment`. Anchored at the start, which does two jobs
# at once: a `uses:` inside a `run:` script's text is not a site, and neither
# is a commented-out line, because `#` is not whitespace. (An explicit
# comment-line skip used to sit beside this; a mutation pass showed the
# self-test could not tell it from the anchor, because the anchor already
# did its work.)
_USES_LINE = re.compile(
    r"""^\s*(?:-\s+)?uses:\s*(?P<q>['"]?)(?P<value>[^'"\s#]+)(?P=q)\s*(?:#\s*(?P<comment>.*?))?\s*$"""
)

# `owner/repo[/sub/path]@ref`. The owner and repository segments take
# GitHub's name alphabet; the sub-path is anything up to the `@`.
_ACTION_REF = re.compile(
    r"^(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+)(?P<sub>(?:/[^@\s]+)?)@(?P<ref>\S+)$"
)

# What a version comment starts with: `v4`, `v4.2.2`, `4.2.2`, `v1.14.2 (pypi)`.
_VERSION = re.compile(r"v?\d+(?:\.\d+)*")
_VERSION_COMMENT = re.compile(r"^v?\d+(?:\.\d+)*(?:$|[^\w.])")


class Refusal(RuntimeError):
    """Could not check. Which is not 'all clear', and never exits 0."""


class Site(NamedTuple):
    repo: str
    path: str
    lineno: int
    value: str  # the raw `uses:` value, quotes stripped
    comment: str  # the trailing comment's text, '' when absent


class ThirdParty(NamedTuple):
    site: Site
    publisher: str
    action: str  # owner/repo[/sub]
    ref: str


class Scan(NamedTuple):
    """What one pass over a corpus found, before it is judged."""

    third_party: list[ThirdParty]
    own: list[Site]  # `<org>/...` refs: pin-coherence's subject, not ours
    local: list[Site]  # `./path`: not a ref
    unclassified: list[Site]  # anything else: refused, never skipped


# --- scanning ------------------------------------------------------------------


def scan_text(repo: str, path: str, text: str) -> list[Site]:
    """Every `uses:` site in one file's text, with its trailing comment."""
    sites: list[Site] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        match = _USES_LINE.match(line)
        if match:
            sites.append(
                Site(repo, path, lineno, match.group("value"), (match.group("comment") or "").strip())
            )
    return sites


def classify(sites: Iterable[Site], org: str) -> Scan:
    """Sort every site into the estate's own, local, third-party, or unclassifiable."""
    third: list[ThirdParty] = []
    own: list[Site] = []
    local: list[Site] = []
    unclassified: list[Site] = []
    for site in sites:
        if site.value.startswith("./"):
            local.append(site)
            continue
        # `docker://image:tag` lands here too: `:` is outside the owner
        # alphabet, so the ref pattern cannot match it, and judge() names it
        # for what it is rather than as an unknown shape.
        match = _ACTION_REF.match(site.value)
        if not match:
            unclassified.append(site)
            continue
        owner = match.group("owner")
        if owner.lower() == org.lower():
            own.append(site)
            continue
        third.append(
            ThirdParty(
                site,
                owner,
                f"{owner}/{match.group('repo')}{match.group('sub')}",
                match.group("ref"),
            )
        )
    return Scan(third, own, local, unclassified)


def collect(
    repos: Iterable[str],
    yaml_paths_of: Callable[[str], list[str]],
    text_of: Callable[[str, str], str],
) -> list[Site]:
    """Scan every repository's YAML surface. A reader that raises is not caught.

    The readers are injected so the self-test can drive this with pure stubs,
    and so the organisation mode can hand in `pin-coherence`'s readers
    unchanged: one derivation of the estate, two scanners reading it.
    """
    sites: list[Site] = []
    for repo in repos:
        for path in yaml_paths_of(repo):
            sites.extend(scan_text(repo, path, text_of(repo, path)))
    return sites


def yaml_paths_under(root: Path) -> list[str]:
    """Every `.github/**/*.yml|yaml` file under one checked-out tree.

    The tree, never a filename: a call site is not confined to `checks.yml`,
    and this estate's register once gave a command that named one.
    """
    github = root / ".github"
    if not github.is_dir():
        raise Refusal(
            f"{root} has no .github directory, so there is no workflow surface "
            "to scan. Either this is not a checkout or the scanner was pointed "
            "at the wrong directory; a guard looking at nothing is not a guard."
        )
    found = sorted(
        p.relative_to(root).as_posix()
        for p in github.rglob("*")
        if p.is_file() and p.suffix in (".yml", ".yaml")
    )
    if not found:
        raise Refusal(
            f"{root}/.github holds no .yml or .yaml file at any depth. Nothing "
            "to scan is not the same as nothing wrong."
        )
    return found


# --- judging -------------------------------------------------------------------


def where(site: Site) -> str:
    return f"{site.repo}/{site.path}:{site.lineno}"


class Problem(NamedTuple):
    kind: str  # a key of EXPLANATIONS
    line: str  # one line naming the site, the ref and the publisher


# The reasoning behind each refusal, printed ONCE per kind under the sites it
# applies to. Twenty-two tag sites in one file are twenty-two lines and one
# paragraph, not twenty-two paragraphs.
EXPLANATIONS = {
    "zero-refs": (
        "Found ZERO third-party refs. Every workflow in this estate checks "
        "out, so either the surface scanned holds no workflows or this "
        "matcher no longer matches how `uses:` is written - both are "
        "findings, and neither is 'all clear'."
    ),
    "not-a-pin": (
        "A tag or a branch is a mutable pointer owned by someone else: when it "
        "moves, the code this workflow runs changes with no diff here and no "
        "pull request. Pin the 40-hex commit the tag resolves to, with the "
        "version as a trailing comment: `owner/action@<sha> # vN`. Resolve "
        "with `gh api repos/{owner}/{action}/git/ref/tags/{tag}` and "
        "dereference an annotated tag to its commit (ADR-0040)."
    ),
    "no-version-comment": (
        "A pin with no version comment. The comment is what a reviewer reads "
        "and what Dependabot maintains; without it a bump is a review of a "
        "hash. Write `# vX.Y.Z` after the ref."
    ),
    "comment-is-not-a-version": (
        "The trailing comment does not start with a version. The comparator "
        "reads that comment as the version label and Dependabot rewrites it "
        "as one; anything else there is prose where the version should be."
    ),
    "publisher-not-enumerated": (
        "The publisher is outside the set ADR-0040 enumerates. A pin proves "
        "the code does not change; the publisher set is the whole of the claim "
        "that it is worth running. Adding one is a dated line in "
        "constellation's ORGANISATION.md register and then a line in this "
        "scanner's TRUSTED_PUBLISHERS."
    ),
    "container-image": (
        "A `docker://` image is not an action, and ADR-0040 enumerates action "
        "publishers only. It is refused rather than waved through as out of "
        "scope: an image by tag is the same mutable pointer a tag is."
    ),
    "unrecognised": (
        "Not a `uses:` form this scanner recognises (owner/repo[/path]@ref, "
        "or ./local). Refused rather than classified as fine: an unknown "
        "shape is exactly where a scan narrows without anyone noticing."
    ),
}


def judge(scan: Scan) -> list[Problem]:
    """Every refusal in the corpus. Empty means every third-party ref is a pin."""
    problems: list[Problem] = []

    if not scan.third_party:
        problems.append(Problem("zero-refs", "nothing to judge"))

    for site in scan.unclassified:
        kind = "container-image" if site.value.startswith("docker://") else "unrecognised"
        problems.append(Problem(kind, f"{where(site)}: `{site.value}`"))

    for tp in scan.third_party:
        site = tp.site
        named = f"{where(site)}: {tp.action}@{_shown(tp.ref)} (publisher `{tp.publisher}`)"
        if tp.publisher not in TRUSTED_PUBLISHERS:
            problems.append(Problem("publisher-not-enumerated", named))
        if not _FULL_SHA.match(tp.ref):
            problems.append(Problem("not-a-pin", named))
        elif not site.comment:
            problems.append(Problem("no-version-comment", named))
        elif not _VERSION_COMMENT.match(site.comment):
            problems.append(Problem("comment-is-not-a-version", f"{named} `# {site.comment}`"))

    return problems


def _shown(ref: str) -> str:
    return ref[:12] + "..." if _FULL_SHA.match(ref) else ref


def _version_key(label: str) -> tuple:
    """`v10.0.1` after `v5`, not before it: numeric where the label is numeric."""
    match = _VERSION.match(label)
    if not match:
        return (1, label)
    return (0, tuple(int(n) for n in match.group(0).lstrip("v").split(".")), label)


def version_label(tp: ThirdParty) -> str:
    """What a human calls this ref: its comment for a pin, the ref itself for a tag."""
    if _FULL_SHA.match(tp.ref):
        match = _VERSION.match(tp.site.comment)
        return match.group(0) if match else "(no version comment)"
    return tp.ref


def divergences(third_party: Iterable[ThirdParty]) -> dict[str, dict[str, list[ThirdParty]]]:
    """action -> ref -> sites, for every action sitting at MORE THAN ONE ref.

    Keyed on the ref rather than the version label, because the ref is what
    runs. Tags are compared too: before a migration the divergence IS between
    tags, and the record's expected first cases are `actions/checkout` at
    `v4` / `v7` and `astral-sh/setup-uv` at `v5` / `v7` / `v10.0.1`.
    """
    by_action: dict[str, dict[str, list[ThirdParty]]] = defaultdict(lambda: defaultdict(list))
    for tp in third_party:
        by_action[tp.action][tp.ref].append(tp)
    return {action: dict(refs) for action, refs in by_action.items() if len(refs) > 1}


def render_divergence(action: str, refs: dict[str, list[ThirdParty]]) -> str:
    """One action's refs side by side: version label, ref, and who sits where."""
    lines = [f"  {action} is at {len(refs)} refs:"]
    for ref, members in sorted(refs.items(), key=lambda kv: _version_key(version_label(kv[1][0]))):
        labels = sorted({version_label(m) for m in members})
        per_repo: dict[str, int] = defaultdict(int)
        for m in members:
            per_repo[m.site.repo] += 1
        holders = ", ".join(f"{repo} ({n})" for repo, n in sorted(per_repo.items()))
        lines.append(f"    {' / '.join(labels):<16} {_shown(ref):<16} {holders}")
    return "\n".join(lines)


def emit_set(third_party: Iterable[ThirdParty]) -> list[str]:
    """Each repository's (action, ref # version) set, one line per distinct triple."""
    seen: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for tp in third_party:
        seen[(tp.site.repo, tp.action, tp.ref)].append(version_label(tp))
    return [
        f"  {repo}: {action}@{_shown(ref)} # {' / '.join(sorted(set(labels)))} ({len(labels)} site(s))"
        for (repo, action, ref), labels in sorted(seen.items())
    ]


# --- the two modes -------------------------------------------------------------


def scan_tree(root: Path, org: str) -> Scan:
    paths = yaml_paths_under(root)

    def text_of(_repo: str, path: str) -> str:
        try:
            return (root / path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise Refusal(f"could not read {path}: {exc}. An unreadable file is not a clean one.") from exc

    repo_name = os.environ.get("GITHUB_REPOSITORY") or root.resolve().name
    return classify(collect([repo_name], lambda _r: paths, text_of), org)


def scan_org(token: str, org: str) -> tuple[Scan, list[str], list[str]]:
    """(scan, repositories read, notes) - the population is pin-coherence's, imported."""
    sibling = Path(__file__).resolve().parent.parent / "pin-coherence"
    sys.path.insert(0, str(sibling))
    try:
        import check_pin_coherence as pc
    except ImportError as exc:
        raise Refusal(
            f"could not import pin-coherence's readers from {sibling}: {exc}. "
            "The organisation mode shares that module's population "
            "derivation by design and has no second one to fall back on."
        ) from exc
    try:
        repos, yaml_paths_of, text_of, notes = pc.make_readers(token, org)
        sites = collect(repos, yaml_paths_of, text_of)
    except pc.Refusal as exc:
        raise Refusal(str(exc)) from exc
    return classify(sites, org), repos, notes


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--org",
        required=True,
        help="the organisation: whose refs are 'our own' (excluded, pin-coherence's "
        "subject) and, without --tree, whose repositories are the population",
    )
    ap.add_argument(
        "--tree",
        metavar="DIR",
        help="scan one checked-out tree instead of the organisation (the guard, in a caller's pull request)",
    )
    args = ap.parse_args(argv)

    notes: list[str] = []
    repos: list[str] = []
    try:
        if args.tree:
            scan = scan_tree(Path(args.tree), args.org)
            mode = f"tree {args.tree}"
        else:
            token = os.environ.get("GH_TOKEN", "")
            if not token:
                print(
                    "third-party pins REFUSED: GH_TOKEN is empty or absent, so the "
                    "organisation cannot be read. A check that cannot look reports "
                    "red, never an empty success.",
                    file=sys.stderr,
                )
                return 1
            scan, repos, notes = scan_org(token, args.org)
            mode = f"organisation {args.org}"
    except Refusal as exc:
        print(f"third-party pins REFUSED: {exc}", file=sys.stderr)
        return 1

    problems = judge(scan)

    # The comparison is printed whether or not the run is red: mid-migration
    # the divergence is between tags, and that report is the record's second
    # box, wanted BEFORE the sets are made equal.
    split = divergences(scan.third_party)
    print(f"third-party pins: scanned {mode}")
    print(
        f"  {len(scan.third_party)} third-party site(s), {len(scan.own)} of the "
        f"estate's own (pin-coherence's subject, not judged here), "
        f"{len(scan.local)} local path(s)"
    )
    for note in notes:
        print(f"  note: {note}")
    print()
    print("the (action, ref # version) set, per repository:")
    for line in emit_set(scan.third_party):
        print(line)
    print()
    if split:
        print(f"DIVERGENCE: {len(split)} action(s) sit at more than one ref across the surface scanned.")
        print("Allowed, and reported - two majors of one action may exist, not uncompared:")
        for action, refs in sorted(split.items()):
            print(render_divergence(action, refs))
            if os.environ.get("GITHUB_ACTIONS"):
                summary = "; ".join(
                    f"{version_label(m[0])} in {', '.join(sorted({t.site.repo for t in m}))}"
                    for m in refs.values()
                )
                print(f"::warning::{action} is at {len(refs)} refs: {summary}")
    else:
        print("no divergence: every action sits at one ref.")
    print()

    if problems:
        # Everything on ONE stream. A runner reads stdout and stderr through
        # separate pipes and interleaves them by arrival, and three CI runs of
        # #59 showed a stderr verdict printed AFTER a flushed stdout report
        # still landing above it in the log. The exit code is the verdict;
        # the words go where the evidence goes.
        print(f"REFUSALS: {len(problems)}\n")
        by_kind: dict[str, list[str]] = defaultdict(list)
        for problem in problems:
            by_kind[problem.kind].append(problem.line)
        for kind in EXPLANATIONS:
            if kind not in by_kind:
                continue
            print(f"  [{kind}] {len(by_kind[kind])} site(s):")
            for line in by_kind[kind]:
                print(f"    {line}")
            print(f"    {EXPLANATIONS[kind]}\n")
        print(f"third-party pins FAILED: {len(problems)} refusal(s), listed above")
        return 1

    holding = sorted({tp.site.repo for tp in scan.third_party})
    print(
        f"third-party pins OK: {len(scan.third_party)} site(s) across "
        f"{len(holding)} repositor{'y' if len(holding) == 1 else 'ies'}, every "
        "one a 40-hex commit with a version comment from an enumerated publisher"
    )
    if not args.tree:
        silent = sorted(set(repos) - set(holding))
        print(
            f"scanned {len(repos)} readable repositor{'y' if len(repos) == 1 else 'ies'} "
            f"in {args.org}; {len(silent)} hold no third-party refs ({', '.join(silent) or 'none'})"
        )
    # Printed output is ASCII on purpose, for the same reason pin-coherence's
    # is: a checker that crashes encoding its own caveat after printing OK is
    # a red exit wearing a green body.
    print(
        "WARNING - a pin is not a review: this run says the code behind each "
        "ref cannot change unseen. Whether it is benign is the publisher set's "
        "claim, and whether it is current is Dependabot's job, not this one's."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
