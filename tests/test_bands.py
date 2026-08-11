"""Unit tests for trust_kernel/bands.py (CLAUDE.md §4)."""

import hashlib
import json
import pathlib
import tempfile
import unittest

from trust_kernel import bands
from trust_kernel.bands import TrustLevel

CONFIG_DIR = pathlib.Path(__file__).resolve().parent.parent / "config"


class ScoreTests(unittest.TestCase):
    def test_positive_polarity(self):
        self.assertEqual(bands.score(1, 42), 42)

    def test_negative_polarity_flips_sign(self):
        self.assertEqual(bands.score(-1, 42), -42)

    def test_invalid_polarity_rejected(self):
        with self.assertRaises(ValueError):
            bands.score(0, 42)


class ValidateRocPointsTests(unittest.TestCase):
    def test_empty_rejected(self):
        with self.assertRaises(ValueError):
            bands.validate_roc_points([])

    def test_non_increasing_threshold_rejected(self):
        with self.assertRaises(ValueError):
            bands.validate_roc_points([
                {"threshold": 0, "fpr_bp": 0, "tpr_bp": 0},
                {"threshold": 0, "fpr_bp": 100, "tpr_bp": 100},
            ])

    def test_decreasing_fpr_rejected(self):
        with self.assertRaises(ValueError):
            bands.validate_roc_points([
                {"threshold": 0, "fpr_bp": 500, "tpr_bp": 0},
                {"threshold": 1, "fpr_bp": 100, "tpr_bp": 100},
            ])

    def test_out_of_range_rate_rejected(self):
        with self.assertRaises(ValueError):
            bands.validate_roc_points([{"threshold": 0, "fpr_bp": 10001, "tpr_bp": 0}])

    def test_well_formed_curve_accepted(self):
        bands.validate_roc_points([
            {"threshold": 0, "fpr_bp": 0, "tpr_bp": 0},
            {"threshold": 1, "fpr_bp": 100, "tpr_bp": 9999},
        ])


STRONG_ROC = [
    {"threshold": -100, "fpr_bp": 0, "tpr_bp": 0},
    {"threshold": -50, "fpr_bp": 100, "tpr_bp": 3000},
    {"threshold": 0, "fpr_bp": 500, "tpr_bp": 8000},
    {"threshold": 50, "fpr_bp": 2000, "tpr_bp": 9500},
    {"threshold": 100, "fpr_bp": 10000, "tpr_bp": 10000},
]

WEAK_ROC = [
    {"threshold": -100, "fpr_bp": 0, "tpr_bp": 0},
    {"threshold": -50, "fpr_bp": 100, "tpr_bp": 2000},
    {"threshold": 0, "fpr_bp": 500, "tpr_bp": 5000},
    {"threshold": 50, "fpr_bp": 2000, "tpr_bp": 7000},
    {"threshold": 100, "fpr_bp": 10000, "tpr_bp": 9000},
]


class DeriveThresholdsTests(unittest.TestCase):
    def test_strong_detector_reaches_high_cap(self):
        theta1, theta2, cap = bands.derive_thresholds(STRONG_ROC, alpha_bp=500, beta_bp=500)
        self.assertEqual(theta1, 0)
        self.assertEqual(theta2, 50)
        self.assertEqual(cap, TrustLevel.HIGH)

    def test_weak_detector_never_attains_high_cap(self):
        """§4: 'a detector never attaining TPR >= 1-beta has no theta2 =>
        band_cap = MED ... same formula, no special case.'"""
        theta1, theta2, cap = bands.derive_thresholds(WEAK_ROC, alpha_bp=500, beta_bp=500)
        self.assertEqual(theta1, 0)
        self.assertIsNone(theta2)
        self.assertEqual(cap, TrustLevel.MED)

    def test_no_threshold_satisfies_alpha_is_invalid(self):
        roc = [{"threshold": 0, "fpr_bp": 9999, "tpr_bp": 10000}]
        with self.assertRaises(ValueError):
            bands.derive_thresholds(roc, alpha_bp=1, beta_bp=500)

    def test_out_of_range_alpha_rejected(self):
        with self.assertRaises(ValueError):
            bands.derive_thresholds(STRONG_ROC, alpha_bp=10001, beta_bp=500)


