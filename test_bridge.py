#!/usr/bin/env python3
"""End-to-end bridge test (no browser).

Spins up the auriga bridge on a free port and a simulated Chrome extension
service worker that long-polls `GET /poll` and answers `POST /result`. Then
drives each basic action — `tabs`, `navigate`, `click`, `type`, `read`, `eval`,
`screenshot`, `cookies` — through `POST /command` and asserts the bridge routes
the action and its params correctly.

Run with pytest:

    python3 -m pytest -q
"""
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))

BASIC_ACTIONS = ["tabs", "navigate", "click", "type", "read", "eval", "screenshot", "cookies"]

PARAMS = {
    "tabs": {},
    "navigate": {"url": "https://example.com"},
    "click": {"selector": "#login-button"},
    "type": {"selector": "input[name=email]", "text": "me@example.com"},
    "read": {"selector": "main"},
    "eval": {"js": "document.title"},
    "screenshot": {},
    "cookies": {"url": "https://example.com"},
}


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _get(base, path):
    return json.loads(urllib.request.urlopen(base + path, timeout=30).read())


def _post(base, path, body):
    req = urllib.request.Request(base + path, json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=30).read())


@pytest.fixture(scope="module")
def bridge():
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    env = dict(os.environ, AURIGA_PORT=str(port),
               AURIGA_AUDIT=f"/tmp/auriga-test-{port}.jsonl")
    proc = subprocess.Popen([sys.executable, f"{HERE}/auriga.py"], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(100):
        try:
            _get(base, "/health")
            break
        except Exception:
            time.sleep(0.05)
    else:
        proc.terminate()
        raise RuntimeError("bridge did not start on " + base)
    try:
        yield base
    finally:
        proc.terminate()
        proc.wait()


@pytest.fixture(scope="module")
def extension(bridge):
    """Simulated service worker: long-poll /poll and echo each command's action + params."""

    def serve():
        while True:
            try:
                cmd = _get(bridge, "/poll")
            except Exception:
                return
            if not cmd.get("id"):
                continue
            params = {k: v for k, v in cmd.items() if k not in ("id", "action")}
            try:
                _post(bridge, "/result", {"id": cmd["id"], "ok": True,
                                          "result": {"action": cmd.get("action"), "params": params}})
            except Exception:
                return

    threading.Thread(target=serve, daemon=True).start()


@pytest.mark.parametrize("action", BASIC_ACTIONS)
def test_basic_action_roundtrip(bridge, extension, action):
    params = PARAMS[action]
    r = _post(bridge, "/command", {"action": action, **params})
    assert r.get("ok") is True, r
    assert r["result"]["action"] == action
    assert r["result"]["params"] == params
