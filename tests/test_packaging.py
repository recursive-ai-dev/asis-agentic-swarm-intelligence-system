"""The Debian artifact is runnable without pip, a checkout, or root access."""

import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tarfile
import time
import urllib.error
import urllib.request

import pytest

from asis import __version__


ROOT = Path(__file__).resolve().parent.parent
BUILDER = ROOT / "packaging/build_deb.py"
SYSTEM_PYTHON = Path("/usr/bin/python3")
pytestmark = pytest.mark.skipif(
    shutil.which("dpkg-deb") is None or not SYSTEM_PYTHON.exists(),
    reason="Debian package checks require dpkg-deb and /usr/bin/python3",
)


@pytest.fixture(scope="module")
def deb(tmp_path_factory):
    directory = tmp_path_factory.mktemp("deb build with spaces")
    env = {**os.environ, "SOURCE_DATE_EPOCH": "1770000000"}
    subprocess.run([str(SYSTEM_PYTHON), str(BUILDER), "--output-dir", str(directory)], check=True, env=env)
    artifact = directory / f"asis-swarm_{__version__}_all.deb"
    extracted = directory / "extracted"
    subprocess.run(["dpkg-deb", "--extract", str(artifact), str(extracted)], check=True)
    return artifact, extracted, env


def test_package_metadata_files_and_checksums(deb):
    artifact, _, _ = deb
    metadata = subprocess.check_output(["dpkg-deb", "--field", str(artifact)], text=True)
    assert "Package: asis-swarm\n" in metadata
    assert f"Version: {__version__}\n" in metadata
    assert "Architecture: all\n" in metadata
    assert "Depends: python3 (>= 3.10)\n" in metadata
    checksum = artifact.with_suffix(".deb.sha256").read_text()
    assert checksum == f"{hashlib.sha256(artifact.read_bytes()).hexdigest()}  {artifact.name}\n"
    archive = subprocess.check_output(["dpkg-deb", "--fsys-tarfile", str(artifact)])
    with tarfile.open(fileobj=io.BytesIO(archive)) as payload:
        files = {member.name.removeprefix("./"): member for member in payload.getmembers()}
        for filename in (
            "usr/bin/asis", "usr/lib/asis-swarm/asis/dashboard.html",
            "usr/lib/asis-swarm/asis/domains/web_service.json",
            "usr/share/applications/asis-swarm.desktop", "usr/share/man/man1/asis.1.gz",
            "usr/share/icons/hicolor/scalable/apps/asis-swarm.svg", "usr/share/doc/asis-swarm/LICENSE",
        ):
            assert filename in files
        assert files["usr/bin/asis"].mode == 0o755
        assert all(member.uid == member.gid == 0 for member in files.values())
        assert not any("__pycache__" in filename or filename.endswith(".pyc") or "/tests/" in filename for filename in files)


def test_extracted_launcher_ignores_pythonpath_and_current_directory(deb, tmp_path):
    _, extracted, _ = deb
    # Neither accidental local modules nor a hostile PYTHONPATH may replace the
    # application's imports; the package launcher uses Python isolated mode.
    (tmp_path / "asis.py").write_text("raise RuntimeError('wrong module')\n")
    env = {**os.environ, "PYTHONPATH": str(tmp_path)}
    launcher = extracted / "usr/bin/asis"
    completed = subprocess.run([str(launcher), "--version"], cwd=tmp_path, env=env, text=True, capture_output=True, check=True)
    assert completed.stdout.strip() == f"asis {__version__}"
    completed = subprocess.run([str(launcher), "kb", "--json"], cwd=tmp_path, env=env, text=True, capture_output=True, check=True)
    assert json.loads(completed.stdout)["name"] == "web_service"


def test_extracted_launcher_solves_custom_knowledge_base(deb, tmp_path):
    _, extracted, _ = deb
    custom = tmp_path / "custom kb.json"
    custom.write_text(json.dumps({
        "name": "package-probe",
        "metrics": {"speed": {"baseline": 10}},
        "actions": {"boost": {"cost": 5, "effects": {"speed": {"add": 10}}}},
    }))
    completed = subprocess.run(
        [str(extracted / "usr/bin/asis"), "solve", "speed >= 20", "--kb", str(custom), "--json"],
        cwd=tmp_path, text=True, capture_output=True, check=True,
    )
    result = json.loads(completed.stdout)
    assert result["status"] == "solved"
    assert result["plan"] == {"boost": 1}
    assert result["metrics"]["speed"] == 20


