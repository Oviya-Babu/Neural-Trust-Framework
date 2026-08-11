"""EIS v1 interpretation layer (CLAUDE.md §4): per-claim score -> band,
threshold derivation from ROC, and intra-dimension reduction ("bands" and
"reduce" stages of bands -> reduce -> CTPR -> π).

Serves T1 (monotonicity) and T2 (non-compensation): band() and
reduce_dimension() are both meet-based / order-preserving by construction,
which is what makes π = policy(ctpr(reduce(band(...)))) a meet of monotone
maps -- monotone by construction, not by a case analysis that could be
wrong (§12: "⊓-of-monotone-maps-is-monotone is a theorem; the check fails
only on a dict typo").

No I/O, no state, no clocks, no floats: everything here sits in π's call
path (§11). Rates are fixed-point basis points (0..10000), never floats.
"""

import hashlib
import json
from enum import IntEnum


class TrustLevel(IntEnum):
    LOW = 0
    MED = 1
    HIGH = 2


def meet(*levels: TrustLevel) -> TrustLevel:
    """Lattice meet (glb) over LOW ⊑ MED ⊑ HIGH: the worst level."""
    if not levels:
        raise ValueError("meet() requires at least one level")
    return TrustLevel(min(int(l) for l in levels))


DIMENSIONS = (
    "Signal", "Model", "Calibration",
    "Device", "FSI", "ActuationFidelity",
)

BP_SCALE = 10_000  # fixed-point basis-points scale for rates -- no floats.

# eis.v1 (prerequisite-to-Phase-9 representation fix, not a threshold
# derivation): the same fixed-point rate representation, widened from
# basis points (min nonzero rate 1e-4) to parts-per-billion (min nonzero
# rate 1e-9). Only the SCALE widens; s = pol x raw_measurement, band(),
# reduce_dimension(), and the theta1/theta2/band_cap formula in
# derive_thresholds() are all scale-parametric already and are otherwise
# untouched -- there is no new interpretation rule, only more precision to
# express the existing one at.
PPB_SCALE = 1_000_000_000  # fixed-point parts-per-billion scale for rates.

EIS_SCHEMA_VERSION_V0 = 0  # implicit: no eis_schema_version field, bp fields
EIS_SCHEMA_VERSION_V1 = 1  # explicit "eis_schema_version": 1, ppb fields

# name -> (scale, alpha_key, beta_key, fpr_key, tpr_key). eis.v0.json has no
# eis_schema_version field at all (never edited by this change -- CLAUDE.md
# 13's six-config-hash discipline treats every historical verdict's
# roc_config_hash as pointing at a specific, unmodified file; adding a
# field to that file would be an in-place mutation of the very artifact
# this rule exists to protect); the "bp" format's alpha_bp key is what
# implicitly marks a config as v0. "ppb" configs (eis.v1 and later) must
# declare eis_schema_version explicitly rather than being inferred, since
# there is more than one such format once eis.v1 exists.
_RATE_FORMATS = {
    "bp": (BP_SCALE, "alpha_bp", "beta_bp", "fpr_bp", "tpr_bp"),
    "ppb": (PPB_SCALE, "alpha_ppb", "beta_ppb", "fpr_ppb", "tpr_ppb"),
}

_FORMAT_TO_SCHEMA_VERSION = {
    "bp": EIS_SCHEMA_VERSION_V0,
    "ppb": EIS_SCHEMA_VERSION_V1,
}

# CLAUDE.md §20's Tail-Floor Rule stable-label convention: whether a
# claim's threshold at a given swept budget is a genuine point estimate
# ("stable") or a conservative floor ("tail_floor"), or not yet derived at
# all ("pending" -- the only legal value pre-Phase-9, since assigning
# "stable"/"tail_floor" IS the Phase-9 derivation this repo's other gates
# forbid doing early). This is a CONFIG-side field (part of the object
# roc_config_hash() hashes) -- never a wire/signed field: §8's frozen
# Statement/Verdict schemas are untouched, and nothing in T4 admission or
# verdict issuance (trust_kernel/schema.py) reads it. Required only for
# non-"bp" formats (eis.v1 and later): eis.v0.json predates this concept
# entirely and must stay byte-identical, so v0-shaped configs are never
# required (or permitted) to carry it.
RESOLUTION_STATUS_VALUES = {"pending", "stable", "tail_floor"}
SWEPT_BUDGET_LABELS = ("0.1%", "1%", "5%")  # CLAUDE.md §20's three illustrative budgets


