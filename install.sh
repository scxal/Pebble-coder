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

# User home: ~/.pbl with config/templates. Copy defaults only if missing so user
# edits survive; the app also auto-bootstraps on first run.
PBL_HOME="${HOME}/.pbl"
mkdir -p "$PBL_HOME" "$PBL_HOME/agents" "$PBL_HOME/skills"
for f in config.json tools.json commands.json \
         translations_es.json translations_en.json \
         system_prompt.md system_prompt_xml.md \
         system_prompt_hermes.md system_prompt_deepseek.md; do
  [ -e "$PBL_HOME/$f" ] || cp "$SCRIPT_DIR/defaults/$f" "$PBL_HOME/$f"
done
cp -rn "$SCRIPT_DIR/defaults/agents/." "$PBL_HOME/agents/" 2>/dev/null || true
cp -rn "$SCRIPT_DIR/defaults/skills/." "$PBL_HOME/skills/" 2>/dev/null || true

echo "Installed 'pbl' -> $TARGET"
echo "Installed ~/.pbl from defaults/ ($PBL_HOME)"
echo "Ensure $INSTALL_DIR is in your PATH (add 'export PATH=\"\$HOME/.local/bin:\$PATH\"' to ~/.bashrc or ~/.zshrc)"
