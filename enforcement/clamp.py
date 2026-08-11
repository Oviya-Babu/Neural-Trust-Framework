"""Enforcement Plane: envelope config, acceptance, and clamping (CLAUDE.md
§6). Dumb, capability-gated actuator writer. Produces no evidence about
itself. Its bound is computed independently of the verdict.

realise(verdict) = Env(verdict) ⊓ Ceil, meet = componentwise min. Ceil is
loaded once from config/ceil.json at process start and is never a function
of any verdict field -- this is the entire content of T5(a) (§5): "the
content is not the arithmetic (x ⊓ c ⊑ c is an axiom) -- it is that Ceil is
not a function of ν."

Five-field boundary (§6): the enforcer reads exactly schema_version,
window_id, verdict, expires_at, kernel_sig from a verdict object, and NEVER
reads evidence_root, effective_dims, policy_version, crit_table_hash,
ctpr_config_hash, roc_config_hash, claim_registry_hash, key_registry_hash,
calibration_status, or issued_at. This module's own source text contains
none of those nine forbidden identifiers as string literals -- that is the
"dependency analysis" that discharges the field-boundary half of T5(a); see
experiments/phase5_enforcement.py's structural check for the grep and the
dynamic GuardedVerdictDict test.

One deliberate exception to "never read other fields": signature
verification (trust_kernel.schema.verify_verdict_signature) necessarily
recomputes a hash over the FULL signed payload -- that is inherent to
verifying a signature over a wire object, and is a bytewise/opaque
operation, not a decision that branches on any individual field's meaning.
It is delegated entirely to trust_kernel.schema, which this module calls as
a black box; nothing in enforcement/ itself inspects, names, or branches on
any field outside the five. Everything downstream of that signature check
(schema-support check, replay-cache lookup, expiry check, envelope
selection) operates only on the EnforcerView five-field extraction.

Ceil is not read from ν anywhere in this module -- ceil is always a
separately-loaded parameter, never sourced from a verdict object.
"""

import json
from dataclasses import dataclass
from typing import Optional

from trust_kernel import schema

ENFORCER_FIELDS = ("schema_version", "window_id", "verdict", "expires_at", "kernel_sig")
SUPPORTED_SCHEMA_VERSIONS = (schema.SCHEMA_VERSION,)
VERDICT_NAMES = ("Safe", "Constrained", "Normal")


class EnforcementConfigError(ValueError):
    pass


# --------------------------------------------------------------------------
# Ceil / Env config: fail-closed load + validate, binding condition.
# --------------------------------------------------------------------------

def validate_ceil(raw: dict):
    for field in ("max_speed", "max_acceleration"):
        if field not in raw:
            raise EnforcementConfigError(f"ceil config missing '{field}'")
        v = raw[field]
        if isinstance(v, bool) or not isinstance(v, int):
            raise EnforcementConfigError(f"ceil.{field} must be a fixed-point int, got {v!r}")
        if v < 0:
            raise EnforcementConfigError(f"ceil.{field} must be non-negative")


def load_ceil(path) -> dict:
    with open(path) as f:
        raw = json.load(f)
    validate_ceil(raw)
    return {"max_speed": raw["max_speed"], "max_acceleration": raw["max_acceleration"]}


def validate_env(raw: dict):
    missing = set(VERDICT_NAMES) - set(raw)
    if missing:
        raise EnforcementConfigError(f"env config missing verdict zone(s): {sorted(missing)}")
    for name in VERDICT_NAMES:
        entry = raw[name]
        for field in ("max_speed", "max_acceleration"):
            if field not in entry:
                raise EnforcementConfigError(f"env.{name} missing '{field}'")
            v = entry[field]
            if isinstance(v, bool) or not isinstance(v, int):
                raise EnforcementConfigError(f"env.{name}.{field} must be a fixed-point int, got {v!r}")
            if v < 0:
                raise EnforcementConfigError(f"env.{name}.{field} must be non-negative")


def load_env(path) -> dict:
    with open(path) as f:
        raw = json.load(f)
    validate_env(raw)
    return {name: {"max_speed": raw[name]["max_speed"], "max_acceleration": raw[name]["max_acceleration"]}
            for name in VERDICT_NAMES}


def validate_binding(ceil: dict, env: dict):
    """§6: 'Ceil ⊏ Env(Normal) in both components is required. ... a
    non-binding Ceil makes T5 true-but-empty and must be caught, not
    shipped.' Strict componentwise less-than."""
    normal = env["Normal"]
    if not (ceil["max_speed"] < normal["max_speed"] and ceil["max_acceleration"] < normal["max_acceleration"]):
        raise EnforcementConfigError(
            "binding condition violated: Ceil must be strictly below Env(Normal) "
            f"componentwise (ceil={ceil}, Env(Normal)={normal}) -- a non-binding "
            "Ceil makes T5(a) true-but-empty (§6)"
        )


