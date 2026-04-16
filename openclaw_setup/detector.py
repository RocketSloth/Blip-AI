"""
System detection layer.

Detects OS, available package managers, installed binaries, and environment
variables without modifying anything. All results are plain dataclasses so the
planner and installer can consume them without re-running subprocesses.
"""

import os
import platform
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Optional

from .manifests import BinaryRequirement


@dataclass
class SystemInfo:
    os_name: str                    # linux, darwin, windows
    os_version: str
    arch: str                       # x86_64, arm64, etc.
    package_managers: list          # list[str] — available: brew, apt, dnf, uv, npm, go
    found_bins: dict                # {name: path} for detected binaries
    missing_bins: list              # list[BinaryRequirement] not found
    present_env: dict               # {name: value} for env vars that are set
    missing_env: list               # list[str] for env vars not set
    openclaw_version: Optional[str] # None if not installed


def _run(cmd: str, timeout: int = 5) -> Optional[str]:
    """Run a shell command and return stdout, or None on failure."""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 0:
            return result.stdout.strip()
        return None
    except Exception:
        return None


def detect_os() -> tuple:
    """Return (os_name, os_version, arch)."""
    system = platform.system().lower()
    if system == "darwin":
        os_name = "darwin"
    elif system == "linux":
        os_name = "linux"
    elif system == "windows":
        os_name = "windows"
    else:
        os_name = system

    os_version = platform.version()
    arch = platform.machine()
    return os_name, os_version, arch


def detect_package_managers() -> list:
    """Return list of available package manager names."""
    candidates = {
        "brew": "brew --version",
        "apt": "apt-get --version",
        "dnf": "dnf --version",
        "uv": "uv --version",
        "npm": "npm --version",
        "go": "go version",
        "pip": "pip --version",
    }
    found = []
    for name, cmd in candidates.items():
        if _run(cmd) is not None:
            found.append(name)
    return found


def detect_binary(req: BinaryRequirement) -> Optional[str]:
    """Return the path to a binary if found, else None."""
    path = shutil.which(req.name)
    if path and _run(req.check_cmd) is not None:
        return path
    return None


def detect_binaries(requirements: list) -> tuple:
    """
    Check a list of BinaryRequirement objects.
    Returns (found: dict {name: path}, missing: list[BinaryRequirement]).
    """
    found = {}
    missing = []
    for req in requirements:
        path = detect_binary(req)
        if path:
            found[req.name] = path
        else:
            missing.append(req)
    return found, missing


def detect_env_vars(names: list) -> tuple:
    """
    Check which env vars are set.
    Returns (present: dict {name: value}, missing: list[str]).
    """
    present = {}
    missing = []
    for name in names:
        val = os.environ.get(name)
        if val:
            present[name] = val
        else:
            missing.append(name)
    return present, missing


def detect_openclaw_version() -> Optional[str]:
    """Return the installed openclaw version string, or None."""
    return _run("openclaw --version")


def run_detection(
    required_bins: list,
    required_env: list,
) -> SystemInfo:
    """
    Full system detection pass.

    required_bins: list[BinaryRequirement]
    required_env:  list[str]
    """
    os_name, os_version, arch = detect_os()
    pkg_managers = detect_package_managers()
    found_bins, missing_bins = detect_binaries(required_bins)
    present_env, missing_env = detect_env_vars(required_env)
    openclaw_version = detect_openclaw_version()

    return SystemInfo(
        os_name=os_name,
        os_version=os_version,
        arch=arch,
        package_managers=pkg_managers,
        found_bins=found_bins,
        missing_bins=missing_bins,
        present_env=present_env,
        missing_env=missing_env,
        openclaw_version=openclaw_version,
    )
