# WorkBuddy Token Usage Status Bar

[中文](README.md) | English

A floating status bar for the WorkBuddy desktop client (Electron app) that shows
real-time token & credit usage of the current conversation. It only reads the local
`~/.workbuddy/workbuddy.db` SQLite database — never touches the network.

Inspired by [zcode-token-usage-statusbar](https://github.com/xhwxt/zcode-token-usage-statusbar),
retargeted to WorkBuddy's data model.

> **Acknowledgments**: this is a port of [@xhwxt](https://github.com/xhwxt)'s
> [zcode-token-usage-statusbar](https://github.com/xhwxt/zcode-token-usage-statusbar)
> to WorkBuddy. See [Acknowledgments](#acknowledgments). The original is MIT-licensed.

## Quick install (lazy bundle)

No Python? Just download and run:

1. Go to [Releases](https://github.com/qyo123oyq/wb-token-usage-statusbar/releases/latest)
2. Download `wb-usage-install.exe`
3. **Right-click → Run as administrator** (writing `app.asar` needs elevation)
4. Restart WorkBuddy when prompted — the floating bar appears at the bottom

> The lazy bundle is a PyInstaller onefile that bundles the Python runtime and all
> runtime files; it self-extracts to a temp dir on each run. To uninstall, run
> `wb-usage-install.exe --remove`.

## Source install

Requirements: Windows (or macOS); Python 3.8+ (zero third-party dependencies).

```
git clone https://github.com/qyo123oyq/wb-token-usage-statusbar.git
cd wb-token-usage-statusbar
python install.py            # add --lang en for English installer output
```

One command does it all: locate WorkBuddy (`WORKBUDDY_ASAR` env → common install
locations → `--root`, e.g. `--root E:\WorkBuddy`) → copy runtime into
`~/.workbuddy/wb-token-usage-statusbar/` → generate `config  .json` → patch `app.asar`
(a single `require()` loader line) → register the MCP server in `~/.workbuddy/mcp.json` →
install the `/usage` command → remind you to restart WorkBuddy.

**WorkBuddy upgrades overwrite `app.asar` — re-run `python install.py` (or the lazy bundle) after upgrading.**

## Features

The status bar floats at the bottom of the WorkBuddy window and shows real-time usage.
All items can be toggled in the ⚙ panel.

### ① Context capacity
A mini progress bar plus percentage showing how much of the context window the current
session uses (`session_usage.used / size`). Color shifts green → yellow → red as usage
grows; ≥1M-token windows warn earlier at 40% / 60%.

### ② This turn
Token & credit delta of the most recent completed turn — derived by sampling
`usage_updated_at` changes between polls (WorkBuddy does not store per-turn rows locally,
so the delta is computed client-side from successive reads).

### ③ Session total
Total tokens & credits for the current session, with request count (from
`session_usage.credit_json`).

### ④ Today total
Token & credit consumption across all of today's sessions (by `last_activity_at`).

### ⑤ Model & status
Current model id and session status (`working` / `completed` / `pending`).

### ⑥ Settings panel (⚙)
Toggle any item, switch UI language (中文 / English). Position is draggable and
remembered. Respects `prefers-color-scheme` (light/dark).

### More
- **MCP in-chat query**: `token_usage(scope)` — `now` / `today` / `json` / `days:N` /
  `sessions:N` / `session:<id-prefix>` / `workspace:<dir-keyword>`.
- **CLI**: `python busage.py [now|today|json|days N|sessions [N]|workspace <kw>|session <prefix>|watch|serve]`.
- **`/usage` command** template.

## Data source

Reads `~/.workbuddy/workbuddy.db`, strictly read-only:

- `sessions` (id, cwd, status, mode, model, context_window, created_at, updated_at, …)
- `session_usage` (session_id, used, size, updated_at, credit_json)
- `workspaces` (path, last_opened_at)

The "current" session is approximated as the most recently active session (WorkBuddy does
not expose the focused-window session id to local data). Each conversation window's data
is its own; the bar simply shows the most recent. Credits are the sum of
`session_usage.credit_json` values — WorkBuddy's own accounting; the numeric unit is
whatever WorkBuddy records, surfaced as-is.

## Uninstall

```
python install.py --remove          # source
wb-usage-install.exe --remove       # lazy bundle
```

Only strips this tool's own injection line (other tools' injections untouched), removes
the MCP registration and data directory.

## Differences from the ZCode version

WorkBuddy's local DB has coarser granularity than ZCode's (`model_usage` / `turn_usage` /
`tool_usage` per request). So:
- No per-tool-call breakdown / error badge.
- No per-model / cache read-write / thinking split.
- "This turn" is a client-side delta, not a stored row.
- No sub-agent tracking (sessions carry no parent link in the local schema).

What's preserved 1:1: floating bar UX, context-capacity bar, today/session totals,
bilingual settings panel, CLI, MCP, zero-dependency Python, asar-injection install model.

## Usage examples

```bash
# data layer / CLI
python busage.py now                    # current/recent active session
python busage.py today                   # today summary
python busage.py sessions 10             # recent 10 sessions
python busage.py workspace AIwork        # aggregate by dir keyword
python busage.py session 9ddc            # one session detail (id prefix)
python busage.py watch                    # live refresh (2s)
python busage.py serve --port 0          # local HTTP JSON service
python busage.py --lang en now           # English output
```

```bash
# installer
python install.py --root E:\WorkBuddy    # specify install dir
python install.py --dev                  # dev mode: inject at repo, hot reload
python install.py --no-mcp               # status bar only, no MCP
python install.py --dry-run
python install.py --remove
```

## Config (config.json)

```json
{
  "python_path": "python",
  "poll_ms": 2000,
  "hot_reload": true,
  "context_window": 0,
  "lang": "zh",
  "show": { "context": true, "turn": true, "session": true, "today": true, "model": true, "status": true }
}
```

- `context_window`: 0 = auto (from DB size/context_window); positive overrides.
- `poll_ms`: bar poll interval (ms).
- `lang`: zh / en.
- `show`: default visible items (panel toggles overwrite to localStorage).

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│ WorkBuddy (Electron)                                          │
│  app.asar  ← inject one line require(inject-main.cjs) (CJS) │
│   └ main process: inject-main.cjs                           │
│       ├ spawn busage.py serve  (local HTTP JSON)            │
│       ├ relax CSP (so renderer can fetch 127.0.0.1)      │
│       └ inject overlay.js into all renderer windows (executeJavaScript) │
│   └ renderer: overlay.js (floating bar DOM + poll every poll_ms) │
└──────────────────────────────────────────────────────────────┘
        │ fetch http://127.0.0.1:<port>/now
        ▼
┌──────────────────────────────────────────────────────────────┐
│ busage.py (Python stdlib, zero deps)                         │
│  ├ read-only ~/.workbuddy/workbuddy.db (sessions / session_usage) │
│  ├ CLI: now / today / json / days / sessions / workspace …   │
│  └ serve: local HTTP JSON server (port 0 = OS-assigned)      │
└──────────────────────────────────────────────────────────────┘
```

## Acknowledgments

This project is a direct retarget of **[@xhwxt](https://github.com/xhwxt)'s
[zcode-token-usage-statusbar](https://github.com/xhwxt/zcode-token-usage-statusbar)**
to the WorkBuddy desktop client. The architecture — Python stdlib data layer,
Electron `main/index.js` asar injection, renderer overlay, pure-Python asar patcher,
one-shot installer, MCP + CLI + slash command — and large parts of the asar repack
code are adapted from the original. Thank you @xhwxt for the design and the clean
zero-dependency implementation, which made porting to WorkBuddy straightforward.

## Notes
- Patching `app.asar` is an unofficial injection; WorkBuddy updates overwrite it — re-run install after upgrading.
- WorkBuddy's Electron build embeds no integrity-validation fuse (no sentinel), so asar modification loads fine.
- Numbers refresh every 2 s (configurable via `poll_ms`); zero polling when idle is not guaranteed since the bar itself polls — the DB is only touched on poll.
- License: MIT.