"""Tests for roc_estimability/stability.py. Pure Python, no real-data
dependency -- run via plain python3:
    python3 -m unittest discover -s tests_roc_estimability
"""

import math
import unittest

from roc_estimability import stability as st


class ClassPresenceTests(unittest.TestCase):
    def test_both_present(self):
        self.assertTrue(st.class_presence([1, 2], [3, 4]))

    def test_honest_empty(self):
        self.assertFalse(st.class_presence([], [3, 4]))

    def test_attack_empty(self):
        self.assertFalse(st.class_presence([1, 2], []))

    def test_both_empty(self):
        self.assertFalse(st.class_presence([], []))


class ClassSeparatesTests(unittest.TestCase):
    def test_separates_when_attack_median_lower(self):
        self.assertTrue(st.class_separates([90, 100, 110], [-100, -90, -80], polarity=1))

    def test_does_not_separate_when_medians_equal(self):
        self.assertFalse(st.class_separates([10, 20, 30], [10, 20, 30], polarity=1))

    def test_does_not_separate_when_attack_median_higher(self):
        self.assertFalse(st.class_separates([-10, 0, 10], [50, 60, 70], polarity=1))

    def test_negative_polarity_flips_comparison(self):
        # polarity=-1: "more attack-like" means higher raw score, so attack
        # median must be numerically HIGHER than honest median to separate.
        self.assertTrue(st.class_separates([10, 20, 30], [80, 90, 100], polarity=-1))

    def test_empty_inputs_do_not_separate(self):
        self.assertFalse(st.class_separates([], [1, 2]))


class PrivateEphemeralHelperTests(unittest.TestCase):
    """These two helpers are private (leading underscore) and their return
    value must never appear in any public function's return value -- see
    the module docstring's ephemerality contract. Tested directly here for
    correctness, exactly because they are the only place a threshold or an
    absolute FPR/TPR value is ever computed in this module."""

    def test_low_tail_threshold_hand_computed(self):
        # sorted honest scores: [10, 20, 30, 40] -> second-smallest is 20
        self.assertEqual(st._low_tail_threshold([40, 10, 30, 20], polarity=1), 20)

    def test_low_tail_threshold_needs_at_least_two_samples(self):
        self.assertIsNone(st._low_tail_threshold([10], polarity=1))
        self.assertIsNone(st._low_tail_threshold([], polarity=1))

    def test_fpr_tpr_at_hand_computed(self):
        honest = [10, 20, 30, 40]  # 1 of 4 strictly below threshold=20 -> FPR=0.25
        attack = [-10, 5, 15, 25]  # 3 of 4 strictly below threshold=20 -> TPR=0.75
        fpr, tpr = st._fpr_tpr_at(20, honest, attack, polarity=1)
        self.assertAlmostEqual(fpr, 0.25)
        self.assertAlmostEqual(tpr, 0.75)

    def test_fpr_tpr_at_none_threshold_returns_none(self):
        self.assertEqual(st._fpr_tpr_at(None, [1, 2], [3, 4]), (None, None))


class BandWidthTests(unittest.TestCase):
    def test_hand_computed_width(self):
        # sorted [0..99]; 2.5th pct index=2 -> value 2; 97.5th pct index=97 -> value 97
        samples = list(range(100))
        self.assertEqual(st._band_width(samples), 95)

    def test_fewer_than_two_samples_returns_none(self):
        self.assertIsNone(st._band_width([]))
        self.assertIsNone(st._band_width([1]))


