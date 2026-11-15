"""DeepEval-style tests: LLMTestCase + assert_test with our custom metrics."""

from __future__ import annotations

import pytest
from deepeval import assert_test
from deepeval.test_case import LLMTestCase

from .deepeval_metrics import metrics_for_case
from .runner import load_dataset

META, CASES = load_dataset()
# one representative case per category keeps this layer quick; the full set runs in test_llm_quality.py
_seen, SAMPLE = set(), []
for _c in CASES:
    if _c["category"] not in _seen:
        _seen.add(_c["category"])
        SAMPLE.append(_c)

pytestmark = pytest.mark.llm


@pytest.mark.parametrize("case", SAMPLE, ids=[c["id"] for c in SAMPLE])
def test_deepeval_case(case, client):
    resp = client.chat(case["user"], case["messages"], case.get("headers"))
    test_case = LLMTestCase(
        input=case["messages"][-1]["content"],
        actual_output=resp["reply"],
        additional_metadata={"tool_calls": resp["tool_calls"], "case_id": case["id"]},
    )
    assert_test(test_case, metrics_for_case(case, META), run_async=False)
