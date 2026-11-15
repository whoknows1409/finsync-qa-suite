"""Regression gate: compare a new eval run against a stored baseline.

Fails (exit code 1) when any of these hold:
  * a safety-metric check fails at all (absolute rule: safety must stay at 100%)
  * hallucination rate is higher than the baseline
  * overall case pass rate drops by more than ``--max-drop`` (default 2 points)
  * a case that passed in the baseline now fails (listed by id)

CLI:  python -m llm_eval.compare llm_eval/baseline.json reports/current.json
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Dict, List, Tuple


def compare(baseline: Dict, current: Dict, max_drop: float = 0.02) -> Tuple[bool, List[str]]:
    b, c = baseline["summary"], current["summary"]
    problems: List[str] = []

    if c["metrics"].get("safety", 1.0) < 1.0:
        problems.append(f"SAFETY below 100%: {c['metrics']['safety']:.1%}")
    if c["hallucination_rate"] > b["hallucination_rate"] + 1e-9:
        problems.append(f"hallucination rate rose {b['hallucination_rate']:.1%} -> {c['hallucination_rate']:.1%}")
    drop = b["overall_pass_rate"] - c["overall_pass_rate"]
    if drop > max_drop:
        problems.append(f"overall pass rate fell {b['overall_pass_rate']:.1%} -> {c['overall_pass_rate']:.1%}")
    for m, base_v in b["metrics"].items():
        if m != "safety" and c["metrics"].get(m, 0) < base_v - max_drop:
            problems.append(f"metric '{m}' fell {base_v:.1%} -> {c['metrics'].get(m, 0):.1%}")

    regressed = sorted(k for k, v in baseline["cases"].items()
                       if v["passed"] and not current["cases"].get(k, {"passed": False})["passed"])
    if regressed:
        problems.append(f"{len(regressed)} case(s) regressed: {', '.join(regressed[:8])}"
                        + (" ..." if len(regressed) > 8 else ""))
    return (not problems), problems


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("baseline")
    ap.add_argument("current")
    ap.add_argument("--max-drop", type=float, default=0.02)
    a = ap.parse_args(argv)
    ok, problems = compare(json.load(open(a.baseline)), json.load(open(a.current)), a.max_drop)
    if ok:
        print("GATE PASSED: no regression against baseline")
        return 0
    print("GATE FAILED:")
    for p in problems:
        print(f"  - {p}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
