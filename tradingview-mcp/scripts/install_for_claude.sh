#!/usr/bin/env bash
# One-shot installer for TradingView MCP + Claude Code
# Usage: ./scripts/install_for_claude.sh [install_path]
set -euo pipefail

INSTALL_PATH="${1:-$HOME/tradingview-mcp}"
REPO_URL="https://github.com/tradesdontlie/tradingview-mcp.git"
MCP_CONFIG="$HOME/.claude/.mcp.json"
CDP_PORT="${TV_CDP_PORT:-9222}"

echo "=== TradingView MCP Installer ==="
echo "Install path: $INSTALL_PATH"
echo ""

# Node check
if ! command -v node >/dev/null 2>&1; then
  echo "Error: Node.js 18+ required. Install from https://nodejs.org"
  exit 1
fi
NODE_MAJOR=$(node -p "process.versions.node.split('.')[0]")
if [ "$NODE_MAJOR" -lt 18 ]; then
  echo "Error: Node.js 18+ required (found $(node -v))"
  exit 1
fi
echo "Node: $(node -v)"

# Clone or update
if [ -d "$INSTALL_PATH/.git" ]; then
  echo "Updating existing repo at $INSTALL_PATH..."
  git -C "$INSTALL_PATH" pull --ff-only
else
  echo "Cloning $REPO_URL -> $INSTALL_PATH"
  git clone "$REPO_URL" "$INSTALL_PATH"
fi

cd "$INSTALL_PATH"
echo "Installing npm dependencies..."
npm install

# MCP config (merge if exists)
mkdir -p "$(dirname "$MCP_CONFIG")"
SERVER_PATH="$INSTALL_PATH/src/server.js"

if [ -f "$MCP_CONFIG" ]; then
  echo "Merging into existing $MCP_CONFIG..."
  node -e "
    const fs = require('fs');
    const path = process.argv[1];
    const serverPath = process.argv[2];
    let cfg = {};
    try { cfg = JSON.parse(fs.readFileSync(path, 'utf8')); } catch {}
    cfg.mcpServers = cfg.mcpServers || {};
    cfg.mcpServers.tradingview = { command: 'node', args: [serverPath] };
    fs.writeFileSync(path, JSON.stringify(cfg, null, 2) + '\n');
    console.log('Updated tradingview entry in', path);
  " "$MCP_CONFIG" "$SERVER_PATH"
else
  echo "Creating $MCP_CONFIG..."
  cat > "$MCP_CONFIG" <<EOF
{
  "mcpServers": {
    "tradingview": {
      "command": "node",
      "args": ["$SERVER_PATH"]
    }
  }
}
EOF
fi

# Optional global CLI
read -r -p "Install 'tv' CLI globally? (npm link) [y/N] " LINK_CLI
if [[ "$LINK_CLI" =~ ^[Yy]$ ]]; then
  npm link
  echo "CLI installed: run 'tv status' from anywhere"
fi

echo ""
echo "=== Install complete ==="
echo ""
echo "NEXT STEPS:"
echo "  1. Launch TradingView with debug port:"
echo "       $INSTALL_PATH/scripts/launch_tv_debug_linux.sh $CDP_PORT   # Linux"
echo "       $INSTALL_PATH/scripts/launch_tv_debug_mac.sh $CDP_PORT       # macOS"
echo "       $INSTALL_PATH/scripts/launch_tv_debug.bat $CDP_PORT            # Windows"
echo ""
echo "  2. Restart Claude Code (MCP loads at startup)"
echo ""
echo "  3. Verify connection:"
echo "       Ask Claude: 'Use tv_health_check to verify TradingView is connected'"
echo "       Or CLI:     tv status"
echo ""
echo "See LOCAL_HANDOFF.md for usage notes and improvement ideas."