def load_envelope_configs(ceil_path, env_path) -> tuple:
    """Fail-closed: loads, validates, and checks the binding condition
    before returning anything usable."""
    ceil = load_ceil(ceil_path)
    env = load_env(env_path)
    validate_binding(ceil, env)
    return ceil, env


# --------------------------------------------------------------------------
# realise(): the only place a verdict name touches an envelope.
# --------------------------------------------------------------------------

def realise(verdict_name: str, env: dict, ceil: dict) -> dict:
    """realise(ν) = Env(π̂(ν)) ⊓ Ceil, meet = componentwise min (§5, §6).
    Ceil is a parameter here, never derived from verdict_name or any other
    verdict field -- that independence is the entire content of T5(a)."""
    if verdict_name not in env:
        raise EnforcementConfigError(f"unknown verdict zone: {verdict_name!r}")
    e = env[verdict_name]
    return {
        "max_speed": min(e["max_speed"], ceil["max_speed"]),
        "max_acceleration": min(e["max_acceleration"], ceil["max_acceleration"]),
    }


# --------------------------------------------------------------------------
# EnforcerView: the five-field boundary made structural, not just documented.
# __slots__ means no other attribute can ever be attached to this object,
# even by accident -- code holding an EnforcerView physically cannot reach
# evidence_root, effective_dims, or any of the other nine fields through it.
# --------------------------------------------------------------------------

class EnforcerView:
    __slots__ = ENFORCER_FIELDS

    def __init__(self, schema_version, window_id, verdict, expires_at, kernel_sig):
        self.schema_version = schema_version
        self.window_id = window_id
        self.verdict = verdict
        self.expires_at = expires_at
        self.kernel_sig = kernel_sig

    @classmethod
    def from_verdict_object(cls, verdict_obj: dict) -> "EnforcerView":
        return cls(**{f: verdict_obj[f] for f in ENFORCER_FIELDS})


# --------------------------------------------------------------------------
# accept_cache: 2-entry ring keyed on window_id (§6). No "current round"
# comparison anywhere -- the enforcer must never learn the round from a
# host-controlled input; dedup against recently-seen window_ids is the only
# window_id check performed here.
# --------------------------------------------------------------------------

class AcceptCache:
    def __init__(self, size: int = 2):
        if size < 1:
            raise EnforcementConfigError("accept_cache size must be >= 1")
        self._size = size
        self._seen: list = []

    def contains(self, window_id) -> bool:
        return window_id in self._seen

    def record(self, window_id):
        if window_id in self._seen:
            return
        self._seen.append(window_id)
        if len(self._seen) > self._size:
            self._seen.pop(0)


@dataclass(frozen=True)
class AcceptResult:
    accepted: bool
    reason: Optional[str]
    view: Optional[EnforcerView]


def accept(verdict_obj: dict, kernel_public_key: bytes, now_ms: int, cache: AcceptCache) -> AcceptResult:
    """accept(ν) iff sig valid ∧ schema supported ∧ window_id ∉ accept_cache
    ∧ now < expires_at (§6). Any rejection ⇒ fail safe: no EnforcerView (and
    therefore no envelope, no actuator write) is ever produced for a
    rejected verdict."""
    if not schema.verify_verdict_signature(kernel_public_key, verdict_obj):
        return AcceptResult(False, "signature", None)

    view = EnforcerView.from_verdict_object(verdict_obj)

    if view.schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        return AcceptResult(False, "schema", None)
    if cache.contains(view.window_id):
        return AcceptResult(False, "replay", None)
    if not (now_ms < view.expires_at):
        return AcceptResult(False, "expired", None)

    cache.record(view.window_id)
    return AcceptResult(True, None, view)


@dataclass(frozen=True)
class EnforcementDecision:
    accepted: bool
    reason: Optional[str]
    envelope: Optional[dict]  # None iff not accepted -- no envelope is computed for a rejected verdict


def accept_and_clamp(verdict_obj: dict, kernel_public_key: bytes, now_ms: int,
                      cache: AcceptCache, env: dict, ceil: dict) -> EnforcementDecision:
    """Composition of accept() and realise(). A rejected verdict produces no
    envelope at all here -- see enforcement/capability.py: 'rejected/failed
    verdict ⇒ no token presented ⇒ no actuator write' is enforced by the
    caller never having an envelope to write, not by writing (0,0)."""
    result = accept(verdict_obj, kernel_public_key, now_ms, cache)
    if not result.accepted:
        return EnforcementDecision(False, result.reason, None)
    return EnforcementDecision(True, None, realise(result.view.verdict, env, ceil))
