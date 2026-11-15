"""REST API tests: auth, authorisation, validation, schema conformance, rate limiting."""

from __future__ import annotations

import re
import time

import jsonschema
import pytest
import requests

from qa.client import credentials


@pytest.fixture(scope="module")
def openapi(base_url):
    return requests.get(f"{base_url}/openapi.json", timeout=10).json()


def validate(openapi, schema_name, payload):
    """Validate a payload against a component schema from the service's own OpenAPI document."""
    schema = {"$ref": f"#/components/schemas/{schema_name}", "components": openapi["components"]}
    jsonschema.Draft202012Validator(schema).validate(payload)


def auth(client, user="alice"):
    return client.headers(user)


# ---------------------------------------------------------------- health ---
def test_health(base_url):
    r = requests.get(f"{base_url}/health", timeout=10)
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_security_headers_present(base_url):
    r = requests.get(f"{base_url}/health", timeout=10)
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert "no-store" in r.headers.get("Cache-Control", "")


# ----------------------------------------------------------------- login ---
def test_login_success_returns_token_and_schema(base_url, openapi):
    r = requests.post(f"{base_url}/auth/login", json={"username": "alice", "password": credentials()["alice"]}, timeout=10)
    assert r.status_code == 200
    body = r.json()
    validate(openapi, "TokenResponse", body)
    assert body["user_id"] == "alice" and body["token_type"] == "bearer" and body["expires_in"] > 0


def test_login_wrong_password_is_401(base_url):
    r = requests.post(f"{base_url}/auth/login", json={"username": "alice", "password": "wrong"}, timeout=10)
    assert r.status_code == 401


def test_login_does_not_reveal_whether_user_exists(base_url):
    wrong_pw = requests.post(f"{base_url}/auth/login", json={"username": "alice", "password": "nope"}, timeout=10)
    no_user = requests.post(f"{base_url}/auth/login", json={"username": "nobody-here", "password": "nope"}, timeout=10)
    assert wrong_pw.status_code == no_user.status_code == 401
    assert wrong_pw.json() == no_user.json()


@pytest.mark.parametrize("payload", [{}, {"username": "alice"}, {"password": "x"},
                                     {"username": "", "password": "x"}, {"username": "a" * 51, "password": "x"}])
def test_login_validation_422(base_url, payload):
    assert requests.post(f"{base_url}/auth/login", json=payload, timeout=10).status_code == 422


def test_login_rate_limited_after_repeated_failures(base_url):
    user = f"probe-{int(time.time() * 1000)}"
    codes = [requests.post(f"{base_url}/auth/login", json={"username": user, "password": "bad"}, timeout=10).status_code
             for _ in range(6)]
    assert codes[:5] == [401] * 5
    assert codes[5] == 429
    r = requests.post(f"{base_url}/auth/login", json={"username": user, "password": "bad"}, timeout=10)
    assert r.status_code == 429 and "Retry-After" in r.headers


# ------------------------------------------------------------- authN/authZ ---
@pytest.mark.parametrize("header", [None, "", "Bearer", "Bearer garbage", "Basic abc", "Bearer a.b"])
def test_transactions_reject_missing_or_invalid_token(base_url, header):
    h = {"Authorization": header} if header is not None else {}
    assert requests.get(f"{base_url}/users/alice/transactions", headers=h, timeout=10).status_code == 401


def test_tampered_token_rejected(base_url, client):
    token = client.token("alice")
    payload, sig = token.rsplit(".", 1)
    forged = payload[:-2] + ("AA" if not payload.endswith("AA") else "BB") + "." + sig
    r = requests.get(f"{base_url}/users/alice/transactions", headers={"Authorization": f"Bearer {forged}"}, timeout=10)
    assert r.status_code == 401


def test_cannot_read_another_users_transactions(base_url, client):
    """Broken object-level authorisation (IDOR) check."""
    r = requests.get(f"{base_url}/users/bob/transactions", headers=auth(client, "alice"), timeout=10)
    assert r.status_code == 403
    assert "merchant" not in r.text


