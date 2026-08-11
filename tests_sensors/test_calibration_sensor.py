"""Tests for sensors/calibration_sensor.py (Phase 8 Step 2).

Run with the pipeline venv:
    .venv-pipeline/bin/python -m unittest discover -s tests_sensors
"""

import unittest

import numpy as np

from sensors import calibration_sensor
from trust_kernel import sign

N_FEATURES = 20


def _enrollment(rng, n_trials=200, n_features=N_FEATURES):
    return rng.standard_normal((n_trials, n_features))


class MeasureCalibrationDriftTests(unittest.TestCase):
    def test_in_distribution_trial_scores_higher_than_drifted_trial(self):
        rng = np.random.default_rng(10)
        train_features = _enrollment(rng)
        stats = calibration_sensor.compute_enrollment_stats(train_features)

        in_distribution = rng.standard_normal(N_FEATURES)
        drifted = rng.standard_normal(N_FEATURES) + 10.0  # large session-shift offset

        in_dist_raw = calibration_sensor.measure_calibration_drift(in_distribution, stats)
        drifted_raw = calibration_sensor.measure_calibration_drift(drifted, stats)
        self.assertGreater(in_dist_raw, drifted_raw)

    def test_severe_drift_saturates_at_floor(self):
        rng = np.random.default_rng(11)
        train_features = _enrollment(rng)
        stats = calibration_sensor.compute_enrollment_stats(train_features)
        extreme = rng.standard_normal(N_FEATURES) + 1000.0
        raw = calibration_sensor.measure_calibration_drift(extreme, stats)
        self.assertEqual(raw, calibration_sensor.RAW_FLOOR)

    def test_output_is_clipped_int_in_range(self):
        rng = np.random.default_rng(12)
        train_features = _enrollment(rng)
        stats = calibration_sensor.compute_enrollment_stats(train_features)
        for _ in range(20):
            vec = rng.standard_normal(N_FEATURES) * rng.uniform(0.1, 50)
            raw = calibration_sensor.measure_calibration_drift(vec, stats)
            self.assertIsInstance(raw, int)
            self.assertGreaterEqual(raw, calibration_sensor.RAW_FLOOR)
            self.assertLessEqual(raw, calibration_sensor.RAW_CEIL)


class CalibrationSensorStatementTests(unittest.TestCase):
    def test_build_statement_produces_verifiable_signed_statement(self):
        pk, sk = sign.keypair_from_seed(b"\x03" * 32)
        sensor = calibration_sensor.CalibrationSensor(sk)
        rng = np.random.default_rng(13)
        train_features = _enrollment(rng)
        stats = calibration_sensor.compute_enrollment_stats(train_features)
        vec = rng.standard_normal(N_FEATURES)

        stmt = sensor.build_statement(
            feature_vector=vec, enrollment_stats=stats, window_id=5, claimed_at=50,
        )

        self.assertEqual(stmt["claim_type"], calibration_sensor.CALIBRATION_CLAIM_TYPE)
        from trust_kernel import schema
        self.assertTrue(schema.verify_statement_signature(pk, stmt))


if __name__ == "__main__":
    unittest.main()
