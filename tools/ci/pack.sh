#!/bin/bash
#
# Local packaging script for arduino-TuyaOpen vendor SDKs.
# Creates a Python venv, installs dependencies, and runs package_release.py.
#
# Usage:
#   ./pack.sh <version> [target]
#
# Examples:
#   ./pack.sh 0.0.9 t5          # Package T5 vendor SDK v0.0.9
#   ./pack.sh 1.2.5 t3          # Package T3 vendor SDK v1.2.5
#   ./pack.sh 1.2.5 enabled     # Package all enabled platforms
#   ./pack.sh 1.2.5 all         # Package arduino core + all vendor SDKs
#   ./pack.sh 1.2.5 arduino     # Package arduino core only
#
# Available targets are read from package-config.json:
#   arduino, t2, t3, t5, ln882h, esp32, enabled, all

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG_FILE="$SCRIPT_DIR/package-config.json"
VENV_DIR="$SCRIPT_DIR/.venv"
LOG_LEVEL="${LOG_LEVEL:-INFO}"

# --- Argument parsing ---
if [ $# -lt 1 ]; then
    echo "Usage: $0 <version> [target]"
    echo ""
    echo "  version   Release version (e.g. 0.0.9)"
    echo "  target    What to build (default: enabled)"
    echo ""
    # List available platforms from config
    echo "Available targets:"
    echo "  arduino                  - Arduino core package"
    python3 -c "
import json
with open('$CONFIG_FILE') as f:
    config = json.load(f)
for key, plat in config['platforms'].items():
    status = 'enabled' if plat.get('enabled') else 'disabled'
    print(f'  {key:22s} - {plat[\"toolName\"]} ({status})')
" 2>/dev/null || true
    echo "  enabled                  - All enabled platforms"
    echo "  all                      - Arduino core + all platforms"
    exit 1
fi

VERSION="$1"
TARGET="${2:-enabled}"

# Validate version format
if ! echo "$VERSION" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+$'; then
    echo "Error: Invalid version format '$VERSION' (expected x.y.z)"
    exit 1
fi

echo "=== Arduino-TuyaOpen Packaging ==="
echo "  Version: $VERSION"
echo "  Target:  $TARGET"
echo "  Output:  $SCRIPT_DIR/output"
echo ""

# --- Download ci-data if needed ---
download_data() {
    local platform="$1"
    local data_dir="$SCRIPT_DIR/data/$platform"

    if [ -d "$data_dir" ] && [ "$(ls -A "$data_dir" 2>/dev/null)" ]; then
        return 0
    fi

    echo "Downloading ci-data for $platform..."
    python3 "$SCRIPT_DIR/manage_data.py" download --platform "$platform"
}

# Determine which platforms need data
if [ "$TARGET" = "arduino" ]; then
    : # no vendor data needed
elif [ "$TARGET" = "all" ] || [ "$TARGET" = "enabled" ]; then
    platforms=$(python3 -c "
import json
with open('$CONFIG_FILE') as f:
    config = json.load(f)
for key, plat in config['platforms'].items():
    if '$TARGET' == 'all' or plat.get('enabled'):
        print(key)
")
    for p in $platforms; do
        download_data "$p"
    done
else
    download_data "$TARGET"
fi

# --- Setup Python venv ---
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating Python virtual environment..."
    python3 -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"

pip install -q --upgrade pip > /dev/null
pip install -q -r "$SCRIPT_DIR/requirements.txt" > /dev/null

# --- Run packaging ---
echo ""
echo "Starting packaging..."
echo ""

python3 "$SCRIPT_DIR/package_release.py" \
    --version "$VERSION" \
    --target "$TARGET" \
    --output "$SCRIPT_DIR/output" \
    --log-level "$LOG_LEVEL"

deactivate

echo ""
echo "=== Packaging complete ==="
echo "Output: $SCRIPT_DIR/output/"
ls -lh "$SCRIPT_DIR/output/"*.tar.bz2 "$SCRIPT_DIR/output/"*.zip 2>/dev/null || true