class BootstrapBandWidthsTests(unittest.TestCase):
    def test_deterministic_perfect_separation_gives_zero_width(self):
        """Model/Device/FSI-style claims: every subject's honest samples are
        a constant CEIL and attack samples a constant FLOOR -- the
        bootstrap band must collapse to exactly zero width, matching the
        task's expectation that these claims 'pass trivially'."""
        subject_ids = [4, 5, 6, 7, 8, 9]
        honest = {s: [100] * 5 for s in subject_ids}
        attack = {s: [-100] * 5 for s in subject_ids}
        result = st.bootstrap_band_widths(subject_ids, honest, attack, n_boot=1000, seed=0)
        self.assertEqual(result["fpr_band_width"], 0.0)
        self.assertEqual(result["tpr_band_width"], 0.0)

    def test_noisy_data_gives_nonzero_width(self):
        import random
        rng = random.Random(1)
        subject_ids = list(range(1, 7))
        honest = {s: [rng.gauss(50, 15) for _ in range(30)] for s in subject_ids}
        attack = {s: [rng.gauss(0, 15) for _ in range(30)] for s in subject_ids}
        result = st.bootstrap_band_widths(subject_ids, honest, attack, n_boot=1000, seed=2)
        self.assertGreater(result["tpr_band_width"], 0.0)

    def test_n_boot_below_1000_rejected(self):
        with self.assertRaises(ValueError):
            st.bootstrap_band_widths([1, 2], {1: [1, 2], 2: [1, 2]}, {1: [1, 2], 2: [1, 2]}, n_boot=999)

    def test_return_keys_never_include_a_location_field(self):
        """Structural guard: the only permitted keys are widths/counts, not
        an absolute fpr/tpr value or a threshold."""
        subject_ids = [1, 2]
        honest = {1: [1, 2, 3], 2: [4, 5, 6]}
        attack = {1: [-1, -2], 2: [-4, -5]}
        result = st.bootstrap_band_widths(subject_ids, honest, attack, n_boot=1000)
        self.assertEqual(set(result.keys()), {"n_boot", "n_resamples_with_data", "fpr_band_width", "tpr_band_width"})


class LeaveOneSubjectOutSwingTests(unittest.TestCase):
    def test_deterministic_data_gives_zero_swing(self):
        subject_ids = [4, 5, 6, 7, 8, 9]
        honest = {s: [100] * 5 for s in subject_ids}
        attack = {s: [-100] * 5 for s in subject_ids}
        result = st.leave_one_subject_out_swing(subject_ids, honest, attack)
        self.assertEqual(result["max_fpr_swing"], 0.0)
        self.assertEqual(result["max_tpr_swing"], 0.0)

    def test_one_outlier_subject_produces_large_swing(self):
        subject_ids = [1, 2, 3, 4]
        honest = {1: [10, 11, 12], 2: [10, 11, 12], 3: [10, 11, 12], 4: [10, 11, 12]}
        # subject 4's attack samples are far from the other subjects' attack
        # samples -- dropping subject 4 should swing TPR substantially.
        attack = {1: [0, 1, 2], 2: [0, 1, 2], 3: [0, 1, 2], 4: [20, 21, 22]}
        result = st.leave_one_subject_out_swing(subject_ids, honest, attack)
        self.assertGreater(result["max_tpr_swing"], 0.0)

    def test_return_keys_never_include_a_location_field(self):
        subject_ids = [1, 2]
        honest = {1: [1, 2, 3], 2: [4, 5, 6]}
        attack = {1: [-1, -2], 2: [-4, -5]}
        result = st.leave_one_subject_out_swing(subject_ids, honest, attack)
        self.assertEqual(set(result.keys()), {"max_fpr_swing", "max_tpr_swing", "n_subjects"})

    def test_swing_is_the_true_maximum_not_the_last_drop_evaluated(self):
        """The outlier subject is FIRST in iteration order, not last -- if
        the implementation tracked only the most recently evaluated drop
        instead of the running maximum, dropping the (normal) last subject
        would overwrite the correct (large) swing from dropping the
        (outlier) first subject with a near-zero value."""
        subject_ids = [1, 2, 3, 4]
        honest = {s: [10, 11, 12] for s in subject_ids}
        attack = {1: [20, 21, 22], 2: [0, 1, 2], 3: [0, 1, 2], 4: [0, 1, 2]}
        result = st.leave_one_subject_out_swing(subject_ids, honest, attack)
        self.assertGreater(result["max_tpr_swing"], 0.2)


