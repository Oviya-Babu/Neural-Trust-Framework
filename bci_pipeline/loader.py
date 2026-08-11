"""BCIC IV 2a loader (CLAUDE.md §17a, Phase 7). Substrate only -- this
module emits no evidence, calls no trust_kernel/enforcement/evidence_plane/
observer code, and performs no security instrumentation. It exists to
answer exactly one question safely: "is this the file we think it is?"
before anything downstream (filtering, features, a classifier) ever touches
it.

Access is via MOABB's BNCI2014_001 dataset class (BCI Competition IV
Dataset 2a), using its standard download/parse machinery -- but MOABB's own
download path (moabb.datasets.download.data_dl, backed by pooch) does not
let a caller supply an externally-pinned expected hash for a *first*
download; it only re-hashes a file that already exists locally, as a
resume/skip check. So the reproducibility pin required by CLAUDE.md §17a
("pin the MOABB dataset version, the resolved download mirror URL, and a
per-file SHA-256 of every downloaded file... a hash mismatch at load time
must fail closed, not warn") is layered on top here, independently of
MOABB's own logic: after MOABB has obtained (downloaded or found cached)
the raw .mat file(s), this module hashes the actual bytes on disk and
compares them against config/dataset_pins.json, refusing to return
anything if they disagree.

The resolved_base_url and per-file URLs in config/dataset_pins.json were
confirmed by inspecting the installed moabb==1.5.0 package's source
(moabb.datasets.bnci.base.BNCI_URL and the A{subject:02d}{T|E}.mat naming
in moabb.datasets.bnci.bnci_2014._load_data_001_2014), not assumed --
"'MOABB default' is not a pin; the resolved URL and file hashes are."
"""

import hashlib
import json
import os
import pathlib

CONFIG_DIR = pathlib.Path(__file__).resolve().parent.parent / "config"
DEFAULT_PINS_PATH = CONFIG_DIR / "dataset_pins.json"
DEFAULT_CACHE_DIR = pathlib.Path(__file__).resolve().parent.parent / ".bci_data_cache"

DATASET_CODE = "BNCI2014-001"


class DatasetIntegrityError(ValueError):
    """Raised on any pin-config defect or hash mismatch. Fail closed: the
    caller gets an exception, never a warning and a best-effort result."""


def validate_pins(raw: dict):
    for field in ("moabb_version", "dataset_code", "resolved_base_url", "files"):
        if field not in raw:
            raise DatasetIntegrityError(f"dataset pin config missing '{field}'")
    if raw["dataset_code"] != DATASET_CODE:
        raise DatasetIntegrityError(
            f"pinned dataset_code {raw['dataset_code']!r} != expected {DATASET_CODE!r}"
        )
    if not raw["files"]:
        raise DatasetIntegrityError("dataset pin config declares no files")
    for key, entry in raw["files"].items():
        for field in ("url", "sha256", "bytes"):
            if field not in entry:
                raise DatasetIntegrityError(f"file pin {key!r} missing '{field}'")
        if not entry["url"].startswith(raw["resolved_base_url"]):
            raise DatasetIntegrityError(
                f"file pin {key!r} url {entry['url']!r} is not under the pinned "
                f"resolved_base_url {raw['resolved_base_url']!r}"
            )


def load_pins(path=DEFAULT_PINS_PATH) -> dict:
    """Fail-closed load (§11 pattern, same as every other config loader in
    this repo): validate before returning anything usable."""
    with open(path) as f:
        raw = json.load(f)
    validate_pins(raw)
    return raw


def _sha256_of(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_file(path: pathlib.Path, expected_sha256: str, key: str):
    if not pathlib.Path(path).exists():
        raise DatasetIntegrityError(f"file pin {key!r} points at a path that does not exist: {path}")
    actual = _sha256_of(path)
    if actual != expected_sha256:
        raise DatasetIntegrityError(
            f"hash mismatch for {key!r}: expected sha256={expected_sha256}, got {actual} "
            f"-- refusing to load {path}"
        )
    return actual


def resolve_and_verify_subject_files(subject: int, cache_dir: pathlib.Path = DEFAULT_CACHE_DIR,
                                      pins: dict = None) -> dict:
    """Obtains (via MOABB, downloading only if not already cached) subject
    `subject`'s two raw .mat files, then verifies each against the pinned
    SHA-256 before returning anything. Raises DatasetIntegrityError --
    before any parsing, filtering, or feature extraction is attempted -- if
    either file is unpinned or its hash disagrees with the pin.
    """
    pins = pins or load_pins()
    cache_dir = pathlib.Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    # MOABB resolves its download root from MNE_DATASETS_BNCI_PATH (env var
    # or persisted mne config); set only the in-process environment for
    # this call so this module never mutates the user's persisted mne
    # config as a side effect of merely being imported.
    os.environ["MNE_DATASETS_BNCI_PATH"] = str(cache_dir)

    from moabb.datasets import BNCI2014_001
    dataset = BNCI2014_001()
    local_paths = dataset.data_path(subject, path=str(cache_dir))

    verified = {}
    for label, local_path in zip(("T", "E"), local_paths):
        key = f"A{subject:02d}{label}"
        if key not in pins["files"]:
            raise DatasetIntegrityError(
                f"no pinned entry for {key!r} -- refuse to load an unpinned file "
                f"(add it to {DEFAULT_PINS_PATH} first)"
            )
        expected = pins["files"][key]["sha256"]
        actual = verify_file(local_path, expected, key)
        verified[label] = {"path": pathlib.Path(local_path), "sha256": actual, "key": key}
    return verified


def load_subject_data(subject: int, cache_dir: pathlib.Path = DEFAULT_CACHE_DIR, pins: dict = None):
    """The only entry point downstream pipeline stages should call. Returns
    (mne_data, verified_files): mne_data is MOABB's own {subject: {session:
    {run: mne.io.Raw}}} structure (from BNCI2014_001.get_data), obtained
    only after resolve_and_verify_subject_files() has confirmed both files
    match their pin -- a hash mismatch raises before get_data() is ever
    called, so no unverified bytes are parsed."""
    pins = pins or load_pins()
    verified_files = resolve_and_verify_subject_files(subject, cache_dir, pins)

    os.environ["MNE_DATASETS_BNCI_PATH"] = str(pathlib.Path(cache_dir))
    from moabb.datasets import BNCI2014_001
    dataset = BNCI2014_001()
    mne_data = dataset.get_data(subjects=[subject])
    return mne_data[subject], verified_files
