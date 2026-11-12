# Auriga

Drive your own Chrome from any local tool or model — same tabs, same logins — over a loopback HTTP bridge and a small Chrome extension. No MCP server, no native messaging host, no large dependency tree.

![Auriga architecture](docs/architecture.svg)

## Contents

- [Auriga architecture](#auriga-architecture)
- [What it does](#what-it-does)
- [Screenshots](#screenshots)
- [Quick start](#quick-start)
- [Usage](#usage)
- [MCP server](#mcp-server-connect-an-llm)
- [Autostart](#autostart-macos)
- [Configuration](#configuration)
- [How it works](#how-it-works)
- [Status and limits](#status-and-limits)
- [Roadmap](#roadmap)
- [Safety](#safety)
- [Troubleshooting](#troubleshooting)
- [Licence](#licence)

## What it does

- List open tabs with their id, title, url and active state — `tabs` action, processed in `extension/background.js` line 72 and `auriga` CLI wrapper line 148.
- Navigate to URLs, click elements by CSS selector, type text into form fields, read page text, and execute arbitrary JavaScript — handled by `content.js` and routed through `sendToTab()` in `background.js`.
- Generate PNG screenshots of the active tab via `chrome.tabs.captureVisibleTab` — `screenshot` action in `background.js` line 141.
- Build an accessibility tree of interactive elements with numeric refs, then click those elements precisely — `snapshot` and `clickRef` in `background.js` lines 243–276.
- Click or hover at raw screen coordinates for elements without recognisable labels (canvas drawings, icon-only controls) — `clickXY` and `hover` in `background.js` lines 279–292.
- Upload local files into file input fields across all frames via Chrome DevTools Protocol — `upload` in `background.js` lines 205–241, with frame iteration and change-event firing.
- Capture console output, network responses and failures for debugging — `capture` action using CDP `Runtime.enable` / `Network.enable` + event collection in `background.js` lines 294–325.
- List, read, create and delete cookies for the active tab's origin — `cookies`, `getCookie`, `setCookie`, `removeCookie` using the `chrome.cookies` API in `background.js` lines 106–128.
- Approve or revoke sites for automated control; gated actions require explicit per-origin approval before executing — `aurigaAllowed` / `aurigaPending` stored in `chrome.storage.local` in `background.js` lines 45–104.

## Screenshots

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

# 4. Start the bridge (on macOS it's already running as a launchd agent — see Autostart below)
./auriga start

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

## MCP server (connect an LLM)

Give a model the browser as a set of tools. `mcp_server.py` is a stdlib-only
Model Context Protocol server that wraps the bridge's HTTP API, so any MCP client
(Claude Desktop, OpenCode, Hermes, a local model) can drive the browser through
the same actions as the CLI: `auriga_tabs`, `auriga_navigate`, `auriga_click`,
`auriga_click_text`, `auriga_find`, `auriga_type`, `auriga_read`, `auriga_eval`,
`auriga_screenshot`, `auriga_snapshot`, `auriga_click_ref`, `auriga_click_xy`,
`auriga_hover`, `auriga_capture`, `auriga_cookies`, `auriga_extensions`,
`auriga_approve`, `auriga_revoke`.

The extension's per-site approval still gates every action — a model cannot act
on a site until you click "Allow" in the popup (or `./auriga approve <url>`).

```bash
# run it manually (stdio transport)
python3 mcp_server.py

# or point it at a bridge elsewhere / with a token
AURIGA_URL=http://127.0.0.1:8765 AURIGA_TOKEN=... python3 mcp_server.py
```

Register it in your client, e.g. Claude Desktop
(`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "auriga": {
      "command": "python3",
      "args": ["/absolute/path/to/auriga/mcp_server.py"],
      "env": { "AURIGA_URL": "http://127.0.0.1:8765" }
    }
  }
}
```

## Autostart (macOS)

`install.sh` registers the bridge as a launchd agent (`com.c1lab.auriga.bridge`),
so it starts on login and is kept alive — no manual `./auriga start` after a
reboot. The reverse tunnel (`com.c1lab.auriga.tunnel`) is registered the same way.

- Log: `/tmp/auriga-bridge.log`
- Restart: `launchctl unload ~/Library/LaunchAgents/com.c1lab.auriga.bridge.plist && launchctl load ~/Library/LaunchAgents/com.c1lab.auriga.bridge.plist`
- On Linux there is no agent yet: run `./auriga start` after login, or write your own `systemd --user` unit.

The extension side self-heals on its own: it long-polls the bridge, and a
`chrome.alarms` ping every 30s re-wakes the service worker after a browser
restart or crash, then reconnects with a 2s retry.

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
├── mcp_server.py     MCP server (connect an LLM)
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

## Troubleshooting

- **"site not approved"** — gated actions need per-origin approval. Open the Auriga popup and click Allow, or run `./auriga approve <url>`.
- **`./auriga status` says "bridge: NOT running"** — macOS: `launchctl load ~/Library/LaunchAgents/com.c1lab.auriga.bridge.plist`; otherwise `./auriga start`.
- **"extension: not polling"** — bridge is up but the extension isn't connected. Reload the extension once in `chrome://extensions`; it reconnects on the next poll.
- **Nothing responds after a browser restart** — the 30s alarm re-wakes the worker automatically; wait up to ~30s, or open the popup once.
- **After editing the extension code** — Chrome keeps the old service worker until you click Reload on `chrome://extensions`.
- **Port already in use** — another bridge is running: `./auriga stop`, or `lsof -ti :8765 | xargs kill`.

## Licence

Auriga is licensed under the GNU Affero General Public License v3.0. See `LICENSE` for the full text.

---

More homelab field notes: https://iamtech.cn1-lab.uk