class CohortStabilityGapTests(unittest.TestCase):
    def test_ratio_hand_computed(self):
        gap = st.cohort_stability_gap(
            {"fpr_band_width": 0.10, "tpr_band_width": 0.20},
            {"fpr_band_width": 0.05, "tpr_band_width": 0.05},
        )
        self.assertAlmostEqual(gap["fpr_band_width_ratio_6_over_9"], 2.0)
        self.assertAlmostEqual(gap["tpr_band_width_ratio_6_over_9"], 4.0)

    def test_both_zero_is_none_not_nan(self):
        gap = st.cohort_stability_gap(
            {"fpr_band_width": 0.0, "tpr_band_width": 0.0},
            {"fpr_band_width": 0.0, "tpr_band_width": 0.0},
        )
        self.assertIsNone(gap["fpr_band_width_ratio_6_over_9"])
        self.assertIsNone(gap["tpr_band_width_ratio_6_over_9"])

    def test_denominator_zero_numerator_nonzero_is_infinite(self):
        gap = st.cohort_stability_gap(
            {"fpr_band_width": 0.1, "tpr_band_width": 0.1},
            {"fpr_band_width": 0.0, "tpr_band_width": 0.0},
        )
        self.assertTrue(math.isinf(gap["fpr_band_width_ratio_6_over_9"]))

    def test_none_input_propagates_as_none(self):
        gap = st.cohort_stability_gap(
            {"fpr_band_width": None, "tpr_band_width": 0.1},
            {"fpr_band_width": 0.1, "tpr_band_width": None},
        )
        self.assertIsNone(gap["fpr_band_width_ratio_6_over_9"])
        self.assertIsNone(gap["tpr_band_width_ratio_6_over_9"])


