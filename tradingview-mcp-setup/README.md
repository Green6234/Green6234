# TradingView MCP Setup

Prepared TradingView MCP bridge for Claude Code integration.

## Quick start

1. Read **[tradingview-mcp/LOCAL_HANDOFF.md](tradingview-mcp/LOCAL_HANDOFF.md)** — full setup checklist
2. Run the installer:
   ```bash
   cd tradingview-mcp && ./scripts/install_for_claude.sh
   ```
3. Launch TradingView with debug port, restart Claude Code, run `tv_health_check`

## MCP config template

Copy `mcp.json.template` to `~/.claude/.mcp.json` and replace the path with your install location.

## What's included

- `tradingview-mcp/` — full repo with `npm install` completed (run `npm install` again on your machine if needed)
- `LOCAL_HANDOFF.md` — usage warnings, troubleshooting, improvement ideas

Upstream: https://github.com/tradesdontlie/tradingview-mcp
