#!/usr/bin/env python3
"""End-to-end test of the auriga bridge (no browser): simulate the extension SW polling + the tool commanding."""
import subprocess, json, threading, time, urllib.request, sys, os

HERE = os.path.dirname(os.path.abspath(__file__))
proc = subprocess.Popen([sys.executable, f"{HERE}/auriga.py"], stderr=subprocess.DEVNULL)


def get(path):
    return json.loads(urllib.request.urlopen(f"http://127.0.0.1:8765{path}", timeout=30).read())


def post(path, body):
    req = urllib.request.Request(f"http://127.0.0.1:8765{path}", json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=30).read())


def sw():
    # act like the extension: poll, then answer
    while True:
        cmd = get("/poll")
        if cmd.get("id"):
            post("/result", {"id": cmd["id"], "ok": True, "result": [{"id": 1, "title": "tab", "url": "x", "active": True}]})
            return


time.sleep(0.3)
assert get("/health")["ok"] is True
t = threading.Thread(target=sw); t.start()
r = post("/command", {"action": "tabs"})
t.join()

print("command result:", json.dumps(r))
ok = r.get("ok") and r["result"][0]["title"] == "tab"
print("BRIDGE:", "PASS" if ok else "FAIL")
proc.terminate()
sys.exit(0 if ok else 1)
