"""Playwright fixtures. On failure we keep a screenshot and a trace for debugging."""

from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

ARTIFACTS = Path(__file__).resolve().parent.parent / "reports" / "ui_artifacts"


@pytest.fixture(scope="session")
def ui_browser():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        yield browser
        browser.close()


@pytest.fixture
def ui_page(ui_browser, request):
    context = ui_browser.new_context(viewport={"width": 1280, "height": 800})
    context.tracing.start(screenshots=True, snapshots=True)
    page = context.new_page()
    page.set_default_timeout(8000)
    yield page
    failed = getattr(request.node, "rep_call", None) is not None and request.node.rep_call.failed
    if failed:
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        name = request.node.name.replace("/", "_")
        page.screenshot(path=str(ARTIFACTS / f"{name}.png"), full_page=True)
        context.tracing.stop(path=str(ARTIFACTS / f"{name}.zip"))
    else:
        context.tracing.stop()
    context.close()
