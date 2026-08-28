#!/usr/bin/env python3
"""Refuse a runtime-touching PR whose body does not say how it was verified.

WHY THIS EXISTS. Testing in this repo happens during a PR; after the merge,
attention moves to the next branch. Everything below passed its PR and was still
wrong in production:

  - #283  `data_contract_breach_sensor` iterated the wrong collection and raised on
          every invocation. Live history: 1799 SKIPPED / 201 FAILURE / 0 SUCCESS,
          while sitting on `CONTROLS.md` as `proven`.
  - #391  the nightly `/explore/refresh` was a no-op every OTHER night (24 h
          freshness against a 24 h cron) and returned `200 ok` in 5.5 s having
          profiled nothing. Billed 200 MB, 0, 275 MB, 0 on consecutive nights.
  - #80/#129  seven asset checks validated nothing, because `PolarsData` made every
          assertion vacuous.
  - #210  both Healthchecks dead-man switches were never wired, while looking
          configured, because `read_env` returns `""` for an absent key.
  - #436  the `kill()` escalation had ZERO coverage while `engine_runner.py` and
          `CONTROLS.md` both implied it was proven.

The common shape is not a missing test. It is a **missing statement of what was
observed after the change was live**, which is the one thing a PR body never has to
contain. This makes it contain it.

MOVED HERE FROM groundstation (scripts/check_verification_section.py), the half
groundstation#32 settled; whether it BINDS a repository, and with which fields,
is workbench#23's ruling (2026-08-28, per-repo fields): `Dev:` is required in
every enforced repository; `Prod:`/`Discriminator:` are required only where a
box exists to observe (`require-prod`), because a field that is structurally
always N/A trains the reflex of writing N/A -- measured on 112 merged PRs, 24
of 27 would-be failures were a missing `Prod:` no library repo can honestly
fill. Where Prod is not required it is still never ignored: a `Prod:` line
that IS present is validated exactly as in full mode, because a present claim
is a claim.

WHAT IT ASSERTS. If the PR changes a runtime path, its body must carry a
`## Verification` section with:

    ## Verification

    **Dev:** what was run, and the result.
    **Prod:** what was observed on the box  --  OR  --  `N/A - <reason>`
    **Discriminator:** what reads DIFFERENTLY before and after.

`Prod: N/A` is allowed and always will be: plenty of changes are not wire-visible,
and some need a billed query nobody should run to satisfy a linter. **But it must
carry a reason.** The failure being fixed is silence, and a written reason is
auditable where an absence is not. That is the whole of the escape hatch, and it is
deliberately one line wide.

`Discriminator:` is required only when Prod is not N/A, and it is the field that
separates verification from #391. *"`GET /maintain/schema` returned 200"* is not a
discriminator, because it returned 200 before the change too. **A discriminator is
a thing whose value differs between the old build and the new one** -- an image
digest, a log line's changed wording, a field that appears or disappears, a number
that moves. Prose cannot be checked for that, so this script only checks the field
is present and substantive; the reader does the rest.

WHAT IT DELIBERATELY DOES NOT DO. It does not grade the evidence, and it holds no
list of acceptable phrasings. A checker that scored wording would be gamed into
hollow compliance, which is worse than the silence it replaced: it would make an
unverified change *look* verified, which is the exact failure mode of every incident
listed above.

WHICH PATHS IT GATES, AND WHY THAT IS NOW THE DEFAULT. A changed path is runtime
unless `NOT_RUNTIME` says why it is not. It used to be the reverse -- four declared
prefixes were gated and everything else was exempt by saying nothing -- which meant
a new runtime directory exempted itself on arrival, with no diff recording it.

It still does NOT gate `scripts/` or `.github/`, and that remains a decision rather
than an oversight. A CI checker cannot be observed on the box, so its `Prod:` line
would be `N/A` every single time -- and a field that is structurally always N/A
teaches the reflex of writing N/A, which is precisely the habit this gate exists to
break. The control appropriate to a checker is a **self-test that is proven to go
red**, and `pr-hygiene` already runs one for every checker it invokes, including
this one. What changed is that the reason is now written next to the exemption and
printed when it applies, instead of being inferred from a name's absence.

That paragraph was also WRONG about two files, and only about them.
`scripts/role_watch.py` (the entrypoint of a running compose service) and
`scripts/resolve_role.py` (shipped inside the dex-api image) were exempt for as
long as this gate had existed, and were then named in `SHIPPED_ANYWAY` and
gated. ⚠️ Both LEFT this tree at #77 with the dex-api split — the shipping
copies live in `catincloud-labs/dex-api` — so `SHIPPED_ANYWAY` is EMPTY now,
kept as the mechanism (with its self-test) for the next file that ships from
`scripts/` despite the directory's exemption.

NOTHING SCANNED IS NOT ALL CLEAR. If the changed-file list is absent or empty, this
exits 1 saying it could not check. `check_upstream_refs.py` carries the same rule for
the same reason: exit 0 has to mean "checked and clean", never "found nothing to do".

    python3 scripts/check_verification_section.py --self-test
    python3 scripts/check_verification_section.py pr.txt --changed-files files.txt
"""

