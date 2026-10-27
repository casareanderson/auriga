#!/usr/bin/env python3
"""auriga.py — local HTTP bridge for the Auriga Chrome extension (no native messaging).

The extension's background worker long-polls GET /poll for commands; any tool POSTs /command.
Run it yourself (and keep it running):
    python3 auriga.py

Config: ~/.auriga/config.json (env vars override). Everything stays on this machine; each command
is written to a local audit log (redacted) and optionally shipped to an Ephor ingest endpoint.
"""
import json, os, sys, threading, time, uuid, http.server, urllib.parse, urllib.request

CONFIG_PATH = os.path.expanduser("~/.auriga/config.json")


def _load_config():
    try:
        return json.load(open(CONFIG_PATH))
    except Exception:
        return {}


CFG = _load_config()


def _get(key, env, default=None):
    return os.environ.get(env) or CFG.get(key, default)


PORT = int(_get("port", "AURIGA_PORT", "8765"))
TIMEOUT = 30
TOKEN = _get("token", "AURIGA_TOKEN") or None
AUDIT = _get("audit", "AURIGA_AUDIT") or os.path.expanduser("~/.auriga/audit.jsonl")
EPHOR_URL = _get("ephor_url", "AURIGA_EPHOR_URL") or None
EPHOR_TOKEN = _get("ephor_token", "AURIGA_EPHOR_TOKEN") or None
AGENT = _get("agent", "AURIGA_AGENT", "auriga")
WEBHOOK_URL = _get("webhook_url", "AURIGA_WEBHOOK_URL") or None  # Discord webhook for failure tickets
SESSION_MAX_MIN = int(_get("session_max_min", "AURIGA_SESSION_MAX_MIN", "0") or 0)  # 0 = off; alert when a session runs this long
EXT_ORIGIN = "chrome-extension://ocoojeadkmddpggpnfajgpbnahbfgkea"
SENSITIVE_RESULT = {"cookies", "getCookie"}

_cmds = {}          # id -> command dict
_order = []         # FIFO of ids
_cmds_cond = threading.Condition()
_res = {}           # id -> {ok, result|error}
_res_cond = threading.Condition()
_last_poll = 0.0

_chats = {}         # id -> {goal, ts}
_chat_order = []    # FIFO
_chat_cond = threading.Condition()
_chat_res = {}      # id -> text
_chat_res_cond = threading.Condition()


def ship_to_ephor(entry):
    if not EPHOR_URL:
        return
    def _ship():
        try:
            body = json.dumps({"agent": AGENT, "action": entry["action"], "params": entry["params"],
                               "ok": entry["ok"], "ts": int(entry["ts"])}).encode()
            h = {"Content-Type": "application/json"}
            if EPHOR_TOKEN:
                h["X-Auth-Token"] = EPHOR_TOKEN
            urllib.request.urlopen(urllib.request.Request(EPHOR_URL.rstrip("/") + "/ingest/browser", body, h),
                                   timeout=5)
        except Exception as e:
            print(f"auriga: ephor ship failed: {e}", file=sys.stderr)
    threading.Thread(target=_ship, daemon=True).start()


def notify_failure(action, params, error):
    """Post a 'ticket' to the failure webhook (e.g. a Discord channel) so issues get seen and fixed."""
    if not WEBHOOK_URL:
        return
    def _post():
        try:
            safe = dict(params)
            for k in ("text", "js", "cookie", "value"):
                if k in safe:
                    safe[k] = "<redacted>"
            msg = (f"⚠️ **Auriga action failed** — `{action}`\n"
                   f"params: {json.dumps(safe)[:300]}\n"
                   f"error: {str(error)[:400]}")
            body = json.dumps({"username": "Auriga", "content": msg}).encode()
            urllib.request.urlopen(urllib.request.Request(WEBHOOK_URL, body,
                                                         {"Content-Type": "application/json"}), timeout=5)
        except Exception as e:
            print(f"auriga: failure webhook failed: {e}", file=sys.stderr)
    threading.Thread(target=_post, daemon=True).start()


def monitor_extension():
    """If the extension stops polling for a while (SW killed / browser closed), raise a ticket."""
    last_notified = 0.0
    session_alerted = False
    started = time.time()
    while True:
        time.sleep(30)
        if _last_poll and time.time() - _last_poll > 120 and time.time() - last_notified > 300:
            notify_failure("extension-disconnect", {}, "extension hasn't polled for >2 min (is Chrome open with Auriga loaded?)")
            last_notified = time.time()
        if SESSION_MAX_MIN and not session_alerted and time.time() - started > SESSION_MAX_MIN * 60:
            notify_failure("session-timeout", {}, f"session has been live for over {SESSION_MAX_MIN} min")
            session_alerted = True


def audit(action, params, ok, result):
    try:
        safe = dict(params)
        for k in ("text", "js", "cookie", "value"):
            if k in safe:
                safe[k] = "<redacted %d chars>" % len(str(safe[k]))
        entry = {"ts": round(time.time(), 3), "action": action, "params": safe, "ok": ok}
        if ok and action in SENSITIVE_RESULT:
            entry["result"] = "<redacted>"          # cookie values are secrets — never log them
        else:
            entry["result" if ok else "error"] = result
        d = os.path.dirname(AUDIT)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(AUDIT, "a") as f:
            f.write(json.dumps(entry) + "\n")
        ship_to_ephor(entry)
        if not ok:
            notify_failure(action, params, result)
    except Exception:
        pass


