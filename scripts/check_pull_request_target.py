#!/usr/bin/env python3
"""Refuse the `pull_request_target` trigger in a repository's workflows.

WHY THIS EXISTS. A workflow triggered by `pull_request_target` runs in the
base repository's context, with its token and its secrets, and the obvious
way to make it useful (checking out the pull request's head) runs a fork's
code with both. A fork's pull request is otherwise run on `pull_request`,
with a read-only token and no secrets. That safety holds today only because
no workflow uses the trigger, and the first obvious fix for acting on a
fork's pull request automatically (labelling it, say) is exactly this
trigger. Absence is not a control; this file is.

WHAT IT READS. Every `*.yml` and `*.yaml` file directly under
`.github/workflows/` in the tree given by `--root`, which is every file
GitHub will run as a workflow (it reads no subdirectory). Each is parsed by
PyYAML's composer rather than its loader, for two reasons: the composer
keeps each node's line, so a refusal names file and line; and it keeps the
`on` key as the string it is, where a YAML 1.1 loader reads a bare `on` as
the boolean true.

WHAT IT REFUSES. `pull_request_target` as a trigger in the workflow's `on:`,
in each form the key takes:

  * a string:   on: pull_request_target
  * a list:     on: [push, pull_request_target]   (flow or block)
  * a mapping:  on: {pull_request_target: ...}     (flow or block)

The word anywhere else (a comment, a step's text, a job's name) is not a
trigger and passes. Every top-level `on` key is read, not the first, and the
key, the trigger and a file's suffix are compared without case: each of
those choices can only refuse more, never pass a trigger GitHub would run.

AN ALLOWED USE carries its reason on the trigger's own line, as a comment:

    pull_request_target:  # allow pull_request_target: <why, in words>

The marker is looked for only after the line's last YAML token, so the same
text inside a string on that line allows nothing. A trigger reached through
an alias is reported at its `on` key's line, and only a marker there allows
it. A marker with no reason is refused. Each allowed use is printed, because
an exemption nobody can see applied is indistinguishable from a guard that
did not fire.

IT IS RED, NOT QUIET, when it cannot look. A workflow file that does not
parse is refused by name, and so is a tree with no workflow file at all: a
repository that calls this guard has at least the workflow that calls it,
so an empty read is a wrong root, not a clean tree. PyYAML is stricter than
GitHub in a few places (a tab after a colon; a next-line or line-separator
character in a comment), and a file in those shapes is refused as
unparseable rather than passed.

WHAT IT DELIBERATELY DOES NOT DO. `workflow_run` consuming a fork's
artifacts and `issue_comment` workflows that check out a fork's head can
reach a fork's code with secrets too. They are a different shape of check
(what a job does, not which trigger it names) and are not read here.

    python3 check_pull_request_target.py --root .
    python3 check_pull_request_target.py --self-test
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys
import tempfile

import yaml

TRIGGER = "pull_request_target"

#: The allow marker on the trigger's line; group 1 is the reason.
ALLOW = re.compile(r"#\s*allow " + TRIGGER + r":\s*(\S.*?)\s*$")


def workflow_files(root: pathlib.Path) -> list[pathlib.Path]:
    """Every file GitHub would run as a workflow under `root`. The suffix is
    compared without case: reading a file GitHub ignores costs nothing, and
    missing one it runs is the failure this guard exists to prevent."""
    directory = root / ".github" / "workflows"
    if not directory.is_dir():
        return []
    return sorted(p for p in directory.iterdir() if p.is_file() and p.suffix.lower() in (".yml", ".yaml"))


def on_entries(document: yaml.Node | None) -> list[tuple[yaml.ScalarNode, yaml.Node]]:
    """Every top-level `on` key in a workflow document, with its value. Every
    one, not the first: a duplicate key must not hide a second trigger list."""
    if not isinstance(document, yaml.MappingNode):
        return []
    return [
        (key, value) for key, value in document.value
        if isinstance(key, yaml.ScalarNode) and key.value.lower() == "on"
    ]


def trigger_nodes(on: yaml.Node) -> list[yaml.ScalarNode]:
    """Each trigger named under `on`, as the scalar node that names it,
    compared without case."""
    if isinstance(on, yaml.ScalarNode):
        names = [on]
    elif isinstance(on, yaml.SequenceNode):
        names = [item for item in on.value if isinstance(item, yaml.ScalarNode)]
    elif isinstance(on, yaml.MappingNode):
        names = [key for key, _ in on.value if isinstance(key, yaml.ScalarNode)]
    else:
        names = []
    return [node for node in names if node.value.lower() == TRIGGER]


def code_ends(text: str) -> dict[int, int]:
    """For each line, the column where its last YAML token ends. Anything
    after it on the line is a comment or blank: a marker inside a string,
    which a line-wide search would also find, ends before it."""
    ends: dict[int, int] = {}
    for token in yaml.scan(text):
        line = token.end_mark.line
        ends[line] = max(ends.get(line, 0), token.end_mark.column)
    return ends


def trigger_line(key: yaml.ScalarNode, on: yaml.Node, node: yaml.ScalarNode) -> int:
    """The 0-based line a trigger is reported at, and its marker read from.
    A trigger reached through an alias is defined outside the `on` value;
    it is reported at the `on` key's line, and only a marker there allows it."""
    inside = (on.start_mark.line, on.start_mark.column) <= (node.start_mark.line, node.start_mark.column) \
        <= (on.end_mark.line, on.end_mark.column)
    return node.start_mark.line if inside else key.start_mark.line


