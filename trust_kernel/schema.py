"""Wire schema, T4 statement admission, and verdict issuance (CLAUDE.md §8,
§9, §10). Statement and Verdict objects per the FROZEN §8 schema; signing
over canon.encode_tagged(domain, fields) so a statement's signed bytes can
never be replayed as a verdict (§9: "sign over encode([domain_tag,
object])... within the restricted domain there is nothing to disagree
about" -- the tagged pair is injective by construction).

Serves T4 (verdict authenticity + freshness): admit_statement() implements
the exact fixed verification order of §10 -- any failure at any step
routes to "that dimension reads LOW", never "record absent". T4 is
honest-evidence-conditional under Position A (§3): an adversary who owns
the host forges kernel_sig and controls clocks, so T4 is not the basis of
the central claim; the central claim is T5 (§5).

No curve arithmetic here (delegates to trust_kernel.sign); no I/O in the
admission/issuance logic itself beyond what the caller passes in --
arrival_time, window_open_time, issued_at are all explicit parameters, not
live clock reads, so this module stays deterministic and testable.
"""

import hashlib
import json
from dataclasses import dataclass
from typing import Optional

from trust_kernel import canon, sign
from trust_kernel.bands import DIMENSIONS, TrustLevel
from trust_kernel.policy import Verdict

SCHEMA_VERSION = 1

DOMAIN_STATEMENT = "statement"
DOMAIN_VERDICT = "verdict"

# §7 (FROZEN)
WINDOW_PERIOD_MS = 100
EVIDENCE_DEADLINE_MS = 60          # Delta(w) = t_w + 60ms
KERNEL_BUDGET_MS = 5
ISSUED_AT_OFFSET_MS = 62
EXPIRES_AT_OFFSET_MS = 170

STATEMENT_REQUIRED_FIELDS = {
    "schema_version", "key_id", "source_id", "boundary", "claim_type",
    "raw_measurement", "window_id", "claimed_at",
}
STATEMENT_OPTIONAL_FIELDS = {"window_hash"}

VERDICT_FIELDS = {
    "schema_version", "window_id", "evidence_root", "effective_dims", "verdict",
    "policy_version", "crit_table_hash", "ctpr_config_hash", "roc_config_hash",
    "claim_registry_hash", "key_registry_hash", "calibration_status",
    "issued_at", "expires_at",
}


class SchemaError(ValueError):
    pass


# --------------------------------------------------------------------------
# Registries (key_registry.json, claim_registry.json) -- fail-closed load,
# validate before hashing, same pattern as Phase 2's config loaders.
# --------------------------------------------------------------------------

def load_key_registry(path):
    with open(path) as f:
        raw = json.load(f)
    validate_key_registry(raw)
    return raw


def validate_key_registry(raw):
    if "keys" not in raw or not raw["keys"]:
        raise SchemaError("key registry must contain at least one key")
    for key_id, entry in raw["keys"].items():
        for field in ("public_key", "source_id", "boundary", "authorized_claim_types"):
            if field not in entry:
                raise SchemaError(f"key registry entry '{key_id}' missing '{field}'")
        pk_bytes = bytes.fromhex(entry["public_key"])
        sign.validate_public_key(pk_bytes)  # fail-closed: reject bad keys at load time


def key_registry_hash(path) -> str:
    with open(path) as f:
        raw = json.load(f)
    validate_key_registry(raw)
    canonical = json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


def load_claim_registry(path):
    with open(path) as f:
        raw = json.load(f)
    validate_claim_registry(raw)
    return raw


CLAIM_MEASUREMENT_SOURCES = {"REAL", "EMULATED_PROTOCOL", "SIMULATED"}
CLAIM_HOST_INDEPENDENCE_LEVELS = {"SAME_HOST", "INDEPENDENT_SUBSYSTEM"}
CLAIM_FORGEABLE_UNDER_A_CODE_VALUES = {"TRUE", "FALSE"}

CLAIM_PROVENANCE_FIELDS = (
    "dimension", "boundary", "source_id", "epoch_derived",
    "measurement_source", "host_independence", "forgeable_under_A_code", "provenance_note",
)


