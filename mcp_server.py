#!/usr/bin/env python3
"""auriga-mcp — Model Context Protocol server exposing Auriga's browser tools.

Connects an LLM (Claude Desktop, OpenCode, Hermes, a local model) to the Auriga
bridge so it can drive the Chrome you already use. Stdio transport
(newline-delimited JSON-RPC 2.0), stdlib only.

Env:
  AURIGA_URL    bridge address (default http://127.0.0.1:8765)
  AURIGA_TOKEN  shared token, if the bridge has one set

The extension's per-site approval still gates every action: the model cannot act
on a site until you click "Allow" in the Auriga popup.
"""
import base64
import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("AURIGA_URL", "http://127.0.0.1:8765")
TOKEN = os.environ.get("AURIGA_TOKEN", "")
TIMEOUT = 90
VERSION = "0.1.0"

# name -> (bridge action, description, params: {name: (type, required, description)})
TOOLS = {
    "auriga_tabs": ("tabs", "List open Chrome tabs with id, title, url and active flag.", {}),
    "auriga_navigate": ("navigate", "Navigate a tab to a URL (defaults to the active tab).",
                        {"url": ("string", True, "full URL to open")}),
    "auriga_click": ("click", "Click an element by CSS selector.", {"selector": ("string", True, "CSS selector")}),
    "auriga_click_text": ("clickText", "Click an element by its visible text (for CSP-heavy sites).",
                          {"text": ("string", True, "visible button/link text")}),
    "auriga_find": ("find", "List elements whose text matches a string.", {"text": ("string", True, "text to match")}),
    "auriga_type": ("type", "Type text into a field (focus + set value + fire events).",
                    {"selector": ("string", True, "CSS selector"), "text": ("string", True, "text to type")}),
    "auriga_read": ("read", "Read the active tab's title, url and visible text (or one element).",
                    {"selector": ("string", False, "optional CSS selector to narrow the read")}),
    "auriga_eval": ("eval", "Run JavaScript in the page and return the result.", {"js": ("string", True, "JavaScript")}),
    "auriga_screenshot": ("screenshot", "Save a PNG screenshot of the active tab to a local path.",
                          {"path": ("string", True, "output file path, e.g. /tmp/shot.png")}),
    "auriga_snapshot": ("snapshot", "Build an accessibility tree with numeric refs (use auriga_click_ref next).", {}),
    "auriga_click_ref": ("clickRef", "Click an element by its snapshot ref.", {"ref": ("string", True, "ref from snapshot")}),
    "auriga_click_xy": ("clickXY", "Click at raw screen coordinates (canvas, unlabelled icons).",
                        {"x": ("integer", True, "x"), "y": ("integer", True, "y")}),
    "auriga_hover": ("hover", "Move the mouse to coordinates.", {"x": ("integer", True, "x"), "y": ("integer", True, "y")}),
    "auriga_capture": ("capture", "Capture console and/or network events for N seconds.",
                       {"what": ("string", False, "console|network|both"), "duration": ("integer", False, "seconds")}),
    "auriga_cookies": ("cookies", "List cookies for the tab's origin.", {"url": ("string", False, "optional origin")}),
    "auriga_extensions": ("extensions", "List installed extensions and flag automation ones.", {}),
    "auriga_approve": ("approve", "Approve a site for automation (bypasses the popup).",
                       {"urls": ("array", True, "list of site URLs to approve")}),
    "auriga_revoke": ("revoke", "Revoke a previously approved site.",
                      {"urls": ("array", True, "list of site URLs to revoke")}),
}


def bridge(action, **params):
    body = json.dumps({"action": action, **params}).encode()
    headers = {"Content-Type": "application/json"}
    if TOKEN:
        headers["X-Auth-Token"] = TOKEN
    req = urllib.request.Request(BASE + "/command", data=body, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            d = json.load(r)
    except urllib.error.HTTPError as e:
        return False, f"bridge HTTP {e.code}"
    except Exception as e:  # noqa: BLE001
        return False, str(e)
    if not d.get("ok"):
        return False, d.get("error", "unknown error")
    return True, d.get("result")


def run_tool(name, args):
    action, _desc, spec = TOOLS[name]
    params = {k: args[k] for k in spec if k in args}
    # approve/revoke take a list of urls; the bridge takes one url per call
    if action in ("approve", "revoke"):
        urls = args.get("urls") or []
        out = []
        for u in urls:
            ok, res = bridge(action, url=u)
            if not ok:
                return False, f"approve {u}: {res}"
            out.append(res)
        return True, {"approved": out}
    if action == "screenshot":
        ok, res = bridge(action, **params)
        if not ok:
            return False, res
        data = res.get("dataUrl", "")
        if not data:
            return False, "no screenshot data returned"
        png = base64.b64decode(data.split(",", 1)[1])
        path = args["path"]
        with open(path, "wb") as f:
            f.write(png)
        return True, {"path": path, "bytes": len(png)}
    ok, res = bridge(action, **params)
    if not ok:
        return False, res
    return True, res


def input_schema(spec):
    props, required = {}, []
    for k, (typ, req, desc) in spec.items():
        props[k] = {"type": typ, "description": desc}
        if typ == "array":
            props[k]["items"] = {"type": "string"}
        if req:
            required.append(k)
    s = {"type": "object", "properties": props}
    if required:
        s["required"] = required
    return s


def list_tools():
    return [{"name": name, "description": desc, "inputSchema": input_schema(spec)}
            for name, (_a, desc, spec) in TOOLS.items()]


def send(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError:
            continue
        rid = req.get("id")
        method = req.get("method")
        # notifications have no id — never reply
        if rid is None:
            continue
        if method == "initialize":
            send({"jsonrpc": "2.0", "id": rid, "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "auriga-mcp", "version": VERSION}}})
        elif method == "ping":
            send({"jsonrpc": "2.0", "id": rid, "result": {}})
        elif method == "tools/list":
            send({"jsonrpc": "2.0", "id": rid, "result": {"tools": list_tools()}})
        elif method == "tools/call":
            name = req["params"]["name"]
            args = req["params"].get("arguments") or {}
            ok, res = run_tool(name, args)
            text = json.dumps(res, ensure_ascii=False) if ok else res
            send({"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text", "text": text}], "isError": not ok}})
        else:
            send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"method not found: {method}"}})


if __name__ == "__main__":
    main()
