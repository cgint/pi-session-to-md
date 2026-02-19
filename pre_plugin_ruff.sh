#!/bin/bash

set -euo pipefail

PLUGIN_NAME="Ruff"
echo
echo "Running Plugin $PLUGIN_NAME..."
uv add ruff --dev
uv run ruff check --fix
ruff_status=$? # Capture the exit status

# Optional: Add logging based on status
if [ $ruff_status -ne 0 ]; then
    echo "Plugin $PLUGIN_NAME failed with status $ruff_status" >&2
fi

exit $ruff_status # Exit with the actual status of the ruff command 