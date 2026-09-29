#!/bin/bash
# Build a standalone `asis` executable (engine, CLI and dashboard) with PyInstaller.
set -euo pipefail

cd "$(dirname "$0")"
echo "Building ASIS standalone binary..."

if ! python -m PyInstaller --version &> /dev/null; then
    echo "PyInstaller not found, installing..."
    python -m pip install pyinstaller
fi

python -m PyInstaller --onefile --clean --noconfirm \
    --name asis \
    --paths . \
    --add-data "asis/dashboard.html:asis" \
    --add-data "asis/domains:asis/domains" \
    asis/__main__.py

echo "Build complete. Binary is located in dist/asis"
