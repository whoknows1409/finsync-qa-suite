"""Tests of the test suite ("mutation testing").

For each known bug we start a build with that bug injected and assert that this
suite notices: the regression gate fails and the expected categories fail. If a
future change to the suite makes it blind to one of these, this file fails.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from llm_eval.compare import compare
from llm_eval.runner import run_eval
from qa.server import ROOT, ServerProcess

pytestmark = pytest.mark.meta
BASELINE = json.loads((Path(__file__).resolve().parent.parent / "llm_eval" / "baseline.json").read_text())

LLM_BUGS = {
    "hallucination": {"total_spent", "recurring", "categorise_unknown"},
    "no_refusal": {"off_topic_refusal", "blocked_topic_refusal"},
    "pii_leak": {"pii_protection"},
    "injection": {"prompt_injection"},
    "jailbreak": {"jailbreak"},
    "multiturn": {"multi_turn"},
    "tool_failure": {"tool_failure_recovery"},
}


@pytest.mark.parametrize("bug,expected_categories", LLM_BUGS.items(), ids=LLM_BUGS.keys())
def test_llm_eval_detects_bug(bug, expected_categories):
    with ServerProcess(bug) as s:
        res = run_eval(s.base_url, repeat=1, tag=bug)
    failed = {v["category"] for v in res["cases"].values() if not v["passed"]}
    assert expected_categories <= failed, f"{bug}: expected {expected_categories}, only saw {failed}"
    ok, problems = compare(BASELINE, res)
    assert not ok and problems, f"{bug}: regression gate did not fail"


def test_clean_build_passes_the_gate():
    with ServerProcess("") as s:
        res = run_eval(s.base_url, repeat=1, tag="clean")
    ok, problems = compare(BASELINE, res)
    assert ok, problems


API_BUGS = {
    "idor": "test_cannot_read_another_users_transactions",
    "no_rate_limit": "test_login_rate_limited_after_repeated_failures",
}


@pytest.mark.parametrize("bug,test_name", API_BUGS.items(), ids=API_BUGS.keys())
def test_api_suite_detects_bug(bug, test_name):
    env = dict(os.environ, FINSYNC_BUGS=bug)
    env.pop("FINSYNC_BASE_URL", None)
    proc = subprocess.run([sys.executable, "-m", "pytest", "api_tests/test_api.py", "-k", test_name, "-q",
                           "-p", "no:cacheprovider"], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
    assert proc.returncode != 0, f"API suite did not fail with bug '{bug}':\n{proc.stdout[-800:]}"
    assert "1 failed" in proc.stdout


def test_ui_xss_check_is_not_vacuous():
    """Sanity: the XSS test targets a real behaviour (selector exists and message is rendered)."""
    src = (Path(__file__).resolve().parent.parent / "target" / "app.py").read_text()
    assert "d.textContent=text" in src and "innerHTML=text" not in src
