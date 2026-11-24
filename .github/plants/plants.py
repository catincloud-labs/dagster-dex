# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""The sweep's plant pass (#222). Branch-only: removed before the merge.

`list` prints every plant as JSON: one deletion per branch of the code that
enforces the suite's clauses, generated from the source with `ast`, plus the
hand plants in HAND. `run GROUP OF` applies each plant of one group to this
checkout in turn, runs the suite in both engine arms with a junit report per
arm, and restores the file. A control (no plant) runs first in every group.

A deletion is spliced into the file's text at the node's own offsets, so every
other byte of the file is unchanged: a test that reads a source file sees only
the plant.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

TARGETS = sorted(
    [str(p.relative_to(ROOT)).replace("\\", "/") for p in (ROOT / "src" / "dagster_dex").glob("*.py")]
    + [
        "scripts/file_upstream_red.py",
        "scripts/check_readme_excerpt.py",
        "tests/conftest.py",
    ]
)

# Test files whose module-level helpers ARE the control their cases calibrate:
# only those helpers are planted, never a test's own body.
HELPER_TARGETS = [
    "tests/test_ascii_only.py",
    "tests/test_design_docs.py",
    "tests/test_documented_commands.py",
    "tests/test_pin_coherence.py",
    "tests/test_load_time_checks.py",
    "tests/test_packaging.py",
]

# Named defects: each is a failure `AGENTS.md` or the code's own text names.
HAND: list[dict[str, str]] = [
    {"id": "hand-semantic-notes", "file": "src/dagster_dex/dex.py", "line": "371",
     "kind": "notes= dropped from the SemanticLayer constructor (AGENTS.md, Sharp edges)",
     "old": "        metrics=metrics,\n        notes=list(semantic_layer_notes(declarations)),\n",
     "new": "        metrics=metrics,\n"},
    {"id": "hand-transform-notes", "file": "src/dagster_dex/dex.py", "line": "234",
     "kind": "notes= dropped from the TransformLayer constructor (the same defect, other layer)",
     "old": "        notes=list(transform_layer_notes(declarations)),\n", "new": ""},
    {"id": "hand-empty-path", "file": "src/dagster_dex/dex.py", "line": "216",
     "kind": "path is the empty-string sentinel, not None (AGENTS.md, Sharp edges)",
     "old": "path=source.declared_in or None,", "new": "path=source.declared_in or \"\","},
    {"id": "hand-within-prefix", "file": "src/dagster_dex/project.py", "line": "689",
     "kind": "_within by string prefix, not by segment (AGENTS.md; its docstring)",
     "old": "        candidate == PurePosixPath(prefix) or PurePosixPath(prefix) in candidate.parents\n",
     "new": "        candidate.as_posix().startswith(prefix)\n"},
    {"id": "hand-verify-floor-exclusive", "file": "src/dagster_dex/dex.py", "line": "1614",
     "kind": "the verify floor's inclusive bound made exclusive",
     "old": "    if _release_tuple(release) < VERIFY_JUDGES_FROM:\n",
     "new": "    if _release_tuple(release) <= VERIFY_JUDGES_FROM:\n"},
    {"id": "hand-grain-floor-exclusive", "file": "src/dagster_dex/dex.py", "line": "1663",
     "kind": "the grain-coverage floor's inclusive bound made exclusive",
     "old": "    if _release_tuple(release) >= GRAIN_COVERAGE_FROM:\n",
     "new": "    if _release_tuple(release) > GRAIN_COVERAGE_FROM:\n"},
    {"id": "hand-placement-case", "file": "src/dagster_dex/dex.py", "line": "810",
     "kind": "placement matches the table name with regard to case (#141)",
     "old": "        wanted = {f\"{model}{suffix}\".lower() for suffix in _YAML_SUFFIXES}\n",
     "new": "        wanted = {f\"{model}{suffix}\" for suffix in _YAML_SUFFIXES}\n"},
    {"id": "hand-placement-case-key", "file": "src/dagster_dex/dex.py", "line": "814",
     "kind": "placement matches the file key with regard to case (#141)",
     "old": "key.startswith(prefix) and key[len(prefix) :].lower() in wanted",
     "new": "key.startswith(prefix) and key[len(prefix) :] in wanted"},
]


def _offsets(text: str) -> list[int]:
    starts = [0]
    for line in text.split("\n"):
        starts.append(starts[-1] + len(line) + 1)
    return starts


def _span(starts: list[int], node: ast.AST) -> tuple[int, int]:
    return (
        starts[node.lineno - 1] + node.col_offset,  # type: ignore[attr-defined]
        starts[node.end_lineno - 1] + node.end_col_offset,  # type: ignore[attr-defined]
    )


def _block(starts: list[int], body: list[ast.stmt], text: str, replacement: str) -> tuple[int, int, str]:
    a, _ = _span(starts, body[0])
    _, b = _span(starts, body[-1])
    return a, b, replacement


def _in_test_body(stack: list[ast.AST]) -> bool:
    return any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test_") for n in stack) or any(
        isinstance(n, ast.ClassDef) and n.name.startswith("Test") for n in stack
    )