def validate_claim_registry(raw):
    """Fail-closed per CLAUDE.md §8/§13: a claim missing any provenance
    field -- including the three-field honesty tuple added for Phase 8
    (measurement_source, host_independence, forgeable_under_A_code) and its
    mandatory provenance_note -- must not load. This is what lets the
    registry state the honest-evidence case for T5 in its own contents
    (§3): every V1 claim declares forgeable_under_A_code TRUE, so nothing
    in the registry can be misread as a claim of adversarial soundness."""
    if "claims" not in raw or not raw["claims"]:
        raise SchemaError("claim registry must contain at least one claim type")
    for claim_type, entry in raw["claims"].items():
        for field in CLAIM_PROVENANCE_FIELDS:
            if field not in entry:
                raise SchemaError(f"claim registry entry '{claim_type}' missing '{field}'")
        if entry["dimension"] not in DIMENSIONS:
            raise SchemaError(f"claim '{claim_type}' has unknown dimension {entry['dimension']!r}")
        if entry["measurement_source"] not in CLAIM_MEASUREMENT_SOURCES:
            raise SchemaError(
                f"claim '{claim_type}' has invalid measurement_source {entry['measurement_source']!r}, "
                f"must be one of {sorted(CLAIM_MEASUREMENT_SOURCES)}"
            )
        if entry["host_independence"] not in CLAIM_HOST_INDEPENDENCE_LEVELS:
            raise SchemaError(
                f"claim '{claim_type}' has invalid host_independence {entry['host_independence']!r}, "
                f"must be one of {sorted(CLAIM_HOST_INDEPENDENCE_LEVELS)}"
            )
        if entry["forgeable_under_A_code"] not in CLAIM_FORGEABLE_UNDER_A_CODE_VALUES:
            raise SchemaError(
                f"claim '{claim_type}' has invalid forgeable_under_A_code {entry['forgeable_under_A_code']!r}, "
                f"must be one of {sorted(CLAIM_FORGEABLE_UNDER_A_CODE_VALUES)}"
            )
        note = entry["provenance_note"]
        if not isinstance(note, str) or not note.strip():
            raise SchemaError(f"claim '{claim_type}' provenance_note must be a non-empty string")
        if entry["measurement_source"] == "EMULATED_PROTOCOL" and "path" not in note:
            raise SchemaError(
                f"claim '{claim_type}' is EMULATED_PROTOCOL; provenance_note must state on-path or "
                f"off-path (§ Step 1: 'must state on-path vs off-path for emulated protocols')"
            )


def claim_registry_hash(path) -> str:
    with open(path) as f:
        raw = json.load(f)
    validate_claim_registry(raw)
    canonical = json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


# --------------------------------------------------------------------------
# Statement: build, sign, verify.
# --------------------------------------------------------------------------

def build_statement(*, key_id, source_id, boundary, claim_type, raw_measurement,
                     window_id, claimed_at, window_hash=None):
    fields = {
        "schema_version": SCHEMA_VERSION,
        "key_id": key_id,
        "source_id": source_id,
        "boundary": boundary,
        "claim_type": claim_type,
        "raw_measurement": raw_measurement,
        "window_id": window_id,
        "claimed_at": claimed_at,
    }
    if window_hash is not None:
        fields["window_hash"] = window_hash
    return fields


def _statement_payload(fields: dict) -> bytes:
    unsigned = {k: v for k, v in fields.items() if k != "sig"}
    return canon.encode_tagged(DOMAIN_STATEMENT, unsigned)


def sign_statement(secret_key: bytes, fields: dict) -> dict:
    payload = _statement_payload(fields)
    sig = sign.sign(secret_key, payload)
    return {**fields, "sig": sig}


def verify_statement_signature(public_key: bytes, statement: dict) -> bool:
    if "sig" not in statement:
        return False
    try:
        payload = _statement_payload(statement)
    except canon.CanonError:
        return False
    return sign.verify(public_key, payload, statement["sig"])


def statement_hash(statement: dict) -> bytes:
    """Content address for evidence_root (§8): hash of the full signed
    statement (including sig), so dedupe is over exact wire bytes."""
    return hashlib.sha256(canon.encode(statement)).digest()


# --------------------------------------------------------------------------
# T4 statement admission (§10, fixed verification order).
# --------------------------------------------------------------------------

ADMISSION_STEPS = ("signature", "schema", "authorization", "window_id", "arrival")


@dataclass(frozen=True)
class AdmissionResult:
    accepted: bool
    failed_step: Optional[str]
    reason: Optional[str]


def _validate_statement_shape(statement: dict, claim_registry: dict) -> Optional[str]:
    fields = set(statement.keys()) - {"sig"}
    if not STATEMENT_REQUIRED_FIELDS.issubset(fields):
        return f"missing required field(s): {sorted(STATEMENT_REQUIRED_FIELDS - fields)}"
    if not fields.issubset(STATEMENT_REQUIRED_FIELDS | STATEMENT_OPTIONAL_FIELDS):
        return f"unknown field(s): {sorted(fields - STATEMENT_REQUIRED_FIELDS - STATEMENT_OPTIONAL_FIELDS)}"
    if statement.get("schema_version") != SCHEMA_VERSION:
        return f"unsupported schema_version: {statement.get('schema_version')!r}"

    claim_type = statement.get("claim_type")
    claim_entry = claim_registry.get("claims", {}).get(claim_type)
    if claim_entry is not None:
        has_window_hash = "window_hash" in fields
        if claim_entry["epoch_derived"] and not has_window_hash:
            return f"claim_type {claim_type!r} is epoch-derived and requires window_hash"
        if not claim_entry["epoch_derived"] and has_window_hash:
            return f"claim_type {claim_type!r} is not epoch-derived; window_hash is forbidden"
    return None


