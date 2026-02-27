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

# Install Python 3.12 system-wide via uv (needed for Claude Desktop extension)
echo "Ensuring Python 3.12 is installed..."
uv python install 3.12

# Make python3.12 available on PATH for Claude Desktop
PYTHON_312="$HOME/.local/bin/python3.12"
if [ ! -f "$PYTHON_312" ]; then
    # Find where uv installed it
    UV_PYTHON=$(uv python find 3.12 2>/dev/null || true)
    if [ -n "$UV_PYTHON" ]; then
        mkdir -p "$HOME/.local/bin"
        ln -sf "$UV_PYTHON" "$PYTHON_312"
        echo "Linked python3.12 → $UV_PYTHON"
    fi
fi

# Also link as 'python3' if the system one is too old
SYSTEM_PYTHON_VERSION=$(python3 -c "import sys; print(sys.version_info.minor)" 2>/dev/null || echo "0")
if [ "$SYSTEM_PYTHON_VERSION" -lt 10 ]; then
    echo "System python3 is 3.${SYSTEM_PYTHON_VERSION} (too old). Linking python3.12 as python3..."
    ln -sf "$PYTHON_312" "$HOME/.local/bin/python3"
fi

# Ensure ~/.local/bin is on PATH
if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
    echo ""
    echo "Adding ~/.local/bin to your PATH..."
    SHELL_RC=""
    if [ -f "$HOME/.zshrc" ]; then
        SHELL_RC="$HOME/.zshrc"
    elif [ -f "$HOME/.bashrc" ]; then
        SHELL_RC="$HOME/.bash_profile"
    fi
    if [ -n "$SHELL_RC" ]; then
        if ! grep -q 'local/bin' "$SHELL_RC" 2>/dev/null; then
            echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$SHELL_RC"
            echo "Added to $SHELL_RC — restart your terminal or run: source $SHELL_RC"
        fi
    fi
    export PATH="$HOME/.local/bin:$PATH"
fi

# Create venv with Python 3.12
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
echo "Python 3.12 installed and available as: $PYTHON_312"
echo ""
echo "Option 1: Install the .mcpb extension in Claude Desktop"
echo "  Open Claude Desktop → Install Extension → select salesforce-impl.mcpb"
echo "  (Restart your terminal first so Claude Desktop picks up Python 3.12)"
echo ""
echo "Option 2: Add to Claude Desktop config manually"
echo "  Edit: ~/Library/Application Support/Claude/claude_desktop_config.json"
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
