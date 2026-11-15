"""Run the eval datasets against a FinSync base URL and write a results file.

Each case is executed ``repeat`` times, because real LLMs are non-deterministic:
a single pass/fail hides flakiness. We report pass *rates* per case, per metric
family and per category, plus hallucination rate and latency percentiles.

CLI:
  python -m llm_eval.runner --base-url http://127.0.0.1:8000 --out reports/current.json --repeat 3
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from qa.client import FinSyncClient

from .metrics import run_checks

DATASETS = Path(__file__).parent / "datasets"


def load_dataset(names=("golden", "safety", "multiturn")):
    meta = yaml.safe_load((DATASETS / "meta.yaml").read_text())
    cases: List[Dict] = []
    for n in names:
        cases += yaml.safe_load((DATASETS / f"{n}.yaml").read_text())
    return meta, cases


def _pct(values: List[float], q: float) -> float:
    if not values:
        return 0.0
    v = sorted(values)
    return v[min(len(v) - 1, int(round(q * (len(v) - 1))))]


def run_eval(base_url: str, repeat: int = 3, names=("golden", "safety", "multiturn"),
             tag: str = "run") -> Dict:
    meta, cases = load_dataset(names)
    client = FinSyncClient(base_url)
    results: Dict[str, Dict] = {}
    metric_counts = defaultdict(lambda: [0, 0])          # metric -> [passed, total]
    halluc_runs = [0, 0]                                 # [runs with groundedness failure, runs with groundedness checks]
    latencies: List[float] = []

    for case in cases:
        runs = []
        for _ in range(repeat):
            resp = client.chat(case["user"], case["messages"], case.get("headers"))
            latencies.append(resp["wall_ms"])
            checks = run_checks(case, resp["reply"], resp["tool_calls"], meta)
            for c in checks:
                metric_counts[c["metric"]][1] += 1
                metric_counts[c["metric"]][0] += int(c["passed"])
            g = [c for c in checks if c["metric"] == "groundedness"]
            if g:
                halluc_runs[1] += 1
                halluc_runs[0] += int(any(not c["passed"] for c in g))
            runs.append({"reply": resp["reply"], "passed": all(c["passed"] for c in checks),
                         "failures": [f"{c['type']}: {c['reason']}" for c in checks if not c["passed"]]})
        pass_rate = sum(r["passed"] for r in runs) / len(runs)
        results[case["id"]] = {
            "category": case["category"], "pass_rate": pass_rate, "passed": pass_rate >= case.get("min_pass_rate", 1.0),
            "failures": sorted({f for r in runs for f in r["failures"]}), "sample_reply": runs[0]["reply"]}

    by_cat = defaultdict(list)
    for r in results.values():
        by_cat[r["category"]].append(r["passed"])
    summary = {
        "cases": len(results),
        "overall_pass_rate": sum(r["passed"] for r in results.values()) / len(results),
        "metrics": {m: p / t for m, (p, t) in sorted(metric_counts.items())},
        "hallucination_rate": (halluc_runs[0] / halluc_runs[1]) if halluc_runs[1] else 0.0,
        "by_category": {c: sum(v) / len(v) for c, v in sorted(by_cat.items())},
        "latency_ms": {"p50": round(statistics.median(latencies), 2), "p95": round(_pct(latencies, 0.95), 2)},
    }
    return {"meta": {"tag": tag, "repeat": repeat, "base_url": base_url,
                     "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")},
            "summary": summary, "cases": results}


def to_markdown(result: Dict) -> str:
    s = result["summary"]
    lines = [f"# LLM eval summary ({result['meta']['tag']})", "",
             f"- Cases: **{s['cases']}**, repeats per case: {result['meta']['repeat']}",
             f"- Overall case pass rate: **{s['overall_pass_rate']:.1%}**",
             f"- Hallucination rate: **{s['hallucination_rate']:.1%}**",
             f"- Latency p50 / p95: {s['latency_ms']['p50']} ms / {s['latency_ms']['p95']} ms", "",
             "| Metric | Pass rate |", "|---|---|"]
    lines += [f"| {m} | {v:.1%} |" for m, v in s["metrics"].items()]
    lines += ["", "| Category | Pass rate |", "|---|---|"]
    lines += [f"| {c} | {v:.0%} |" for c, v in s["by_category"].items()]
    failing = [(k, v) for k, v in result["cases"].items() if not v["passed"]]
    if failing:
        lines += ["", "## Failing cases"]
        for k, v in failing:
            lines.append(f"- `{k}` ({v['category']}, {v['pass_rate']:.0%}): {'; '.join(v['failures'][:2])}")
    return "\n".join(lines) + "\n"


def main(argv: Optional[List[str]] = None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--out", default="reports/current.json")
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--tag", default="run")
    a = ap.parse_args(argv)
    res = run_eval(a.base_url, a.repeat, tag=a.tag)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=2))
    out.with_suffix(".md").write_text(to_markdown(res))
    print(to_markdown(res))


if __name__ == "__main__":
    main()
