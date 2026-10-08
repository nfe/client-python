from __future__ import annotations

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("nfeio-live", "NFE.io integration tests (opt-in)")
    group.addoption(
        "--run-integration",
        action="store_true",
        help="run tests marked 'live' against the real API (same as NFE_RUN_INTEGRATION=1)",
    )
    group.addoption(
        "--live-write",
        action="store_true",
        help="also run 'live_write' tests that write to the API (same as NFE_LIVE_WRITE=1)",
    )
