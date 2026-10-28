#!/usr/bin/env python3
"""Build the dependency-free Debian application package without root or pip.

Only Python's standard library and dpkg-deb are needed. The application lives in
a private directory, leaving the distribution's Python import path untouched.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone


ROOT = Path(__file__).resolve().parent.parent
PACKAGE = "asis-swarm"


def _write(path: Path, content: str | bytes, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
    path.chmod(0o755 if executable else 0o644)


def _version() -> str:
    match = re.search(r'^__version__\s*=\s*"([^"]+)"', (ROOT / "asis/core.py").read_text(), re.MULTILINE)
    if match is None or re.fullmatch(r"\d+\.\d+\.\d+(?:[+~][a-zA-Z0-9.]+)?", match[1]) is None:
        raise ValueError("asis/core.py must declare a Debian-compatible release version")
    return match[1]


def _epoch() -> int:
    supplied = os.environ.get("SOURCE_DATE_EPOCH")
    if supplied is None:
        git = shutil.which("git")
        result = subprocess.run([git, "log", "-1", "--format=%ct"], cwd=ROOT, text=True, capture_output=True) if git else None
        supplied = result.stdout.strip() if result is not None and result.returncode == 0 else "0"
    if not supplied.isdecimal():
        raise ValueError("SOURCE_DATE_EPOCH must be a non-negative integer")
    return int(supplied)


def _stage(stage: Path, version: str, epoch: int) -> None:
    app = stage / "usr/lib/asis-swarm/asis"
    for source in sorted((ROOT / "asis").glob("*.py")):
        _write(app / source.name, source.read_bytes())
    _write(app / "dashboard.html", (ROOT / "asis/dashboard.html").read_bytes())
    for source in sorted((ROOT / "asis/domains").glob("*.json")):
        _write(app / "domains" / source.name, source.read_bytes())

    _write(stage / "usr/bin/asis", (ROOT / "packaging/asis-launcher.py").read_bytes(), executable=True)
    _write(stage / "usr/share/applications/asis-swarm.desktop", (ROOT / "packaging/asis-swarm.desktop").read_bytes())
    _write(stage / "usr/share/icons/hicolor/scalable/apps/asis-swarm.svg", (ROOT / "packaging/asis-swarm.svg").read_bytes())
    manual = (ROOT / "packaging/asis.1").read_text().replace("@VERSION@", version)
    _write(stage / "usr/share/man/man1/asis.1.gz", gzip.compress(manual.encode(), mtime=epoch))

    docs = stage / "usr/share/doc/asis-swarm"
    _write(docs / "copyright", (ROOT / "packaging/copyright").read_bytes())
    _write(docs / "LICENSE", (ROOT / "LICENSE.md").read_bytes())
    _write(docs / "README.md", (ROOT / "README.md").read_bytes())
    _write(docs / "changelog.gz", gzip.compress((ROOT / "CHANGELOG.md").read_bytes(), mtime=epoch))
    date = datetime.fromtimestamp(epoch, timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    changelog = (
        f"{PACKAGE} ({version}) unstable; urgency=medium\n\n"
        "  * Package the ASIS planner, CLI and local dashboard.\n"
        "  * Use the distribution's Python 3 without runtime downloads.\n\n"
        f" -- ASIS contributors <recursive-ai-dev@users.noreply.github.com>  {date}\n"
    )
    _write(docs / "changelog.Debian.gz", gzip.compress(changelog.encode(), mtime=epoch))

    files = sorted(path for path in stage.rglob("*") if path.is_file())
    size = (sum(path.stat().st_size for path in files) + 1023) // 1024
    control = (
        f"Package: {PACKAGE}\nVersion: {version}\n"
        "Section: science\nPriority: optional\nArchitecture: all\n"
        "Maintainer: ASIS contributors <recursive-ai-dev@users.noreply.github.com>\n"
        f"Installed-Size: {size}\n"
        "Depends: python3 (>= 3.10)\nSuggests: xdg-utils, www-browser\n"
        "Homepage: https://github.com/recursive-ai-dev/asis-agentic-swarm-intelligence-system\n"
        "Description: deterministic constraint planner and local swarm dashboard\n"
        " ASIS composes bounded search operations to find action plans against a\n"
        " knowledge base. It includes residual-guided compensation, model checks,\n"
        " a command-line interface, JSON traces and a local browser dashboard.\n"
        " .\n"
        " The application uses Python's standard library and runs offline.\n"
    )
    _write(stage / "DEBIAN/control", control)
    checksums = "".join(f"{hashlib.md5(path.read_bytes()).hexdigest()}  {path.relative_to(stage)}\n" for path in files)
    _write(stage / "DEBIAN/md5sums", checksums)
    # Source permissions and the caller's umask must not leak into the package.
    # Normalize directories and timestamps, including the archive root.
    for path in [stage, *sorted(stage.rglob("*"))]:
        if path.is_dir():
            path.chmod(0o755)
        os.utime(path, (epoch, epoch))


def build(output: Path, force: bool = False) -> Path:
    dpkg_deb = shutil.which("dpkg-deb")
    if dpkg_deb is None:
        raise ValueError("dpkg-deb is required (install dpkg-dev on Debian/Ubuntu)")
    version, epoch = _version(), _epoch()
    output = output.expanduser().resolve()
    protected = [ROOT / name for name in ("asis", "tests", "packaging", ".git")]
    if any(output == path or path in output.parents for path in protected):
        raise ValueError("the output directory must not be inside application, test, packaging or Git sources")
    output.mkdir(parents=True, exist_ok=True)
    artifact = output / f"{PACKAGE}_{version}_all.deb"
    checksum = artifact.with_suffix(".deb.sha256")
    if not force and (artifact.exists() or checksum.exists()):
        raise ValueError(f"output already exists: {artifact}; use --force to replace the package and checksum")

    # Build beside the final outputs so publishing via replace stays atomic.
    with tempfile.TemporaryDirectory(prefix=".asis-deb-", dir=output) as temporary:
        temporary_path = Path(temporary)
        stage, built = temporary_path / "root", temporary_path / artifact.name
        stage.mkdir()
        _stage(stage, version, epoch)
        subprocess.run(
            [dpkg_deb, "--root-owner-group", "--uniform-compression", "--compression=xz",
             "--threads-max=1", "--build", str(stage), str(built)],
            check=True, env={**os.environ, "SOURCE_DATE_EPOCH": str(epoch)},
        )
        metadata = subprocess.check_output([dpkg_deb, "--field", str(built), "Package", "Version", "Architecture"], text=True)
        if f"Package: {PACKAGE}\n" not in metadata or "Architecture: all\n" not in metadata:
            raise ValueError("package metadata verification failed")
        digest = hashlib.sha256(built.read_bytes()).hexdigest()
        staged_checksum = temporary_path / checksum.name
        _write(staged_checksum, f"{digest}  {artifact.name}\n")
        built.chmod(0o644)
        built.replace(artifact)
        staged_checksum.replace(checksum)
    return artifact


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist", help="artifact destination (default: %(default)s)")
    parser.add_argument("--force", action="store_true", help="replace an existing package and checksum after a successful build")
    args = parser.parse_args()
    try:
        artifact = build(args.output_dir, args.force)
    except (OSError, ValueError, subprocess.CalledProcessError, OverflowError) as exc:
        print(f"build-deb: {exc}", file=sys.stderr)
        return 1
    print(f"Package: {artifact}\nChecksum: {artifact.with_suffix('.deb.sha256')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
