#!/usr/bin/env python3
"""Refuse a pull request that does not carry exactly one `deploy:` label.

WHY THIS EXISTS. `deploy:` says what merging does to a box, which is a fact
about the change rather than a claim about the reviewer's week. A pull request
carrying none is unclassified: nobody reading the merge log later can tell a
change that deployed nothing from one that moved production, and the answer is
not recoverable after the fact. The rule was ruled rather than assumed -- a
fortnight of merges was measured first, and the `review:` axis was measured
UNUSED and deliberately left to no guard. This file is the `deploy:` half.

WHAT IT ASSERTS, and nothing else:

  Exactly one label whose name begins `deploy:`. Zero is refused as
  unclassified; two or more is refused because the pull request then makes two
  incompatible claims about the same merge and the log cannot resolve them.

WHAT IT DELIBERATELY DOES NOT ASSERT. It does not enumerate the legal `deploy:`
values and does not compare them against anything. The declared set lives in
`labels.yml` and is compared org-wide by the `labels` action; a label that is
not declared cannot be applied in the first place. A second hand-written copy
of that set here would be a set claim nothing computes -- the commonest shape
of stale claim in this estate -- and it would go wrong silently the first time
a value is added.

THE PREFIX IS `deploy:`, WITH THE COLON. `deployment`, `deploy-now` and
`not-deploy:cd` are not `deploy:` labels and are not counted. The self-test
pins each of those, because a prefix rule that quietly matched `deploy` would
pass a pull request carrying no classification at all.

ONE SHAPE PASSES WHOLE, and it prints when it applies, because an exemption
nobody can see applied is indistinguishable from a gate that did not fire:

  * `--author dependabot[bot]`. MEASURED before this guard shipped: the
    machine's pull requests arrive carrying `dependencies` and an ecosystem
    label and no `deploy:` label, because nothing has ever asked it for one.
    THIS IS A HOLE, NOT A PRINCIPLE, AND IT HAS A CLOSING CONDITION. Unlike
    a title prefix, a machine author's labels ARE per-repository configuration:
    `dependabot.yml` takes a `labels:` key, and a repository that sets it to
    its own correct `deploy:` value classifies every bump without anyone's
    hand. The exemption's message says so at every firing, so the hole reports
    itself rather than being remembered. The exemption is the AUTHOR, never the
    emptiness: the same empty label set from any other author is refused.

    Remove the author from EXEMPT_AUTHORS once every repository calling this
    guard sets `labels:` in `dependabot.yml`; the self-test's last refusal arm
    already pins the behaviour you would be turning on.

    python3 check_deploy_label.py --labels-json '["deploy:none"]'
    python3 check_deploy_label.py --labels-json "$PR_LABELS_JSON" --author "$PR_AUTHOR"
    (the action passes both through the environment, never interpolated into
    shell -- a label name is repository-controlled text)
"""

from __future__ import annotations

import argparse
import json
import sys

PREFIX = "deploy:"

EXEMPT_AUTHORS = ("dependabot[bot]",)

#: Named so the refusal can point somewhere a reader can act, without this file
#: claiming to know which values are declared today.
WHERE_DECLARED = "`labels.yml` in this estate's shared CI repository"


def label_names(raw: str) -> list[str]:
    """The label names in `raw`, which is either GitHub's array of label objects
    (`toJSON(github.event.pull_request.labels)`) or a plain array of strings.

    Accepting both is not politeness: the workflow passes the first, a person
    debugging passes the second, and a guard that could only be exercised the
    hard way would be exercised rarely.
    """
    if not raw.strip():
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(
            "deploy-label CANNOT READ its input: %s\n"
            "  Pass toJSON(github.event.pull_request.labels), or a JSON array of names." % exc
        )
    if not isinstance(parsed, list):
        raise SystemExit("deploy-label CANNOT READ its input: expected a JSON array, got %s"
                         % type(parsed).__name__)
    names = []
    for entry in parsed:
        if isinstance(entry, str):
            names.append(entry)
        elif isinstance(entry, dict) and isinstance(entry.get("name"), str):
            names.append(entry["name"])
        else:
            raise SystemExit(
                "deploy-label CANNOT READ its input: an array entry is neither a name nor "
                "an object carrying one: %r" % (entry,)
            )
    return names


