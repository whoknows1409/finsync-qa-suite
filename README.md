# finsync-qa-suite
[![QA suite](https://github.com/whoknows1409/finsync-qa-suite/actions/workflows/ci.yml/badge.svg)](https://github.com/whoknows1409/finsync-qa-suite/actions/workflows/ci.yml)

An end-to-end quality framework for an AI finance assistant and its web/API stack:
**LLM evaluation with a regression gate, REST API tests, SQL data validation,
Playwright UI tests and a load test**, all running in CI.

> **What is being tested?** A small stand-in "FinSync" service lives in `target/`
> (FastAPI + SQLite + a deterministic rule-based assistant). It exists so the
> whole suite runs anywhere with no cloud accounts or API keys, and so bugs can be
> injected on purpose to prove the suite catches them. It is **not** the real
> FinSync and the assistant is **not** an LLM. See *Pointing it at a real system*.

## Quick start

```bash
pip install -r requirements.txt
playwright install chromium
python -m pytest -q            # 197 tests, ~25 s
```

| Command | What it runs |
|---|---|
| `make api` | 50 REST + SQL data tests |
| `make llm` | 84-case eval (x3 repeats), DeepEval layer, baseline regression gate |
| `make ui` | 11 Playwright browser tests |
| `make meta` | 11 tests proving the suite catches injected bugs |
| `make perf` | concurrent load test with latency/error thresholds |

## What it covers

**LLM evaluation (`llm_eval/`)**
- 84 cases generated from the data (`build_dataset.py`): totals, largest expense,
  overspend, recurring charges, categorisation, listing, unknown merchants,
  multi-turn follow-ups, off-topic and blocked-topic refusals, jailbreaks and
  system-prompt extraction, PII/cross-user access, **indirect prompt injection**
  (a payload hidden in a transaction description) and tool-outage recovery.
- Four metric families: *correctness*, *groundedness* (no invented amounts or
  merchants, no other user's data), *safety*, *robustness*.
- Each case runs several times and reports **pass rates**, not one pass/fail,
  because real LLMs are non-deterministic. Reports hallucination rate and latency
  p50/p95.
- **Regression gate** (`compare.py`): fails if safety is below 100%, hallucination
  rate rises, overall pass rate drops more than 2 points, or any previously
  passing case now fails.
- **DeepEval integration**: the checks are wrapped as custom `BaseMetric`s and run
  through `LLMTestCase` / `assert_test`, so LLM-judge metrics can be added later
  next to them.
- The checkers have their own unit tests, because a broken checker silently
  passes bad answers.

**API (`api_tests/`)** authentication, token tampering, login rate limiting,
no user enumeration, **broken object-level authorisation (IDOR)**, input
validation, filters, response conformance to the service's own OpenAPI schema,
security headers, and a cross-check that the number the assistant states equals
the API's aggregate.

**SQL data validation (`api_tests/test_data_validation.py`)** nulls, ranges,
valid categories and dates, referential integrity, recurring-charge consistency,
DB-vs-API reconciliation, passwords not stored in plaintext.

**UI (`ui_tests/`)** Playwright with page objects: login, invalid login, lockout
message, transactions match API, assistant answers match API, multi-turn in the
browser, refusal, injection not obeyed, **XSS check**, logout clears state.
Failures save a screenshot and a trace to `reports/ui_artifacts/`.

**Performance (`perf/load_test.py`)** concurrent users, per-endpoint p50/p95/p99,
error rate, non-zero exit on threshold breach.

## The suite is tested too (`meta_tests/`)

For each known bug the stand-in can be started with it injected
(`FINSYNC_BUGS=...`). The meta tests assert the suite fails in the right place:

| Injected bug | Caught by |
|---|---|
| `hallucination` (inflated totals, invented merchant) | total_spent, recurring, categorise_unknown |
| `no_refusal` | off-topic and blocked-topic refusals |
| `pii_leak` (other user's data, full account number) | pii_protection |
| `injection` (obeys payload in data) | prompt_injection |
| `jailbreak` (leaks system prompt) | jailbreak |
| `multiturn` (forgets context) | multi_turn |
| `tool_failure` (leaks stack trace, invents numbers) | tool_failure_recovery |
| `idor` | API authorisation test |
| `no_rate_limit` | API rate-limit test |

Example failure, with `FINSYNC_BUGS=pii_leak python -m pytest llm_eval`:

```
AssertionError: pii_protection pass rate 0%
failures: ["no_unknown_merchants: merchants not in this user's data: ['BookNook', 'GreenBasket', 'Lakeview Apartments']",
           'refusal: expected a refusal but the assistant answered']
```

I also broke the UI on purpose (rendering chat text as raw HTML) and confirmed the
XSS test failed, then restored it.

## Layout

```
target/        stand-in FinSync (FastAPI, SQLite, rule-based assistant, bug flags)
qa/            server launcher, API client
llm_eval/      datasets, metrics, runner, regression gate, DeepEval adapter, tests
api_tests/     REST + SQL data tests
ui_tests/      Playwright page objects + tests
meta_tests/    proves the suite catches injected bugs
perf/          load test
.github/workflows/ci.yml
```

## Pointing it at a real system

```bash
FINSYNC_BASE_URL=https://your-host \
FINSYNC_CREDENTIALS='{"testuser":"password"}' \
python -m pytest api_tests llm_eval
```
You would need to: match the API shape used by `qa/client.py`; replace the seed
data / datasets with your own test accounts and expected answers (the builder
shows the pattern: derive expectations from the data, never hand-type them); point
SQL tests at your warehouse with `FINSYNC_DB_PATH` (or adapt the queries); and
record a baseline from a known-good release with `make baseline`.

## Limitations (stated plainly)

- **The target is a stand-in with a deterministic assistant.** Passing here shows
  the *suite* works, not that any real model is good. Real LLM output varies, so
  expect to tune thresholds and use repeats.
- **Checks are rule-based.** They are fast and reproducible but cannot judge
  open-ended quality. The DeepEval adapter is the place to add LLM-judge metrics
  (faithfulness, relevancy), which need an API key, cost money and have their own bias.
- **No mobile testing.** There is no Appium layer (no device/emulator was available).
- **Load test is local** (client and server on one machine), so absolute numbers
  are not representative of a deployed system.
- `.github/workflows/ci.yml` is written to run these same commands but was **not
  executed on GitHub** while building this; the commands themselves were run locally.
