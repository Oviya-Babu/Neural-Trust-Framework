"""Model evidence producer (CLAUDE.md §2, §9, §10, Phase 8 Step 2).

Per config/claim_registry.json's model.provisional_v0 entry:
measurement_source=EMULATED_PROTOCOL, host_independence=SAME_HOST,
forgeable_under_A_code=TRUE. The cryptography here is real (real Ed25519
signature + hash verification, §9 rule set, C-backed libsodium) -- it is
EMULATED_PROTOCOL rather than REAL only because the verifier runs on the
same host as the artifact it checks, so it is a protocol demonstration
rather than an independent hardware root of trust.

Two distinct keys are involved, deliberately not conflated:
  1. the ARTIFACT signing key (held by whoever trains/publishes the
     classifier -- a training-pipeline identity) signs the trained
     model's weight bytes once, at publish time (sign_artifact below).
  2. the SENSOR's own statement-signing key (ModelSensor's secret_key,
     provisioned like every other sensor per §6/§9) signs the resulting
     evidence STATEMENT announcing what the integrity check found.
Conflating them would mean the entity attesting "this model verifies" and
the entity that produced the model are the same key -- which is exactly
the self-attestation P2 forbids for a sensor, even though here it is two
different keys playing two different roles rather than one sensor
attesting its own reliability.

Runtime component: a verifier run once per session at classifier-artifact
load time (not per window -- see ModelSensor.build_statement).
Runtime measurement: whether the loaded classifier artifact's bytes match
a pinned SHA-256 hash AND carry a valid Ed25519 signature over those exact
bytes, both checked against a signing record produced once at publish time.
Mathematical calculation: raw_measurement = MODEL_TRUST_CEIL if
(hash_matches AND signature_valid) else MODEL_TRUST_FLOOR -- a two-factor
AND, deliberately not a partial/graded score: a hash match with a broken
signature (or vice versa) is exactly as untrustworthy as failing both,
because either failure alone means the bytes actually running are not
provably the bytes that were trained and published.
measurement units: dimensionless trust extreme, fixed-point int in
{MODEL_TRUST_FLOOR, MODEL_TRUST_CEIL}.
claim type: model.provisional_v0. trust dimension: Model.
timestamp/provenance: caller-supplied window_id/claimed_at.
expected polarity: +1 (higher raw = more trustworthy, per config/eis.v0.json).
window binding: checked once per session/deployment (the artifact does
not change mid-session); the resulting boolean result is re-announced
each window via build_statement, per the sensor contract's "exactly one
statement per registered claim type per window" (§10) -- re-verifying the
full artifact every 100ms window is unnecessary work, not a correctness
requirement, since the artifact identity does not change between windows.
smoothing: none -- a boolean-derived measurement has nothing to smooth.
attacks influencing this measurement: model replacement (§3) -- substitute
a different trained model: hash mismatch, caught. Bit-flipped weights
(post-training tamper): hash mismatch, caught. Stripped signature: no sig
in the signing record or on the wire means verify_artifact fails closed
(absent is never treated as "unknown, pass"). Unsigned substitute (an
artifact with no corresponding signing record at all): rejected the same
way as a hash mismatch -- there is no pinned hash to match against.
Explicitly NOT caught: model poisoning during the training pipeline itself,
before this artifact was ever signed (CLAUDE.md's no-detector class,
documented in experiments/phase5_enforcement.py's ATTACK_CLASSES) -- this
producer verifies artifact integrity after signing, not training-time
provenance.

No confidence is computed here (§2): this is a raw measurement only.
"""

import hashlib

import numpy as np

from trust_kernel import schema, sign

MODEL_CLAIM_TYPE = "model.provisional_v0"
MODEL_SOURCE_ID = "model_sensor_v0"
MODEL_BOUNDARY = "TB2"

MODEL_TRUST_FLOOR = -100
MODEL_TRUST_CEIL = 100


def serialize_classifier_artifact(clf) -> bytes:
    """Deterministic byte serialization of the trained classifier's
    learned parameters -- exactly the numbers that determine predictions,
    not a pickle of the whole Python object (which would embed library/
    process version noise irrelevant to model *identity*)."""
    parts = [
        np.ascontiguousarray(clf.coef_, dtype=np.float64).tobytes(),
        np.ascontiguousarray(clf.intercept_, dtype=np.float64).tobytes(),
        np.ascontiguousarray(clf.classes_).tobytes(),
    ]
    return b"|".join(parts)


def artifact_hash(artifact_bytes: bytes) -> str:
    return hashlib.sha256(artifact_bytes).hexdigest()


def sign_artifact(secret_key: bytes, artifact_bytes: bytes) -> dict:
    """Publish-time operation (training-pipeline identity, §9 rule set):
    produces the signing record ModelSensor verifies against later."""
    return {
        "sha256": artifact_hash(artifact_bytes),
        "sig": sign.sign(secret_key, artifact_bytes).hex(),
    }


def verify_artifact(public_key: bytes, artifact_bytes: bytes, signing_record: dict) -> bool:
    """Both the hash and the signature must check out (see module
    docstring's two-factor-AND rationale). Never raises on a malformed or
    missing record -- a pure predicate over untrusted input, consistent
    with §10's fail-to-LOW discipline (sign.verify already follows this
    convention; this function extends it to the hash/record checks)."""
    if not isinstance(signing_record, dict):
        return False
    recorded_hash = signing_record.get("sha256")
    recorded_sig = signing_record.get("sig")
    if not isinstance(recorded_hash, str) or not isinstance(recorded_sig, str):
        return False
    if artifact_hash(artifact_bytes) != recorded_hash:
        return False
    try:
        sig_bytes = bytes.fromhex(recorded_sig)
    except ValueError:
        return False
    return sign.verify(public_key, artifact_bytes, sig_bytes)


def measure_model_integrity(artifact_bytes: bytes, artifact_public_key: bytes, signing_record: dict) -> int:
    ok = verify_artifact(artifact_public_key, artifact_bytes, signing_record)
    return MODEL_TRUST_CEIL if ok else MODEL_TRUST_FLOOR


class ModelSensor:
    def __init__(self, secret_key: bytes, key_id: str = MODEL_SOURCE_ID, source_id: str = MODEL_SOURCE_ID):
        self._secret_key = secret_key
        self.key_id = key_id
        self.source_id = source_id

    def build_statement(self, *, artifact_bytes: bytes, artifact_public_key: bytes,
                         signing_record: dict, window_id: int, claimed_at: int) -> dict:
        raw = measure_model_integrity(artifact_bytes, artifact_public_key, signing_record)
        fields = schema.build_statement(
            key_id=self.key_id, source_id=self.source_id, boundary=MODEL_BOUNDARY,
            claim_type=MODEL_CLAIM_TYPE, raw_measurement=raw,
            window_id=window_id, claimed_at=claimed_at,
        )
        return schema.sign_statement(self._secret_key, fields)