from __future__ import annotations

import argparse
import contextlib
import io
import re
import sys
from pathlib import Path

#: A CHANGED PATH IS RUNTIME UNLESS SOMETHING BELOW SAYS WHY IT IS NOT.
#:
#: This used to be the other way round: a tuple named RUNTIME_PREFIXES held four
#: directories, and everything outside it was exempt by saying nothing. That list
#: was the SCOPE OF ENFORCEMENT, so a new runtime directory exempted itself on
#: arrival and no diff recorded the decision -- the shape `catincloud-labs/
#: constellation`'s ADR-0025 refuses. Measured at 851f9a2, eleven paths that alter
#: what runs on the box read as not-runtime, among them `backups/` and `caddy/`
#: (both `build:` contexts for running compose services) and `scripts/
#: role_watch.py`, which compose executes as an ENTRYPOINT.
#:
#: The declared list is now the EXEMPTION, which is the half ADR-0025 says must be
#: minimal and must carry its reason. A reason is data here rather than a comment
#: beside the rule, because the run prints it: an exemption nobody can see applied
#: is indistinguishable from a gate that did not fire.
#:
#: NOT the derived half of ADR-0025, and the falsifier there does not apply. That
#: falsifier -- "an exclusion list longer than the enumeration it replaced" -- is
#: about a DERIVED population whose hand-written list merely moved. Deriving here
#: would mean classifying all 34 top-level entries so a new one goes red, i.e.
#: trading a 4-entry list for a 30-entry one, which is the thing the falsifier
#: names. Refusal by default is the other authorised shape, and it is this one.
NOT_RUNTIME: tuple[tuple[str, str], ...] = (
    (r"(^|/)tests?/", "a test does not ship; it is what runs before shipping"),
    (r"\.md$", "prose cannot alter what the box does"),
    (
        r"^\.github/",
        "CI. A checker cannot be observed on the box, so its `Prod:` line is "
        "structurally N/A -- see WHAT IT DELIBERATELY DOES NOT DO above",
    ),
    (r"^\.githooks/", "a hook runs on a workstation, never on the box"),
    (
        r"^scripts/",
        "same reason as `.github/`: this directory is CI checkers -- any path "
        "here that ships despite that goes in SHIPPED_ANYWAY below (empty "
        "since #77, when its two entries left with the dex-api split)",
    ),
    (r"^LICENSE$", "not executed by anything"),
    (r"^\.gitignore$|^\.gitattributes$", "VCS metadata; git does not run on the box"),
    (
        r"^renovate\.json$",
        "configures a bot that opens pull requests, and every change it proposes "
        "arrives as a PR gated by this very check",
    ),
    (
        r"^\.trivyignore$",
        "decides what CI refuses to ship, not what a shipped image does once it "
        "is running",
    ),
    (
        r"^\.env\.example$",
        "a template. The box reads /opt/app/.env; this file is compared against "
        "it by check_env_key_drift.py and is never copied onto the host",
    ),
)

