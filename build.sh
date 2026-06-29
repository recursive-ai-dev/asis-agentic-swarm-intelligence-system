#!/bin/bash
set -e

echo "Building ASIS 2.0 Desktop Deployment Binary..."

# Ensure pyinstaller is installed
if ! command -v pyinstaller &> /dev/null
then
    echo "pyinstaller could not be found, installing..."
    pip install pyinstaller
fi

# Run the build
pyinstaller --onefile --clean asis.py

echo "Build complete. Binary is located in dist/asis"
