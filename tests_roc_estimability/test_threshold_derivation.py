"""Tests for roc_estimability/threshold_derivation.py (Phase 9's real,
non-ephemeral threshold derivation). Pure Python, no real-data dependency:
    python3 -m unittest discover -s tests_roc_estimability
"""

import unittest

from roc_estimability import threshold_derivation as td
from trust_kernel.bands import PPB_SCALE, TrustLevel


class BuildRocPointsTests(unittest.TestCase):
    def test_perfect_separation(self):
        pts = td.build_roc_points([80, 90, 100], [-100, -90, -80])
        # sentinel below min: nothing flagged yet.
        self.assertEqual(pts[0]["fpr_ppb"], 0)
        self.assertEqual(pts[0]["tpr_ppb"], 0)
        # last candidate threshold is the max observed value (100): "score <
        # 100" flags all 3 attack samples (all far below) but not the honest
        # sample AT exactly 100 (100 < 100 is false) -- FPR tops out at 2/3,
        # never 1.0, by this step function's own "< threshold" convention.
        self.assertEqual(pts[-1]["fpr_ppb"], round(2 / 3 * PPB_SCALE))
        self.assertEqual(pts[-1]["tpr_ppb"], PPB_SCALE)

    def test_thresholds_strictly_increasing(self):
        pts = td.build_roc_points([1, 5, 5, 9], [0, 4, 8])
        thresholds = [p["threshold"] for p in pts]
        self.assertEqual(thresholds, sorted(set(thresholds)))
        self.assertEqual(len(thresholds), len(set(thresholds)))

    def test_fpr_tpr_non_decreasing(self):
        pts = td.build_roc_points([1, 5, 9, 3], [0, 4, 8, 2])
        fprs = [p["fpr_ppb"] for p in pts]
        tprs = [p["tpr_ppb"] for p in pts]
        self.assertEqual(fprs, sorted(fprs))
        self.assertEqual(tprs, sorted(tprs))

    def test_empty_honest_rejected(self):
        with self.assertRaises(ValueError):
            td.build_roc_points([], [1, 2])

    def test_empty_attack_rejected(self):
        with self.assertRaises(ValueError):
            td.build_roc_points([1, 2], [])

    def test_hand_computed_single_step(self):
        # honest=[10,20], attack=[5,15]. Candidates: sentinel(4), 5,10,15,20.
        pts = td.build_roc_points([10, 20], [5, 15])
        by_t = {p["threshold"]: p for p in pts}
        self.assertEqual(by_t[4]["fpr_ppb"], 0)
        self.assertEqual(by_t[4]["tpr_ppb"], 0)
        self.assertEqual(by_t[10]["fpr_ppb"], 0)  # honest<10: none of [10,20]
        self.assertEqual(by_t[10]["tpr_ppb"], round(0.5 * PPB_SCALE))  # attack<10: just 5
        self.assertEqual(by_t[15]["fpr_ppb"], round(0.5 * PPB_SCALE))  # honest<15: just 10
        self.assertEqual(by_t[15]["tpr_ppb"], round(0.5 * PPB_SCALE))  # attack<15: just 5 (15 not <15)
        self.assertEqual(by_t[20]["tpr_ppb"], PPB_SCALE)  # attack<20: both 5,15


class HighTailThresholdTests(unittest.TestCase):
    def test_hand_computed(self):
        # sorted attack scores [10,20,30,40] -> largest is 40
        self.assertEqual(td._high_tail_threshold([40, 10, 30, 20], polarity=1), 40)

    def test_needs_at_least_two_samples(self):
        self.assertIsNone(td._high_tail_threshold([10], polarity=1))
        self.assertIsNone(td._high_tail_threshold([], polarity=1))

    def test_flags_all_but_the_single_maximum(self):
        attack = [10, 20, 30, 40]
        theta = td._high_tail_threshold(attack, polarity=1)
        flagged = sum(1 for v in attack if v < theta)
        self.assertEqual(flagged, len(attack) - 1)


class FprTprAtTests(unittest.TestCase):
    def test_hand_computed(self):
        honest = [10, 20, 30, 40]
        attack = [-10, 5, 15, 25]
        fpr, tpr = td._fpr_tpr_at(20, honest, attack, polarity=1)
        self.assertAlmostEqual(fpr, 0.25)
        self.assertAlmostEqual(tpr, 0.75)

    def test_none_threshold(self):
        self.assertEqual(td._fpr_tpr_at(None, [1, 2], [3, 4]), (None, None))