#: EXCEPTIONS TO AN EXEMPTION, and they are the reason `scripts/` above is a
#: blanket rather than a truth. `dex_api/Dockerfile:203` says in as many words
#: "Deliberately NOT `COPY scripts/ scripts/`. Most of that directory is CI" --
#: and then COPYs exactly these two. So the docstring's claim that this checker
#: does not gate `scripts/` was right about the directory and wrong about the
#: two files in it that production runs.
#:
#: Both leave with `dex_api/` at the ADR-0026 split, and the self-test asserts
#: they are still in the tree -- so this carve-out goes red rather than quietly
#: becoming a claim about files that no longer exist.
SHIPPED_ANYWAY: tuple[tuple[str, str], ...] = (
    # EMPTY since #77 — `scripts/role_watch.py` and `scripts/resolve_role.py`
    # (the two entries this held) left with the dex-api split; the copies that
    # ship live in `catincloud-labs/dex-api` and are gated by that repository's
    # CI. The mechanism stays: a `scripts/` file that starts shipping again is
    # named here with its reason, and the self-test asserts every entry both
    # carves a real hole and names a file that exists.
)

_NOT_RUNTIME_RES: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(p), why) for p, why in NOT_RUNTIME
)

_HEADING_RE = re.compile(r"^\s{0,3}(#{2,6})\s*verification\b", re.IGNORECASE)
_NEXT_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+\S")

#: `**Dev:**`, `Dev:`, `- **Prod**:` ... permissive on decoration, strict on the label.
def _label_re(label: str) -> re.Pattern[str]:
    return re.compile(
        rf"^\s*(?:[-*+]\s*)?\**\s*{label}\s*\**\s*:\s*\**\s*(?P<value>.*)$",
        re.IGNORECASE,
    )


_DEV_RE = _label_re("dev")
_PROD_RE = _label_re("prod")
_DISCRIMINATOR_RE = _label_re("discriminator")

#: `N/A`, `n/a`, `NA`, `none`, optionally followed by the reason.
_NA_RE = re.compile(r"^\s*(?:n/?a|none|not applicable)\b[\s:—\-–]*(?P<reason>.*)$", re.IGNORECASE)

#: Enough alphanumerics to be a sentence rather than a shrug. Deliberately low: the
#: point is to force a statement, not to police prose length.
_MIN_CONTENT = 15
_MIN_REASON = 20


def _substance(text: str) -> int:
    """Alphanumeric characters, so `-`, `n/a`, `...` and `TODO:` do not qualify."""

    return len(re.sub(r"[^0-9A-Za-z]", "", text))


def _normalise(path: str) -> str:
    """A repo-relative POSIX path.

    The leading `./` is stripped ONE segment at a time and only when it is
    exactly that. This used to be `.lstrip("./")`, which strips any run of `.`
    and `/` characters and therefore ate the leading dot off every dotfile:
    `.github/workflows/ci.yml` normalised to `github/workflows/ci.yml`.

    That was harmless while no pattern here began with a dot, and it stopped
    being harmless in this change -- `^\\.github/` and three of its neighbours in
    NOT_RUNTIME would never have matched, so the exemptions would have silently
    failed to apply. It fails toward gating rather than toward silence, which is
    the safe direction and still the wrong answer.
    """

    path = path.strip().replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    return path


def exemption_for(
    path: str, extra_shipped: tuple[tuple[str, str], ...] = ()
) -> str | None:
    """Why this path is not runtime, or None when it is.

    Order is the control: a SHIPPED_ANYWAY path is runtime even though a
    NOT_RUNTIME pattern covers it, so it has to be asked first.

    ``extra_shipped`` is the per-repository half of that list, arriving from the
    action's ``shipped-anyway`` input (workbench #23 step 3): the built-in list
    describes what every adopter shares, and a file only one repository ships —
    dex-api's ``scripts/role_watch.py``, the case the built-in list's own
    history warned about — is that repository's to declare, not this file's to
    hardcode.
    """

    path = _normalise(path)
    if not path:
        return "empty path"
    for shipped, _why in tuple(SHIPPED_ANYWAY) + tuple(extra_shipped):
        if path == shipped:
            return None
    for pattern, why in _NOT_RUNTIME_RES:
        if pattern.search(path):
            return why
    return None


