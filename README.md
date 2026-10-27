# Auriga

A lightweight way to drive your **existing Chrome** (same tabs, same logins) from any local tool or model.
No MCP server, no big dependency tree — one small Chrome extension + one stdlib-only Python bridge + a tiny CLI.

```
your tool/model  ──HTTP──▶  auriga.py (bridge)  ◀──long-poll──  Chrome extension  ──▶  the page
           (127.0.0.1:8765)
```

## Install (Linux / macOS)

1. `./install.sh` — makes the scripts executable and creates `~/.auriga/config.json`.
2. `chrome://extensions` → enable **Developer mode** → **Load unpacked** → pick the `extension/` folder.
3. Start the bridge (keep it running): `python3 auriga.py`
4. Test: `./auriga tabs`

## Use

```bash
./auriga tabs                          # list tabs
./auriga navigate "https://gelato.com" # navigate the active tab
./auriga click "#login-button"         # click by CSS selector
./auriga type "input[name=email]" "me@example.com"   # type into a field
./auriga read                          # dump the active tab's text (or: read "SELECTOR")
./auriga eval "document.title"         # run JS in the page
./auriga screenshot out.png            # screenshot the active tab
./auriga cookies                       # list cookies for the tab's domain
./auriga get-cookie sessionid          # one cookie's value
./auriga set-cookie "name=value"       # set a cookie
./auriga delete-cookie name            # delete a cookie
```

## Drive it from any tool

The bridge exposes a plain HTTP API on `127.0.0.1:8765` (loopback only):

- `GET  /health`
- `POST /command`  body `{"action": "click", "selector": "#x", "tabId": 12}` — blocks until the extension replies

So any model that can make an HTTP call (or `curl`) can drive it:

```bash
curl -s -X POST http://127.0.0.1:8765/command \
  -H 'Content-Type: application/json' \
  -d '{"action":"type","selector":"input[name=q]","text":"hello"}'
```

## Commands

| action | params | does |
|---|---|---|
| `tabs` | — | list tabs (id, title, url, active) |
| `navigate` | `url`, optional `tabId` | navigate |
| `click` | `selector`, optional `tabId` | click an element |
| `type` | `selector`, `text`, optional `tabId` | focus + set value + fire input/change |
| `read` | optional `selector`, optional `tabId` | page text / element text |
| `eval` | `js`, optional `tabId` | run JS, JSON result |
| `screenshot` | optional `tabId` | PNG data URL |
| `cookies` | optional `url` | list cookies for the domain |
| `getCookie` | `name`, optional `url` | one cookie |
| `setCookie` | `cookie` (`name=value`), optional `url`, `path` | set a cookie |
| `removeCookie` | `name`, optional `url` | delete a cookie |

## Auth

Two layers, both local:

1. **Loopback-only bind** — the bridge listens on `127.0.0.1`, so only processes on this machine can reach it.
2. **Optional shared token** — set `"token": "..."` in `~/.auriga/config.json` (or `AURIGA_TOKEN`), and pass the same token to the CLI / HTTP caller (`X-Auth-Token` header or `?token=`). Without it set, no token is required (loopback is the whole gate).

## Audit log (everything stays local)

Every command is appended to a local JSONL log — default `~/.auriga/audit.jsonl`, override with `AURIGA_AUDIT`. Typed text, eval'd JS and cookie values are redacted so no passwords/keys/cookies end up in the log. Nothing leaves the machine.

## Config file

You run the bridge yourself, so it reads `~/.auriga/config.json` (created by `install.sh`); env vars still override it:

```json
{
  "port": 8765,
  "agent": "auriga",
  "ephor_url": "http://100.74.235.132:8899",
  "ephor_token": "sekret",
  "token": ""
}
```

## Ship logs to Ephor

Set `ephor_url` + `ephor_token` in `~/.auriga/config.json` and every browser action lands in Ephor's store
(shown as a "Browser actions" table in the `ephor serve` page and queryable via `ephor browser-actions`):

```json
{ "ephor_url": "http://100.74.235.132:8899", "ephor_token": "sekret", "agent": "auriga" }
```

- `ephor_url` — the Ephor `serve` address (reachable from this machine).
- `ephor_token` — must match `EPHOR_INGEST_TOKEN` on the Ephor side.
- `agent` — the label the browser actions are attributed to in Ephor.

On the Ephor box: `EPHOR_INGEST_TOKEN=sekret ephor serve --host 0.0.0.0 --port 8899`. Ships are non-blocking
and fail silently — if Ephor is down, browser control keeps working and the local JSONL still records everything.

## Config keys / env vars

| config key | env var | default | purpose |
|---|---|---|---|
| `port` | `AURIGA_PORT` | `8765` | host HTTP port |
| `token` | `AURIGA_TOKEN` | — | if set, the HTTP API requires this token |
| `audit` | `AURIGA_AUDIT` | `~/.auriga/audit.jsonl` | local audit log |
| `ephor_url` | `AURIGA_EPHOR_URL` | — | ship each action to this Ephor `serve` URL |
| `ephor_token` | `AURIGA_EPHOR_TOKEN` | — | token for the Ephor ingest endpoint |
| `agent` | `AURIGA_AGENT` | `auriga` | agent label used in Ephor |

## Safety

- The HTTP API binds to `127.0.0.1` only — nothing on the network can reach it.
- Nothing is automated without a call from the tool; there is no "always-on" controller.
- Be careful driving pages that spend money (checkout/order buttons). The CLI just does what you tell it.

## Files

- `extension/` — manifest + background + content script (load unpacked)
- `auriga.py` — the local HTTP bridge (stdlib only; run it and keep it running)
- `auriga` — CLI wrapper
- `install.sh` — one-time setup (chmod + config template)
