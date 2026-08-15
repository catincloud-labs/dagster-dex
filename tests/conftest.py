# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""A skipped conformance assertion is a criterion not met, not one met quietly.

**The hole this closes.** `tests/test_upstream_contract.py` runs this format
against the conformance suite dex-core ships, which is upstream's acceptance
criterion for a second project format. Upstream declines to judge a format on
assertions it cannot reach: a declared-content hook returning ``None`` makes the
matching test **skip**, with a reason naming what went unchecked. One of those
reasons said outright that an implementation mirroring one side of a join onto
the other would pass the suite.

So the criterion step could report green over assertions that never ran, and a
green step is exactly how it would be read. `DEX_UPSTREAM_CONTRACT_REQUIRED=1`
already turns a *missing* contract into a collection error; this turns a
*skipped* one into a failure, which is the same argument applied one level in.

**Scoped by marker, deliberately, not by file or by run.** `publish.yml` runs
the whole suite with that variable set, and `tests/test_ascii_only.py` carries a
legitimate `skipif` for a file that is not always present. A run-scoped guard
would fail on it. `pytest.mark.criterion` says "this assertion is upstream's to
make", and only those are held to zero skips. It also survives a rename, which a
filename check would not.

**The zero-collected arm is the half that replaces a count.** This package used
to record the number of assertions the criterion step collected, re-derived at
every engine bump. That number is not carried here: it measured the size of
somebody else's suite, and a number in a document drifts from the thing it
describes. What is kept is the property the number was watching for - that the
step ran *something* - because a green scan of nothing is indistinguishable from
a green scan of everything.

**What this does not catch, stated so it is not assumed:** upstream silently
deleting an assertion from inside a contract this format mixes in. Only a count
sees that, and the count was never ours to hold constant. The coverage test in
`test_upstream_contract.py` is the answer to the adjacent case - upstream adding
a contract nobody here considered.

Engine-free on purpose: this module imports `pytest` and the standard library
only, so it loads in the control step alongside everything else that must work
without dex-core installed.
"""

from __future__ import annotations

import os

import pytest

#: The variable already means "in this run, a skip is not a signal". This guard
#: extends the meaning it carries rather than inventing a second switch, which
#: is also why no workflow edit was needed to arm it.
REQUIRED_ENV = "DEX_UPSTREAM_CONTRACT_REQUIRED"

#: Applied at module scope in `test_upstream_contract.py`, so it propagates to
#: every assertion inherited from an upstream contract class.
MARKER = "criterion"

_collected: set[str] = set()
_skipped: list[tuple[str, str]] = []


def _skip_reason(report: pytest.TestReport) -> str:
    """The reason pytest recorded, which is the useful half of the report.

    Upstream's skip reasons name the assertion that went unchecked, so a failure
    here that printed only node ids would send a reader to find out something
    the run already knew.
    """

    longrepr = report.longrepr
    if isinstance(longrepr, tuple) and len(longrepr) == 3:
        return str(longrepr[2])
    return str(longrepr) if longrepr else "(no reason recorded)"


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):  # type: ignore[no-untyped-def]
    outcome = yield
    report = outcome.get_result()

    if item.get_closest_marker(MARKER) is None:
        return

    _collected.add(item.nodeid)

    # `wasxfail` rides on a report for an expected failure, which is a different
    # statement from "this was not run" and is not what this guard is about.
    if report.skipped and not hasattr(report, "wasxfail"):
        _skipped.append((item.nodeid, _skip_reason(report)))


def pytest_sessionfinish(session, exitstatus):  # type: ignore[no-untyped-def]
    if os.environ.get(REQUIRED_ENV) != "1":
        return

    problems: list[str] = []

    if not _collected:
        problems.append(
            f"no test carrying the '{MARKER}' marker was collected, so the "
            f"criterion proved nothing. A green run over zero assertions and a "
            f"green run over all of them look identical from outside."
        )

    for nodeid, reason in _skipped:
        problems.append(f"criterion assertion skipped: {nodeid}\n    reason: {reason}")

    if not problems:
        return

    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    lines = [
        "",
        f"{REQUIRED_ENV}=1 is set, so a skipped criterion assertion is a failure:",
        "",
        *problems,
        "",
        "A skipped conformance assertion is a criterion not met, not a criterion",
        "met quietly. Supply the hook upstream is asking for, or declare the tier",
        "declined and say so where the coverage test can see it.",
        "",
    ]
    message = "\n".join(lines)

    if reporter is not None:
        reporter.write_line(message)
    else:  # pragma: no cover - reporter is present under every runner used here
        print(message)

    session.exitstatus = pytest.ExitCode.TESTS_FAILED