def is_runtime_path(
    path: str, extra_shipped: tuple[tuple[str, str], ...] = ()
) -> bool:
    return _normalise(path) != "" and exemption_for(path, extra_shipped) is None


def runtime_paths(
    paths: list[str], extra_shipped: tuple[tuple[str, str], ...] = ()
) -> list[str]:
    return [p.strip() for p in paths if is_runtime_path(p, extra_shipped)]


def parse_shipped_anyway(entries: list[str]) -> tuple[tuple[str, str], ...]:
    """Validate caller-supplied carve-outs, refusing the two registry defects.

    Each entry is ``path -- reason``. The same discipline the self-test applies
    to the built-in list applies here, at parse time and fail-closed: a
    carve-out must carve a real hole (some NOT_RUNTIME pattern must cover the
    path, or the entry asserts a hole that does not exist), and it must carry a
    reason with substance (a name nobody dares delete is how registries rot).
    The one assertion that CANNOT move here is tree existence — the caller runs
    without a checkout, deliberately — so that half of the discipline lives in
    the adopting repository, whose own docs name the shipping files this input
    repeats.

    Raises ``SystemExit(1)`` with the defect named, because a misdeclared
    carve-out silently un-carving itself is exactly the fail-open registry
    shape this checker exists to refuse.
    """

    parsed: list[tuple[str, str]] = []
    for raw in entries:
        head, sep, reason = raw.partition(" -- ")
        path = _normalise(head.strip())
        if not sep or not path or _substance(reason) < _MIN_REASON:
            print(
                f"could NOT check: shipped-anyway entry {raw!r} is not "
                "'path -- reason' with a reason of substance. A carve-out "
                "without a reviewable reason is a name somebody will not dare "
                "delete.",
                file=sys.stderr,
            )
            raise SystemExit(1)
        if not any(p.search(path) for p, _ in _NOT_RUNTIME_RES):
            print(
                f"could NOT check: shipped-anyway entry {path!r} is covered by "
                "no exemption, so naming it asserts a hole that does not "
                "exist — it is already runtime and the entry is dead weight.",
                file=sys.stderr,
            )
            raise SystemExit(1)
        parsed.append((path, reason.strip()))
    return tuple(parsed)


def extract_section(body: str) -> str | None:
    """The `## Verification` section's text, or None when there is no such heading."""

    lines = body.splitlines()
    start = None
    for i, line in enumerate(lines):
        if _HEADING_RE.match(line):
            start = i + 1
            break
    if start is None:
        return None
    out: list[str] = []
    for line in lines[start:]:
        if _NEXT_HEADING_RE.match(line):
            break
        out.append(line)
    return "\n".join(out)


def _field(section: str, pattern: re.Pattern[str]) -> str | None:
    for line in section.splitlines():
        m = pattern.match(line)
        if m:
            return m.group("value").strip()
    return None


