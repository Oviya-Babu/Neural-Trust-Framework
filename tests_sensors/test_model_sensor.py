"""Tests for sensors/model_sensor.py (Phase 8 Step 2). Includes the three
attack cases named in the task spec: bit-flipped weights -> hash mismatch,
stripped signature -> verify fail, unsigned substitute -> rejected.

Run with the pipeline venv:
    .venv-pipeline/bin/python -m unittest discover -s tests_sensors
"""

import unittest

import numpy as np

from sensors import model_sensor
from trust_kernel import schema, sign


class _FakeClassifier:
    """Stand-in with the same coef_/intercept_/classes_ shape sklearn's
    LogisticRegression exposes -- avoids depending on an actually-trained
    model just to exercise artifact serialization/signing."""

    def __init__(self, seed=0):
        rng = np.random.default_rng(seed)
        self.coef_ = rng.standard_normal((4, 20))
        self.intercept_ = rng.standard_normal(4)
        self.classes_ = np.array([0, 1, 2, 3])


class ArtifactSerializationTests(unittest.TestCase):
    def test_serialization_is_deterministic(self):
        clf = _FakeClassifier()
        a = model_sensor.serialize_classifier_artifact(clf)
        b = model_sensor.serialize_classifier_artifact(clf)
        self.assertEqual(a, b)

    def test_different_weights_serialize_differently(self):
        a = model_sensor.serialize_classifier_artifact(_FakeClassifier(seed=1))
        b = model_sensor.serialize_classifier_artifact(_FakeClassifier(seed=2))
        self.assertNotEqual(a, b)


class VerifyArtifactHonestPathTests(unittest.TestCase):
    def setUp(self):
        self.artifact_pk, self.artifact_sk = sign.keypair_from_seed(b"\x04" * 32)
        self.clf = _FakeClassifier()
        self.artifact_bytes = model_sensor.serialize_classifier_artifact(self.clf)
        self.signing_record = model_sensor.sign_artifact(self.artifact_sk, self.artifact_bytes)

    def test_genuine_artifact_verifies(self):
        self.assertTrue(
            model_sensor.verify_artifact(self.artifact_pk, self.artifact_bytes, self.signing_record)
        )

    def test_measure_model_integrity_returns_ceil_for_genuine_artifact(self):
        raw = model_sensor.measure_model_integrity(self.artifact_bytes, self.artifact_pk, self.signing_record)
        self.assertEqual(raw, model_sensor.MODEL_TRUST_CEIL)


class BitFlippedWeightsAttackTests(unittest.TestCase):
    """Attack case 1: bit-flipped weights -> hash mismatch."""

    def test_tampered_weights_fail_hash_check(self):
        artifact_pk, artifact_sk = sign.keypair_from_seed(b"\x05" * 32)
        clf = _FakeClassifier()
        genuine_bytes = model_sensor.serialize_classifier_artifact(clf)
        signing_record = model_sensor.sign_artifact(artifact_sk, genuine_bytes)

        clf.coef_[0, 0] += 1e-3  # a single bit-flip-scale tamper to the weights
        tampered_bytes = model_sensor.serialize_classifier_artifact(clf)

        self.assertNotEqual(model_sensor.artifact_hash(tampered_bytes), signing_record["sha256"])
        self.assertFalse(model_sensor.verify_artifact(artifact_pk, tampered_bytes, signing_record))
        raw = model_sensor.measure_model_integrity(tampered_bytes, artifact_pk, signing_record)
        self.assertEqual(raw, model_sensor.MODEL_TRUST_FLOOR)


class StrippedSignatureAttackTests(unittest.TestCase):
    """Attack case 2: stripped signature -> verify fail."""

    def test_missing_sig_field_fails_closed(self):
        artifact_pk, artifact_sk = sign.keypair_from_seed(b"\x06" * 32)
        clf = _FakeClassifier()
        artifact_bytes = model_sensor.serialize_classifier_artifact(clf)
        signing_record = model_sensor.sign_artifact(artifact_sk, artifact_bytes)
        del signing_record["sig"]

        self.assertFalse(model_sensor.verify_artifact(artifact_pk, artifact_bytes, signing_record))

    def test_corrupted_sig_bytes_fail_closed(self):
        artifact_pk, artifact_sk = sign.keypair_from_seed(b"\x07" * 32)
        clf = _FakeClassifier()
        artifact_bytes = model_sensor.serialize_classifier_artifact(clf)
        signing_record = model_sensor.sign_artifact(artifact_sk, artifact_bytes)
        signing_record["sig"] = "00" * 64  # structurally valid hex, wrong signature

        self.assertFalse(model_sensor.verify_artifact(artifact_pk, artifact_bytes, signing_record))


class UnsignedSubstituteAttackTests(unittest.TestCase):
    """Attack case 3: unsigned substitute -> rejected (no signing record
    for this artifact at all -- distinct from a corrupted/missing sig on a
    record that does exist)."""

    def test_no_signing_record_rejected(self):
        artifact_pk, _ = sign.keypair_from_seed(b"\x08" * 32)
        substitute_bytes = model_sensor.serialize_classifier_artifact(_FakeClassifier(seed=99))
        self.assertFalse(model_sensor.verify_artifact(artifact_pk, substitute_bytes, None))

    def test_wrong_artifact_against_someone_elses_signing_record_rejected(self):
        artifact_pk, artifact_sk = sign.keypair_from_seed(b"\x09" * 32)
        genuine_bytes = model_sensor.serialize_classifier_artifact(_FakeClassifier(seed=1))
        signing_record = model_sensor.sign_artifact(artifact_sk, genuine_bytes)

        substitute_bytes = model_sensor.serialize_classifier_artifact(_FakeClassifier(seed=2))
        self.assertFalse(model_sensor.verify_artifact(artifact_pk, substitute_bytes, signing_record))


class ModelSensorStatementTests(unittest.TestCase):
    def test_build_statement_produces_verifiable_signed_statement(self):
        artifact_pk, artifact_sk = sign.keypair_from_seed(b"\x0a" * 32)
        sensor_pk, sensor_sk = sign.keypair_from_seed(b"\x0b" * 32)
        clf = _FakeClassifier()
        artifact_bytes = model_sensor.serialize_classifier_artifact(clf)
        signing_record = model_sensor.sign_artifact(artifact_sk, artifact_bytes)

        sensor = model_sensor.ModelSensor(sensor_sk)
        stmt = sensor.build_statement(
            artifact_bytes=artifact_bytes, artifact_public_key=artifact_pk,
            signing_record=signing_record, window_id=1, claimed_at=0,
        )

        self.assertEqual(stmt["raw_measurement"], model_sensor.MODEL_TRUST_CEIL)
        self.assertTrue(schema.verify_statement_signature(sensor_pk, stmt))

    def test_artifact_key_and_sensor_key_are_independent(self):
        """The artifact-signing key and the sensor's statement-signing key
        must be distinct identities (module docstring) -- a sensor key
        must never be able to forge a valid artifact signing record."""
        artifact_pk, _ = sign.keypair_from_seed(b"\x0c" * 32)
        _, sensor_sk_wrong = sign.keypair_from_seed(b"\x0d" * 32)
        clf = _FakeClassifier()
        artifact_bytes = model_sensor.serialize_classifier_artifact(clf)

        forged_record = model_sensor.sign_artifact(sensor_sk_wrong, artifact_bytes)
        self.assertFalse(model_sensor.verify_artifact(artifact_pk, artifact_bytes, forged_record))


if __name__ == "__main__":
    unittest.main()