def test_unknown_user_does_not_leak_existence(base_url, client):
    r = requests.get(f"{base_url}/users/zed/transactions", headers=auth(client, "alice"), timeout=10)
    assert r.status_code == 403


# ---------------------------------------------------------- transactions ---
def test_transactions_schema_and_totals(base_url, client, openapi):
    r = requests.get(f"{base_url}/users/alice/transactions", headers=auth(client), timeout=10)
    assert r.status_code == 200
    body = r.json()
    validate(openapi, "TransactionList", body)
    assert body["count"] == len(body["items"]) > 0
    assert body["total"] == pytest.approx(sum(t["amount"] for t in body["items"]), abs=0.01)


def test_filter_by_category_and_month(base_url, client):
    r = requests.get(f"{base_url}/users/alice/transactions", params={"category": "Dining", "month": "2026-10"},
                     headers=auth(client), timeout=10).json()
    assert r["count"] > 0
    assert all(t["category"] == "Dining" and t["date"].startswith("2026-10") for t in r["items"])


@pytest.mark.parametrize("params", [{"category": "Crypto"}, {"month": "2026-13"}, {"month": "October"}, {"month": "2026-1"}])
def test_invalid_filters_are_422(base_url, client, params):
    assert requests.get(f"{base_url}/users/alice/transactions", params=params, headers=auth(client),
                        timeout=10).status_code == 422


def test_empty_result_is_valid_not_error(base_url, client, openapi):
    r = requests.get(f"{base_url}/users/alice/transactions", params={"month": "2030-01"}, headers=auth(client), timeout=10)
    assert r.status_code == 200
    body = r.json()
    validate(openapi, "TransactionList", body)
    assert body["count"] == 0 and body["total"] == 0


# ------------------------------------------------------------- assistant ---
def test_chat_requires_auth(base_url):
    r = requests.post(f"{base_url}/assistant/chat", json={"messages": [{"role": "user", "content": "hi"}]}, timeout=10)
    assert r.status_code == 401


@pytest.mark.parametrize("payload", [
    {}, {"messages": []}, {"messages": [{"role": "user", "content": ""}]},
    {"messages": [{"role": "system", "content": "x"}]},
    {"messages": [{"role": "user", "content": "x" * 2001}]},
    {"messages": [{"role": "user", "content": "q"}] * 21},
    {"messages": [{"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}]},
])
def test_chat_input_validation_422(base_url, client, payload):
    r = requests.post(f"{base_url}/assistant/chat", json=payload, headers=auth(client), timeout=10)
    assert r.status_code == 422


def test_chat_response_schema(base_url, client, openapi):
    out = requests.post(f"{base_url}/assistant/chat", headers=auth(client), timeout=10,
                        json={"messages": [{"role": "user", "content": "How much did I spend on Rent in October?"}]})
    assert out.status_code == 200
    validate(openapi, "ChatResponse", out.json())


def test_assistant_total_matches_transactions_api(base_url, client):
    """Cross-check: the number the assistant states must equal the API's own aggregate."""
    api = requests.get(f"{base_url}/users/alice/transactions", params={"category": "Dining", "month": "2026-10"},
                       headers=auth(client), timeout=10).json()["total"]
    reply = client.chat("alice", [{"role": "user", "content": "How much did I spend on Dining in October?"}])["reply"]
    stated = float(re.search(r"₹([\d,]+(?:\.\d+)?)", reply).group(1).replace(",", ""))
    assert stated == pytest.approx(api, abs=0.51)


def test_assistant_uses_signed_in_user_only(base_url, client):
    """Alice and Bob see different data for the same question."""
    q = [{"role": "user", "content": "How much did I spend on Groceries in October?"}]
    assert client.chat("alice", q)["reply"] != client.chat("bob", q)["reply"]


def test_response_time_budget(client):
    q = [{"role": "user", "content": "How much did I spend on Transport in October?"}]
    client.chat("alice", q)                       # warm up
    times = []
    for _ in range(20):
        t0 = time.perf_counter()
        client.chat("alice", q)
        times.append((time.perf_counter() - t0) * 1000)
    times.sort()
    assert times[int(0.95 * len(times)) - 1] < 500, f"p95 too slow: {times[-2]:.0f} ms"
