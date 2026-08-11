"""Calibration evidence producer (CLAUDE.md §2, §4, §10, Phase 8 Step 2).

Grounded, REAL measurement source (config/claim_registry.json's
calibration.provisional_v0: measurement_source=REAL, host_independence=
SAME_HOST, forgeable_under_A_code=TRUE).

CLAUDE.md §4 is explicit about what this dimension is and is not: "LOW
Calibration = detected mapping collapse (electrode shift, session
mismatch, enrollment failure); the intent map is known invalid... It does
not defend against within-prior calibration poisoning, which keeps the
sensor at MED/HIGH by construction and remains uncovered-but-consequence-
bounded." This producer measures exactly the first thing (mapping
collapse / session mismatch), never the second -- it has no way to detect
a poisoned-but-plausible enrollment distribution, and must not be read as
doing so.

Runtime component: a per-trial drift check comparing session-E (test) to
the session-T (train) enrollment distribution -- BCIC IV 2a's two-session
structure is the calibration signal (§17a: "cross-session structure makes
replay detection non-trivial... this is why §17a picked a cross-session
dataset in the first place").

Runtime measurement: the tangent-space feature vector for one session-E
trial (bci_pipeline/features.py's fitted_features, transformed -- never
refit -- on session E), compared against the per-dimension mean/std of the
same feature space computed once from session-T (the enrollment session).

Mathematical calculation:
  z_i = (x_i - mu_train_i) / max(std_train_i, EPS)   for each feature dim i
  drift_stat = mean(z_i^2) over all feature dimensions
A per-dimension (diagonal) normalized squared z-score, not a full
Mahalanobis distance with the inverted feature covariance: the tangent
space here has ~253 dimensions from ~288 enrollment trials, so the full
sample covariance is not reliably invertible. drift_stat's dimension-
normalized form has a similar interpretation to Mahalanobis under a
diagonal-covariance assumption -- documented as an approximation, not
claimed as the exact statistic.
  raw_measurement = clip(round((DRIFT_REFERENCE - drift_stat) * DRIFT_SCALE),
                          RAW_FLOOR, RAW_CEIL)
drift_stat ~= 1.0 for an in-distribution trial under the diagonal-normal
approximation (each z_i^2 has expectation 1); DRIFT_REFERENCE = 1.0 centres
the score there, so raw_measurement is positive (trustworthy) for typical
session-E trials and falls as drift_stat grows.

measurement units: dimensionless fixed-point score, scale pinned by
DRIFT_SCALE below.
claim type: calibration.provisional_v0. trust dimension: Calibration.
timestamp/provenance: caller-supplied window_id/claimed_at.
expected polarity: +1 (higher raw = more trustworthy, per config/eis.v0.json).
window binding: one measurement per window/trial, against the fixed
session-T enrollment statistics (computed once per session, not per
window -- see compute_enrollment_stats).
smoothing behaviour: none per trial; the enrollment mean/std themselves
are a session-level statistic computed once, which is intentional (they
represent "the enrolled mapping", not a moving baseline).
attacks influencing this measurement: session mismatch / electrode shift /
enrollment failure (§4) -- the class this producer is designed to catch,
by construction: any of these push the session-E feature distribution away
from the session-T statistics, raising drift_stat. Explicitly NOT caught:
within-prior calibration poisoning (§4) -- an attacker who poisons the
*enrollment* distribution itself (session T) before this producer ever
runs has corrupted mu_train/std_train, and every subsequent session-E
trial will look "in-distribution" against the poisoned baseline. This is
the documented uncovered-but-consequence-bounded case, not a bug here.

No confidence is computed here (§2): this is a raw measurement only.
"""

import numpy as np

from trust_kernel import schema

CALIBRATION_CLAIM_TYPE = "calibration.provisional_v0"
CALIBRATION_SOURCE_ID = "calibration_sensor_v0"
CALIBRATION_BOUNDARY = "TB2"

DRIFT_REFERENCE = 1.0
DRIFT_SCALE = 40
RAW_FLOOR = -100
RAW_CEIL = 100
EPS = 1e-12


def compute_enrollment_stats(train_features: np.ndarray) -> dict:
    """Computed once per session from session-T (train) features. Returns
    {mean, std} over the feature dimension, both (n_features,) arrays."""
    mean = train_features.mean(axis=0)
    std = train_features.std(axis=0)
    return {"mean": mean, "std": std}


def measure_calibration_drift(feature_vector: np.ndarray, enrollment_stats: dict) -> int:
    z = (feature_vector - enrollment_stats["mean"]) / np.maximum(enrollment_stats["std"], EPS)
    drift_stat = float(np.mean(z ** 2))
    raw = (DRIFT_REFERENCE - drift_stat) * DRIFT_SCALE
    return int(np.clip(round(raw), RAW_FLOOR, RAW_CEIL))


class CalibrationSensor:
    def __init__(self, secret_key: bytes, key_id: str = CALIBRATION_SOURCE_ID,
                 source_id: str = CALIBRATION_SOURCE_ID):
        self._secret_key = secret_key
        self.key_id = key_id
        self.source_id = source_id

    def build_statement(self, *, feature_vector: np.ndarray, enrollment_stats: dict,
                         window_id: int, claimed_at: int) -> dict:
        raw = measure_calibration_drift(feature_vector, enrollment_stats)
        fields = schema.build_statement(
            key_id=self.key_id, source_id=self.source_id, boundary=CALIBRATION_BOUNDARY,
            claim_type=CALIBRATION_CLAIM_TYPE, raw_measurement=raw,
            window_id=window_id, claimed_at=claimed_at,
        )
        return schema.sign_statement(self._secret_key, fields)