class H(http.server.BaseHTTPRequestHandler):
    def _json(self, obj, code=200):
        b = json.dumps(obj).encode()
        try:
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Private-Network", "true")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _auth(self):
        if not TOKEN:
            return True
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        return self.headers.get("X-Auth-Token") == TOKEN or q.get("token", [None])[0] == TOKEN

    def _origin_ok(self):
        """Reject browser-originated requests (CSRF from a page in another tab). The extension SW/popup
        send Origin: chrome-extension://…, and curl/tools send no Origin — both pass."""
        o = self.headers.get("Origin")
        return (not o) or o.startswith(EXT_ORIGIN)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Auth-Token")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.end_headers()

    def do_GET(self):
        global _last_poll
        if not self._origin_ok():
            self._json({"ok": False, "error": "forbidden origin"}, 403)
            return
        p = self.path.split("?")[0]
        if p == "/health":
            connected = time.time() - _last_poll < 60
            self._json({"ok": True, "service": "auriga", "port": PORT,
                        "extension": "connected" if connected else "not polling"})
            return
        if p == "/poll":
            first = _last_poll == 0.0
            _last_poll = time.time()
            if first:
                print("extension connected (polling)", file=sys.stderr, flush=True)
            with _cmds_cond:
                if not _order:
                    _cmds_cond.wait(timeout=25)
                if _order:
                    cid = _order.pop(0)
                    cmd = _cmds.pop(cid)
                else:
                    cmd = None
            self._json(cmd or {})
            return
        if p == "/chat/pending":
            with _chat_cond:
                if not _chat_order:
                    _chat_cond.wait(timeout=25)
                if _chat_order:
                    cid = _chat_order.pop(0)
                    chat = _chats.pop(cid)
                else:
                    chat = None
            self._json(chat or {})
            return
        if p == "/chat/result":
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            cid = q.get("id", [None])[0]
            with _chat_res_cond:
                text = _chat_res.get(cid)
            self._json({"text": text} if text else {})
            return
        self._json({"ok": False, "error": "not found"}, 404)

    def do_POST(self):
        if not self._origin_ok():
            self._json({"ok": False, "error": "forbidden origin"}, 403)
            return
        p = self.path.split("?")[0]
        if p == "/command":
            if not self._auth():
                self._json({"ok": False, "error": "unauthorized"}, 401)
                return
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or b"{}")
            action = body.get("action")
            params = {k: v for k, v in body.items() if k != "action"}
            cid = uuid.uuid4().hex
            with _cmds_cond:
                _cmds[cid] = {"id": cid, "action": action, **params}
                _order.append(cid)
                _cmds_cond.notify_all()
            deadline = time.time() + TIMEOUT
            with _res_cond:
                while cid not in _res:
                    if time.time() > deadline:
                        audit(action, params, False, "timeout waiting for extension")
                        self._json({"ok": False, "error": "timeout waiting for extension "
                                    "(is Chrome open with the Auriga extension loaded?)"})
                        return
                    _res_cond.wait(timeout=1)
                res = _res.pop(cid)
            ok = res.get("ok")
            result = res.get("result") if ok else res.get("error")
            audit(action, params, ok, result)
            self._json({"ok": ok, **({"result": result} if ok else {"error": result})})
            return
        if p == "/result":
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or b"{}")
            cid = body.get("id")
            with _res_cond:
                _res[cid] = body
                _res_cond.notify_all()
            self._json({"ok": True})
            return
        if p == "/chat":
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or b"{}")
            cid = uuid.uuid4().hex
            with _chat_cond:
                _chats[cid] = {"id": cid, "goal": body.get("goal", ""), "ts": time.time()}
                _chat_order.append(cid)
                _chat_cond.notify_all()
            self._json({"id": cid})
            return
        if p == "/chat/result":
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or b"{}")
            with _chat_res_cond:
                _chat_res[body.get("id")] = body.get("text", "")
                _chat_res_cond.notify_all()
            self._json({"ok": True})
            return
        self._json({"ok": False, "error": "not found"}, 404)

    def log_message(self, *a):
        pass


def main():
    try:
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), H)
    except OSError as e:
        print(f"auriga: port {PORT} in use ({e}) — another instance is already running", file=sys.stderr)
        sys.exit(1)
    try:
        d = os.path.dirname(os.path.expanduser("~/.auriga/bridge.pid"))
        os.makedirs(d, exist_ok=True)
        with open(os.path.expanduser("~/.auriga/bridge.pid"), "w") as f:
            f.write(str(os.getpid()))
    except Exception:
        pass
    print(f"auriga bridge on http://127.0.0.1:{PORT}  audit={AUDIT}  token={'set' if TOKEN else 'off'}",
          file=sys.stderr)
    threading.Thread(target=monitor_extension, daemon=True).start()
    srv.serve_forever()


if __name__ == "__main__":
    main()
