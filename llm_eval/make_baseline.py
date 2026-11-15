"""Record a baseline from a known-good build: python -m llm_eval.make_baseline

Commit the resulting llm_eval/baseline.json. CI compares every new run to it.
Only refresh the baseline deliberately, after reviewing why numbers changed.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from qa.server import ServerProcess

from .runner import run_eval

OUT = Path(__file__).parent / "baseline.json"


def main():
    base_url = os.environ.get("FINSYNC_BASE_URL")
    if base_url:
        res = run_eval(base_url, repeat=5, tag="baseline")
    else:
        with ServerProcess("") as s:
            res = run_eval(s.base_url, repeat=5, tag="baseline")
    OUT.write_text(json.dumps(res, indent=2))
    s = res["summary"]
    print(f"baseline written: {s['cases']} cases, pass rate {s['overall_pass_rate']:.1%}, "
          f"hallucination {s['hallucination_rate']:.1%}")


if __name__ == "__main__":
    main()