def judge_file(path: pathlib.Path, shown: str) -> list[str]:
    """Every refusal in one workflow file, each naming `shown:line`."""
    try:
        text = path.read_text(encoding="utf-8")
        documents = list(yaml.compose_all(text))
        ends = code_ends(text)
    except (UnicodeDecodeError, yaml.YAMLError) as error:
        return [f"{shown}: could not be parsed, so its triggers cannot be read: {error}"]
    lines = text.splitlines()
    refusals: list[str] = []
    for document in documents:
        for key, on in on_entries(document):
            refusals += judge_triggers(key, on, lines, ends, shown)
    return refusals


def judge_triggers(key: yaml.ScalarNode, on: yaml.Node, lines: list[str], ends: dict[int, int],
                   shown: str) -> list[str]:
    """The refusals for one `on` entry's triggers."""
    refusals: list[str] = []
    for node in trigger_nodes(on):
        line = trigger_line(key, on, node)
        number = line + 1
        allowed = ALLOW.search(lines[line], ends.get(line, 0))
        if allowed:
            print(f"allowed: {shown}:{number}: {TRIGGER}, because: {allowed.group(1)}")
            continue
        refusals.append(
            f"{shown}:{number}: `{TRIGGER}` is a trigger here. It runs with the base repository's "
            "token and secrets and can be made to run a fork's code; use `pull_request`, or carry "
            f"`# allow {TRIGGER}: <reason>` as a comment on this line."
        )
    return refusals


def scan(root: pathlib.Path) -> tuple[int, list[str]]:
    """How many workflow files were read, and every refusal across them."""
    files = workflow_files(root)
    if not files:
        return 0, [
            f"no workflow file under {root / '.github' / 'workflows'}. A repository calling this "
            "guard has at least the workflow that calls it, so an empty read is a wrong root."
        ]
    refusals: list[str] = []
    for path in files:
        refusals += judge_file(path, path.relative_to(root).as_posix())
    return len(files), refusals


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=".", help="the checked-out tree whose workflows are read")
    parser.add_argument("--self-test", action="store_true", help="prove the guard fires and goes quiet")
    args = parser.parse_args()
    if args.self_test:
        return self_test()

    read, refusals = scan(pathlib.Path(args.root))
    print(f"read {read} workflow file(s) for `{TRIGGER}`.")
    if not refusals:
        print(f"{TRIGGER} OK: no workflow triggers on it unallowed.")
        return 0
    for refusal in refusals:
        print(f"::error::{refusal}")
    print(f"{TRIGGER} REFUSED: {len(refusals)} finding(s).", file=sys.stderr)
    return 1


# Self-test. Each fixture is a whole workflow file, written into a scratch
# tree's .github/workflows/ and read by scan(), the function main() runs.

STEPS = "jobs:\n  label:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo hello\n"