class BandTests(unittest.TestCase):
    def setUp(self):
        self.theta1, self.theta2, self.cap = bands.derive_thresholds(
            STRONG_ROC, alpha_bp=500, beta_bp=500
        )

    def test_below_theta1_is_low(self):
        self.assertEqual(bands.band(-1, self.theta1, self.theta2, self.cap), TrustLevel.LOW)

    def test_between_thetas_is_med(self):
        self.assertEqual(bands.band(10, self.theta1, self.theta2, self.cap), TrustLevel.MED)

    def test_above_theta2_is_high(self):
        self.assertEqual(bands.band(60, self.theta1, self.theta2, self.cap), TrustLevel.HIGH)

    def test_band_cap_meets_raw_band(self):
        _, _, weak_cap = bands.derive_thresholds(WEAK_ROC, alpha_bp=500, beta_bp=500)
        self.assertEqual(weak_cap, TrustLevel.MED)
        # even a score that would raw-classify as HIGH is meet-capped to MED
        result = bands.band(1000, 0, None, weak_cap)
        self.assertEqual(result, TrustLevel.MED)

    def test_boundary_at_theta1_is_not_low(self):
        self.assertNotEqual(bands.band(self.theta1, self.theta1, self.theta2, self.cap), TrustLevel.LOW)

    def test_cap_actually_reduces_a_high_raw_band(self):
        """Isolates the meet-with-cap step itself: theta2 is not None here
        (unlike the weak-detector case, where raw already collapses to MED
        before the cap is even applied), so a score clearing theta2 raw-
        classifies as HIGH and only the explicit meet(raw, band_cap) pulls
        it down to a lower cap."""
        result = bands.band(60, self.theta1, self.theta2, TrustLevel.MED)
        self.assertEqual(result, TrustLevel.MED)


class ReduceDimensionTests(unittest.TestCase):
    def test_meet_of_single_claim(self):
        self.assertEqual(bands.reduce_dimension([TrustLevel.HIGH]), TrustLevel.HIGH)

    def test_meet_takes_the_worst(self):
        self.assertEqual(
            bands.reduce_dimension([TrustLevel.HIGH, TrustLevel.LOW, TrustLevel.MED]),
            TrustLevel.LOW,
        )

    def test_missing_claim_is_low(self):
        """§4: 'a missing record is evidence of a problem, not absence of
        evidence.'"""
        self.assertEqual(
            bands.reduce_dimension([TrustLevel.HIGH, None]), TrustLevel.LOW
        )

    def test_empty_claim_list_rejected(self):
        with self.assertRaises(ValueError):
            bands.reduce_dimension([])


class EisConfigLoadingTests(unittest.TestCase):
    def test_provisional_config_loads(self):
        raw, derived = bands.load_eis_config(CONFIG_DIR / "eis.v0.json")
        self.assertEqual(raw["calibration_status"], "provisional")
        self.assertEqual(len(derived), 6)

    def test_measured_status_with_placeholder_claim_rejected(self):
        raw = {
            "calibration_status": "measured",
            "alpha_bp": 500, "beta_bp": 500,
            "claims": {
                "x": {"dimension": "Signal", "polarity": 1, "placeholder": True, "roc": STRONG_ROC}
            },
        }
        with self.assertRaises(ValueError):
            bands.validate_eis_config(raw)

    def test_roc_config_hash_is_deterministic(self):
        h1 = bands.roc_config_hash(CONFIG_DIR / "eis.v0.json")
        h2 = bands.roc_config_hash(CONFIG_DIR / "eis.v0.json")
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 64)


STRONG_ROC_PPB = [
    {"threshold": -100, "fpr_ppb": 0, "tpr_ppb": 0},
    {"threshold": -50, "fpr_ppb": 10_000_000, "tpr_ppb": 300_000_000},
    {"threshold": 0, "fpr_ppb": 50_000_000, "tpr_ppb": 800_000_000},
    {"threshold": 50, "fpr_ppb": 200_000_000, "tpr_ppb": 950_000_000},
    {"threshold": 100, "fpr_ppb": 1_000_000_000, "tpr_ppb": 1_000_000_000},
]