def detect_rate_format(raw: dict) -> str:
    """Detect which of _RATE_FORMATS an eis config uses, from which
    top-level alpha_* field is present -- fail-closed: a config defining
    both (or neither) alpha field is ambiguous and rejected outright
    rather than guessed at, since silently picking one is exactly the kind
    of silent reinterpretation CLAUDE.md 8 forbids for config edits.
    A ppb-format config must additionally declare eis_schema_version
    explicitly and it must agree with the format actually used (the field
    names must not disagree with the declared version) -- this is the
    'verdict's config-version and the loaded config-version disagree'
    fail-closed check, done at load time before any threshold is derived
    from the (possibly mismatched) config.
    """
    present = [name for name, (_, alpha_key, *_rest) in _RATE_FORMATS.items() if alpha_key in raw]
    if len(present) != 1:
        alpha_keys = sorted(v[1] for v in _RATE_FORMATS.values())
        raise ValueError(
            f"eis config must define exactly one of {alpha_keys} at top level; "
            f"found {sorted(present)}"
        )
    fmt = present[0]
    declared_version = raw.get("eis_schema_version", EIS_SCHEMA_VERSION_V0)
    expected_version = _FORMAT_TO_SCHEMA_VERSION[fmt]
    if declared_version != expected_version:
        raise ValueError(
            f"eis config declares eis_schema_version={declared_version!r} but its "
            f"fields match the version-{expected_version} ('{fmt}') format; "
            "declared version and field format must agree"
        )
    return fmt


def score(polarity: int, raw_measurement: int) -> int:
    """s = pol × raw_measurement (§4). Fixed-point int; lower = more
    attack-like, uniformly, once oriented by polarity."""
    if polarity not in (1, -1):
        raise ValueError("polarity must be +1 or -1")
    return polarity * raw_measurement


def validate_roc_points(roc_points, *, scale: int = BP_SCALE,
                         fpr_key: str = "fpr_bp", tpr_key: str = "tpr_bp"):
    """Fail-closed structural validation (§11): strictly increasing
    thresholds, non-decreasing FPR/TPR, rates within [0, scale]. Raises
    on any violation -- an invalid ROC must never acquire an identity a
    verdict could point at (roc_config_hash() validates before hashing).

    scale/fpr_key/tpr_key default to the eis.v0 basis-point format so every
    existing call site (which passes only roc_points) is byte-for-byte
    unaffected; eis.v1 (ppb) callers pass scale=PPB_SCALE,
    fpr_key="fpr_ppb", tpr_key="tpr_ppb" explicitly via
    validate_eis_config()'s format detection."""
    if not roc_points:
        raise ValueError("ROC curve must have at least one point")
    prev = None
    for p in roc_points:
        for key in ("threshold", fpr_key, tpr_key):
            if key not in p:
                raise ValueError(f"ROC point missing '{key}'")
        if not (0 <= p[fpr_key] <= scale) or not (0 <= p[tpr_key] <= scale):
            raise ValueError(f"{fpr_key}/{tpr_key} must be in [0, {scale}]")
        if prev is not None:
            if p["threshold"] <= prev["threshold"]:
                raise ValueError("ROC thresholds must be strictly increasing")
            if p[fpr_key] < prev[fpr_key] or p[tpr_key] < prev[tpr_key]:
                raise ValueError("FPR/TPR must be non-decreasing in threshold")
        prev = p


