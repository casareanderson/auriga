#!/usr/bin/env python3
"""End-to-end test of the auriga bridge (no browser): simulate the extension SW polling + the tool commanding."""
import subprocess, json, threading, time, urllib.request, urllib.error, sys, os, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))

PNG1X1 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="  # 1x1 transparent PNG
AUDIT = os.path.join(tempfile.mkdtemp(), "audit.jsonl")
env = dict(os.environ, AURIGA_AUDIT=AUDIT)
proc = subprocess.Popen([sys.executable, f"{HERE}/auriga.py"], stderr=subprocess.DEVNULL, env=env)


def get(path):
    return json.loads(urllib.request.urlopen(f"http://127.0.0.1:8765{path}", timeout=30).read())


def get_raw(path):
    return urllib.request.urlopen(f"http://127.0.0.1:8765{path}", timeout=30)


def post(path, body):
    req = urllib.request.Request(f"http://127.0.0.1:8765{path}", json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=30).read())


def sw(respond):
    # act like the extension: poll, then answer with respond(cmd)
    while True:
        cmd = get("/poll")
        if cmd.get("id"):
            post("/result", {"id": cmd["id"], "ok": True, "result": respond(cmd)})
            return


def sw_fail(error):
    while True:
        cmd = get("/poll")
        if cmd.get("id"):
            post("/result", {"id": cmd["id"], "ok": False, "error": error})
            return


time.sleep(0.3)
assert get("/health")["ok"] is True

# existing /command flow still works
t = threading.Thread(target=sw, args=(lambda cmd: [{"id": 1, "title": "tab", "url": "x", "active": True}],)); t.start()
r = post("/command", {"action": "tabs"})
t.join()
print("command result:", json.dumps(r))
ok = r.get("ok") and r["result"][0]["title"] == "tab"

# /live returns the screenshot PNG with no-store
t = threading.Thread(target=sw, args=(lambda cmd: {"dataUrl": "data:image/png;base64," + PNG1X1},)); t.start()
resp = get_raw("/live")
frame = resp.read()
t.join()
ok = ok and resp.headers["Content-Type"] == "image/png" \
    and resp.headers.get("Cache-Control") == "no-store" \
    and frame[:8] == b"\x89PNG\r\n\x1a\n"

# /live failure path: extension answers ok:false (e.g. site not approved) -> 502
t = threading.Thread(target=sw_fail, args=("site not approved: https://x — approve it in the Auriga popup",)); t.start()
try:
    get_raw("/live")
    ok = False
except urllib.error.HTTPError as e:
    err = json.loads(e.read())
    t.join()
    ok = ok and e.code == 502 and err["ok"] is False and "not approved" in err["error"]

# /live.html viewer page has the auto-refresh machinery
page_resp = get_raw("/live.html")
page = page_resp.read().decode()
ok = ok and page_resp.headers.get("Cache-Control") == "no-store" \
    and "setInterval" in page and "liveUrl" in page and "/live" in page

# audit: the /command tabs action is audited, live frames are NOT (no per-frame audit/ephor spam)
if os.path.exists(AUDIT):
    audited = [json.loads(l)["action"] for l in open(AUDIT)]
else:
    audited = []
ok = ok and "tabs" in audited and "screenshot" not in audited

print("LIVE:", "PASS" if ok else "FAIL")

# token-gated bridge: auth enforced on /live and /live.html (fast checks, no SW needed)
env2 = dict(os.environ, AURIGA_PORT="8766", AURIGA_TOKEN="sekret")
proc2 = subprocess.Popen([sys.executable, f"{HERE}/auriga.py"], stderr=subprocess.DEVNULL, env=env2)
time.sleep(0.3)


def status2(path):
    try:
        urllib.request.urlopen(f"http://127.0.0.1:8766{path}", timeout=5)
        return 200
    except urllib.error.HTTPError as e:
        return e.code


ok = ok and status2("/live") == 401 and status2("/live.html") == 401 and status2("/live.html?token=sekret") == 200
page2 = urllib.request.urlopen("http://127.0.0.1:8766/live.html?token=sekret", timeout=5).read().decode()
ok = ok and "sekret" in page2
proc2.terminate()

proc.terminate()
print("BRIDGE:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
