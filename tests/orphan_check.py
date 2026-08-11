"""Orphan-check utility for the L8->L6 relattice (CLAUDE.md changelog
2026-07-19: 'Context removed... Safety removed...').

Most of this is already discharged structurally by existing fail-closed
config validation: trust_kernel.bands.validate_eis_config() and
trust_kernel.schema.validate_claim_registry() both reject any claim whose
"dimension" field is not in trust_kernel.bands.DIMENSIONS, and
trust_kernel.policy.validate_crit_table() requires strict|lenient to equal
exactly set(DIMENSIONS) -- so a leftover "Safety"/"Context" claim or a
malformed crit table fails to load at all, loudly, the moment DIMENSIONS
shrinks to 6. That leaves exactly one class of staleness those validators
cannot see: config/key_registry.json has no "dimension" field and is never
cross-checked against claim_registry.json, so an orphaned
safety_sensor_v0/context_sensor_v0 key entry (still valid on its own
terms: well-formed public key, authorized_claim_types pointing at a claim
type that itself no longer exists anywhere) would load silently. This
module closes that gap with a direct recursive scan.
"""

import json
import pathlib

FORBIDDEN_DIMENSIONS = {"Safety", "Context"}
FORBIDDEN_CLAIM_TYPES = {"safety.provisional_v0", "context.provisional_v0"}
FORBIDDEN_SOURCE_IDS = {"safety_sensor_v0", "context_sensor_v0"}
FORBIDDEN_IDENTIFIERS = FORBIDDEN_DIMENSIONS | FORBIDDEN_CLAIM_TYPES | FORBIDDEN_SOURCE_IDS


def _scan(obj) -> set:
    found = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str) and k in FORBIDDEN_IDENTIFIERS:
                found.add(k)
            found |= _scan(v)
    elif isinstance(obj, list):
        for item in obj:
            found |= _scan(item)
    elif isinstance(obj, str):
        if obj in FORBIDDEN_IDENTIFIERS:
            found.add(obj)
    return found


def find_orphan_references(config_paths: dict) -> dict:
    """config_paths: {name: path}. Returns {name: [forbidden identifiers
    found]} for any config file that still references a removed dimension,
    claim type, or source_id; empty dict means clean."""
    hits = {}
    for name, path in config_paths.items():
        raw = json.loads(pathlib.Path(path).read_text())
        found = _scan(raw)
        if found:
            hits[name] = sorted(found)
    return hits


def check_or_raise(config_paths: dict):
    """Fail loudly (§ orphan check requirement): raise rather than return a
    result silently ignorable by a caller that forgets to check it."""
    hits = find_orphan_references(config_paths)
    if hits:
        raise ValueError(
            f"orphan L8 dimension/claim/source references found after L8->L6 "
            f"relattice: {hits}"
        )
