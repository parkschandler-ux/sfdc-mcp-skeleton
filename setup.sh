#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"

echo "=== Salesforce Implementation Tracker — MCP Server Setup ==="
echo ""

# Ensure uv is available (for Python version management + venv)
if ! command -v uv &>/dev/null; then
    echo "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

# Create venv with Python 3.12 (uv will download it if needed)
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment with Python 3.12..."
    uv venv --python 3.12 "$VENV_DIR"
fi

echo "Installing dependencies..."
source "$VENV_DIR/bin/activate"
uv pip install -r "$SCRIPT_DIR/requirements.txt"

PYTHON_PATH="$VENV_DIR/bin/python3"

echo ""
echo "=== Setup complete ==="
echo ""
echo "Add the following to your Claude Desktop config (~/.claude/claude_desktop_config.json):"
echo ""
cat <<EOF
{
  "mcpServers": {
    "salesforce-impl": {
      "command": "$PYTHON_PATH",
      "args": ["$SCRIPT_DIR/mcp_server.py"],
      "env": {
        "SF_CLIENT_ID": "<your-client-id>",
        "SF_CLIENT_SECRET": "<your-client-secret>",
        "SF_INSTANCE_URL": "https://your-org.my.salesforce.com",
        "SF_USER_EMAIL": "<your-email>"
      }
    }
  }
}
EOF
echo ""
echo "Replace the placeholder values with your Salesforce credentials."
echo "SF_USER_EMAIL should be your Salesforce login email."