def admit_statement(statement: dict, *, key_registry: dict, claim_registry: dict,
                     current_window_id: int, window_open_time_ms: int, arrival_time_ms: int,
                     evidence_deadline_ms: int = EVIDENCE_DEADLINE_MS) -> AdmissionResult:
    """Fixed order (§10): sig -> schema/version -> source authorised for
    boundary -> window_id matches round -> arrival before Delta(w) -> value
    enters lattice. Any failure returns accepted=False at that exact step;
    it never falls through to a later step."""

    # 1. signature
    key_id = statement.get("key_id")
    key_entry = key_registry.get("keys", {}).get(key_id) if isinstance(key_id, str) else None
    if key_entry is None:
        return AdmissionResult(False, "signature", f"unknown key_id: {key_id!r}")
    public_key = bytes.fromhex(key_entry["public_key"])
    if not verify_statement_signature(public_key, statement):
        return AdmissionResult(False, "signature", "signature verification failed")

    # 2. schema / version
    shape_error = _validate_statement_shape(statement, claim_registry)
    if shape_error is not None:
        return AdmissionResult(False, "schema", shape_error)

    # 3. source authorised for boundary (+ claim type authorisation)
    if statement["source_id"] != key_entry["source_id"]:
        return AdmissionResult(False, "authorization",
                                f"key_id {key_id!r} is not registered for source_id {statement['source_id']!r}")
    if statement["boundary"] != key_entry["boundary"]:
        return AdmissionResult(False, "authorization",
                                f"key_id {key_id!r} is not authorised at boundary {statement['boundary']!r}")
    if statement["claim_type"] not in key_entry["authorized_claim_types"]:
        return AdmissionResult(False, "authorization",
                                f"key_id {key_id!r} is not authorised for claim_type {statement['claim_type']!r}")
    claim_entry = claim_registry.get("claims", {}).get(statement["claim_type"])
    if claim_entry is None:
        return AdmissionResult(False, "authorization",
                                f"claim_type {statement['claim_type']!r} is not registered")

    # 4. window_id matches round
    if statement["window_id"] != current_window_id:
        return AdmissionResult(False, "window_id",
                                f"statement window_id {statement['window_id']} != current round {current_window_id}")

    # 5. arrival before Delta(w)
    deadline = window_open_time_ms + evidence_deadline_ms
    if arrival_time_ms >= deadline:
        return AdmissionResult(False, "arrival",
                                f"arrived at {arrival_time_ms}ms, deadline was {deadline}ms")

    # 6. value enters the lattice
    return AdmissionResult(True, None, None)


# --------------------------------------------------------------------------
# Verdict: build, sign, verify.
# --------------------------------------------------------------------------

def build_evidence_root(admitted_statements) -> bytes:
    """§8: dedupe by statement hash, sort lexicographically, encode as
    canonical list, then hash that list -- a set has no order, two honest
    verifiers must not disagree."""
    hashes = sorted(set(statement_hash(s) for s in admitted_statements))
    return hashlib.sha256(canon.encode(hashes)).digest()


def build_verdict(*, window_id, evidence_root: bytes, effective_dims: dict,
                   verdict: Verdict, policy_version: str,
                   crit_table_hash: str, ctpr_config_hash: str, roc_config_hash: str,
                   claim_registry_hash: str, key_registry_hash: str,
                   calibration_status: str, issued_at: int, expires_at: int) -> dict:
    missing = set(DIMENSIONS) - set(effective_dims)
    if missing:
        raise SchemaError(f"verdict requires all {len(DIMENSIONS)} dimensions; missing {sorted(missing)}")
    return {
        "schema_version": SCHEMA_VERSION,
        "window_id": window_id,
        "evidence_root": evidence_root,
        "effective_dims": {d: effective_dims[d].name for d in DIMENSIONS},
        "verdict": verdict.name,
        "policy_version": policy_version,
        "crit_table_hash": crit_table_hash,
        "ctpr_config_hash": ctpr_config_hash,
        "roc_config_hash": roc_config_hash,
        "claim_registry_hash": claim_registry_hash,
        "key_registry_hash": key_registry_hash,
        "calibration_status": calibration_status,
        "issued_at": issued_at,
        "expires_at": expires_at,
    }


def _verdict_payload(fields: dict) -> bytes:
    unsigned = {k: v for k, v in fields.items() if k != "kernel_sig"}
    return canon.encode_tagged(DOMAIN_VERDICT, unsigned)


def sign_verdict(kernel_secret_key: bytes, fields: dict) -> dict:
    payload = _verdict_payload(fields)
    kernel_sig = sign.sign(kernel_secret_key, payload)
    return {**fields, "kernel_sig": kernel_sig}


def verify_verdict_signature(kernel_public_key: bytes, verdict_obj: dict) -> bool:
    if "kernel_sig" not in verdict_obj:
        return False
    try:
        payload = _verdict_payload(verdict_obj)
    except canon.CanonError:
        return False
    return sign.verify(kernel_public_key, payload, verdict_obj["kernel_sig"])
