#!/bin/sh
# Build ASIS for Debian/Ubuntu with the system Python and dpkg-deb; no root/pip.
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if ! command -v python3 >/dev/null 2>&1; then
    printf '%s\n' 'python3 is required to build the Debian package.' >&2
    exit 1
fi
exec python3 "$script_dir/packaging/build_deb.py" "$@"
