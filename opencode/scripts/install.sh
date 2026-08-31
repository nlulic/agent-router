#!/usr/bin/env sh
set -eu

if ! command -v opencode2 >/dev/null 2>&1; then
  echo "OpenCode V2 (opencode2) was not found in PATH." >&2
  echo "Install the current V2 release, then rerun this script." >&2
  exit 1
fi

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
SOURCE_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd -P)
CONFIG_HOME=${XDG_CONFIG_HOME:-"$HOME/.config"}
TARGET_DIR="$CONFIG_HOME/opencode"
TARGET_AGENTS="$TARGET_DIR/agents"

same_link() {
  [ -L "$1" ] && [ "$(readlink "$1")" = "$2" ]
}

check_target() {
  target=$1
  source=$2
  if [ -e "$target" ] || [ -L "$target" ]; then
    if same_link "$target" "$source"; then
      return 0
    fi
    echo "Refusing to overwrite existing OpenCode path: $target" >&2
    echo "Merge or move that file manually, then rerun this installer." >&2
    exit 1
  fi
}

check_target "$TARGET_DIR/opencode.jsonc" "$SOURCE_DIR/opencode.jsonc"
for source in "$SOURCE_DIR"/agents/*.md; do
  check_target "$TARGET_AGENTS/$(basename "$source")" "$source"
done

mkdir -p "$TARGET_AGENTS"

if ! same_link "$TARGET_DIR/opencode.jsonc" "$SOURCE_DIR/opencode.jsonc"; then
  ln -s "$SOURCE_DIR/opencode.jsonc" "$TARGET_DIR/opencode.jsonc"
fi

for source in "$SOURCE_DIR"/agents/*.md; do
  target="$TARGET_AGENTS/$(basename "$source")"
  if ! same_link "$target" "$source"; then
    ln -s "$source" "$target"
  fi
done

echo "Installed OpenCode V2 configuration in $TARGET_DIR"
echo "The files are symlinked to $SOURCE_DIR; repository updates take effect after OpenCode reloads them."