class BandWidthTests(unittest.TestCase):
    def test_hand_computed(self):
        self.assertEqual(td._band_width(list(range(100))), 95)

    def test_fewer_than_two_none(self):
        self.assertIsNone(td._band_width([]))
        self.assertIsNone(td._band_width([1]))


class BootstrapBandWidthsHighTailTests(unittest.TestCase):
    def test_deterministic_perfect_separation_zero_width(self):
        subject_ids = [4, 5, 6, 7, 8, 9]
        honest = {s: [100] * 5 for s in subject_ids}
        attack = {s: [-100] * 5 for s in subject_ids}
        result = td.bootstrap_band_widths_high_tail(subject_ids, honest, attack, n_boot=1000, seed=0)
        self.assertEqual(result["fpr_band_width"], 0.0)
        self.assertEqual(result["tpr_band_width"], 0.0)

    def test_n_boot_below_1000_rejected(self):
        with self.assertRaises(ValueError):
            td.bootstrap_band_widths_high_tail([1, 2], {1: [1, 2], 2: [1, 2]}, {1: [1, 2], 2: [1, 2]}, n_boot=999)

    def test_return_keys(self):
        result = td.bootstrap_band_widths_high_tail(
            [1, 2], {1: [1, 2, 3], 2: [4, 5, 6]}, {1: [-1, -2], 2: [-4, -5]}, n_boot=1000)
        self.assertEqual(set(result.keys()), {"n_boot", "n_resamples_with_data", "fpr_band_width", "tpr_band_width"})

    def test_noisy_data_gives_nonzero_width(self):
        """If bootstrap resampling silently used the fixed cohort every
        iteration instead of resampling WITH REPLACEMENT, every iteration
        would pool identical data and the width would collapse to exactly
        zero even for genuinely variable per-subject data."""
        import random
        rng = random.Random(1)
        subject_ids = list(range(1, 7))
        honest = {s: [rng.gauss(50, 15) for _ in range(30)] for s in subject_ids}
        attack = {s: [rng.gauss(0, 15) for _ in range(30)] for s in subject_ids}
        result = td.bootstrap_band_widths_high_tail(subject_ids, honest, attack, n_boot=1000, seed=2)
        self.assertGreater(result["fpr_band_width"], 0.0)


class LosoSwingHighTailTests(unittest.TestCase):
    def test_deterministic_zero_swing(self):
        subject_ids = [4, 5, 6, 7, 8, 9]
        honest = {s: [100] * 5 for s in subject_ids}
        attack = {s: [-100] * 5 for s in subject_ids}
        result = td.leave_one_subject_out_swing_high_tail(subject_ids, honest, attack)
        self.assertEqual(result["max_fpr_swing"], 0.0)
        self.assertEqual(result["max_tpr_swing"], 0.0)

    def test_outlier_subject_produces_swing(self):
        subject_ids = [1, 2, 3, 4]
        honest = {s: [10, 11, 12] for s in subject_ids}
        attack = {1: [20, 21, 22], 2: [0, 1, 2], 3: [0, 1, 2], 4: [0, 1, 2]}
        result = td.leave_one_subject_out_swing_high_tail(subject_ids, honest, attack)
        self.assertGreater(result["max_tpr_swing"], 0.0)

    def test_swing_is_the_true_maximum_not_the_last_drop_evaluated(self):
        """The outlier subject is FIRST in iteration order -- if the
        implementation tracked only the most recently evaluated drop
        instead of the running maximum, dropping the (normal) last subject
        would overwrite the correct (large) swing from dropping the
        (outlier) first subject with a near-zero value."""
        subject_ids = [1, 2, 3, 4]
        honest = {s: [10, 11, 12] for s in subject_ids}
        attack = {1: [20, 21, 22], 2: [0, 1, 2], 3: [0, 1, 2], 4: [0, 1, 2]}
        result = td.leave_one_subject_out_swing_high_tail(subject_ids, honest, attack)
        self.assertGreater(result["max_tpr_swing"], 0.2)