def check(
    body: str,
    changed: list[str],
    require_prod: bool = True,
    extra_shipped: tuple[tuple[str, str], ...] = (),
) -> list[str]:
    """Every problem found. Empty means clean.

    `require_prod=False` is the library-repo mode (workbench#23): `Prod:` and
    `Discriminator:` stop being REQUIRED, and everything present is still
    validated -- a bare `Prod: N/A` or thin evidence fails in both modes.
    """

    problems: list[str] = []
    touched = runtime_paths(changed, extra_shipped)
    if not touched:
        return problems

    section = extract_section(body)
    if section is None:
        fields = (
            "Dev / Prod / Discriminator lines; `Prod: N/A - <reason>` is a "
            "valid answer, silence is not."
            if require_prod
            else "a Dev line saying what was run and what it reported."
        )
        return [
            "no `## Verification` section, and this PR changes runtime paths "
            f"({', '.join(touched[:4])}{'...' if len(touched) > 4 else ''}). "
            f"Add {fields}"
        ]

    dev = _field(section, _DEV_RE)
    prod = _field(section, _PROD_RE)
    disc = _field(section, _DISCRIMINATOR_RE)

    if dev is None or _substance(dev) < _MIN_CONTENT:
        problems.append(
            "`Dev:` is missing or too thin. Say what was run and what it reported."
        )

    if prod is None:
        if require_prod:
            problems.append(
                "`Prod:` is missing. It is the line this check exists for: every "
                "incident in this script's docstring passed its PR and failed on "
                "the box."
            )
        # Not required here: absent is a complete answer, and `Discriminator:`
        # without a Prod claim has nothing to discriminate.
        return problems

    na = _NA_RE.match(prod)
    if na:
        reason = na.group("reason")
        if _substance(reason) < _MIN_REASON:
            problems.append(
                "`Prod: N/A` needs a reason on the same line. 'N/A' alone is the "
                "silence this check replaces -- write why the change is not "
                "observable on the box, or what would have to be true to observe it."
            )
        return problems

    if _substance(prod) < _MIN_CONTENT:
        problems.append("`Prod:` is too thin to be evidence. Name what was observed.")

    if disc is None or _substance(disc) < _MIN_CONTENT:
        problems.append(
            "`Discriminator:` is missing or too thin, and `Prod:` claims real "
            "evidence. Name the thing that reads DIFFERENTLY before and after -- an "
            "image digest, a changed log wording, a field that appears or "
            "disappears, a number that moves. '200 OK' is not a discriminator: it "
            "was 200 before the change too (#391 returned 200 for weeks while doing "
            "nothing)."
        )
    return problems


# --------------------------------------------------------------------------- #
# Self-test. Runs FIRST in CI, because a checker that has silently stopped
# matching is indistinguishable from a clean PR -- which is the class of bug this
# whole script is about.
# --------------------------------------------------------------------------- #

_RUNTIME = ["dex_api/services/responder.py"]
_DOCS = ["dex_api/CONTRACT.md", "README.md"]
_TESTS = ["dex_api/tests/test_responder.py"]

_GOOD = """## Verification

**Dev:** full dex_api suite, 864 passed / 7 skipped at dex-core 1.4.3.
**Prod:** `GET /maintain/schema` 200 in 5.65s on the deployed image; ledger untouched.
**Discriminator:** `maintain_in_process_enabled` logs the post-#436 wording, absent from the old image.
"""

_NA_WITH_REASON = """## Verification

**Dev:** 14 new tests, suite 850 -> 864.
**Prod:** N/A - nothing is wired yet, so no route reaches this code and there is no wire-visible change to observe.
"""

_CASES: list[tuple[str, str, list[str], bool]] = [
    ("complete", _GOOD, _RUNTIME, True),
    ("n/a with a reason", _NA_WITH_REASON, _RUNTIME, True),
    ("docs-only change is not gated", "no section at all", _DOCS, True),
    ("test-only change is not gated", "no section at all", _TESTS, True),
    ("no section", "Some body text.", _RUNTIME, False),
    (
        "no Prod line",
        "## Verification\n\n**Dev:** ran the whole suite, 864 passed.\n",
        _RUNTIME,
        False,
    ),
    (
        "bare N/A",
        "## Verification\n\n**Dev:** ran the whole suite, 864 passed.\n**Prod:** N/A\n",
        _RUNTIME,
        False,
    ),
    (
        "evidence but no discriminator",
        "## Verification\n\n**Dev:** ran the whole suite, 864 passed.\n"
        "**Prod:** hit the endpoint on the box and it returned 200 OK.\n",
        _RUNTIME,
        False,
    ),
    (
        "thin Dev",
        "## Verification\n\n**Dev:** ok\n**Prod:** N/A - not wire-visible, nothing is wired to this path yet.\n",
        _RUNTIME,
        False,
    ),
]