def test_extracted_launcher_serves_bundled_dashboard(deb, tmp_path):
    _, extracted, _ = deb
    # Ask the kernel for an available loopback port; the process owns no service
    # or global state and is always stopped by this test's finally block.
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    process = subprocess.Popen(
        [str(extracted / "usr/bin/asis"), "dashboard", "--port", str(port), "--no-browser", "--no-demo"],
        cwd=tmp_path, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            assert process.poll() is None, process.stderr.read().decode()
            try:
                with urllib.request.urlopen(url, timeout=0.25) as response:
                    html = response.read()
                break
            except (OSError, urllib.error.URLError):
                time.sleep(0.02)
        else:
            pytest.fail("packaged dashboard did not start")
        assert b"ASIS" in html and b"/api/step" in html
        with urllib.request.urlopen(url + "/api/kb", timeout=2) as response:
            assert json.load(response)["name"] == "web_service"
    finally:
        process.terminate()
        process.communicate(timeout=5)


def test_build_is_reproducible_and_requires_explicit_replacement(deb, tmp_path):
    artifact, _, env = deb
    original = artifact.read_bytes()
    duplicate = subprocess.run(
        [str(SYSTEM_PYTHON), str(BUILDER), "--output-dir", str(artifact.parent)], env=env,
        text=True, capture_output=True,
    )
    assert duplicate.returncode == 1 and "--force" in duplicate.stderr
    assert artifact.read_bytes() == original
    subprocess.run([str(SYSTEM_PYTHON), str(BUILDER), "--output-dir", str(tmp_path)], env=env, check=True)
    assert (tmp_path / artifact.name).read_bytes() == original


def test_builder_rejects_source_output_paths_and_bad_epoch(tmp_path):
    invalid = subprocess.run(
        [str(SYSTEM_PYTHON), str(BUILDER), "--output-dir", str(ROOT / "asis")], text=True, capture_output=True,
    )
    assert invalid.returncode == 1 and "must not be inside" in invalid.stderr
    invalid = subprocess.run(
        [str(SYSTEM_PYTHON), str(BUILDER), "--output-dir", str(tmp_path)],
        env={**os.environ, "SOURCE_DATE_EPOCH": "not-a-timestamp"}, text=True, capture_output=True,
    )
    assert invalid.returncode == 1 and "SOURCE_DATE_EPOCH" in invalid.stderr


@pytest.mark.skipif(shutil.which("dpkg") is None, reason="private-root install test requires dpkg")
def test_rootless_install_verify_and_purge_in_private_database(deb, tmp_path):
    artifact, _, _ = deb
    install_root = tmp_path / "private-root"
    install_root.mkdir()
    # The empty, private dpkg database has no python3 package record. Dependency
    # forcing applies only to that database; the launcher uses the real system
    # interpreter. No maintainer scripts, host package changes or sudo are used.
    command = ["dpkg", "--force-not-root", "--force-depends", f"--root={install_root}", f"--log={tmp_path / 'dpkg.log'}"]
    subprocess.run([*command, "--install", str(artifact)], check=True, capture_output=True)
    try:
        status = subprocess.check_output([*command, "--status", "asis-swarm"], text=True)
        assert "Status: install ok installed\n" in status
        version = subprocess.check_output([str(install_root / "usr/bin/asis"), "--version"], cwd=tmp_path, text=True)
        assert version.strip() == f"asis {__version__}"
        verified = subprocess.run([*command, "--verify", "asis-swarm"], check=True, capture_output=True)
        assert not verified.stdout
    finally:
        subprocess.run([*command, "--purge", "asis-swarm"], check=True, capture_output=True)
    assert not (install_root / "usr/bin/asis").exists()
    assert not (install_root / "usr/lib/asis-swarm").exists()