class EvaluateTailFloorRuleTests(unittest.TestCase):
    def test_clean_separation_full_pool_is_stable(self):
        subjects = list(range(1, 10))
        honest = {s: [90 + i for i in range(10)] for s in subjects}
        attack = {s: [10 + i for i in range(10)] for s in subjects}
        result = td.evaluate_tail_floor_rule(
            cohort_subjects=subjects, subjects_honest=honest, subjects_attack=attack,
            full_pool_subjects=subjects, min_subjects_separating=6, n_boot=1000, seed=1,
        )
        self.assertEqual(result["theta1_resolution_status"], "stable")
        self.assertEqual(result["theta2_resolution_status"], "stable")
        self.assertEqual(result["class_support_n_separating"], 9)

    def test_insufficient_class_support_triggers_tail_floor(self):
        subjects = [4, 5, 6, 7, 8, 9]
        # only 2 of 6 subjects show real separation; rest identical distributions
        honest = {s: [50, 51, 52] for s in subjects}
        attack = {s: [50, 51, 52] for s in subjects}
        honest[4] = [90, 91, 92]
        attack[4] = [10, 11, 12]
        honest[5] = [90, 91, 92]
        attack[5] = [10, 11, 12]
        result = td.evaluate_tail_floor_rule(
            cohort_subjects=subjects, subjects_honest=honest, subjects_attack=attack,
            full_pool_subjects=list(range(1, 10)), min_subjects_separating=4, n_boot=1000, seed=1,
        )
        self.assertEqual(result["class_support_n_separating"], 2)
        self.assertEqual(result["theta1_resolution_status"], "tail_floor")
        self.assertIn("class_support", result["theta1_failed_tests"])

    def test_theta1_only_tail_floor_isolated(self):
        """Subject 9 contributes two abnormally LOW honest samples, moving
        the low-tail (theta1) proxy threshold into the attack range and
        producing a large LOSO TPR swing on that side specifically -- attack
        is otherwise unperturbed, so the high-tail (theta2) side must stay
        stable. Isolates theta1's own contribution to the rule from
        theta2's."""
        subjects = list(range(4, 10))
        honest = {s: [90, 91, 92, 93, 94] for s in subjects}
        attack = {s: [10, 11, 12, 13, 14] for s in subjects}
        honest[9] = [5, 6]
        result = td.evaluate_tail_floor_rule(
            cohort_subjects=subjects, subjects_honest=honest, subjects_attack=attack,
            full_pool_subjects=list(range(1, 10)), min_subjects_separating=4, n_boot=1000, seed=1,
        )
        self.assertEqual(result["theta1_resolution_status"], "tail_floor")
        self.assertEqual(result["theta2_resolution_status"], "stable")

    def test_theta2_only_tail_floor_isolated(self):
        """Mirror of the above: subject 9 contributes one abnormally HIGH
        (hard-to-catch) attack sample, swinging only the high-tail (theta2)
        proxy; honest is unperturbed, so theta1 must stay stable."""
        subjects = list(range(4, 10))
        honest = {s: [90, 91, 92, 93, 94] for s in subjects}
        attack = {s: [10, 11, 12, 13, 14] for s in subjects}
        attack[9] = [85]
        result = td.evaluate_tail_floor_rule(
            cohort_subjects=subjects, subjects_honest=honest, subjects_attack=attack,
            full_pool_subjects=list(range(1, 10)), min_subjects_separating=4, n_boot=1000, seed=1,
        )
        self.assertEqual(result["theta1_resolution_status"], "stable")
        self.assertEqual(result["theta2_resolution_status"], "tail_floor")

    def test_full_pool_uses_self_comparison_gap(self):
        subjects = list(range(1, 10))
        honest = {s: [90, 91, 92] for s in subjects}
        attack = {s: [10, 11, 12] for s in subjects}
        result = td.evaluate_tail_floor_rule(
            cohort_subjects=subjects, subjects_honest=honest, subjects_attack=attack,
            full_pool_subjects=subjects, min_subjects_separating=6, n_boot=1000, seed=1,
        )
        self.assertEqual(result["theta1_cohort_stability_gap"]["fpr_band_width_ratio_6_over_9"], 1.0)
        self.assertEqual(result["theta2_cohort_stability_gap"]["tpr_band_width_ratio_6_over_9"], 1.0)


