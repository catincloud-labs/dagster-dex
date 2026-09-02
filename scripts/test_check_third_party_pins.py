#!/usr/bin/env python3
"""The third-party pin guard fires, goes quiet, refuses, and compares - proven before trusted.

Every case is pure: the reader layer is injected, so no network and no broken
organisation is needed to stage the red arms. The estate rule this satisfies:
a control observed only to pass, against the one tree it is known to pass in,
has not been shown to be a control.

The known-positive is a tag; the known-negative is a commit with its version
comment. Both are ADR-0040's own words for what the guard ships with.

    python3 test_check_third_party_pins.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from check_third_party_pins import (
    TRUSTED_PUBLISHERS,
    Refusal,
    classify,
    collect,
    divergences,
    emit_set,
    judge,
    render_divergence,
    scan_text,
    version_label,
    yaml_paths_under,
)

ORG = "catincloud-labs"
SHA_A = "a" * 40
SHA_B = "b" * 40

failures = 0


def case(name: str, ok: bool) -> None:
    global failures
    if not ok:
        failures += 1
    print(f"  {'ok  ' if ok else 'FAIL'} {name}")


def wf(*lines: str) -> str:
    return "\n".join(lines) + "\n"


def judged(repo: str, path: str, text: str):
    return judge(classify(scan_text(repo, path, text), ORG))


def kinds(problems) -> list[str]:
    return sorted(p.kind for p in problems)


# --- the quiet case first: a corpus of pins with comments must pass -------------

good_text = wf(
    f"      - uses: actions/checkout@{SHA_A} # v4.2.2",
    f"      - uses: astral-sh/setup-uv@{SHA_B}  # v10.0.1",
    f"        uses: google-github-actions/auth@{SHA_A} # v3",
    f'      - uses: "docker/build-push-action@{SHA_B}" # v7',
    f"      - uses: {ORG}/workbench/.github/actions/markdown@{SHA_A} # workbench main, prose is fine here",
    "      - uses: ./.github/actions/local",
    f"      # - uses: actions/checkout@v4 (commented out, not a site)",
)
good = classify(scan_text("org/one", ".github/workflows/checks.yml", good_text), ORG)
case("a corpus of commit pins with version comments passes", judge(good) == [])
case("...and every third-party site was collected (4, not fewer)", len(good.third_party) == 4)
case("...the estate's own ref is set aside for pin-coherence, not judged", len(good.own) == 1)
case("...a local ./path is not a ref", len(good.local) == 1)
case("...and a commented-out line is not a site", len(good.unclassified) == 0)
case(
    "...a quoted value is read without its quotes",
    any(tp.action == "docker/build-push-action" and tp.ref == SHA_B for tp in good.third_party),
)
case(
    "...and the trailing comment is captured as the version label",
    sorted(version_label(tp) for tp in good.third_party) == ["v10.0.1", "v3", "v4.2.2", "v7"],
)

# --- the known-positive: a tag is refused, naming file, line, ref, publisher -----

tag = judged("org/one", ".github/workflows/ci.yml", wf("      - uses: actions/checkout@v4"))
case("a tag is refused as not-a-pin", kinds(tag) == ["not-a-pin"])
case(
    "...naming the file, the line, the ref and the publisher",
    bool(tag)
    and "org/one/.github/workflows/ci.yml:1" in tag[0].line
    and "actions/checkout@v4" in tag[0].line
    and "publisher `actions`" in tag[0].line,
)

for label, ref in (("a branch name", "main"), ("a short sha", "a" * 7), ("a pinned-looking tag", "v4.2.2")):
    ps = judged("org/one", ".github/workflows/ci.yml", wf(f"      - uses: actions/checkout@{ref}"))
    case(f"{label} is refused as not-a-pin", kinds(ps) == ["not-a-pin"])

# --- a pin without its version is refused too ----------------------------------

bare = judged("org/one", ".github/workflows/ci.yml", wf(f"      - uses: actions/checkout@{SHA_A}"))
case("a commit with no version comment is refused", kinds(bare) == ["no-version-comment"])

prose = judged(
    "org/one", ".github/workflows/ci.yml", wf(f"      - uses: actions/checkout@{SHA_A} # the usual one")
)
case("a commit whose comment is not a version is refused", kinds(prose) == ["comment-is-not-a-version"])

for comment in ("v4", "v4.2.2", "4.2.2", "v1.14.2 (release)", "v7 - node 24"):
    ps = judged("org/one", ".github/workflows/ci.yml", wf(f"      - uses: actions/checkout@{SHA_A} # {comment}"))
    case(f"a comment starting `{comment}` reads as a version", ps == [])

# --- the publisher set is enforced, and it is the record's set -----------------

case(
    "the enumerated set is ADR-0040's nine, no more and no fewer",
    TRUSTED_PUBLISHERS
    == {
        "actions",
        "google-github-actions",
        "tailscale",
        "docker",
        "astral-sh",
        "aquasecurity",
        "hashicorp",
        "terraform-linters",
        "pypa",
    },
)
stranger = judged(
    "org/one", ".github/workflows/ci.yml", wf(f"      - uses: someone-else/setup-thing@{SHA_A} # v1.0.0")
)
case("a publisher outside the set is refused even when commit-pinned", kinds(stranger) == ["publisher-not-enumerated"])
case("...naming the publisher", bool(stranger) and "publisher `someone-else`" in stranger[0].line)

stranger_tag = judged("org/one", ".github/workflows/ci.yml", wf("      - uses: someone-else/setup-thing@v1"))
case(
    "a stranger's tag is refused on both counts, not the first one found",
    kinds(stranger_tag) == ["not-a-pin", "publisher-not-enumerated"],
)

# --- nothing found is not all clear ---------------------------------------------

case("zero third-party refs is refused, never 'all clear'", kinds(judge(classify([], ORG))) == ["zero-refs"])
only_own = judged("org/one", ".github/workflows/ci.yml", wf(f"      - uses: {ORG}/workbench/.github/actions/markdown@{SHA_A}"))
case("...and a surface holding only the estate's own refs is zero too", kinds(only_own) == ["zero-refs"])

# --- shapes the scanner will not classify are refused, never skipped -------------

PINNED = f"      - uses: actions/checkout@{SHA_A} # v4.2.2"

image = judged("org/one", ".github/workflows/ci.yml", wf(PINNED, "      - uses: docker://alpine:3.20"))
case("a docker:// image is refused rather than waved through", kinds(image) == ["container-image"])

odd = judged("org/one", ".github/workflows/ci.yml", wf(PINNED, "      - uses: actions/checkout"))
case("a ref-less uses: is refused as unrecognised", kinds(odd) == ["unrecognised"])

# --- the matcher's edges, each one a way the scan could quietly narrow ----------

in_run = scan_text(
    "org/one", ".github/workflows/ci.yml", wf('      - run: echo "uses: actions/checkout@v4"')
)
case("a uses: inside a run: script is not a site", in_run == [])

lookalike = classify(
    scan_text("org/one", ".github/workflows/ci.yml", wf(f"      - uses: {ORG}X/thing@{SHA_A} # v1")), ORG
)
case("an org-prefixed lookalike owner is third-party, not our own", len(lookalike.own) == 0 and len(lookalike.third_party) == 1)

reusable = classify(
    scan_text(
        "org/one", ".github/workflows/ci.yml", wf(f"    uses: actions/starter-workflows/.github/workflows/x.yml@{SHA_A} # v1")
    ),
    ORG,
)
case(
    "a job-level reusable-workflow ref with a sub-path is a site with the path in its action",
    len(reusable.third_party) == 1 and reusable.third_party[0].action == "actions/starter-workflows/.github/workflows/x.yml",
)

composite = scan_text("org/one", ".github/actions/local/action.yml", wf(f"      uses: actions/setup-python@{SHA_A} # v6"))
case("a composite action's own uses: is a site too", len(composite) == 1)

# --- the comparator: divergence is reported, side by side, tags included --------

split_sites = (
    scan_text("org/a", ".github/workflows/checks.yml", wf("      - uses: actions/checkout@v4"))
    + scan_text("org/b", ".github/workflows/checks.yml", wf("      - uses: actions/checkout@v7", "      - uses: actions/checkout@v7"))
    + scan_text("org/c", ".github/workflows/checks.yml", wf(f"      - uses: actions/checkout@{SHA_A} # v7.0.0"))
    + scan_text("org/a", ".github/workflows/ci.yml", wf(f"      - uses: astral-sh/setup-uv@{SHA_B} # v10.0.1"))
    + scan_text("org/b", ".github/workflows/ci.yml", wf(f"      - uses: astral-sh/setup-uv@{SHA_B} # v10.0.1"))
)
split = divergences(classify(split_sites, ORG).third_party)
case("an action at two refs across repositories is a divergence", "actions/checkout" in split)
case("...an action at one ref across repositories is not", "astral-sh/setup-uv" not in split)
case("...and the divergence is over tags as well as commits (the calibrating case)", len(split.get("actions/checkout", {})) == 3)

table = render_divergence("actions/checkout", split["actions/checkout"])
case(
    "the report puts the version labels side by side with who sits where",
    "v4" in table and "v7" in table and "v7.0.0" in table and "org/a (1)" in table and "org/b (2)" in table and "org/c (1)" in table,
)
case("...ordered by version, patch after major", table.index("v4") < table.index("v7 ") < table.index("v7.0.0"))

spread = divergences(
    classify(
        scan_text("org/a", "x.yml", wf("      - uses: astral-sh/setup-uv@v10.0.1"))
        + scan_text("org/b", "x.yml", wf("      - uses: astral-sh/setup-uv@v5"))
        + scan_text("org/c", "x.yml", wf("      - uses: astral-sh/setup-uv@v7")),
        ORG,
    ).third_party
)
spread_table = render_divergence("astral-sh/setup-uv", spread["astral-sh/setup-uv"])
case(
    "...numerically, so v10.0.1 sorts after v5 and v7 rather than between them",
    spread_table.index("v5") < spread_table.index("v7") < spread_table.index("v10.0.1"),
)

emitted = emit_set(classify(split_sites, ORG).third_party)
case(
    "each repository's (action, ref # version) set is emitted",
    any("org/b: actions/checkout@v7 # v7 (2 site(s))" in line for line in emitted)
    and any(f"org/c: actions/checkout@{SHA_A[:12]}... # v7.0.0" in line for line in emitted),
)

case("a coherent corpus reports no divergence", divergences(good.third_party) == {})

# --- the refusals: empty and blind are different inputs and both are loud --------


def boom(_repo):
    raise Refusal("stub: this repository cannot be read")


try:
    collect(["org/dark"], boom, lambda r, p: "")
except Refusal:
    case("an unreadable repository REFUSES rather than being scanned past", True)
else:
    case("an unreadable repository REFUSES rather than being scanned past", False)


def boom_text(_repo, _path):
    raise Refusal("stub: this file cannot be read")


try:
    collect(["org/dim"], lambda r: [".github/workflows/checks.yml"], boom_text)
except Refusal:
    case("an unreadable file REFUSES too - the listing is not the surface", True)
else:
    case("an unreadable file REFUSES too - the listing is not the surface", False)

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    try:
        yaml_paths_under(root)
    except Refusal:
        case("a tree with no .github REFUSES - looking at nothing is not a guard", True)
    else:
        case("a tree with no .github REFUSES - looking at nothing is not a guard", False)

    (root / ".github" / "workflows").mkdir(parents=True)
    (root / ".github" / "README.md").write_text("not yaml\n")
    try:
        yaml_paths_under(root)
    except Refusal:
        case("a .github with no yml or yaml at any depth REFUSES", True)
    else:
        case("a .github with no yml or yaml at any depth REFUSES", False)

    (root / ".github" / "workflows" / "a.yml").write_text("x: 1\n")
    (root / ".github" / "actions" / "l").mkdir(parents=True)
    (root / ".github" / "actions" / "l" / "action.yaml").write_text("x: 1\n")
    (root / ".github" / "dependabot.yml").write_text("x: 1\n")
    (root / "src").mkdir()
    (root / "src" / "uses.yml").write_text("x: 1\n")
    case(
        "the tree walk takes .github yml and yaml at any depth and nothing outside it",
        yaml_paths_under(root) == [".github/actions/l/action.yaml", ".github/dependabot.yml", ".github/workflows/a.yml"],
    )

print()
if failures:
    print(f"self-test FAILED: {failures} case(s)", file=sys.stderr)
    sys.exit(1)
print(
    "self-test OK: the quiet case, the known-positive (a tag) and known-negative "
    "(a commit with its version), the comment and publisher refusals, the "
    "unclassifiable shapes, zero-refs, the matcher edges, the comparator over "
    "tags and commits, and the refusals (unreadable repository, unreadable "
    "file, empty tree)"
)
