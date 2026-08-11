"""CTPR, Cross-Trust Propagation Rule (CLAUDE.md §4): effective_child =
meet(child, g(parent)) for the two frozen edges FSI→Signal, FSI→Model. The
"CTPR" stage of bands -> reduce -> CTPR -> π.

g is monotone in the PARENT'S TRUST LEVEL, not confidence ("confidence is
static per detector; g(confidence) would be a constant cap and propagation
inert" -- §4). This module implements g as the identity map: the simplest
function satisfying "monotone in the parent's level". CLAUDE.md does not
pin down g's exact shape beyond monotonicity, so this is an explicit
implementation choice flagged for PI confirmation per §18, not a verbatim
spec formula -- adjacent to §17's already-open "dependency DAG beyond
FSI→{Signal, Model}".

Serves T1: meet(child, g(parent)) is monotone in both arguments, so CTPR
composes with a monotone bands()/reduce_dimension() and a monotone
policy() without breaking T1's overall monotonicity.
"""

import hashlib
import json

from trust_kernel.bands import DIMENSIONS, TrustLevel, meet


def g(parent_level: TrustLevel) -> TrustLevel:
    """Monotone map from a parent dimension's trust level to the cap it
    imposes on its children. Identity -- see module docstring."""
    return parent_level


def load_ctpr_config(path):
    with open(path) as f:
        raw = json.load(f)
    validate_ctpr_config(raw)
    edges = tuple((e["parent"], e["child"]) for e in raw["edges"])
    return raw, edges


def validate_ctpr_config(raw):
    if raw.get("g") != "identity":
        raise ValueError("only g == 'identity' is implemented (see module docstring)")
    if "edges" not in raw or not raw["edges"]:
        raise ValueError("ctpr config must declare at least one edge")
    for e in raw["edges"]:
        parent, child = e.get("parent"), e.get("child")
        if parent not in DIMENSIONS or child not in DIMENSIONS:
            raise ValueError(f"CTPR edge references unknown dimension: {parent}->{child}")
        if parent == child:
            raise ValueError(f"CTPR edge cannot be self-referential: {parent}->{child}")


def ctpr_config_hash(path) -> str:
    """Fail-closed: validates before hashing (§11)."""
    with open(path) as f:
        raw = json.load(f)
    validate_ctpr_config(raw)
    canonical = json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


def apply_ctpr(raw_dims: dict, edges) -> dict:
    """raw_dims: {dimension_name: TrustLevel} for all of DIMENSIONS (post
    intra-dimension reduction, pre-propagation). Returns effective_dims with
    each CTPR edge applied: effective_child = meet(child, g(parent))."""
    missing = set(DIMENSIONS) - set(raw_dims)
    if missing:
        raise ValueError(f"apply_ctpr requires all {len(DIMENSIONS)} dimensions; missing {sorted(missing)}")

    effective = dict(raw_dims)
    for parent, child in edges:
        effective[child] = meet(effective[child], g(effective[parent]))
    return effective
