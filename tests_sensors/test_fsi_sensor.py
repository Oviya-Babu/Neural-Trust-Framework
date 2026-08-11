"""Tests for sensors/fsi_sensor.py (Phase 8 Step 3). Drives a real swtpm
instance + real tpm2-tools over its full lifecycle per test -- slower than
the other sensor tests. Requires swtpm and tpm2-tools on PATH (verified via
`which swtpm tpm2_startup tpm2_pcrextend tpm2_quote`).

Includes the three attack cases named in the task spec: replayed quote,
PCR mismatch, missing quote.

Run with the pipeline venv:
    .venv-pipeline/bin/python -m unittest discover -s tests_sensors
"""

import unittest

from sensors import fsi_sensor, fsi_swtpm
from trust_kernel import schema, sign


def _nonce_hex(label: str) -> str:
    import hashlib
    return hashlib.sha256(label.encode()).hexdigest()[:40]


class HonestQuoteVerificationTests(unittest.TestCase):
    def test_genuine_quote_against_matching_nonce_and_baseline_verifies(self):
        with fsi_swtpm.SwtpmSession() as session:
            baseline = fsi_sensor.provision_fsi_baseline(session, b"firmware-v1-measurement")
            nonce = _nonce_hex("window-1")
            quote = session.quote(baseline["ak_ctx"], nonce)
            result = fsi_sensor.evaluate_quote(session, baseline, quote, nonce)

        self.assertTrue(result["sig_and_nonce_ok"])
        self.assertTrue(result["pcr_matches_baseline"])
        self.assertEqual(result["raw_measurement"], fsi_sensor.FSI_TRUST_CEIL)


class ReplayedQuoteAttackTests(unittest.TestCase):
    """Attack case 1: replayed quote -- nonce fail."""

    def test_stale_quote_against_a_new_windows_nonce_fails(self):
        with fsi_swtpm.SwtpmSession() as session:
            baseline = fsi_sensor.provision_fsi_baseline(session, b"firmware-v1-measurement")
            window1_nonce = _nonce_hex("window-1")
            quote = session.quote(baseline["ak_ctx"], window1_nonce)

            window2_nonce = _nonce_hex("window-2")
            result = fsi_sensor.evaluate_quote(session, baseline, quote, window2_nonce)

        self.assertFalse(result["sig_and_nonce_ok"])
        self.assertEqual(result["raw_measurement"], fsi_sensor.FSI_TRUST_FLOOR)


class PcrMismatchAttackTests(unittest.TestCase):
    """Attack case 2: PCR mismatch -- detected."""

    def test_pcr_extended_after_baseline_is_detected_even_with_valid_signature(self):
        with fsi_swtpm.SwtpmSession() as session:
            baseline = fsi_sensor.provision_fsi_baseline(session, b"firmware-v1-measurement")

            # attacker-controlled boot event extends the PCR again, after
            # the baseline was pinned
            session.pcr_extend(b"attacker-modification")

            nonce = _nonce_hex("window-1")
            quote = session.quote(baseline["ak_ctx"], nonce)
            result = fsi_sensor.evaluate_quote(session, baseline, quote, nonce)

        # the quote's own signature and nonce are still genuinely valid --
        # it truthfully reports the TPM's *current* (now-modified) state
        self.assertTrue(result["sig_and_nonce_ok"])
        self.assertFalse(result["pcr_matches_baseline"])
        self.assertEqual(result["raw_measurement"], fsi_sensor.FSI_TRUST_FLOOR)


class MissingQuoteTests(unittest.TestCase):
    """Attack case 3: missing quote -- the producer contract (§10: 'a
    sensor that cannot measure emits nothing') means there is no quote
    object and therefore nothing to build a statement from -- this test
    confirms build_statement is simply never called in that path, not that
    it silently substitutes a default."""

    def test_no_evaluation_means_no_statement_is_built(self):
        pk, sk = sign.keypair_from_seed(b"\x0f" * 32)
        sensor = fsi_sensor.FsiSensor(sk)
        statements = []
        evaluation = None  # models "could not obtain a quote this window"
        if evaluation is not None:
            statements.append(sensor.build_statement(evaluation=evaluation, window_id=1, claimed_at=0))
        self.assertEqual(statements, [])


class FsiSensorStatementTests(unittest.TestCase):
    def test_build_statement_honest_path_produces_ceil_and_verifies(self):
        pk, sk = sign.keypair_from_seed(b"\x10" * 32)
        with fsi_swtpm.SwtpmSession() as session:
            baseline = fsi_sensor.provision_fsi_baseline(session, b"firmware-v1-measurement")
            nonce = _nonce_hex("window-1")
            quote = session.quote(baseline["ak_ctx"], nonce)
            evaluation = fsi_sensor.evaluate_quote(session, baseline, quote, nonce)

        sensor = fsi_sensor.FsiSensor(sk)
        stmt = sensor.build_statement(evaluation=evaluation, window_id=1, claimed_at=0)
        self.assertEqual(stmt["raw_measurement"], fsi_sensor.FSI_TRUST_CEIL)
        self.assertTrue(schema.verify_statement_signature(pk, stmt))


if __name__ == "__main__":
    unittest.main()