def derive_thresholds(roc_points, alpha_bp: int, beta_bp: int, *,
                       scale: int = BP_SCALE,
                       fpr_key: str = "fpr_bp", tpr_key: str = "tpr_bp"):
    """θ1 = max{t : FPR(t) ≤ α}; θ2 = min{t : TPR(t) ≥ 1−β}; band_cap = HIGH
    iff θ2 exists, else MED (§4). Never hand-assigned (§11 hard rule) --
    always derived from roc_points, the same formula regardless of detector
    quality: 'a detector never attaining TPR ≥ 1−β has no θ2 ⇒ band_cap =
    MED ⇒ structurally cannot license HIGH... same formula, no special
    case.'

    The alpha/beta and fpr/tpr parameters are always in the SAME scale
    (bp by default, matching eis.v0; ppb when scale=PPB_SCALE is passed for
    eis.v1) -- this is a representation widening only, not a new formula."""
    validate_roc_points(roc_points, scale=scale, fpr_key=fpr_key, tpr_key=tpr_key)
    if not (0 <= alpha_bp <= scale) or not (0 <= beta_bp <= scale):
        raise ValueError(f"alpha/beta must be in [0, {scale}]")

    theta1 = None
    for p in roc_points:
        if p[fpr_key] <= alpha_bp:
            theta1 = p["threshold"]
    if theta1 is None:
        raise ValueError(
            "no threshold satisfies FPR(t) <= alpha; invalid ROC/alpha pairing"
        )

    tpr_floor = scale - beta_bp
    theta2 = None
    for p in roc_points:
        if p[tpr_key] >= tpr_floor:
            theta2 = p["threshold"]
            break

    band_cap = TrustLevel.HIGH if theta2 is not None else TrustLevel.MED
    return theta1, theta2, band_cap


def band(s: int, theta1: int, theta2, band_cap: TrustLevel) -> TrustLevel:
    """band(s) = LOW if s<θ1; MED if s<θ2; else HIGH, then ⊓ band_cap (§4).
    θ2 may be None (no threshold attains TPR ≥ 1−β, so band_cap is already
    MED and HIGH is unreachable regardless); s >= θ1 then resolves to MED
    directly -- the meet with band_cap produces the same result either way,
    this just avoids comparing against a nonexistent θ2."""
    if s < theta1:
        raw = TrustLevel.LOW
    elif theta2 is not None and s < theta2:
        raw = TrustLevel.MED
    elif theta2 is not None:
        raw = TrustLevel.HIGH
    else:
        raw = TrustLevel.MED
    return meet(raw, band_cap)


def reduce_dimension(claim_bands) -> TrustLevel:
    """Intra-dimension reduction: meet over all registered claims for this
    dimension (§4). A missing claim (None) contributes LOW to the meet --
    'a missing record is evidence of a problem, not absence of evidence.'
    Detector disagreement is not resolved; meet takes the worst."""
    if not claim_bands:
        raise ValueError("a dimension must have at least one registered claim type")
    resolved = [TrustLevel.LOW if b is None else b for b in claim_bands]
    return meet(*resolved)


def load_eis_config(path):
    """Fail-closed config load (§11): no partial loads: validate every
    claim's ROC and every claim's derived thresholds before returning
    anything. Returns the raw config dict plus a 'derived' map of
    claim_type -> (theta1, theta2, band_cap).

    Format (bp/eis.v0 vs ppb/eis.v1) is detected from the config's own
    fields (detect_rate_format(), inside validate_eis_config) -- the
    caller does not need to know or declare which format a given path
    holds; the loaded config declares it, and disagreement between a
    declared eis_schema_version and its actual field format fails closed
    before any threshold is derived."""
    with open(path) as f:
        raw = json.load(f)
    validate_eis_config(raw)
    scale, alpha_key, beta_key, fpr_key, tpr_key = _RATE_FORMATS[detect_rate_format(raw)]

    derived = {}
    for claim_type, claim in raw["claims"].items():
        derived[claim_type] = derive_thresholds(
            claim["roc"], raw[alpha_key], raw[beta_key],
            scale=scale, fpr_key=fpr_key, tpr_key=tpr_key,
        )
    return raw, derived


