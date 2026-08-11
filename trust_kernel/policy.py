"""Policy π (CLAUDE.md §4, §5): π(e) = ⊓_d crit_d(effective_d), stale ⇒ Safe.
The "π" stage of bands -> reduce -> CTPR -> π.

Serves:
  T1 (monotonicity) -- π is built as a meet of per-dimension monotone crit_d
      maps, monotone by construction.
  T2 (non-compensation) -- a meet is ⊑ every term by definition of infimum,
      so π never exceeds any single dimension's floor. The floor-dominance
      table is this property made concrete: crit_d(ℓ) for every (d, ℓ).
  T3 (fail-safe reachability) -- π(stale) = Safe by the stale branch;
      π(⊥) = Safe because every strict dimension (5 of 6, post L⁸→L⁶
      relattice -- CLAUDE.md changelog 2026-07-19) floors at Safe on LOW,
      and min() over the 6 crit_d(LOW) values is therefore Safe.

No I/O, no state, no clocks, no floats: this sits in π's call path (§11).
"""

import hashlib
import json
from enum import IntEnum

from trust_kernel.bands import DIMENSIONS, TrustLevel


class Verdict(IntEnum):
    Safe = 0
    Constrained = 1
    Normal = 2


def load_crit_table(path):
    with open(path) as f:
        raw = json.load(f)
    validate_crit_table(raw)
    return raw, frozenset(raw["strict"]), frozenset(raw["lenient"])


def validate_crit_table(raw):
    strict = set(raw.get("strict", []))
    lenient = set(raw.get("lenient", []))
    if strict | lenient != set(DIMENSIONS):
        raise ValueError(f"strict/lenient partition does not cover exactly the {len(DIMENSIONS)} dimensions")
    if strict & lenient:
        raise ValueError("strict/lenient partition overlaps")


def crit_table_hash(path) -> str:
    """Fail-closed: validates before hashing (§11)."""
    with open(path) as f:
        raw = json.load(f)
    validate_crit_table(raw)
    canonical = json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


def crit(dimension: str, level: TrustLevel, strict: frozenset, lenient: frozenset) -> Verdict:
    """crit_d: per-dimension criticality map (§4). Strict dimensions floor
    at Safe on LOW; lenient dimensions floor at Constrained on LOW. By
    monotonicity, crit(LOW)=Constrained for a lenient dimension forces
    crit(MED) >= Constrained; CLAUDE.md does not state the MED case
    explicitly, so this module resolves it by also mapping lenient-MED to
    Constrained (the simplest monotone completion: lenient dimensions floor
    at Constrained for anything short of HIGH). Flagged for PI confirmation
    per §18, not asserted as verbatim spec. HIGH always maps to Normal."""
    if dimension in strict:
        table = {
            TrustLevel.LOW: Verdict.Safe,
            TrustLevel.MED: Verdict.Constrained,
            TrustLevel.HIGH: Verdict.Normal,
        }
    elif dimension in lenient:
        table = {
            TrustLevel.LOW: Verdict.Constrained,
            TrustLevel.MED: Verdict.Constrained,
            TrustLevel.HIGH: Verdict.Normal,
        }
    else:
        raise ValueError(f"dimension {dimension!r} is in neither strict nor lenient")
    return table[level]


def policy(effective_dims: dict, strict: frozenset, lenient: frozenset, stale: bool = False) -> Verdict:
    """π(e) = ⊓_d crit_d(effective_d); stale ⇒ Safe (§4)."""
    if stale:
        return Verdict.Safe
    missing = set(DIMENSIONS) - set(effective_dims)
    if missing:
        raise ValueError(f"policy requires all {len(DIMENSIONS)} dimensions; missing {sorted(missing)}")
    return min(crit(d, effective_dims[d], strict, lenient) for d in DIMENSIONS)
