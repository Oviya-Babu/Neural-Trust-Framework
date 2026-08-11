"""Observer (CLAUDE.md §2, P2): reads actuator feedback independently and
is the sole origin of ActuationFidelity evidence. Structurally separate
from the Enforcement Plane -- this module imports nothing from
enforcement/, and enforcement/ imports nothing from here or from
evidence_plane/ (verified by experiments/phase6_observer.py's structural
check: a static scan for forbidden imports/calls/strings in
enforcement/*.py, plus a dynamic run that spies on
trust_kernel.schema.sign_statement/build_statement across a full
enforcement cycle and confirms they are never called).

The Observer signs with its own key, never the enforcer's -- which is
actually a stronger claim than key separation: the enforcer holds no
signing key of any kind. enforcement/capability.py's ActuatorCapability is
an opaque write-authority token, not a keypair; enforcement/clamp.py only
ever *verifies* a kernel signature (schema.verify_verdict_signature), it
never signs. No secret key material of any kind is ever constructed,
imported, or reachable from enforcement/'s module namespaces.

There is no real actuator in this software-only prototype (CLAUDE.md §1),
so "reading actuator feedback" is modelled as the caller supplying a
`commanded` envelope (what the enforcer wrote) and an `observed` envelope
(what the actuator reports having realised) -- in a real deployment the
latter comes from encoder/motor-controller telemetry, structurally
independent of the enforcer's own bookkeeping. This module never reads
enforcement/'s internal state to construct either value.

Honest scope (§3, Position A): under Position A, ActuationFidelity evidence
is forgeable in software like every other statement -- the Observer's
independence is an honest-evidence property. It prevents the enforcer from
self-attesting about its own behaviour under honest operation and under an
A_data that has not compromised the Observer process itself; it is not an
unconditional guarantee, and it is not the basis of T5 (§5: T5 rests
entirely on enforcement-plane termination, not on any sensor's honesty).
"""

from trust_kernel import schema

# Matches config/key_registry.json + config/claim_registry.json (Phase 3):
# the ActuationFidelity claim type and its source_id were already wired as
# their own distinct identity, separate from the other 7 sensors, the
# kernel, and (structurally) the enforcer. Kept as-is rather than renamed
# -- §18: redesign only when implementation demonstrates necessity, and a
# rename here is pure churn across three already-mutation-tested configs.
AF_CLAIM_TYPE = "actuationfidelity.provisional_v0"
AF_SOURCE_ID = "actuationfidelity_sensor_v0"
AF_BOUNDARY = "TB2"

FIDELITY_FLOOR = -100
FIDELITY_CEIL = 100


def measure_actuation_fidelity(commanded: dict, observed: dict) -> int:
    """Runtime measurement (§2 Evidence Producer contract).

    runtime component: Observer process, reading actuator feedback.
    runtime measurement: componentwise absolute discrepancy between the
        envelope the enforcer commanded and the envelope the actuator
        reports having actually realised.
    mathematical calculation: raw = max(FIDELITY_FLOOR, FIDELITY_CEIL -
        (|Δmax_speed| + |Δmax_acceleration|)). The upper bound needs no
        explicit clamp: the discrepancy term is a sum of absolute values,
        always >= 0, so FIDELITY_CEIL - discrepancy can never exceed
        FIDELITY_CEIL -- an explicit min() here would be dead code, not a
        second safeguard.
    measurement units: dimensionless fidelity score, fixed-point int.
    claim type: actuationfidelity.provisional_v0.
    trust dimension: ActuationFidelity.
    timestamp / provenance: supplied by the caller as claimed_at/window_id
        when building the statement (this function is pure).
    expected polarity: +1 (higher raw = closer command/observed match =
        more trustworthy; s = pol × raw per §4).
    window binding: one measurement per window -- the window whose
        commanded envelope is being checked against feedback.
    smoothing behaviour: none. A single window's discrepancy is itself the
        signal; averaging across windows would hide a one-window mismatch.
    attacks influencing this measurement: actuator manipulation (§3);
        TB5 (enforcer<->actuator) command tampering; a compromised or
        miscalibrated physical actuator; observer disagreement (§3).

    No confidence is computed here (§2): this is a raw measurement only.
    """
    discrepancy = (
        abs(observed["max_speed"] - commanded["max_speed"])
        + abs(observed["max_acceleration"] - commanded["max_acceleration"])
    )
    return max(FIDELITY_FLOOR, FIDELITY_CEIL - discrepancy)


class Observer:
    """Holds the Observer's own identity and signing key. Constructed with
    only what a real out-of-band-provisioned sensor process would hold:
    its own key_id/source_id and its own secret key -- never anything
    belonging to the enforcer, and never constructed from or passed to
    anything in enforcement/."""

    def __init__(self, secret_key: bytes, key_id: str = AF_SOURCE_ID, source_id: str = AF_SOURCE_ID):
        self._secret_key = secret_key
        self.key_id = key_id
        self.source_id = source_id

    def build_statement(self, *, commanded: dict, observed: dict, window_id: int, claimed_at: int) -> dict:
        raw = measure_actuation_fidelity(commanded, observed)
        fields = schema.build_statement(
            key_id=self.key_id, source_id=self.source_id, boundary=AF_BOUNDARY,
            claim_type=AF_CLAIM_TYPE, raw_measurement=raw,
            window_id=window_id, claimed_at=claimed_at,
        )
        return schema.sign_statement(self._secret_key, fields)

    def observe_and_append(self, log, *, commanded: dict, observed: dict, window_id: int, claimed_at: int) -> dict:
        """Builds the signed AF statement and appends it to the Evidence
        Plane. `log` is any object exposing .append(statement) -- normally
        an evidence_plane.log.EvidenceLog. The Observer never reads or
        writes anything else in the Evidence Plane; it only appends its
        own statements, per the sensor contract (§10: sensors append
        only)."""
        statement = self.build_statement(
            commanded=commanded, observed=observed, window_id=window_id, claimed_at=claimed_at,
        )
        log.append(statement)
        return statement
