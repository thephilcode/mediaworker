#!/usr/bin/env bash
# run_queue.sh - Simple script to run the mediaworker encode command.
# Assumes uv is installed and the project is installed with `uv pip install -e .`

set -euo pipefail

# Change to the directory containing this script
cd "$(dirname "$0")"

# Run the encode command via uv (preferred) or fallback to python
if command -v uv >/dev/null 2>&1; then
    echo "Running mediaworker encode via uv..."
    uv run encoder/mediaworker.py encode "$@"
else
    echo "uv not found, falling back to python..."
    python3 -m encoder.mediaworker encode "$@"
fi