def _sites(path: str, helpers_only: bool) -> list[dict[str, object]]:
    text = (ROOT / path).read_text(encoding="utf-8")
    tree = ast.parse(text)
    starts = _offsets(text)
    out: list[dict[str, object]] = []

    def add(kind: str, node: ast.AST, a: int, b: int, rep: str) -> None:
        out.append({"file": path, "line": node.lineno, "kind": kind, "a": a, "b": b, "rep": rep})  # type: ignore[attr-defined]

    def visit(node: ast.AST, stack: list[ast.AST]) -> None:
        # In a test file only a helper's own code is planted: never a test's
        # body, never module-level statements.
        skip = helpers_only and (
            _in_test_body(stack) or not any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) for n in stack)
        )
        if not skip:
            if isinstance(node, ast.If):
                add("if-body deleted", node, *_block(starts, node.body, text, "pass"))
                if node.orelse:
                    add("else-body deleted", node.orelse[0], *_block(starts, node.orelse, text, "pass"))
            elif isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
                add("loop-body deleted", node, *_block(starts, node.body, text, "pass"))
            elif isinstance(node, ast.Try):
                for h in node.handlers:
                    add("except-handler deleted (re-raises)", h, *_block(starts, h.body, text, "raise"))
            elif isinstance(node, ast.IfExp):
                a, b = _span(starts, node)
                body = ast.get_source_segment(text, node.body)
                orelse = ast.get_source_segment(text, node.orelse)
                add("ifexp true-arm deleted", node, a, b, f"({orelse})")
                add("ifexp false-arm deleted", node, a, b, f"({body})")
            elif isinstance(node, ast.BoolOp):
                a, b = _span(starts, node)
                op = " and " if isinstance(node.op, ast.And) else " or "
                segs = [ast.get_source_segment(text, v) for v in node.values]
                for i in range(len(segs)):
                    rest = [s for j, s in enumerate(segs) if j != i]
                    add(f"boolop operand {i + 1} deleted", node, a, b, "(" + op.join(f"({s})" for s in rest) + ")")
            elif isinstance(node, ast.comprehension):
                for cond in node.ifs:
                    a, b = _span(starts, cond)
                    add("comprehension filter deleted", cond, a, b, "True")
            elif isinstance(node, ast.Match):
                for case in node.cases:
                    add("match-case body deleted", case.pattern, *_block(starts, case.body, text, "pass"))
        for child in ast.iter_child_nodes(node):
            visit(child, stack + [node])

    visit(tree, [])
    return out


def plants() -> list[dict[str, object]]:
    found: list[dict[str, object]] = []
    for path in TARGETS:
        found += _sites(path, helpers_only=False)
    for path in HELPER_TARGETS:
        found += _sites(path, helpers_only=True)
    for i, p in enumerate(found):
        stem = Path(str(p["file"])).stem
        p["id"] = f"{stem}-{i:04d}"
    for h in HAND:
        found.append(dict(h))
    return found


def apply(p: dict[str, object]) -> str:
    path = ROOT / str(p["file"])
    text = path.read_text(encoding="utf-8")
    if "old" in p:
        old, new = str(p["old"]), str(p["new"])
        if text.count(old) != 1:
            raise SystemExit(f"hand plant {p['id']}: {text.count(old)} matches")
        planted = text.replace(old, new)
    else:
        a, b = int(p["a"]), int(p["b"])  # type: ignore[arg-type]
        planted = text[:a] + str(p["rep"]) + text[b:]
    compile(planted, str(path), "exec")
    path.write_text(planted, encoding="utf-8", newline="\n")
    return text


ARMS = {
    "ceiling": ["tests", "--ignore=tests/test_upstream_contract.py"],
    "ceiling-contract": ["tests/test_upstream_contract.py"],
    "pin": ["tests", "--ignore=tests/test_upstream_contract.py"],
    "pin-contract": ["tests/test_upstream_contract.py"],
}


def run_one(pid: str, out: Path) -> None:
    env = dict(os.environ, DEX_UPSTREAM_CONTRACT_REQUIRED="1")
    for arm, args in ARMS.items():
        venv = os.environ["VENV_" + arm.split("-")[0].upper()]
        junit = out / f"{pid}__{arm}.xml"
        try:
            r = subprocess.run(
                [f"{venv}/bin/python", "-m", "pytest", *args, "-q", "-p", "no:cacheprovider", f"--junitxml={junit}"],
                cwd=ROOT, env=env, timeout=int(os.environ.get("PLANT_CAP", "300")),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            )
            tail = r.stdout.strip().splitlines()[-1:] if r.stdout.strip() else ["(no output)"]
            print(f"  {arm:17} rc={r.returncode} {tail[0]}")
            if not junit.exists():
                (out / f"{pid}__{arm}.crash.txt").write_text(r.stdout[-20000:], encoding="utf-8")
        except subprocess.TimeoutExpired:
            print(f"  {arm:17} TIMEOUT")
            (out / f"{pid}__{arm}.timeout").write_text("", encoding="utf-8")


def main() -> int:
    if sys.argv[1] == "list":
        print(json.dumps(plants(), indent=1))
        return 0
    group, of = int(sys.argv[2]), int(sys.argv[3])
    out = Path(os.environ.get("PLANT_OUT", "plant-out"))
    out.mkdir(parents=True, exist_ok=True)
    every = plants()
    (out / "plants.json").write_text(json.dumps(every, indent=1), encoding="utf-8")
    mine = [p for i, p in enumerate(every) if i % of == group]
    print(f"group {group}/{of}: {len(mine)} plants of {len(every)}")
    print("control")
    run_one(f"control-g{group}", out)
    for p in mine:
        print(f"{p['id']} {p['file']}:{p['line']} {p['kind']}")
        try:
            original = apply(p)
        except (SyntaxError, SystemExit) as e:
            print(f"  NOT APPLIED: {e}")
            (out / f"{p['id']}.notapplied").write_text(str(e), encoding="utf-8")
            continue
        try:
            run_one(str(p["id"]), out)
        finally:
            (ROOT / str(p["file"])).write_text(original, encoding="utf-8", newline="\n")
    subprocess.run(["git", "diff", "--exit-code", "--stat"], cwd=ROOT, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
