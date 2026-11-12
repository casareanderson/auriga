#!/usr/bin/env python3
"""End-to-end tests of the auriga bridge (no browser).

Simulates the extension service worker polling /poll while a tool POSTs
commands to /command, and asserts each action is routed and answered.

Run with:  python3 -m pytest -q
"""
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = "http://127.0.0.1:8765"


def _get(path):
    return json.loads(urllib.request.urlopen(BASE + path, timeout=30).read())


def _post(path, body):
    req = urllib.request.Request(BASE + path, json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=30).read())


@pytest.fixture(scope="module")
def bridge():
    proc = subprocess.Popen([sys.executable, os.path.join(HERE, "auriga.py")],
                            stderr=subprocess.DEVNULL)
    for _ in range(100):
        try:
            if _get("/health").get("ok"):
                break
        except Exception:
            time.sleep(0.05)
    else:
        proc.terminate()
        proc.wait()
        pytest.fail("bridge did not start")
    yield proc
    proc.terminate()
    proc.wait()


def _command(action, params, sw_result):
    """POST a command and run a service-worker thread that polls and answers it."""
    received = {}

    def sw():
        cmd = _get("/poll")
        received["cmd"] = cmd
        if cmd.get("id"):
            _post("/result", {"id": cmd["id"], "ok": True, "result": sw_result})

    t = threading.Thread(target=sw)
    t.start()
    resp = _post("/command", {"action": action, **params})
    t.join(timeout=15)
    return resp, received.get("cmd")


def test_tabs(bridge):
    result = [{"id": 1, "title": "tab", "url": "x", "active": True}]
    resp, cmd = _command("tabs", {}, result)
    assert cmd["action"] == "tabs"
    assert resp["ok"] is True
    assert resp["result"][0]["title"] == "tab"


def test_find(bridge):
    result = [{"tag": "BUTTON", "text": "Sign in", "id": "login", "cls": "", "href": ""}]
    resp, cmd = _command("find", {"text": "sign in"}, result)
    assert cmd["action"] == "find"
    assert cmd["text"] == "sign in"
    assert resp["ok"] is True
    assert resp["result"][0]["tag"] == "BUTTON"


def test_click_text(bridge):
    result = {"clicked": True, "text": "Sign in"}
    resp, cmd = _command("clickText", {"text": "Sign in"}, result)
    assert cmd["action"] == "clickText"
    assert cmd["text"] == "Sign in"
    assert resp["ok"] is True
    assert resp["result"]["clicked"] is True
