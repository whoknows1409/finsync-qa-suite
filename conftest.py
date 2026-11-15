"""Shared fixtures.

By default the suite starts the bundled stand-in FinSync server itself. To test
a deployed instance instead:
    FINSYNC_BASE_URL=https://your-finsync.example.com  (and optionally
    FINSYNC_CREDENTIALS='{"user":"password"}', FINSYNC_DB_PATH=/path/to/db for SQL tests)
To test a deliberately buggy build of the stand-in:  FINSYNC_BUGS=pii_leak,hallucination
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")

from qa.client import FinSyncClient  # noqa: E402
from qa.server import ServerProcess  # noqa: E402


@pytest.fixture(scope="session")
def server():
    external = os.environ.get("FINSYNC_BASE_URL")
    if external:
        yield SimpleNamespace(base_url=external, db_path=os.environ.get("FINSYNC_DB_PATH"))
        return
    with ServerProcess(os.environ.get("FINSYNC_BUGS", "")) as s:
        yield s


@pytest.fixture(scope="session")
def base_url(server):
    return server.base_url


@pytest.fixture(scope="session")
def client(base_url):
    return FinSyncClient(base_url)


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    setattr(item, f"rep_{rep.when}", rep)