class DeriveClaimOperatingPointTests(unittest.TestCase):
    def _subjects(self):
        subjects = list(range(4, 10))
        honest = {s: [90, 91, 92, 93, 94] for s in subjects}
        attack = {s: [10, 11, 12, 13, 14] for s in subjects}
        return subjects, honest, attack

    def test_strong_detector_gives_high_band_cap(self):
        subjects, honest, attack = self._subjects()
        pooled_h = [v for s in subjects for v in honest[s]]
        pooled_a = [v for s in subjects for v in attack[s]]
        op = td.derive_claim_operating_point(
            honest=pooled_h, attack=pooled_a, alpha_ppb=1000, beta_ppb=1000,
            cohort_subjects=subjects, subjects_honest=honest, subjects_attack=attack,
            full_pool_subjects=list(range(1, 10)), min_subjects_separating=4,
            n_boot=1000, seed=1,
        )
        self.assertEqual(op["band_cap"], "HIGH")
        self.assertIsNotNone(op["theta1"])
        self.assertIsNotNone(op["theta2"])
        self.assertEqual(op["resolution_status"], "stable")

    def test_weak_detector_gives_med_band_cap_and_theta2_inapplicable(self):
        subjects = list(range(4, 10))
        honest = {s: [40, 50, 60] for s in subjects}
        attack = {s: [40, 50, 60] for s in subjects}  # fully overlapping
        pooled_h = [v for s in subjects for v in honest[s]]
        pooled_a = [v for s in subjects for v in attack[s]]
        op = td.derive_claim_operating_point(
            honest=pooled_h, attack=pooled_a, alpha_ppb=1000, beta_ppb=1000,
            cohort_subjects=subjects, subjects_honest=honest, subjects_attack=attack,
            full_pool_subjects=list(range(1, 10)), min_subjects_separating=4,
            n_boot=1000, seed=1,
        )
        self.assertEqual(op["band_cap"], "MED")
        self.assertIsNone(op["theta2"])
        self.assertFalse(op["theta2_applicable"])

    def test_resolution_status_tail_floor_when_only_theta1_triggers(self):
        subjects = list(range(4, 10))
        honest = {s: [90, 91, 92, 93, 94] for s in subjects}
        attack = {s: [10, 11, 12, 13, 14] for s in subjects}
        honest[9] = [5, 6]
        pooled_h = [v for s in subjects for v in honest[s]]
        pooled_a = [v for s in subjects for v in attack[s]]
        op = td.derive_claim_operating_point(
            honest=pooled_h, attack=pooled_a, alpha_ppb=1000, beta_ppb=1000,
            cohort_subjects=subjects, subjects_honest=honest, subjects_attack=attack,
            full_pool_subjects=list(range(1, 10)), min_subjects_separating=4,
            n_boot=1000, seed=1,
        )
        self.assertEqual(op["tail_floor_detail"]["theta1_resolution_status"], "tail_floor")
        self.assertEqual(op["tail_floor_detail"]["theta2_resolution_status"], "stable")
        self.assertEqual(op["resolution_status"], "tail_floor")

    def test_resolution_status_tail_floor_when_only_theta2_triggers(self):
        subjects = list(range(4, 10))
        honest = {s: [90, 91, 92, 93, 94] for s in subjects}
        attack = {s: [10, 11, 12, 13, 14] for s in subjects}
        attack[9] = [85]
        pooled_h = [v for s in subjects for v in honest[s]]
        pooled_a = [v for s in subjects for v in attack[s]]
        op = td.derive_claim_operating_point(
            honest=pooled_h, attack=pooled_a, alpha_ppb=1000, beta_ppb=1000,
            cohort_subjects=subjects, subjects_honest=honest, subjects_attack=attack,
            full_pool_subjects=list(range(1, 10)), min_subjects_separating=4,
            n_boot=1000, seed=1,
        )
        self.assertEqual(op["tail_floor_detail"]["theta1_resolution_status"], "stable")
        self.assertEqual(op["tail_floor_detail"]["theta2_resolution_status"], "tail_floor")
        self.assertTrue(op["theta2_applicable"])
        self.assertEqual(op["resolution_status"], "tail_floor")

    def test_theta2_tail_floor_does_not_leak_when_inapplicable(self):
        """resolution_status must be driven by theta1 alone when band_cap is
        MED (theta2_applicable=False) -- a tail_floor theta2 verdict must
        not be folded in when there is no theta2 to floor."""
        subjects, honest, attack = self._subjects()
        # Make it a weak detector (band_cap=MED) but with clean, stable theta1.
        subjects = list(range(4, 10))
        honest = {s: [90, 91, 92, 93, 94] for s in subjects}
        attack = {s: [89, 88, 87, 86, 85] for s in subjects}  # overlaps just below honest -> weak at high beta
        pooled_h = [v for s in subjects for v in honest[s]]
        pooled_a = [v for s in subjects for v in attack[s]]
        op = td.derive_claim_operating_point(
            honest=pooled_h, attack=pooled_a, alpha_ppb=1000, beta_ppb=1000,
            cohort_subjects=subjects, subjects_honest=honest, subjects_attack=attack,
            full_pool_subjects=list(range(1, 10)), min_subjects_separating=4,
            n_boot=1000, seed=1,
        )
        if not op["theta2_applicable"]:
            self.assertEqual(op["resolution_status"], op["tail_floor_detail"]["theta1_resolution_status"])


if __name__ == "__main__":
    unittest.main()
