#!/bin/bash

set -euo pipefail

PLUGIN_NAME="MyPy"
echo
echo "Running Plugin $PLUGIN_NAME..."
uv add mypy --dev
uv run mypy .
mypy_status=$? # Capture the exit status

# Optional: Add logging based on status
if [ $mypy_status -ne 0 ]; then
    echo "Plugin $PLUGIN_NAME failed with status $mypy_status" >&2
fi

exit $mypy_status # Exit with the actual status of the mypy command 