# TradingView MCP — Local Setup Handoff

This document is your final checklist for running the TradingView MCP server with Claude Code on your machine. The cloud agent prepared the repo; you finish the steps that require your local TradingView Desktop app.

## Status (prepared in cloud)

| Step | Status |
|------|--------|
| Repo cloned | Done (`tradingview-mcp/`) |
| `npm install` | Done (94 packages) |
| Unit tests | 29/29 passed (offline + CLI routing) |
| MCP config template | Created at `~/.claude/.mcp.json` |
| E2E / `tv_health_check` | **Requires your local TradingView** |

## Quick install on your machine

Paste this into Claude Code (recommended):

> Install the TradingView MCP server. Clone https://github.com/tradesdontlie/tradingview-mcp.git, run npm install, add it to my MCP config at ~/.claude/.mcp.json, and launch TradingView with the debug port. Then verify the connection with tv_health_check.

Or run the installer script:

```bash
git clone https://github.com/tradesdontlie/tradingview-mcp.git ~/tradingview-mcp
cd ~/tradingview-mcp
./scripts/install_for_claude.sh
```

## Step-by-step (manual)

### 1. Install dependencies

```bash
git clone https://github.com/tradesdontlie/tradingview-mcp.git ~/tradingview-mcp
cd ~/tradingview-mcp
npm install
npm run test:unit   # optional: verify 29 tests pass without TradingView
```

### 2. Add MCP server to Claude Code

Edit `~/.claude/.mcp.json` (create if missing):

```json
{
  "mcpServers": {
    "tradingview": {
      "command": "node",
      "args": ["/Users/YOUR_USERNAME/tradingview-mcp/src/server.js"]
    }
  }
}
```

Replace the path with your actual install location. If you already have other MCP servers, merge the `tradingview` entry into the existing `mcpServers` object — do not overwrite other servers.

### 3. Launch TradingView with CDP (required)

TradingView Desktop must run with Chrome DevTools Protocol on port **9222**. This is **not** enabled by default — you must launch it explicitly.

**macOS:**
```bash
/Applications/TradingView.app/Contents/MacOS/TradingView --remote-debugging-port=9222
# or: ./scripts/launch_tv_debug_mac.sh
```

**Windows:**
```cmd
%LOCALAPPDATA%\TradingView\TradingView.exe --remote-debugging-port=9222
# or: scripts\launch_tv_debug.bat
```

**Linux:**
```bash
/opt/TradingView/tradingview --remote-debugging-port=9222
# or: ./scripts/launch_tv_debug_linux.sh
```

**Important:** Close any TradingView instance that was started *without* the debug flag first. The launch scripts kill existing instances by default.

After launch, confirm CDP is up:
```bash
curl http://localhost:9222/json/version
```

### 4. Restart Claude Code

MCP servers load at Claude Code startup. After editing `.mcp.json`:

1. Exit Claude Code completely
2. Relaunch Claude Code
3. Confirm the `tradingview` MCP server appears in your MCP list

### 5. Verify with `tv_health_check`

In Claude Code, ask:

> Use tv_health_check to verify TradingView is connected

Expected success response:

```json
{
  "success": true,
  "cdp_connected": true,
  "chart_symbol": "AAPL",
  "api_available": true
}
```

CLI equivalent:
```bash
cd ~/tradingview-mcp && npm link   # optional, once
tv status
```

## What to be aware of when using

### Legal and ToS

