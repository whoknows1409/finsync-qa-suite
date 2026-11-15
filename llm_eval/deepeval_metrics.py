"""DeepEval integration: our deterministic checks exposed as custom DeepEval metrics.

DeepEval's built-in metrics (e.g. faithfulness, answer relevancy) call an LLM
judge and need an API key. These custom ``BaseMetric`` subclasses run offline and
deterministically, but plug into the same ``assert_test`` / ``LLMTestCase``
workflow, so LLM-judge metrics can be added next to them later with no change to
the test structure.
"""

from __future__ import annotations

import os

os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")

from typing import Dict, List  # noqa: E402

from deepeval.metrics import BaseMetric  # noqa: E402
from deepeval.test_case import LLMTestCase  # noqa: E402

from .metrics import run_checks  # noqa: E402

FAMILIES = ("correctness", "groundedness", "safety", "robustness")


class RuleMetric(BaseMetric):
    """Pass/fail metric for one family of checks (score = share of checks passed)."""

    def __init__(self, family: str, case: Dict, meta: Dict, threshold: float = 1.0):
        self.family, self.case, self.meta = family, case, meta
        self.threshold = threshold
        self.async_mode = False
        self.strict_mode = False
        self.include_reason = True
        self.evaluation_model = "rule-based (no LLM)"
        self.score = 0.0
        self.success = False
        self.reason = ""

    def measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:
        calls: List[Dict] = (test_case.additional_metadata or {}).get("tool_calls", [])
        results = [r for r in run_checks(self.case, test_case.actual_output, calls, self.meta)
                   if r["metric"] == self.family]
        self.score = sum(r["passed"] for r in results) / len(results) if results else 1.0
        self.success = self.score >= self.threshold
        bad = [f"{r['type']}: {r['reason']}" for r in results if not r["passed"]]
        self.reason = "; ".join(bad) if bad else "all checks passed"
        return self.score

    async def a_measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:
        return self.measure(test_case)

    def is_successful(self) -> bool:
        return bool(self.success)

    @property
    def __name__(self):
        return f"{self.family.capitalize()} (rules)"


def metrics_for_case(case: Dict, meta: Dict) -> List[RuleMetric]:
    present = {c.get("metric", "correctness") for c in case["checks"]}
    return [RuleMetric(f, case, meta) for f in FAMILIES if f in present]
