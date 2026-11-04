# Auriga

Drive your own Chrome from any local tool or model — same tabs, same logins — over a loopback HTTP bridge and a small Chrome extension. No MCP server, no native messaging host, no large dependency tree.

![Auriga architecture](docs/architecture.svg)

## Contents

- [Auriga architecture](#auriga-architecture)
- [What it does](#what-it-does)
- [Screenshots](#screenshots)
- [Quick start](#quick-start)
- [Usage](#usage)
- [Configuration](#configuration)
- [How it works](#how-it-works)
- [Status and limits](#status-and-limits)
- [Roadmap](#roadmap)
- [Safety](#safety)
- [Licence](#licence)

## What it does

### Bridge test result

Running `test_bridge.py` confirms the HTTP bridge correctly queues commands via long-poll and returns results:

```
$ python3 test_bridge.py
command result: {"ok": true, "result": [{"id": 1, "title": "tab", "url": "x", "active": true}]}
BRIDGE: PASS
```

(`test_bridge.py` simulates an extension service worker polling `/poll` then submitting a `tabs` command and asserting the result. Run from a checkout: `python3 test_bridge.py`.)

## Quick start

Install on Linux or macOS:

```bash
# 1. Clone this repository
git clone https://github.com/casareanderson/auriga && cd auriga

# 2. Run the setup script (makes scripts executable, creates config)
./install.sh

# 3. Load the Chrome extension
#    chrome://extensions → Developer mode → Load unpacked → select the extension/ directory

# 4. Start the bridge
python3 auriga.py

# 5. Test it works
./auriga tabs
```

Success looks like a JSON array of tab objects printed to the terminal, e.g.:

```
 * [1] Home  https://example.com
   [2] Gmail  https://mail.google.com/mail/u/0/
```

## Usage

Run commands against the bridge. The CLI auto-starts the bridge if it is not already running.

```bash
./auriga tabs                           # list open tabs
./auriga navigate https://example.com   # navigate the active tab
./auriga click "#login-button"          # click by CSS selector
./auriga type "input[name=email]" "me@example.com"  # type text into a field
./auriga read                           # dump the active tab's text
./auriga eval "document.title"          # run JavaScript in the page
./auriga screenshot out.png             # save a PNG screenshot
./auriga snapshot                       # accessibility tree with clickable refs
./auriga click-ref 12345                # click by ref from a snapshot
./auriga cookies                        # list cookies for the tab origin
./auriga extensions                     # list installed extensions
```

You can also talk to the HTTP API directly:

```bash
curl -s -X POST http://127.0.0.1:8765/command \
  -H 'Content-Type: application/json' \
  -d '{"action":"type","selector":"input[name=q]","text":"hello"}'
```

All 17 supported actions (`click`, `navigate`, `tabs`, `read`, `eval`, `screenshot`, `snapshot`, `clickRef`, `clickXY`, `hover`, `upload`, `capture`, `extensions`, `approve`, `revoke`, `cookies`, `find`) are listed in the CLI wrapper help (`./auriga`).

## Configuration

The bridge reads `~/.auriga/config.json` (created by `install.sh`). Environment variables override the config file:

| config key | env var | default | purpose |
|---|---|---|---|
| `port` | `AURIGA_PORT` | `8765` | HTTP listen port |
| `token` | `AURIGA_TOKEN` | — | optional shared auth token for the HTTP API |
| `audit` | `AURIGA_AUDIT` | `~/.auriga/audit.jsonl` | path to the local audit log |
| `ephor_url` | `AURIGA_EPHOR_URL` | — | send each action to an Ephor ingest endpoint |
| `ephor_token` | `AURIGA_EPHOR_TOKEN` | — | bearer token used when shipping to Ephor |
| `agent` | `AURIGA_AGENT` | `auriga` | label shown in Ephor for attribution |
| `webhook_url` | `AURIGA_WEBHOOK_URL` | — | Discord webhook URL for failure tickets |
| `session_max_min` | `AURIGA_SESSION_MAX_MIN` | `0` | alert when a bridge session runs longer than this many minutes |

Auth for the HTTP API uses two layers:

1. **Loopback bind only** — the bridge listens on `127.0.0.1`, so only local processes can reach it.
2. **Optional shared token** — set `token` in the config (or `AURIGA_TOKEN`) and pass the same value via the `X-Auth-Token` header or `?token=` query parameter on every request. When unset, loopback alone gates access.

Site authorisation is per-origin in the extension's storage (`chrome.storage.local`). Before executing gated actions (`click`, `type`, `read`, `eval`, etc.), the extension checks whether the tab's origin is in the `aurigaAllowed` list and throws if not.

## How it works

Three components communicate over localhost:

1. **CLI wrapper** (`auriga`) — a thin Python script that auto-starts the bridge if needed, sends commands as JSON to the HTTP endpoint, and pretty-prints results.
2. **Bridge** (`auriga.py`) — a stdlib-only `http.server.ThreadingHTTPServer` bound to `127.0.0.1`. It accepts commands via `POST /command`, queues them internally, blocks until the extension replies, writes a redacted entry to the local audit log, optionally ships to Ephor, and posts failure tickets to a configured webhook. The extension connects via `GET /poll` (long-poll).
3. **Chrome extension** — a Manifest V3 service worker (`background.js`) that polls `/poll`, dispatches commands using the Chrome Extension APIs (`chrome.tabs`, `chrome.cookies`, `chrome.scripting`, `chrome.storage`) and Chrome DevTools Protocol (`chrome.debugger`), then posts the result back to `POST /result`. Content scripts run on every page and handle element-level actions (click, type, read).

```mermaid
graph LR
    Tool["Tool / Model"] -->|"POST /command"| Bridge[auriga.py\nlocalhost:8765]
    Bridge -->|"block until reply"| Ext[Chrome extension\nservice worker]
    Ext -->|"GET /poll"| Bridge
    Ext -->|"POST /result"| Bridge
    Bridge --> "audit.jsonl" Audit["Audit log\n(~/.auriga/)"]
    Bridge -.-> ship("ship_to_ephor") Ephor["Ephor ingest\n(optional)"]
    Ext --> debugger["chrome.debugger\n(CDP)"] Page[Browser page\ncontent script]
```

### Project structure

```
auriga/
├── auriga            CLI wrapper (Python)
├── auriga.py         Local HTTP bridge (stdlib only)
├── install.sh        One-time setup script
├── tunnel.sh         Reverse SSH tunnel helper
├── test_bridge.py    End-to-end bridge test (no browser)
└── extension/        Chrome extension (Manifest V3)
    ├── manifest.json       App identity and permissions
    ├── background.js       Service worker (poll loop, command executor)
    ├── content.js          Page content script (element actions)
    └── popup.html          Site-approval UI
```

## Status and limits

- Version 0.3.0 (from `manifest.json`), last code review: 2026-11-04.
- Supports 17 CLI actions covering tab management, page interaction, DOM reading, screenshots, file upload, and debugging.
- Runs only on Linux and macOS (the macOS reverse-tunnel installer uses `launchd`; Linux requires manual `tunnel.sh` execution).
- The bridge requires no third-party Python packages — pure stdlib.
- Nothing leaves the machine except what you explicitly configure to ship (Ephor URL, Discord webhook). Both ship asynchronously and fail silently.
- `session_max_min` defaults to off (value `0`); increase to set a session age alert.

Known gaps:

- No annotated screenshots (numbered element overlays for vision-model input) — tracked in the roadmap.
- No streaming side panel or chat interface for iterative browsing.
- No live remote view capability (screen stream to a remote dashboard).

## Roadmap

| Item | Status |
|---|---|
| Basic tab actions (tabs, navigate, click, type, read, eval, screenshot, cookies) | Done |
| `click-text` / `find` for CSP-heavy sites | Done |
| File upload with iframe support | Done |
| Accessibility tree snapshots and ref-based clicking | Done |
| Coordinate-based click/hover | Done |
| Console + network capture for debugging | Done |
| Installed-extension inspector | Done |
| Annotated screenshots for vision models | In progress |
| Streaming chat / side panel | Planned |
| Live remote view (screenshot stream) | Planned |

## Safety

- The HTTP API binds to `127.0.0.1` only. Nothing on the network can reach it.
- Every action requires a deliberate call from a tool; there is no always-on controller.
- Gated actions require per-origin approval through the extension popup before they execute.
- Typed text, evaluated JavaScript and cookie values are redacted in the audit log.
- The bridge monitors the extension connection; if the browser closes or the service worker dies, a failure ticket fires after 120 seconds.

## Licence

Auriga is licensed under the GNU Affero General Public License v3.0. See `LICENSE` for the full text.
