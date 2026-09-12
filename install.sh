#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR"
TARGET="$PROJECT_DIR/agent.py"
EXEC="python3 $TARGET"
LINK_NAME="pbl"
INSTALL_DIR="${HOME}/.local/bin"

if [ ! -f "$TARGET" ]; then
    echo "Error: agent.py not found at $TARGET" >&2
    exit 1
fi

mkdir -p "$INSTALL_DIR"

ln -sf "$EXEC" "$INSTALL_DIR/$LINK_NAME"
chmod +x "$INSTALL_DIR/$LINK_NAME"

echo "Installed 'pbl' -> $EXEC"
echo "Ensure $INSTALL_DIR is in your PATH (add 'export PATH=\"\$HOME/.local/bin:\$PATH\"' to ~/.bashrc or ~/.zshrc)"