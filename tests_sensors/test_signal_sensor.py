"""Tests for sensors/signal_sensor.py (Phase 8 Step 2).

Run with the pipeline venv (numpy/scipy needed for real spectral analysis):
    .venv-pipeline/bin/python -m unittest discover -s tests_sensors
"""

import unittest

import numpy as np

from sensors import signal_sensor
from trust_kernel import sign

SFREQ = 250.0
N_SAMPLES = 1000
N_CHANNELS = 4


def _sine(freq_hz, n_samples, sfreq, amplitude=1.0, phase=0.0):
    t = np.arange(n_samples) / sfreq
    return amplitude * np.sin(2 * np.pi * freq_hz * t + phase)


class MeasureSignalQualityTests(unittest.TestCase):
    def test_clean_mu_beta_signal_scores_higher_than_broadband_noise(self):
        rng = np.random.default_rng(0)
        clean = np.stack([_sine(12.0, N_SAMPLES, SFREQ) + 0.01 * rng.standard_normal(N_SAMPLES)
                           for _ in range(N_CHANNELS)])
        noisy = np.stack([5.0 * rng.standard_normal(N_SAMPLES) for _ in range(N_CHANNELS)])

        clean_raw = signal_sensor.measure_signal_quality(clean, SFREQ)
        noisy_raw = signal_sensor.measure_signal_quality(noisy, SFREQ)
        self.assertGreater(clean_raw, noisy_raw)

    def test_line_noise_contamination_lowers_score(self):
        rng = np.random.default_rng(1)
        base = np.stack([_sine(12.0, N_SAMPLES, SFREQ) + 0.01 * rng.standard_normal(N_SAMPLES)
                          for _ in range(N_CHANNELS)])
        contaminated = base + np.stack([_sine(50.0, N_SAMPLES, SFREQ, amplitude=3.0)
                                         for _ in range(N_CHANNELS)])

        base_raw = signal_sensor.measure_signal_quality(base, SFREQ)
        contaminated_raw = signal_sensor.measure_signal_quality(contaminated, SFREQ)
        self.assertGreater(base_raw, contaminated_raw)

    def test_output_is_clipped_int_in_range(self):
        rng = np.random.default_rng(2)
        extreme = np.stack([1000.0 * rng.standard_normal(N_SAMPLES) for _ in range(N_CHANNELS)])
        raw = signal_sensor.measure_signal_quality(extreme, SFREQ)
        self.assertIsInstance(raw, int)
        self.assertGreaterEqual(raw, signal_sensor.RAW_FLOOR)
        self.assertLessEqual(raw, signal_sensor.RAW_CEIL)


class SignalSensorStatementTests(unittest.TestCase):
    def test_build_statement_produces_verifiable_signed_statement(self):
        pk, sk = sign.keypair_from_seed(b"\x01" * 32)
        sensor = signal_sensor.SignalSensor(sk)
        rng = np.random.default_rng(3)
        epoch = np.stack([_sine(12.0, N_SAMPLES, SFREQ) + 0.01 * rng.standard_normal(N_SAMPLES)
                           for _ in range(N_CHANNELS)])

        stmt = sensor.build_statement(raw_epoch=epoch, sfreq=SFREQ, window_id=7, claimed_at=100)

        self.assertEqual(stmt["claim_type"], signal_sensor.SIGNAL_CLAIM_TYPE)
        self.assertEqual(stmt["source_id"], signal_sensor.SIGNAL_SOURCE_ID)
        self.assertIsInstance(stmt["raw_measurement"], int)
        from trust_kernel import schema
        self.assertTrue(schema.verify_statement_signature(pk, stmt))

    def test_no_confidence_or_band_field_in_statement(self):
        pk, sk = sign.keypair_from_seed(b"\x02" * 32)
        sensor = signal_sensor.SignalSensor(sk)
        epoch = np.zeros((N_CHANNELS, N_SAMPLES))
        stmt = sensor.build_statement(raw_epoch=epoch, sfreq=SFREQ, window_id=1, claimed_at=0)
        forbidden = {"confidence", "trust_level", "band", "prev_hash"}
        self.assertEqual(set(stmt.keys()) & forbidden, set())


if __name__ == "__main__":
    unittest.main()