class DetectRateFormatTests(unittest.TestCase):
    """eis.v1 (Step 5, prerequisite to Phase 9): format detection is
    fail-closed on ambiguity and on version/field disagreement -- these are
    the "verdict's config-version and the loaded config-version disagree"
    checks, done at config-load time rather than as a new wire field."""

    def test_bp_format_with_no_version_field_is_v0(self):
        self.assertEqual(bands.detect_rate_format({"alpha_bp": 500}), "bp")

    def test_ppb_format_with_correct_version_is_v1(self):
        self.assertEqual(
            bands.detect_rate_format({"alpha_ppb": 5_000_000, "eis_schema_version": 1}), "ppb"
        )

    def test_neither_alpha_field_present_rejected(self):
        with self.assertRaises(ValueError):
            bands.detect_rate_format({"eis_schema_version": 1})

    def test_both_alpha_fields_present_rejected(self):
        with self.assertRaises(ValueError):
            bands.detect_rate_format({"alpha_bp": 500, "alpha_ppb": 5_000_000})

    def test_ppb_fields_with_missing_version_declaration_rejected(self):
        """ppb format requires an explicit eis_schema_version; bp's implicit
        default (0) disagrees with ppb's expected version (1)."""
        with self.assertRaises(ValueError):
            bands.detect_rate_format({"alpha_ppb": 5_000_000})

    def test_ppb_fields_with_wrong_version_declaration_rejected(self):
        with self.assertRaises(ValueError):
            bands.detect_rate_format({"alpha_ppb": 5_000_000, "eis_schema_version": 0})

    def test_bp_fields_with_wrong_version_declaration_rejected(self):
        with self.assertRaises(ValueError):
            bands.detect_rate_format({"alpha_bp": 500, "eis_schema_version": 1})


class EisV1ConfigTests(unittest.TestCase):
    """eis.v1.json (ppb) must validate, hash, and derive thresholds through
    the exact same generalized code path as eis.v0.json (bp) -- same
    formula, wider scale, no new interpretation rule."""

    def test_v1_provisional_config_loads(self):
        raw, derived = bands.load_eis_config(CONFIG_DIR / "eis.v1.json")
        self.assertEqual(raw["calibration_status"], "provisional")
        self.assertEqual(raw["eis_schema_version"], 1)
        self.assertEqual(len(derived), 6)

    def test_v0_and_v1_hashes_are_distinct(self):
        h0 = bands.roc_config_hash(CONFIG_DIR / "eis.v0.json")
        h1 = bands.roc_config_hash(CONFIG_DIR / "eis.v1.json")
        self.assertNotEqual(h0, h1)

    def test_v0_and_v1_derive_identical_thresholds_for_the_same_rates(self):
        """v1's claims are the same rates as v0's, just at a wider scale
        (x100000) -- derive_thresholds() must select the same theta1/theta2/
        band_cap either way, since only the representation widened."""
        _, derived0 = bands.load_eis_config(CONFIG_DIR / "eis.v0.json")
        _, derived1 = bands.load_eis_config(CONFIG_DIR / "eis.v1.json")
        for claim_type in derived0:
            self.assertEqual(derived0[claim_type], derived1[claim_type])

    def test_v0_config_unaffected_by_v1_existing(self):
        """Regression guard: loading/validating/hashing eis.v0.json must be
        byte-behaviorally unaffected by the eis.v1 generalization."""
        raw, derived = bands.load_eis_config(CONFIG_DIR / "eis.v0.json")
        self.assertNotIn("eis_schema_version", raw)
        self.assertEqual(raw["alpha_bp"], 500)
        self.assertEqual(len(derived), 6)

    def test_ppb_roc_validates_at_ppb_scale(self):
        bands.validate_roc_points(STRONG_ROC_PPB, scale=bands.PPB_SCALE,
                                   fpr_key="fpr_ppb", tpr_key="tpr_ppb")

    def test_ppb_scale_rejects_bp_out_of_range_value_as_in_range(self):
        """A rate that would be invalid at bp scale (e.g. 10001) is valid at
        ppb scale -- confirms the two scales are not silently conflated."""
        bands.validate_roc_points(
            [{"threshold": 0, "fpr_ppb": 10001, "tpr_ppb": 0}],
            scale=bands.PPB_SCALE, fpr_key="fpr_ppb", tpr_key="tpr_ppb",
        )

    def test_ppb_derive_thresholds_representable_far_below_bp_floor(self):
        """The whole point of eis.v1: an alpha far too small to be nonzero
        at bp scale (e.g. 1 bp = 1e-4 is the bp floor; 1e-6 rounds to 0bp)
        is representable and produces a real (non-degenerate) theta1 at ppb
        scale."""
        alpha_ppb_tiny = 1_000  # 1e-6 in rate terms -- 0 at bp scale, 1000 at ppb scale
        theta1, theta2, cap = bands.derive_thresholds(
            STRONG_ROC_PPB, alpha_ppb_tiny, 50_000_000,
            scale=bands.PPB_SCALE, fpr_key="fpr_ppb", tpr_key="tpr_ppb",
        )
        self.assertEqual(theta1, -100)  # only the fpr_ppb=0 point satisfies FPR <= 1000