#: The `require_prod=False` mode, asserted separately: what it releases (an
#: absent Prod), and everything it deliberately does NOT release (a present
#: Prod is validated in full; Dev substance is unchanged). The first case is
#: the mode's whole point and its body FAILS the full-mode `no Prod line` case
#: above -- the pair is what proves the flag discriminates.
_OPTIONAL_CASES: list[tuple[str, str, list[str], bool]] = [
    (
        "dev only, prod absent -- the released case",
        "## Verification\n\n**Dev:** ran the whole suite, 864 passed.\n",
        _RUNTIME,
        True,
    ),
    ("complete body still passes", _GOOD, _RUNTIME, True),
    ("n/a with a reason still passes", _NA_WITH_REASON, _RUNTIME, True),
    ("no section is still refused", "Some body text.", _RUNTIME, False),
    (
        "thin Dev is still refused",
        "## Verification\n\n**Dev:** ok\n",
        _RUNTIME,
        False,
    ),
    (
        "a PRESENT bare N/A is still refused",
        "## Verification\n\n**Dev:** ran the whole suite, 864 passed.\n**Prod:** N/A\n",
        _RUNTIME,
        False,
    ),
    (
        "PRESENT evidence without a discriminator is still refused",
        "## Verification\n\n**Dev:** ran the whole suite, 864 passed.\n"
        "**Prod:** hit the endpoint on the box and it returned 200 OK.\n",
        _RUNTIME,
        False,
    ),
]


