#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR"
TARGET="$PROJECT_DIR/agent.py"
LINK_NAME="pbl"
INSTALL_DIR="${HOME}/.local/bin"

if [ ! -f "$TARGET" ]; then
    echo "Error: agent.py not found at $TARGET" >&2
    exit 1
fi

mkdir -p "$INSTALL_DIR"

LAUNCHER="$INSTALL_DIR/$LINK_NAME"

# A symlink cannot carry arguments ("python3 /path"), so an old install leaves a
# dangling link behind. Remove it before writing the launcher script.
rm -f "$LAUNCHER"

cat > "$LAUNCHER" <<EOF
#!/usr/bin/env bash
exec python3 "$TARGET" "\$@"
EOF

chmod +x "$LAUNCHER"

echo "Installed 'pbl' -> $TARGET"
echo "Ensure $INSTALL_DIR is in your PATH (add 'export PATH=\"\$HOME/.local/bin:\$PATH\"' to ~/.bashrc or ~/.zshrc)"
