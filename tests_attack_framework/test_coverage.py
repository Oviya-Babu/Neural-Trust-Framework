"""Tests for attack_framework/coverage.py. Pure Python, no real-data
dependency:
    python3 -m unittest discover -s tests_attack_framework
"""

import unittest

from attack_framework import coverage as cov


class BuildCoverageRowTests(unittest.TestCase):
    def test_detected_row_hand_computed(self):
        row = cov.build_coverage_row(
            attack_name="replay", detected=True, detection_mechanism="T4 window_id mismatch",
            prevented=True, consequence_bounded=True, residual_note="none within the tested replay window",
        )
        self.assertEqual(row["attack"], "replay")
        self.assertTrue(row["detected"])
        self.assertEqual(row["detection_mechanism"], "T4 window_id mismatch")
        self.assertTrue(row["prevented"])
        self.assertTrue(row["consequence_bounded"])

    def test_no_detector_row_hand_computed(self):
        row = cov.build_coverage_row(
            attack_name="model_poisoning", detected=False, detection_mechanism=None,
            prevented=False, consequence_bounded=True, residual_note="training-pipeline poisoning: no detector by design",
        )
        self.assertFalse(row["detected"])
        self.assertIsNone(row["detection_mechanism"])

    def test_prevented_field_independent_of_detected(self):
        # detected but NOT prevented -- e.g. a tamper caught after the fact
        # but not blocked before use -- must be representable and distinct.
        row = cov.build_coverage_row(
            attack_name="x", detected=True, detection_mechanism="m",
            prevented=False, consequence_bounded=True, residual_note="n/a",
        )
        self.assertTrue(row["detected"])
        self.assertFalse(row["prevented"])

    def test_detected_true_requires_mechanism_string(self):
        with self.assertRaises(ValueError):
            cov.build_coverage_row(
                attack_name="x", detected=True, detection_mechanism=None,
                prevented=True, consequence_bounded=True, residual_note="n/a",
            )

    def test_detected_true_rejects_empty_mechanism_string(self):
        with self.assertRaises(ValueError):
            cov.build_coverage_row(
                attack_name="x", detected=True, detection_mechanism="",
                prevented=True, consequence_bounded=True, residual_note="n/a",
            )

    def test_detected_false_rejects_a_mechanism_string(self):
        with self.assertRaises(ValueError):
            cov.build_coverage_row(
                attack_name="x", detected=False, detection_mechanism="should not be here",
                prevented=False, consequence_bounded=True, residual_note="n/a",
            )

    def test_empty_residual_note_rejected(self):
        with self.assertRaises(ValueError):
            cov.build_coverage_row(
                attack_name="x", detected=True, detection_mechanism="m",
                prevented=True, consequence_bounded=True, residual_note="   ",
            )


class SummarizeCoverageTests(unittest.TestCase):
    def _row(self, detected, prevented, consequence_bounded):
        return cov.build_coverage_row(
            attack_name="a", detected=detected,
            detection_mechanism="m" if detected else None,
            prevented=prevented, consequence_bounded=consequence_bounded,
            residual_note="n/a",
        )

    def test_all_detected_and_bounded(self):
        rows = [self._row(True, True, True) for _ in range(4)]
        summary = cov.summarize_coverage(rows)
        self.assertEqual(summary["n_attacks"], 4)
        self.assertEqual(summary["detected_count"], 4)
        self.assertEqual(summary["no_detector_count"], 0)
        self.assertAlmostEqual(summary["consequence_bounded_fraction"], 1.0)

    def test_mixed_detected_and_no_detector(self):
        rows = [self._row(True, True, True), self._row(True, True, True),
                self._row(False, False, True), self._row(False, False, True)]
        summary = cov.summarize_coverage(rows)
        self.assertEqual(summary["detected_count"], 2)
        self.assertEqual(summary["no_detector_count"], 2)
        # no-detector rows are still consequence-bounded (T5 is unconditional)
        self.assertEqual(summary["consequence_bounded_count"], 4)
        self.assertAlmostEqual(summary["consequence_bounded_fraction"], 1.0)

    def test_a_consequence_bound_violation_would_surface_not_be_assumed(self):
        rows = [self._row(True, True, True), self._row(True, True, False)]
        summary = cov.summarize_coverage(rows)
        self.assertEqual(summary["consequence_bounded_count"], 1)
        self.assertAlmostEqual(summary["consequence_bounded_fraction"], 0.5)

    def test_detected_count_distinct_from_prevented_count(self):
        rows = [
            cov.build_coverage_row(attack_name="a", detected=True, detection_mechanism="m",
                                    prevented=False, consequence_bounded=True, residual_note="n/a"),
            cov.build_coverage_row(attack_name="b", detected=True, detection_mechanism="m",
                                    prevented=False, consequence_bounded=True, residual_note="n/a"),
            cov.build_coverage_row(attack_name="c", detected=False, detection_mechanism=None,
                                    prevented=False, consequence_bounded=True, residual_note="n/a"),
        ]
        summary = cov.summarize_coverage(rows)
        self.assertEqual(summary["detected_count"], 2)
        self.assertEqual(summary["prevented_count"], 0)

    def test_empty_rows_rejected(self):
        with self.assertRaises(ValueError):
            cov.summarize_coverage([])


if __name__ == "__main__":
    unittest.main()
