"""Start/stop the stand-in FinSync server as a subprocess (used by fixtures and meta tests)."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ServerProcess:
    def __init__(self, bugs: str = ""):
        self.bugs = bugs
        self.port = free_port()
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.db_dir = tempfile.mkdtemp(prefix="finsync-qa-")
        self.proc = None

    def start(self, timeout: float = 20.0) -> "ServerProcess":
        env = dict(os.environ, FINSYNC_BUGS=self.bugs, FINSYNC_DB=os.path.join(self.db_dir, "finsync.db"))
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "target.app:app", "--port", str(self.port),
             "--log-level", "warning"],
            cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if requests.get(self.base_url + "/health", timeout=0.5).status_code == 200:
                    return self
            except requests.RequestException:
                time.sleep(0.15)
        self.stop()
        raise RuntimeError("server did not start")

    @property
    def db_path(self) -> str:
        return os.path.join(self.db_dir, "finsync.db")

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()
