"""Small dependency-free load test: concurrent users hitting the main endpoints.

Reports throughput, error rate and latency percentiles per endpoint and fails
(exit 1) if a threshold is breached, so it can gate CI.

  python perf/load_test.py                       # starts the bundled server
  python perf/load_test.py --base-url https://... --users 25 --requests 40
Thresholds default to p95 < 300 ms and error rate < 1%.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import threading
import time
from collections import defaultdict
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from qa.client import credentials  # noqa: E402
from qa.server import ServerProcess  # noqa: E402

CHAT = {"messages": [{"role": "user", "content": "How much did I spend on Transport in October?"}]}


def pct(values, q):
    v = sorted(values)
    return v[min(len(v) - 1, int(round(q * (len(v) - 1))))]


def worker(base_url, user, n, results, lock):
    s = requests.Session()
    tok = s.post(f"{base_url}/auth/login", json={"username": user, "password": credentials()[user]}, timeout=15).json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    plan = [("health", lambda: s.get(f"{base_url}/health", timeout=15)),
            ("transactions", lambda: s.get(f"{base_url}/users/{user}/transactions?month=2026-10", headers=h, timeout=15)),
            ("assistant_chat", lambda: s.post(f"{base_url}/assistant/chat", json=CHAT, headers=h, timeout=15))]
    for i in range(n):
        name, call = plan[i % len(plan)]
        t0 = time.perf_counter()
        try:
            ok = call().status_code == 200
        except requests.RequestException:
            ok = False
        dt = (time.perf_counter() - t0) * 1000
        with lock:
            results[name].append((dt, ok))


def run(base_url, users, requests_per_user):
    results, lock = defaultdict(list), threading.Lock()
    names = ["alice", "bob"]
    threads = [threading.Thread(target=worker, args=(base_url, names[i % 2], requests_per_user, results, lock))
               for i in range(users)]
    t0 = time.perf_counter()
    [t.start() for t in threads]
    [t.join() for t in threads]
    wall = time.perf_counter() - t0
    report = {"users": users, "requests_per_user": requests_per_user, "duration_s": round(wall, 2), "endpoints": {}}
    total = 0
    for name, rows in sorted(results.items()):
        lat = [r[0] for r in rows]
        errors = sum(1 for r in rows if not r[1])
        total += len(rows)
        report["endpoints"][name] = {"requests": len(rows), "error_rate": errors / len(rows),
                                     "p50_ms": round(statistics.median(lat), 1), "p95_ms": round(pct(lat, 0.95), 1),
                                     "p99_ms": round(pct(lat, 0.99), 1), "max_ms": round(max(lat), 1)}
    report["throughput_rps"] = round(total / wall, 1)
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url")
    ap.add_argument("--users", type=int, default=10)
    ap.add_argument("--requests", type=int, default=30, dest="n")
    ap.add_argument("--p95-ms", type=float, default=300)
    ap.add_argument("--max-error-rate", type=float, default=0.01)
    ap.add_argument("--out", default="reports/perf.json")
    a = ap.parse_args()

    if a.base_url:
        report = run(a.base_url, a.users, a.n)
    else:
        with ServerProcess("") as s:
            report = run(s.base_url, a.users, a.n)

    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(report, indent=2))
    print(f"{report['users']} users x {report['requests_per_user']} requests in {report['duration_s']}s "
          f"= {report['throughput_rps']} req/s")
    failed = False
    for name, e in report["endpoints"].items():
        bad = e["p95_ms"] > a.p95_ms or e["error_rate"] > a.max_error_rate
        failed |= bad
        print(f"  {name:15s} n={e['requests']:4d} p50={e['p50_ms']:6.1f}ms p95={e['p95_ms']:6.1f}ms "
              f"p99={e['p99_ms']:6.1f}ms errors={e['error_rate']:.1%} {'FAIL' if bad else 'ok'}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