def validate_eis_config(raw):
    """§13: 'validate_eis_config() refuses status: measured while any
    derivation is placeholder -- the flag cannot be flipped without
    replacing the numbers.'

    detect_rate_format() is called first and is itself fail-closed (exactly
    one rate format's alpha field must be present, and a declared
    eis_schema_version must agree with the format actually used) -- for an
    eis.v0-shaped config (no eis_schema_version field, alpha_bp present)
    this reduces to exactly the checks this function performed before eis.v1
    existed, with the same scale (BP_SCALE) and same field names
    (fpr_bp/tpr_bp), so eis.v0.json's validation behaviour is unchanged.

    Non-"bp" formats (eis.v1 and later) additionally require each claim to
    carry a resolution_status entry (CLAUDE.md §20's Tail-Floor Rule
    stable-label convention) -- fail-closed on missing, extra, or invalid
    budget keys/values, the same discipline as every other field here, so
    this field is validated (and therefore present in the canonical bytes
    roc_config_hash() hashes) from the moment eis.v1 exists, not bolted on
    unvalidated later."""
    if raw.get("calibration_status") not in ("provisional", "measured"):
        raise ValueError("calibration_status must be 'provisional' or 'measured'")
    if "claims" not in raw or not raw["claims"]:
        raise ValueError("eis config must register at least one claim type")
    fmt = detect_rate_format(raw)
    scale, alpha_key, beta_key, fpr_key, tpr_key = _RATE_FORMATS[fmt]
    requires_resolution_status = fmt != "bp"
    for claim_type, claim in raw["claims"].items():
        for key in ("dimension", "polarity", "roc"):
            if key not in claim:
                raise ValueError(f"claim '{claim_type}' missing '{key}'")
        if claim["dimension"] not in DIMENSIONS:
            raise ValueError(f"claim '{claim_type}' has unknown dimension {claim['dimension']!r}")
        validate_roc_points(claim["roc"], scale=scale, fpr_key=fpr_key, tpr_key=tpr_key)
        if raw["calibration_status"] == "measured" and claim.get("placeholder"):
            raise ValueError(
                f"calibration_status is 'measured' but claim '{claim_type}' "
                "is still a placeholder derivation"
            )
        if requires_resolution_status:
            _validate_resolution_status(claim_type, claim)


def _validate_resolution_status(claim_type: str, claim: dict):
    if "resolution_status" not in claim:
        raise ValueError(f"claim '{claim_type}' missing 'resolution_status'")
    rs = claim["resolution_status"]
    if not isinstance(rs, dict):
        raise ValueError(f"claim '{claim_type}' resolution_status must be an object keyed by budget")
    if set(rs.keys()) != set(SWEPT_BUDGET_LABELS):
        raise ValueError(
            f"claim '{claim_type}' resolution_status must have exactly the keys "
            f"{SWEPT_BUDGET_LABELS}; found {sorted(rs.keys())}"
        )
    for budget, value in rs.items():
        if value not in RESOLUTION_STATUS_VALUES:
            raise ValueError(
                f"claim '{claim_type}' resolution_status[{budget!r}] = {value!r} "
                f"is not one of {sorted(RESOLUTION_STATUS_VALUES)}"
            )


def representable_at_scale(rate: float, scale: int) -> bool:
    """Whether `rate` (a probability/proportion in [0,1]) has a nonzero
    fixed-point representation at `scale` (BP_SCALE or PPB_SCALE): the
    smallest nonzero representable rate at a given scale is 1/scale, same
    principle as event_model.availability.representable_at_current_granularity
    (which is specific to BP_SCALE), generalised so eis.v1 (PPB_SCALE) can
    be checked with the same formula rather than a second hardcoded copy."""
    return rate * scale >= 1.0


def representability_margin(rate: float, scale: int) -> float:
    """How many multiples of the smallest nonzero representable rate
    (1/scale) `rate` clears -- e.g. 130.0 means `rate` is 130x the
    representability floor at this scale. Purely diagnostic: never fed
    into any signed or hashed value."""
    return rate * scale


def roc_config_hash(path) -> str:
    """Fail-closed: validates before hashing (§11) -- an invalid config
    must never acquire an identity a verdict could point at."""
    with open(path) as f:
        raw = json.load(f)
    validate_eis_config(raw)
    canonical = json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()