- This tool is **not affiliated with TradingView**. You are responsible for complying with [TradingView's Terms of Use](https://www.tradingview.com/policies/).
- Programmatic interaction with TradingView Desktop (especially streaming/OHLCV export) may conflict with their terms on automated data collection. Use for personal chart analysis and Pine development only.
- Market data remains subject to exchange licensing — do not redistribute or resell data pulled through this bridge.

### Stability and breakage risk

- The bridge talks to **undocumented internal Electron APIs** (`window.TradingViewApi`, etc.). Any TradingView Desktop update can break tools without warning.
- **Pin your TradingView version** if you rely on this for daily workflows.
- Run `tv_discover` after TV updates to see which API paths still work.

### Security

- CDP opens a **local debug port on localhost:9222**. Any process on your machine can control TradingView while it is open.
- Do not expose port 9222 to your network or run TradingView with CDP on untrusted machines.
- The MCP server runs locally via stdio — no data is sent to third parties by this project itself.

### Practical usage limits

| Topic | What to know |
|-------|--------------|
| **Subscription** | Requires a valid TradingView paid plan for real-time data. This tool does not bypass paywalls. |
| **Chart must be open** | CDP connects to a chart tab. Open at least one chart before calling tools. |
| **Pine Editor** | Pine tools need the Pine Editor panel open: `ui_open_panel pine-editor open` |
| **Indicator names** | Use full names ("Relative Strength Index") not abbreviations ("RSI") when adding indicators |
| **Context size** | Use `summary: true` on OHLCV, `study_filter` on Pine data tools, avoid `pine_get_source` on large scripts (can be 200KB+) |
| **Stale data** | Wait a few seconds after symbol/timeframe changes before reading values |
| **Replay mode** | Replay tools only work when replay is available for the current symbol |
| **Multi-pane** | Use `pane_focus` before reading data from a specific pane |
| **Kill on launch** | `tv_launch` and launch scripts kill existing TradingView instances — save your work first |

### Recommended first commands in Claude

```
tv_health_check          → confirm connection
chart_get_state          → symbol, timeframe, indicators
quote_get                → current price
data_get_study_values    → RSI, MACD, etc.
capture_screenshot       → visual analysis
```

For Pine Script:
```
ui_open_panel pine-editor open
pine_set_source → pine_smart_compile → pine_get_errors
```

Read `CLAUDE.md` in the repo — Claude Code auto-loads it and contains the full decision tree.

## Ways to change and improve the code

### High-impact improvements

1. **Configurable CDP port** — `connection.js` hardcodes port 9222. Add `TV_CDP_PORT` env var support in MCP config:
   ```json
   "env": { "TV_CDP_PORT": "9223" }
   ```

2. **Connection resilience** — Add automatic reconnect with exponential backoff when TradingView restarts, plus a `tv_reconnect` tool.

3. **API path versioning** — Internal TV APIs change often. Maintain a `api-paths.json` manifest with version probes so `tv_discover` can report compatibility per TradingView build.

4. **Structured error messages** — Map common CDP failures (`ECONNREFUSED`, `No chart target`) to actionable hints in every tool response.

5. **Rate limiting / debounce** — Batch rapid chart reads to avoid overloading the Electron main thread during multi-tool analysis workflows.

### Workflow enhancements

6. **Preset analysis workflows** — Add a `analysis_snapshot` tool that runs the recommended chain (state → quote → study values → pine lines/labels → OHLCV summary → screenshot) in one call with a single compact JSON response.

7. **Pine Script templates** — Ship starter templates in `templates/` and a `pine_from_template` tool for common patterns (EMA crossover, session levels, etc.).

8. **Watchlist-driven batch** — Extend `batch_run` to accept a watchlist name and iterate all symbols automatically.

9. **Session logging** — Optional JSONL audit log of all MCP tool calls for replay/debugging (local file only).

### Code quality

10. **E2E test harness** — Mock CDP with a recorded fixture so CI can run chart tool tests without a live TradingView instance.

11. **Pin zod explicitly** — Tools import `zod` transitively via MCP SDK; add it as a direct dependency to avoid breakage.

12. **`npm audit fix`** — 7 npm vulnerabilities reported at install time; review and patch.

13. **TypeScript migration** — Optional but would catch API shape drift earlier, especially in `connection.js` evaluate strings.

### MCP config enhancements

14. **Project-level config** — Add `.mcp.json` in the repo for team sharing (with path placeholders documented).

15. **Skills integration** — The repo includes skills in `skills/` (chart-analysis, pine-develop, multi-symbol-scan, replay-practice, strategy-report). Register these in Claude Code for richer agent behavior.

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `cdp_connected: false` | Launch TV with `--remote-debugging-port=9222`; verify with `curl localhost:9222/json/version` |
| `ECONNREFUSED` | TradingView not running or wrong port |
| MCP server missing in Claude | Check JSON syntax in `~/.claude/.mcp.json`; restart Claude Code |
| `api_available: false` | Chart tab not fully loaded; wait and retry |
| Pine tools fail | Open Pine Editor panel first |
| Port already in use | Another app on 9222; use `--remote-debugging-port=9223` and set env var |
| Tools return old data | TV still loading after symbol change; wait 2–3 seconds |

## File reference

| File | Purpose |
|------|---------|
| `src/server.js` | MCP server entry point |
| `src/connection.js` | CDP connection + internal API paths |
| `src/cli/index.js` | `tv` CLI (all MCP tools as commands) |
| `CLAUDE.md` | Tool decision tree for Claude |
| `scripts/launch_tv_debug_*.sh` | Platform launch scripts |
| `scripts/install_for_claude.sh` | One-shot installer |
| `skills/` | Claude Code skill definitions |

## Suggested Claude Code prompt for final review

After completing steps 1–5 locally, paste this into Claude Code:

> I've installed tradingview-mcp at ~/tradingview-mcp and TradingView is running with --remote-debugging-port=9222. Please:
> 1. Run tv_health_check and confirm cdp_connected and api_available are true
> 2. Run chart_get_state and quote_get on my current chart
> 3. Read CLAUDE.md and skills/chart-analysis/SKILL.md
> 4. Give me a sample analysis workflow tailored to my current symbol
> 5. Suggest any project-level .mcp.json or skill customizations for my setup