def self_test() -> int:
    failures = 0
    for name, body, changed, want_clean in _CASES:
        problems = check(body, changed)
        got_clean = not problems
        mark = "ok  " if got_clean == want_clean else "FAIL"
        if got_clean != want_clean:
            failures += 1
        print(f"  {mark} {name}: expected {'clean' if want_clean else 'red'}")
        if got_clean != want_clean and problems:
            print(f"        got: {problems[0][:100]}")

    for name, body, changed, want_clean in _OPTIONAL_CASES:
        problems = check(body, changed, require_prod=False)
        got_clean = not problems
        mark = "ok  " if got_clean == want_clean else "FAIL"
        if got_clean != want_clean:
            failures += 1
        print(
            f"  {mark} [no-require-prod] {name}: "
            f"expected {'clean' if want_clean else 'red'}"
        )
        if got_clean != want_clean and problems:
            print(f"        got: {problems[0][:100]}")

    # A checker whose own trigger has stopped firing would pass every case above by
    # declaring nothing runtime. Assert the trigger directly, both directions.
    if not runtime_paths(_RUNTIME):
        print("  FAIL trigger: a runtime path was not recognised as one")
        failures += 1
    if runtime_paths(_DOCS) or runtime_paths(_TESTS):
        print("  FAIL trigger: docs or tests were treated as runtime")
        failures += 1
    if not runtime_paths(["docker-compose.yml"]):
        print("  FAIL trigger: docker-compose.yml was not recognised")
        failures += 1

    # THE POLARITY ITSELF. Every path below read as NOT runtime before this gate
    # was flipped, and each one alters what the box does. A regression to a
    # declared scope of enforcement would make all six green again, silently,
    # which is why they are asserted by name rather than by prefix.
    # (`scripts/role_watch.py` and `scripts/resolve_role.py` were asserted here
    # until #77 — they are not in this tree at all now, and their SHIPPED_ANYWAY
    # carve-outs left with them, so the `^scripts/` exemption correctly covers
    # everything that remains in that directory.)
    _GATED_BY_DEFAULT = [
        ("newservice/main.py", "a directory that did not exist when the list was written"),
        ("backups/Dockerfile", "compose build context for postgres-backup"),
        ("caddy/Caddyfile", "compose build context for caddy"),
        ("uv.lock", "decides what is installed in every image"),
    ]
    for path, why in _GATED_BY_DEFAULT:
        if not is_runtime_path(path):
            print(f"  FAIL polarity: {path} read as exempt -- {why}")
            failures += 1

    # The exemptions still have to hold, or the flip has merely made the gate
    # fire on everything, which is the failure mode that gets a control disabled.
    _STILL_EXEMPT = [
        ".github/workflows/ci.yml",
        ".githooks/commit-msg",
        "scripts/check_dex_pin.py",
        ".gitignore",
        ".env.example",
        "renovate.json",
        "LICENSE",
        "README.md",
        "tests/test_budget_ceilings_agree.py",
    ]
    for path in _STILL_EXEMPT:
        if is_runtime_path(path):
            print(f"  FAIL exemption: {path} was gated and should not be")
            failures += 1

    # `.github/...` above is the case that catches the normalisation defect this
    # change fixed: `.lstrip("./")` ate the leading dot, so a dot-prefixed
    # exemption never matched. Assert the normaliser directly too, because a
    # future rewrite could reintroduce it while that one case still passed by
    # some other route.
    if _normalise("./dex_api/x.py") != "dex_api/x.py":
        print("  FAIL normalise: a leading ./ was not stripped")
        failures += 1
    for dotfile in (".github/workflows/ci.yml", ".env.example", ".trivyignore"):
        if _normalise(dotfile) != dotfile:
            print(f"  FAIL normalise: {dotfile} lost its leading dot")
            failures += 1

    # EVERY EXEMPTION CARRIES A REASON, because a reason is what makes the list
    # reviewable; an entry without one is a name somebody will not dare delete.
    for pattern, why in NOT_RUNTIME:
        if _substance(why) < _MIN_REASON:
            print(f"  FAIL reason: the exemption {pattern!r} has no usable reason")
            failures += 1

    # A CARVE-OUT THAT CARVES NOTHING IS A REGISTRY DEFECT, not a spare part. If
    # no exemption covers a SHIPPED_ANYWAY path, the entry is dead code claiming
    # to hold a hole open, and the next reader will believe it.
    for shipped, _why in SHIPPED_ANYWAY:
        if not any(p.search(shipped) for p, _ in _NOT_RUNTIME_RES):
            print(f"  FAIL carve-out: nothing exempts {shipped}, so naming it here")
            print("        asserts a hole that does not exist")
            failures += 1

    # ... and it must still be a file. Both of these leave with `dex_api/` at the
    # ADR-0026 split, and this is what makes that a red self-test rather than a
    # silent claim about a path nothing has.
    # CWD, not __file__: this file lives in the workbench action, and the
    # tree a SHIPPED_ANYWAY path must exist in is the CALLER's checkout.
    # (This parenthesis used to read "a repository needing a carve-out also
    # needs an action input for it -- add both in the same change" -- that
    # repository arrived (dex-api, wb #23 step 3) and the input exists:
    # `shipped-anyway`, validated by `parse_shipped_anyway`. The built-in list
    # stays for a carve-out EVERY adopter shares, which is still none.)
    repo_root = Path.cwd()
    for shipped, _why in SHIPPED_ANYWAY:
        if not (repo_root / shipped).exists():
            print(f"  FAIL carve-out: {shipped} is not in the tree any more.")
            print("        It has moved or been deleted -- remove the SHIPPED_ANYWAY")
            print("        entry in the same change, or this is a claim about nothing.")
            failures += 1

    # THE PER-REPOSITORY CARVE-OUT CHANNEL, exercised in both directions -- a
    # parser that refused everything would read exactly like one that worked,
    # and one that refused nothing would quietly re-open the fail-open registry
    # this input exists to avoid. Three arms: a valid entry makes an exempt
    # path runtime; an entry carving no hole is refused; a reasonless entry is
    # refused.
    carved = parse_shipped_anyway(
        ["scripts/example_shipped.py -- an entrypoint a compose service executes"]
    )
    if exemption_for("scripts/example_shipped.py", carved) is not None:
        print("  FAIL shipped-anyway: a declared carve-out did not make the path runtime")
        failures += 1
    if exemption_for("scripts/other.py", carved) is None:
        print("  FAIL shipped-anyway: a carve-out for one file un-exempted its neighbours")
        failures += 1
    for bad in (
        "dex_api/main.py -- already runtime, carves nothing",
        "scripts/x.py -- no",
        "scripts/x.py",
    ):
        try:
            # The refusal text goes to a buffer, not the log: these arms are
            # negative controls, and a raw "could NOT check:" line inside a
            # GREEN run's log reads as an error somebody should chase --
            # observed on the first adopter's CI run before this redirect.
            with contextlib.redirect_stderr(io.StringIO()):
                parse_shipped_anyway([bad])
        except SystemExit:
            pass
        else:
            print(f"  FAIL shipped-anyway: {bad!r} was accepted and must not be")
            failures += 1

    if failures:
        print(f"\nself-test FAILED: {failures} case(s)", file=sys.stderr)
        return 1
    print(
        f"\nself-test OK: {len(_CASES)} + {len(_OPTIONAL_CASES)} cases "
        f"(both prod modes), 3 trigger assertions, "
        f"{len(_GATED_BY_DEFAULT)} polarity, {len(_STILL_EXEMPT)} exemption, "
        f"{len(NOT_RUNTIME)} reasons, {len(SHIPPED_ANYWAY)} carve-outs, "
        f"shipped-anyway 2+3 arms"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("body", nargs="?", help="file holding the PR body")
    parser.add_argument(
        "--changed-files",
        help="file holding one changed path per line (from `gh pr view --json files`)",
    )
    parser.add_argument("--label", default="PR body", help="what to call the input")
    parser.add_argument(
        "--require-prod",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "whether `Prod:` (and its Discriminator) are REQUIRED. "
            "--no-require-prod is the library-repo mode (workbench#23): no box "
            "exists to observe, so an absent Prod is a complete answer -- but a "
            "present one is still validated in full."
        ),
    )
    parser.add_argument(
        "--shipped-anyway",
        action="append",
        default=[],
        metavar="PATH -- REASON",
        help=(
            "per-repository carve-out: a path production ships despite an "
            "exemption covering its directory (the action's shipped-anyway "
            "input). Refused unless it carves a real hole and carries a reason."
        ),
    )
    parser.add_argument("--self-test", action="store_true", help="prove it can go red")
    args = parser.parse_args(argv)

    if args.self_test:
        return self_test()

    if not args.body or not args.changed_files:
        print(
            "could NOT check: both a body file and --changed-files are required. "
            "Exiting 1 rather than 0, because 'nothing scanned' must never read as "
            "'all clear'.",
            file=sys.stderr,
        )
        return 1

    body = Path(args.body).read_text(encoding="utf-8")
    raw = Path(args.changed_files).read_text(encoding="utf-8").splitlines()
    changed = [line for line in raw if line.strip()]
    if not changed:
        print(
            "could NOT check: the changed-file list is empty. A PR always changes "
            "something, so this means the list was not produced.",
            file=sys.stderr,
        )
        return 1

    extra_shipped = parse_shipped_anyway(args.shipped_anyway)
    touched = runtime_paths(changed, extra_shipped)
    if not touched:
        # Name the exemption that covered each file, rather than reporting a
        # count. A success line that counts its own list tells you the list was
        # read, not that anything was checked -- `check_image_paths.py` reports
        # the size of its own map and is byte-identical whether or not the thing
        # it exists to notice has happened (catincloud-labs/groundstation#74).
        print(
            f"{args.label}: no runtime paths changed -- verification section not "
            f"required. {len(changed)} file(s), each exempt for a stated reason:"
        )
        for path in changed:
            print(f"  {path.strip()}: {exemption_for(path, extra_shipped)}")
        return 0

    problems = check(
        body, changed, require_prod=args.require_prod, extra_shipped=extra_shipped
    )
    if problems:
        print(f"{args.label}: verification section FAILED\n", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        print(
            "\nRuntime paths in this PR: " + ", ".join(touched[:8]),
            file=sys.stderr,
        )
        return 1

    fields_ok = (
        "Dev/Prod present" if args.require_prod
        else "Dev present; Prod not required here"
    )
    print(
        f"{args.label}: verification section OK "
        f"({len(touched)} runtime path(s) changed, {fields_ok})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