class ClaimSufficiencyVerdictTests(unittest.TestCase):
    def _passing_inputs(self):
        return dict(
            n_subjects_separating=6,
            bootstrap_widths={"fpr_band_width": 0.01, "tpr_band_width": 0.01},
            loso_swing={"max_fpr_swing": 0.01, "max_tpr_swing": 0.01},
            gap={"fpr_band_width_ratio_6_over_9": 1.2, "tpr_band_width_ratio_6_over_9": 1.2},
        )

    def test_all_pass_gives_sufficient(self):
        result = st.claim_sufficiency_verdict(**self._passing_inputs())
        self.assertTrue(result["sufficient_on_held_out"])
        self.assertEqual(result["failed_tests"], [])

    def test_insufficient_class_support_fails(self):
        inputs = self._passing_inputs()
        inputs["n_subjects_separating"] = 3
        result = st.claim_sufficiency_verdict(**inputs)
        self.assertFalse(result["sufficient_on_held_out"])
        self.assertIn("class_support", result["failed_tests"])

    def test_class_support_boundary_four_of_six_passes(self):
        inputs = self._passing_inputs()
        inputs["n_subjects_separating"] = st.CLASS_SUPPORT_MIN_SUBJECTS
        result = st.claim_sufficiency_verdict(**inputs)
        self.assertNotIn("class_support", result["failed_tests"])

    def test_custom_min_subjects_separating_for_a_larger_pool(self):
        """A 9-subject full-pool self-check uses the same 2/3 proportion as
        the 6-subject bar (6/9), not the raw count 4 -- callers pass
        min_subjects_separating explicitly for a differently-sized cohort."""
        inputs = self._passing_inputs()
        inputs["n_subjects_separating"] = 5
        inputs["min_subjects_separating"] = 6
        result = st.claim_sufficiency_verdict(**inputs)
        self.assertIn("class_support", result["failed_tests"])

    def test_custom_min_subjects_separating_boundary_passes(self):
        inputs = self._passing_inputs()
        inputs["n_subjects_separating"] = 6
        inputs["min_subjects_separating"] = 6
        result = st.claim_sufficiency_verdict(**inputs)
        self.assertNotIn("class_support", result["failed_tests"])

    def test_default_min_subjects_separating_unchanged(self):
        """Backward compatibility: omitting min_subjects_separating must
        behave exactly as before (CLASS_SUPPORT_MIN_SUBJECTS = 4)."""
        inputs = self._passing_inputs()
        inputs["n_subjects_separating"] = 4
        result = st.claim_sufficiency_verdict(**inputs)
        self.assertNotIn("class_support", result["failed_tests"])
        inputs["n_subjects_separating"] = 3
        result = st.claim_sufficiency_verdict(**inputs)
        self.assertIn("class_support", result["failed_tests"])

    def test_wide_fpr_bootstrap_ratio_fails(self):
        inputs = self._passing_inputs()
        inputs["gap"] = {"fpr_band_width_ratio_6_over_9": 3.0, "tpr_band_width_ratio_6_over_9": 1.0}
        result = st.claim_sufficiency_verdict(**inputs)
        self.assertIn("bootstrap_band_ratio_fpr", result["failed_tests"])

    def test_wide_tpr_bootstrap_ratio_fails(self):
        inputs = self._passing_inputs()
        inputs["gap"] = {"fpr_band_width_ratio_6_over_9": 1.0, "tpr_band_width_ratio_6_over_9": 3.0}
        result = st.claim_sufficiency_verdict(**inputs)
        self.assertIn("bootstrap_band_ratio_tpr", result["failed_tests"])

    def test_zero_width_ignores_ratio_even_if_reported_as_none(self):
        """Degenerate (Model/Device/FSI-style) claims: width 0 in both
        cohorts means the ratio is None (0/0) -- must not be treated as a
        failure just because the ratio couldn't be computed."""
        inputs = self._passing_inputs()
        inputs["bootstrap_widths"] = {"fpr_band_width": 0.0, "tpr_band_width": 0.0}
        inputs["gap"] = {"fpr_band_width_ratio_6_over_9": None, "tpr_band_width_ratio_6_over_9": None}
        result = st.claim_sufficiency_verdict(**inputs)
        self.assertTrue(result["sufficient_on_held_out"])

    def test_loso_fpr_swing_over_bound_fails(self):
        inputs = self._passing_inputs()
        inputs["loso_swing"] = {"max_fpr_swing": 0.5, "max_tpr_swing": 0.0}
        result = st.claim_sufficiency_verdict(**inputs)
        self.assertIn("loso_fpr_swing", result["failed_tests"])

    def test_loso_tpr_swing_over_bound_fails(self):
        inputs = self._passing_inputs()
        inputs["loso_swing"] = {"max_fpr_swing": 0.0, "max_tpr_swing": 0.5}
        result = st.claim_sufficiency_verdict(**inputs)
        self.assertIn("loso_tpr_swing", result["failed_tests"])

    def test_loso_swing_at_exact_bound_passes(self):
        inputs = self._passing_inputs()
        inputs["loso_swing"] = {"max_fpr_swing": st.MAX_LOSO_SWING, "max_tpr_swing": st.MAX_LOSO_SWING}
        result = st.claim_sufficiency_verdict(**inputs)
        self.assertEqual(result["failed_tests"], [])

    def test_multiple_failures_all_reported(self):
        inputs = self._passing_inputs()
        inputs["n_subjects_separating"] = 2
        inputs["loso_swing"] = {"max_fpr_swing": 0.9, "max_tpr_swing": 0.9}
        result = st.claim_sufficiency_verdict(**inputs)
        self.assertIn("class_support", result["failed_tests"])
        self.assertIn("loso_fpr_swing", result["failed_tests"])
        self.assertIn("loso_tpr_swing", result["failed_tests"])


if __name__ == "__main__":
    unittest.main()