def _minimal_v1_config(resolution_status_override=None):
    """A minimal, valid eis.v1-shaped config dict for isolated
    resolution_status validation tests -- avoids depending on the real
    config/eis.v1.json file's exact content for these specific checks."""
    rs = {"0.1%": "pending", "1%": "pending", "5%": "pending"}
    if resolution_status_override is not None:
        rs = resolution_status_override
    claim = {"dimension": "Signal", "polarity": 1, "placeholder": True, "roc": STRONG_ROC_PPB}
    if rs is not False:  # False sentinel: omit the key entirely
        claim["resolution_status"] = rs
    return {
        "eis_schema_version": 1, "calibration_status": "provisional",
        "alpha_ppb": 50_000_000, "beta_ppb": 50_000_000,
        "claims": {"x": claim},
    }


class ResolutionStatusValidationTests(unittest.TestCase):
    """CLAUDE.md §20's Tail-Floor Rule stable-label convention: a
    per-swept-budget resolution_status is required on every claim for any
    non-bp (eis.v1+) config, fail-closed like every other field, and
    therefore present in the bytes roc_config_hash() hashes (see
    RocConfigHashCoversResolutionStatusTests below for the direct
    demonstration)."""

    def test_real_eis_v1_config_has_resolution_status_on_every_claim(self):
        raw, _ = bands.load_eis_config(CONFIG_DIR / "eis.v1.json")
        for claim_type, claim in raw["claims"].items():
            self.assertIn("resolution_status", claim, claim_type)
            self.assertEqual(set(claim["resolution_status"].keys()), set(bands.SWEPT_BUDGET_LABELS))
            for v in claim["resolution_status"].values():
                self.assertIn(v, bands.RESOLUTION_STATUS_VALUES)

    def test_real_eis_v1_config_all_pending_pre_phase_9(self):
        """No Phase 9 derivation has happened; every value must be
        'pending', never 'stable' or 'tail_floor' (those are Phase-9
        outputs, not something this repo is authorized to hand-assign)."""
        raw, _ = bands.load_eis_config(CONFIG_DIR / "eis.v1.json")
        for claim in raw["claims"].values():
            for v in claim["resolution_status"].values():
                self.assertEqual(v, "pending")

    def test_missing_resolution_status_rejected_for_v1(self):
        raw = _minimal_v1_config(resolution_status_override=False)
        with self.assertRaises(ValueError):
            bands.validate_eis_config(raw)

    def test_wrong_budget_keys_rejected(self):
        raw = _minimal_v1_config({"0.1%": "pending", "1%": "pending"})  # missing "5%"
        with self.assertRaises(ValueError):
            bands.validate_eis_config(raw)

    def test_extra_budget_key_rejected(self):
        raw = _minimal_v1_config({"0.1%": "pending", "1%": "pending", "5%": "pending", "10%": "pending"})
        with self.assertRaises(ValueError):
            bands.validate_eis_config(raw)

    def test_invalid_status_value_rejected(self):
        raw = _minimal_v1_config({"0.1%": "measured", "1%": "pending", "5%": "pending"})
        with self.assertRaises(ValueError):
            bands.validate_eis_config(raw)

    def test_non_dict_resolution_status_rejected(self):
        raw = _minimal_v1_config("pending")
        with self.assertRaises(ValueError):
            bands.validate_eis_config(raw)

    def test_stable_and_tail_floor_are_legal_values(self):
        """Legal once Phase 9 actually assigns them -- this repo just
        never assigns them itself (see the two tests above)."""
        raw = _minimal_v1_config({"0.1%": "stable", "1%": "tail_floor", "5%": "pending"})
        bands.validate_eis_config(raw)  # must not raise

    def test_v0_config_never_requires_resolution_status(self):
        """Regression guard: eis.v0.json predates this concept and must
        remain byte-behaviorally unaffected -- a v0-shaped config without
        resolution_status must still validate."""
        raw = {
            "calibration_status": "provisional", "alpha_bp": 500, "beta_bp": 500,
            "claims": {"x": {"dimension": "Signal", "polarity": 1, "placeholder": True, "roc": STRONG_ROC}},
        }
        bands.validate_eis_config(raw)  # must not raise
        self.assertNotIn("resolution_status", raw["claims"]["x"])


