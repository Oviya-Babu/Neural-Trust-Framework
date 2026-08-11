"""Tests for sensors/device_sensor.py (Phase 8 Step 3). Drives real
OpenSSL DTLS handshakes over UDP loopback -- slower than the other sensor
tests and requires the `openssl` binary with DTLS support (present on this
system, verified via `openssl s_server -help | grep dtls`).

Includes the three attack cases named in the task spec: invalid cert,
expired cert, replayed sequence.

Run with the pipeline venv:
    .venv-pipeline/bin/python -m unittest discover -s tests_sensors
"""

import unittest

from sensors import device_certs, device_sensor
from trust_kernel import schema, sign


class DtlsHandshakeHonestPathTests(unittest.TestCase):
    def test_valid_cert_signed_by_pinned_ca_handshakes_ok(self):
        ca = device_certs.make_ca()
        srv = device_certs.make_valid_server_cert(ca)
        result = device_sensor.run_dtls_handshake(srv["combined_pem"], ca["cert_pem"])
        self.assertTrue(result["handshake_ok"], result["client_output"])
        self.assertEqual(result["client_exit_code"], 0)


class InvalidCertAttackTests(unittest.TestCase):
    """Attack case 1: invalid cert -- not signed by the pinned CA."""

    def test_untrusted_cert_fails_handshake(self):
        ca = device_certs.make_ca()
        untrusted = device_certs.make_untrusted_server_cert()
        result = device_sensor.run_dtls_handshake(untrusted["combined_pem"], ca["cert_pem"])
        self.assertFalse(result["handshake_ok"])
        self.assertNotEqual(result["client_exit_code"], 0)

    def test_untrusted_cert_yields_floor_measurement(self):
        ca = device_certs.make_ca()
        untrusted = device_certs.make_untrusted_server_cert()
        result = device_sensor.run_dtls_handshake(untrusted["combined_pem"], ca["cert_pem"])
        guard = device_sensor.SequenceReplayGuard()
        raw = device_sensor.measure_device_link(result, guard.check_and_record(1))
        self.assertEqual(raw, device_sensor.DEVICE_TRUST_FLOOR)


class ExpiredCertAttackTests(unittest.TestCase):
    """Attack case 2: expired cert -- signed by the real CA, validity
    window entirely in the past."""

    def test_expired_cert_fails_handshake(self):
        ca = device_certs.make_ca()
        expired = device_certs.make_expired_server_cert(ca)
        result = device_sensor.run_dtls_handshake(expired["combined_pem"], ca["cert_pem"])
        self.assertFalse(result["handshake_ok"])
        self.assertNotEqual(result["client_exit_code"], 0)


class ReplayedSequenceAttackTests(unittest.TestCase):
    """Attack case 3: replayed sequence -- a previously-seen sequence
    number re-presented."""

    def test_first_presentation_accepted_replay_rejected(self):
        guard = device_sensor.SequenceReplayGuard()
        self.assertTrue(guard.check_and_record(5))
        self.assertFalse(guard.check_and_record(5))  # exact replay

    def test_old_sequence_outside_window_rejected(self):
        guard = device_sensor.SequenceReplayGuard(window_size=8)
        self.assertTrue(guard.check_and_record(100))
        self.assertFalse(guard.check_and_record(10))  # far behind the window

    def test_out_of_order_within_window_accepted_once(self):
        guard = device_sensor.SequenceReplayGuard(window_size=16)
        self.assertTrue(guard.check_and_record(10))
        self.assertTrue(guard.check_and_record(12))
        self.assertTrue(guard.check_and_record(11))  # out of order, still fresh
        self.assertFalse(guard.check_and_record(11))  # now a replay

    def test_replay_on_otherwise_valid_handshake_yields_floor(self):
        ca = device_certs.make_ca()
        srv = device_certs.make_valid_server_cert(ca)
        result = device_sensor.run_dtls_handshake(srv["combined_pem"], ca["cert_pem"])
        self.assertTrue(result["handshake_ok"])

        guard = device_sensor.SequenceReplayGuard()
        first = device_sensor.measure_device_link(result, guard.check_and_record(1))
        replay = device_sensor.measure_device_link(result, guard.check_and_record(1))
        self.assertEqual(first, device_sensor.DEVICE_TRUST_CEIL)
        self.assertEqual(replay, device_sensor.DEVICE_TRUST_FLOOR)


class DeviceSensorStatementTests(unittest.TestCase):
    def test_build_statement_honest_path_produces_ceil_and_verifies(self):
        pk, sk = sign.keypair_from_seed(b"\x0e" * 32)
        ca = device_certs.make_ca()
        srv = device_certs.make_valid_server_cert(ca)
        result = device_sensor.run_dtls_handshake(srv["combined_pem"], ca["cert_pem"])

        sensor = device_sensor.DeviceSensor(sk)
        stmt = sensor.build_statement(
            handshake_result=result, sequence_number=1, window_id=1, claimed_at=0,
        )
        self.assertEqual(stmt["raw_measurement"], device_sensor.DEVICE_TRUST_CEIL)
        self.assertTrue(schema.verify_statement_signature(pk, stmt))


if __name__ == "__main__":
    unittest.main()
