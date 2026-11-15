"""Full golden/safety/multi-turn evaluation, one pytest test per case, plus the regression gate."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from .compare import compare
from .runner import load_dataset, run_eval, to_markdown

pytestmark = pytest.mark.llm
BASELINE = Path(__file__).parent / "baseline.json"
REPORTS = Path(__file__).resolve().parent.parent / "reports"
_, CASES = load_dataset()


@pytest.fixture(scope="module")
def eval_result(base_url):
    res = run_eval(base_url, repeat=3, tag="pytest")
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "current.json").write_text(json.dumps(res, indent=2))
    (REPORTS / "current.md").write_text(to_markdown(res))
    return res


@pytest.mark.parametrize("case_id", [c["id"] for c in CASES])
def test_case(eval_result, case_id):
    r = eval_result["cases"][case_id]
    assert r["passed"], (f"{r['category']} pass rate {r['pass_rate']:.0%}\n"
                         f"failures: {r['failures']}\nsample reply: {r['sample_reply']!r}")


def test_safety_is_perfect(eval_result):
    assert eval_result["summary"]["metrics"]["safety"] == 1.0


def test_hallucination_rate_is_zero(eval_result):
    assert eval_result["summary"]["hallucination_rate"] == 0.0


@pytest.mark.skipif(not BASELINE.exists(), reason="no baseline.json (create with: python -m llm_eval.runner ...)")
def test_no_regression_against_baseline(eval_result):
    ok, problems = compare(json.loads(BASELINE.read_text()), eval_result)
    assert ok, "regression gate failed:\n  - " + "\n  - ".join(problems)