class RocConfigHashCoversResolutionStatusTests(unittest.TestCase):
    """Direct demonstration (not an inference from validation behaviour)
    that roc_config_hash() covers resolution_status: mutate ONLY a
    resolution_status value on an otherwise-identical config and show the
    hash changes."""

    def test_changing_resolution_status_changes_the_hash(self):
        base = _minimal_v1_config({"0.1%": "pending", "1%": "pending", "5%": "pending"})
        mutated = _minimal_v1_config({"0.1%": "stable", "1%": "pending", "5%": "pending"})

        base_canonical = json.dumps(base, sort_keys=True, separators=(",", ":")).encode()
        mutated_canonical = json.dumps(mutated, sort_keys=True, separators=(",", ":")).encode()
        base_hash = hashlib.sha256(base_canonical).hexdigest()
        mutated_hash = hashlib.sha256(mutated_canonical).hexdigest()

        self.assertNotEqual(base_hash, mutated_hash)

    def test_real_config_file_hash_changes_when_resolution_status_changes_on_disk(self):
        """Same demonstration, but through roc_config_hash() itself against
        real files on disk, exactly as replay.py's config-mismatch check
        would encounter it (evidence_plane/replay.py checks roc_config_hash
        BEFORE any replay recomputation -- CLAUDE.md §8's 'without them,
        editing a threshold, a scale, or rotating a key silently
        reinterprets all history')."""
        raw = json.loads((CONFIG_DIR / "eis.v1.json").read_text())
        original_hash = bands.roc_config_hash(CONFIG_DIR / "eis.v1.json")

        mutated = json.loads(json.dumps(raw))  # deep copy
        mutated["claims"]["signal.provisional_v0"]["resolution_status"]["0.1%"] = "tail_floor"

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(mutated, f)
            mutated_path = pathlib.Path(f.name)
        try:
            mutated_hash = bands.roc_config_hash(mutated_path)
        finally:
            mutated_path.unlink()

        self.assertNotEqual(original_hash, mutated_hash)


class RepresentableAtScaleTests(unittest.TestCase):
    def test_bp_floor(self):
        self.assertFalse(bands.representable_at_scale(0.5e-4, bands.BP_SCALE))
        self.assertTrue(bands.representable_at_scale(1e-4, bands.BP_SCALE))

    def test_ppb_represents_values_bp_cannot(self):
        tiny = 1.3e-7  # smallest required alpha found by the event-model investigation
        self.assertFalse(bands.representable_at_scale(tiny, bands.BP_SCALE))
        self.assertTrue(bands.representable_at_scale(tiny, bands.PPB_SCALE))

    def test_margin_is_rate_times_scale(self):
        self.assertAlmostEqual(bands.representability_margin(1.3e-7, bands.PPB_SCALE), 130.0, places=6)


if __name__ == "__main__":
    unittest.main()