#: (file name, text, the `file:line` a refusal must name). One per form.
REFUSALS = [
    ("string.yml", "name: s\non: pull_request_target\n" + STEPS, "string.yml:2"),
    ("flow-list.yml", "name: f\non: [push, pull_request_target]\n" + STEPS, "flow-list.yml:2"),
    ("block-list.yml", "name: b\non:\n  - push\n  - pull_request_target\n" + STEPS, "block-list.yml:4"),
    ("block-map.yml", "name: m\non:\n  push:\n  pull_request_target:\n    types: [labeled]\n" + STEPS,
     "block-map.yml:4"),
    ("flow-map.yaml", "name: g\non: {pull_request_target: {types: [opened]}}\n" + STEPS, "flow-map.yaml:2"),
    ("quoted.yml", "name: q\n'on':\n  \"pull_request_target\":\n" + STEPS, "quoted.yml:3"),
    ("no-reason.yml", "name: n\non:\n  pull_request_target:  # allow pull_request_target:\n" + STEPS,
     "no-reason.yml:3"),
    ("broken.yml", "name: x\non: [push\n" + STEPS, "broken.yml: could not be parsed"),
    # A marker inside a string on the trigger's line is not a comment.
    ("spoof.yml", "name: v\non: {pull_request_target: {branches-ignore: ['# allow pull_request_target: no']}}\n"
     + STEPS, "spoof.yml:2"),
    ("spoof-tail.yml", 'name: w\non: {pull_request_target: null, x: "# allow pull_request_target: no"}\n' + STEPS,
     "spoof-tail.yml:2"),
    # A trigger defined by an alias is reported at the `on` key, and a marker
    # beside the anchor does not allow it.
    ("alias.yml", "name: l\nenv: {T: &t pull_request_target}  # allow pull_request_target: elsewhere\n"
     "on: [*t]\n" + STEPS, "alias.yml:3"),
    ("second-on.yml", "name: d\non: push\non: pull_request_target\n" + STEPS, "second-on.yml:3"),
    ("cased.yml", "name: k\nOn: Pull_Request_Target\n" + STEPS, "cased.yml:2"),
    ("upper.YML", "name: u\non: pull_request_target\n" + STEPS, "upper.YML:2"),
]

#: (file name, text): each mentions the word and must pass.
PASSES = [
    ("plain.yml", "name: p\non: pull_request\n" + STEPS),
    ("comment.yml", "name: c\n# never pull_request_target here\non:\n  pull_request:  # not pull_request_target\n"
     + STEPS),
    ("step-text.yml", "name: t\non: [push]\njobs:\n  pull_request_target:\n    runs-on: ubuntu-latest\n"
     "    steps:\n      - name: pull_request_target\n        run: echo pull_request_target\n"),
    ("other-key.yml", "name: o\non: {push: {branches: [pull_request_target]}}\n" + STEPS),
    ("allowed.yml", "name: a\non:\n  pull_request_target:  # allow pull_request_target: labels only, no checkout\n"
     + STEPS),
]


def scan_fixture(files: list[tuple[str, str]], subdirectory: bool = False) -> tuple[int, list[str]]:
    with tempfile.TemporaryDirectory() as tmp:
        directory = pathlib.Path(tmp, ".github", "workflows")
        directory.mkdir(parents=True)
        for name, text in files:
            target = directory / "nested" / name if subdirectory else directory / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8", newline="\n")
        return scan(pathlib.Path(tmp))


def wrong(case: str, refusals: list[str], must_name: str) -> int:
    """1 when a case's verdict is wrong; `must_name` empty means it must pass."""
    if not must_name and refusals:
        print(f"SELF-TEST FAIL: {case} should pass but was refused: {refusals}")
        return 1
    if must_name and not any(must_name in r for r in refusals):
        print(f"SELF-TEST FAIL: {case} should be refused naming '{must_name}': {refusals}")
        return 1
    return 0


def self_test() -> int:
    failed = sum(wrong(name, scan_fixture([(name, text)])[1], where) for name, text, where in REFUSALS)
    failed += sum(wrong(name, scan_fixture([(name, text)])[1], "") for name, text in PASSES)
    # Every pass beside one refusal: the refusal is still named, and only it.
    read, refusals = scan_fixture(PASSES + [REFUSALS[0][:2]])
    if read != len(PASSES) + 1 or len(refusals) != 1:
        print(f"SELF-TEST FAIL: a mixed tree read {read} file(s) and refused {len(refusals)}: {refusals}")
        failed += 1
    # A tree with no workflow is red, and a file GitHub would not run is not read.
    failed += wrong("an empty tree", scan_fixture([])[1], "no workflow file")
    failed += wrong("a nested file", scan_fixture([REFUSALS[0][:2]], subdirectory=True)[1], "no workflow file")
    cases = len(REFUSALS) + len(PASSES) + 3
    if failed:
        print(f"self-test: {failed} of {cases} case(s) FAILED")
        return 1
    print(f"self-test OK: {cases} cases, every form refused by file and line, every mention passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
