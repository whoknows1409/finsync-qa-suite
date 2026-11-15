"""Thin HTTP client for the FinSync API (works against the stand-in or the real service).

Credentials default to the demo users; override with FINSYNC_CREDENTIALS='{"user":"password",...}'.
"""

from __future__ import annotations

import json
import os
import time
from typing import Dict, List, Optional

import requests

DEFAULT_CREDENTIALS = {"alice": "alice-pass", "bob": "bob-pass", "carol": "carol-pass"}


def credentials() -> Dict[str, str]:
    raw = os.environ.get("FINSYNC_CREDENTIALS")
    return json.loads(raw) if raw else dict(DEFAULT_CREDENTIALS)


class FinSyncClient:
    def __init__(self, base_url: str, timeout: float = 15.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._tokens: Dict[str, str] = {}
        self.session = requests.Session()

    def login(self, user: str, password: Optional[str] = None) -> requests.Response:
        pw = password if password is not None else credentials()[user]
        return self.session.post(f"{self.base_url}/auth/login", json={"username": user, "password": pw},
                                 timeout=self.timeout)

    def token(self, user: str) -> str:
        if user not in self._tokens:
            r = self.login(user)
            r.raise_for_status()
            self._tokens[user] = r.json()["access_token"]
        return self._tokens[user]

    def headers(self, user: str, extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.token(user)}", **(extra or {})}

    def chat(self, user: str, messages: List[Dict], headers: Optional[Dict[str, str]] = None) -> Dict:
        """Returns {reply, tool_calls, latency_ms (server), wall_ms (client-measured)}."""
        t0 = time.perf_counter()
        r = self.session.post(f"{self.base_url}/assistant/chat", json={"messages": messages},
                              headers=self.headers(user, headers), timeout=self.timeout)
        wall = (time.perf_counter() - t0) * 1000
        r.raise_for_status()
        out = r.json()
        out["wall_ms"] = wall
        return out