def judge(names: list[str], author: str = "") -> list[str]:
    """Every violation, empty when the pull request conforms."""
    deploy = [n for n in names if n.startswith(PREFIX)]

    if author in EXEMPT_AUTHORS and not deploy:
        print(
            "exempt: author '%s' opens pull requests with no `deploy:` label because nothing "
            "has asked it for one. This is a HOLE with a closing condition, not a principle: "
            "set `labels:` in this repository's `dependabot.yml` to its own correct `deploy:` "
            "value and every bump classifies itself, after which this exemption can be "
            "deleted." % author
        )
        return []

    if not deploy:
        near = [n for n in names if "deploy" in n.lower()]
        problem = (
            "no `deploy:` label. A pull request carrying none is unclassified -- the merge log "
            "cannot later tell a change that deployed nothing from one that moved production, "
            "and the answer is not recoverable after the fact. Apply exactly one; the declared "
            "values are in %s and in this repository's label list." % WHERE_DECLARED
        )
        if near:
            problem += (
                " (Carried, but not counted: %s. The prefix is `deploy:`, with the colon, and "
                "at the start of the name.)" % ", ".join(repr(n) for n in near)
            )
        return [problem]

    if len(deploy) > 1:
        return [
            "%d `deploy:` labels (%s). A merge does one thing to a box; two labels make two "
            "claims about it and the log cannot resolve them. Leave exactly one."
            % (len(deploy), ", ".join(repr(n) for n in sorted(deploy)))
        ]

    return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels-json", help="the PR's labels, as JSON")
    parser.add_argument("--author", default="", help="the PR author's login, for the machine-author exemption")
    parser.add_argument("--self-test", action="store_true", help="prove the guard fires and goes quiet")
    args = parser.parse_args()

    if args.self_test:
        return self_test()
    if args.labels_json is None:
        parser.error("--labels-json is required outside --self-test")

    names = label_names(args.labels_json)
    problems = judge(names, args.author)
    if not problems:
        carried = [n for n in names if n.startswith(PREFIX)]
        print("deploy-label OK: %s" % (carried[0] if carried else "exempt"))
        return 0
    print("deploy-label REFUSED. Labels carried: %s"
          % (", ".join(repr(n) for n in names) if names else "(none)"), file=sys.stderr)
    for p in problems:
        print("  - %s" % p, file=sys.stderr)
    return 1


def self_test() -> int:
    """Calibrate both polarities, including the exemption and its absence.

    Every fixture is constructed. Nothing here names a real pull request: this
    file is the kind of thing that gets vendored, and a measurement a stranger
    cannot re-run does not travel with it.
    """
    passes = [
        # (labels, author, why this shape must pass)
        (["deploy:none"], "", "the minimum: exactly one"),
        (["documentation", "review:now", "deploy:cd", "area:ci"], "", "one among many, other axes ignored"),
        (["deploy:by-hand"], "", "a value this file does not enumerate still passes"),
        ([], "dependabot[bot]", "the machine-author hole, printed when it applies"),
        (["dependencies", "github_actions"], "dependabot[bot]", "the machine's real label shape"),
        (["dependencies", "deploy:cd"], "dependabot[bot]", "the exemption does not fire when it need not"),
    ]
    refusals = [
        # (labels, author, a word the refusal must NAME)
        ([], "", "unclassified"),
        (["documentation", "review:this-week"], "", "unclassified"),
        (["deploy:none", "deploy:cd"], "", "two"),
        (["deploy:none", "deploy:cd", "deploy:by-hand"], "", "3"),
        # The prefix is `deploy:`. Each of these carries the word and no classification:
        (["deployment"], "", "colon"),
        (["deploy-now"], "", "colon"),
        (["not-deploy:cd"], "", "colon"),
        # THE ARM THAT MAKES THE EXEMPTION AN EXEMPTION: the same empty label
        # set, from anyone else, is refused. Without this a reader cannot tell
        # "dependabot is exempt" from "an empty label set passes".
        ([], "a-human", "unclassified"),
    ]

    failed = 0
    for names, author, why in passes:
        problems = judge(names, author)
        if problems:
            print("SELF-TEST FAIL: should pass (%s) but was refused: %r -> %s" % (why, names, problems))
            failed += 1
    for names, author, must_name in refusals:
        problems = judge(names, author)
        if not problems:
            print("SELF-TEST FAIL: should be refused but passed: %r (author %r)" % (names, author))
            failed += 1
        elif not any(must_name in p for p in problems):
            print("SELF-TEST FAIL: refused, but no cause names %r: %r -> %s" % (must_name, names, problems))
            failed += 1

    # The reader is a control too: an input it cannot parse must be loud, not empty.
    for bad in ("{not json", '{"name": "deploy:none"}', "[1, 2]"):
        try:
            label_names(bad)
        except SystemExit:
            pass
        else:
            print("SELF-TEST FAIL: unreadable input parsed quietly: %r" % bad)
            failed += 1
    # ...and an input it CAN parse in both shapes must give the same answer.
    if label_names('["deploy:none"]') != label_names('[{"name": "deploy:none"}]'):
        print("SELF-TEST FAIL: the two accepted input shapes disagree")
        failed += 1

    if failed:
        print("self-test: %d case(s) FAILED" % failed)
        return 1
    print("self-test OK: %d pass, %d refusals, every refusal naming its cause, "
          "the reader loud on what it cannot read." % (len(passes), len(refusals)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
