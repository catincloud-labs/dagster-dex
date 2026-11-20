#!/usr/bin/env python3
"""The third-party pin guard fires, goes quiet, refuses, and compares - proven before trusted.

No case needs the network or a broken organisation to stage its red arm: the
reader layer is injected, and the command-line cases run a copy of the checker
with no pin-coherence beside it. The estate rule this satisfies:
a control observed only to pass, against the one tree it is known to pass in,
has not been shown to be a control.

The known-positive is a tag; the known-negative is a commit with its version
comment. Both are ADR-0040's own words for what the guard ships with.

    python3 test_check_third_party_pins.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
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
    scan_tree,
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
    f"      - uses: {ORG}/shared-actions/.github/actions/markdown@{SHA_A} # the estate's own, prose is fine here",
    "      - uses: ./.github/actions/local",
    "      # - uses: actions/checkout@v4",
)
good_sites = scan_text("org/one", ".github/workflows/checks.yml", good_text)
good = classify(good_sites, ORG)
case("a corpus of commit pins with version comments passes", judge(good) == [])
case(
    "...a quoted value is read without its quotes",
    any(tp.action == "docker/build-push-action" and tp.ref == SHA_B for tp in good.third_party),
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

short = judged("org/one", ".github/workflows/ci.yml", wf(f"      - uses: actions/checkout@{'a' * 7}"))
case("a short sha is refused as not-a-pin", kinds(short) == ["not-a-pin"])

# --- a pin without its version is refused too ----------------------------------

bare = judged("org/one", ".github/workflows/ci.yml", wf(f"      - uses: actions/checkout@{SHA_A}"))
case("a commit with no version comment is refused", kinds(bare) == ["no-version-comment"])

prose = judged(
    "org/one", ".github/workflows/ci.yml", wf(f"      - uses: actions/checkout@{SHA_A} # the usual one")
)
case("a commit whose comment is not a version is refused", kinds(prose) == ["comment-is-not-a-version"])

for comment in ("4.2.2", "v1.14.2 (release)"):
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

# --- nothing found is not all clear ---------------------------------------------

case("zero third-party refs is refused, never 'all clear'", kinds(judge(classify([], ORG))) == ["zero-refs"])

# --- shapes the scanner will not classify are refused, never skipped -------------

PINNED = f"      - uses: actions/checkout@{SHA_A} # v4.2.2"

image = judged("org/one", ".github/workflows/ci.yml", wf(PINNED, "      - uses: docker://alpine:3.20"))
case("a docker:// image is refused rather than waved through", kinds(image) == ["container-image"])

odd = judged("org/one", ".github/workflows/ci.yml", wf(PINNED, "      - uses: actions/checkout"))
case("a ref-less uses: is refused as unrecognised", kinds(odd) == ["unrecognised"])

# --- the matcher's start anchor: text before a uses: makes it no site ----------

in_run = scan_text("org/one", ".github/workflows/ci.yml", wf("      - run: echo uses: actions/checkout@v4"))
case("a uses: inside a run: script is not a site", in_run == [])

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

table = render_divergence("actions/checkout", split["actions/checkout"])
case(
    "the report puts the version labels side by side with who sits where",
    "v4" in table and "v7" in table and "v7.0.0" in table and "org/a (1)" in table and "org/b (2)" in table and "org/c (1)" in table,
)

emitted = emit_set(classify(split_sites, ORG).third_party)
case(
    "each repository's (action, ref # version) set is emitted",
    any("org/b: actions/checkout@v7 # v7 (2 site(s))" in line for line in emitted)
    and any(f"org/c: actions/checkout@{SHA_A[:12]}... # v7.0.0" in line for line in emitted),
)

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

    (root / ".github" / "workflows" / "a.yml").write_bytes(b"      - uses: actions/checkout@v4 # \xff\n")
    try:
        scan_tree(root, ORG)
    except Refusal:
        case("a tree file that cannot be decoded REFUSES rather than being scanned past", True)
    else:
        case("a tree file that cannot be decoded REFUSES rather than being scanned past", False)

# --- the command line: the exit code is the product, and each refusal says which ----

CHECKER = Path(__file__).resolve().parent / "check_third_party_pins.py"


def run_checker(checker: Path, *args: str, token: str | None = None) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k != "GH_TOKEN"}
    if token is not None:
        env["GH_TOKEN"] = token
    return subprocess.run([sys.executable, str(checker), *args], capture_output=True, text=True, env=env)


with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    (root / ".github" / "workflows").mkdir(parents=True)
    ci = root / ".github" / "workflows" / "ci.yml"
    ci.write_text(PINNED + "\n")
    case("the checker exits 0 on a tree whose third-party refs are all pins", run_checker(CHECKER, "--org", ORG, "--tree", tmp).returncode == 0)
    ci.write_text("      - uses: actions/checkout@v4\n")
    case("...and exits 1 on a tree holding a tag", run_checker(CHECKER, "--org", ORG, "--tree", tmp).returncode == 1)

# A copy with no pin-coherence beside it, as every vendored copy stands: the
# organisation mode can then never reach the network, whichever refusal fires.
with tempfile.TemporaryDirectory() as tmp:
    alone = Path(tmp) / "alone" / "check_third_party_pins.py"
    alone.parent.mkdir()
    shutil.copyfile(CHECKER, alone)
    no_token = run_checker(alone, "--org", ORG, token="")
    case(
        "an empty GH_TOKEN is refused before the organisation is read",
        no_token.returncode == 1 and "GH_TOKEN is empty or absent" in no_token.stderr,
    )
    no_sibling = run_checker(alone, "--org", ORG, token="stub-token")
    case(
        "...and pin-coherence's readers missing is refused, with no second population to fall back on",
        no_sibling.returncode == 1 and "could not import pin-coherence's readers" in no_sibling.stderr,
    )

print()
if failures:
    print(f"self-test FAILED: {failures} case(s)", file=sys.stderr)
    sys.exit(1)
print(
    "self-test OK: the quiet case, the known-positive (a tag) and known-negative "
    "(a commit with its version), the comment and publisher refusals, the "
    "unclassifiable shapes, zero-refs, the matcher's start anchor, the comparator over "
    "tags and commits, the refusals (unreadable repository, unreadable "
    "file, empty tree, undecodable tree file), and the command line's exit "
    "codes and its two organisation-mode refusals (no token, no pin-coherence)"
)
