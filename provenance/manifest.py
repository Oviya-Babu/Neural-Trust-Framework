"""Run-manifest construction (CLAUDE.md §13): every experiment run emits a
manifest of config+hash, git commit+dirty-state, parameters, seeds,
hardware/OS, timestamps, and generated artifact hashes, so that "no figure
enters the dissertation that cannot be regenerated from its manifest by one
command." Built in Phase 2, not deferred to Phase 9 (§13).
"""

import hashlib
import json
import pathlib
import platform
import subprocess
import sys
from datetime import datetime, timezone


def _git_state(repo_root: pathlib.Path):
    """Best-effort, honest git state. If this directory is not a git
    repository, that fact is recorded rather than fabricated or silently
    omitted -- a manifest is a reproducibility record, and 'unknown' is
    better than a guess."""
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root, capture_output=True, text=True, timeout=10,
        )
        if commit.returncode != 0:
            return {"available": False, "reason": commit.stderr.strip() or "not a git repository"}
        dirty = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_root, capture_output=True, text=True, timeout=10,
        )
        return {
            "available": True,
            "commit": commit.stdout.strip(),
            "dirty": bool(dirty.stdout.strip()),
        }
    except FileNotFoundError:
        return {"available": False, "reason": "git executable not found"}


def _file_hash(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_manifest(
    repo_root: pathlib.Path,
    experiment_name: str,
    config_paths: dict,
    params: dict,
    artifact_paths: dict,
    calibration_status: str,
    seeds: dict,
):
    return {
        "experiment": experiment_name,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "calibration_status": calibration_status,
        "git": _git_state(repo_root),
        "hardware_os": {
            "platform": platform.platform(),
            "processor": platform.processor() or "unknown",
            "python_version": sys.version,
        },
        "params": params,
        "seeds": seeds,
        "config_hashes": {
            name: _file_hash(path) for name, path in config_paths.items()
        },
        "artifacts": {
            name: {"path": str(path), "sha256": _file_hash(path)}
            for name, path in artifact_paths.items()
        },
    }


def write_manifest(manifest: dict, path: pathlib.Path):
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
