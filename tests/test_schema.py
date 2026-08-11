"""Unit tests for trust_kernel/schema.py (CLAUDE.md §8, §9, §10 -- T4
statement admission and verdict issuance)."""

import pathlib
import unittest

from trust_kernel import schema, sign
from trust_kernel.bands import DIMENSIONS, TrustLevel
from trust_kernel.policy import Verdict
from tests import key_fixtures as kf

CONFIG_DIR = pathlib.Path(__file__).resolve().parent.parent / "config"


class RegistryTests(unittest.TestCase):
    def test_key_registry_loads(self):
        reg = schema.load_key_registry(CONFIG_DIR / "key_registry.json")
        self.assertEqual(len(reg["keys"]), 6)

    def test_claim_registry_loads(self):
        reg = schema.load_claim_registry(CONFIG_DIR / "claim_registry.json")
        self.assertEqual(len(reg["claims"]), 6)

    def test_key_registry_hash_deterministic(self):
        h1 = schema.key_registry_hash(CONFIG_DIR / "key_registry.json")
        h2 = schema.key_registry_hash(CONFIG_DIR / "key_registry.json")
        self.assertEqual(h1, h2)

    def test_claim_registry_rejects_unknown_dimension(self):
        with self.assertRaises(schema.SchemaError):
            schema.validate_claim_registry({
                "claims": {"x": {"dimension": "NotADimension", "boundary": "TB2",
                                  "source_id": "x", "epoch_derived": False}}
            })

    def test_key_registry_rejects_bad_public_key(self):
        with self.assertRaises(Exception):
            schema.validate_key_registry({
                "keys": {"x": {"public_key": "00" * 32, "source_id": "x",
                                "boundary": "TB2", "authorized_claim_types": []}}
            })


class StatementSigningTests(unittest.TestCase):
    def setUp(self):
        self.pk, self.sk = kf.keypair_for("signal_sensor_v0")
        self.fields = schema.build_statement(
            key_id="signal_sensor_v0", source_id="signal_sensor_v0", boundary="TB2",
            claim_type="signal.provisional_v0", raw_measurement=42, window_id=7, claimed_at=1000,
        )

    def test_round_trip(self):
        signed = schema.sign_statement(self.sk, self.fields)
        self.assertTrue(schema.verify_statement_signature(self.pk, signed))

    def test_tamper_rejected(self):
        signed = schema.sign_statement(self.sk, self.fields)
        tampered = dict(signed)
        tampered["raw_measurement"] = 999
        self.assertFalse(schema.verify_statement_signature(self.pk, tampered))

    def test_wrong_key_rejected(self):
        signed = schema.sign_statement(self.sk, self.fields)
        other_pk, _ = kf.keypair_for("model_sensor_v0")
        self.assertFalse(schema.verify_statement_signature(other_pk, signed))

    def test_missing_sig_rejected(self):
        self.assertFalse(schema.verify_statement_signature(self.pk, self.fields))

    def test_window_hash_included_when_provided(self):
        fields = schema.build_statement(
            key_id="k", source_id="s", boundary="TB2", claim_type="c",
            raw_measurement=1, window_id=1, claimed_at=1, window_hash=b"\x01" * 32,
        )
        self.assertIn("window_hash", fields)

    def test_window_hash_absent_when_not_provided(self):
        self.assertNotIn("window_hash", self.fields)


class AdmissionOrderTests(unittest.TestCase):
    """One test per §10 verification-order step, each violating exactly
    that step while leaving every earlier step valid."""

    def setUp(self):
        self.key_registry = schema.load_key_registry(CONFIG_DIR / "key_registry.json")
        self.claim_registry = schema.load_claim_registry(CONFIG_DIR / "claim_registry.json")
        self.pk, self.sk = kf.keypair_for("signal_sensor_v0")

    def _valid_signed_statement(self, window_id=7):
        fields = schema.build_statement(
            key_id="signal_sensor_v0", source_id="signal_sensor_v0", boundary="TB2",
            claim_type="signal.provisional_v0", raw_measurement=42, window_id=window_id,
            claimed_at=1000,
        )
        return schema.sign_statement(self.sk, fields)

    def _admit(self, statement, **overrides):
        kwargs = dict(
            key_registry=self.key_registry, claim_registry=self.claim_registry,
            current_window_id=7, window_open_time_ms=0, arrival_time_ms=10,
        )
        kwargs.update(overrides)
        return schema.admit_statement(statement, **kwargs)

    def test_valid_statement_is_admitted(self):
        result = self._admit(self._valid_signed_statement())
        self.assertTrue(result.accepted)
        self.assertIsNone(result.failed_step)

    def test_invalid_signature_rejected_at_signature_step(self):
        signed = self._valid_signed_statement()
        tampered = dict(signed)
        tampered["raw_measurement"] = 999  # invalidates the signature only
        result = self._admit(tampered)
        self.assertFalse(result.accepted)
        self.assertEqual(result.failed_step, "signature")

    def test_unsupported_schema_version_rejected_at_schema_step(self):
        signed = self._valid_signed_statement()
        tampered = dict(signed)
        tampered["schema_version"] = 999
        # re-sign so the signature step passes and schema is what fails
        tampered = schema.sign_statement(self.sk, {k: v for k, v in tampered.items() if k != "sig"})
        result = self._admit(tampered)
        self.assertFalse(result.accepted)
        self.assertEqual(result.failed_step, "schema")

    def test_source_unauthorised_for_boundary_rejected_at_authorization_step(self):
        signed = self._valid_signed_statement()
        tampered = dict(signed)
        tampered["boundary"] = "TB3"  # not what this key is registered for
        tampered = schema.sign_statement(self.sk, {k: v for k, v in tampered.items() if k != "sig"})
        result = self._admit(tampered)
        self.assertFalse(result.accepted)
        self.assertEqual(result.failed_step, "authorization")

    def test_window_id_mismatch_rejected_at_window_id_step(self):
        signed = self._valid_signed_statement(window_id=7)
        result = self._admit(signed, current_window_id=8)
        self.assertFalse(result.accepted)
        self.assertEqual(result.failed_step, "window_id")

    def test_late_arrival_rejected_at_arrival_step(self):
        signed = self._valid_signed_statement()
        result = self._admit(signed, window_open_time_ms=0, arrival_time_ms=61)
        self.assertFalse(result.accepted)
        self.assertEqual(result.failed_step, "arrival")

    def test_arrival_exactly_at_deadline_is_late(self):
        signed = self._valid_signed_statement()
        result = self._admit(signed, window_open_time_ms=0, arrival_time_ms=60)
        self.assertFalse(result.accepted)
        self.assertEqual(result.failed_step, "arrival")

    def test_failure_order_is_fixed_earliest_violation_wins(self):
        """A statement violating BOTH signature and window_id must be
        rejected at 'signature' -- the earliest step in the fixed order --
        never reported as a later-step failure."""
        signed = self._valid_signed_statement(window_id=7)
        tampered = dict(signed)
        tampered["raw_measurement"] = 999  # breaks signature
        result = self._admit(tampered, current_window_id=999)  # also breaks window_id
        self.assertEqual(result.failed_step, "signature")


class CrossDomainReplayTests(unittest.TestCase):
    """§9: 'a statement's signed bytes presented as a verdict must fail on
    the domain tag.'"""

    def test_statement_signature_does_not_validate_as_a_verdict(self):
        pk, sk = kf.keypair_for("signal_sensor_v0")
        fields = schema.build_statement(
            key_id="signal_sensor_v0", source_id="signal_sensor_v0", boundary="TB2",
            claim_type="signal.provisional_v0", raw_measurement=42, window_id=7, claimed_at=1000,
        )
        signed_statement = schema.sign_statement(sk, fields)

        relabelled = dict(signed_statement)
        relabelled["kernel_sig"] = relabelled.pop("sig")
        self.assertFalse(schema.verify_verdict_signature(pk, relabelled))

    def test_verdict_signature_does_not_validate_as_a_statement(self):
        pk, sk = kf.kernel_keypair()
        effective = {d: TrustLevel.HIGH for d in DIMENSIONS}
        vfields = schema.build_verdict(
            window_id=7, evidence_root=b"\x00" * 32, effective_dims=effective,
            verdict=Verdict.Normal, policy_version="v1",
            crit_table_hash="a" * 64, ctpr_config_hash="b" * 64, roc_config_hash="c" * 64,
            claim_registry_hash="d" * 64, key_registry_hash="e" * 64,
            calibration_status="provisional", issued_at=1062, expires_at=1170,
        )
        signed_verdict = schema.sign_verdict(sk, vfields)
        relabelled = dict(signed_verdict)
        relabelled["sig"] = relabelled.pop("kernel_sig")
        self.assertFalse(schema.verify_statement_signature(pk, relabelled))


class EvidenceRootTests(unittest.TestCase):
    def setUp(self):
        _, sk = kf.keypair_for("signal_sensor_v0")
        self.sk = sk
        self.s1 = schema.sign_statement(sk, schema.build_statement(
            key_id="signal_sensor_v0", source_id="signal_sensor_v0", boundary="TB2",
            claim_type="signal.provisional_v0", raw_measurement=1, window_id=1, claimed_at=1))
        self.s2 = schema.sign_statement(sk, schema.build_statement(
            key_id="signal_sensor_v0", source_id="signal_sensor_v0", boundary="TB2",
            claim_type="signal.provisional_v0", raw_measurement=2, window_id=1, claimed_at=1))

    def test_order_independent(self):
        root1 = schema.build_evidence_root([self.s1, self.s2])
        root2 = schema.build_evidence_root([self.s2, self.s1])
        self.assertEqual(root1, root2)

    def test_dedup(self):
        root_single = schema.build_evidence_root([self.s1])
        root_dup = schema.build_evidence_root([self.s1, dict(self.s1)])
        self.assertEqual(root_single, root_dup)

    def test_different_sets_differ(self):
        root1 = schema.build_evidence_root([self.s1])
        root2 = schema.build_evidence_root([self.s1, self.s2])
        self.assertNotEqual(root1, root2)


class VerdictSigningTests(unittest.TestCase):
    def setUp(self):
        self.pk, self.sk = kf.kernel_keypair()
        self.effective = {d: TrustLevel.HIGH for d in DIMENSIONS}
        self.fields = schema.build_verdict(
            window_id=7, evidence_root=b"\x00" * 32, effective_dims=self.effective,
            verdict=Verdict.Normal, policy_version="v1",
            crit_table_hash="a" * 64, ctpr_config_hash="b" * 64, roc_config_hash="c" * 64,
            claim_registry_hash="d" * 64, key_registry_hash="e" * 64,
            calibration_status="provisional", issued_at=1062, expires_at=1170,
        )

    def test_round_trip(self):
        signed = schema.sign_verdict(self.sk, self.fields)
        self.assertTrue(schema.verify_verdict_signature(self.pk, signed))

    def test_tamper_rejected(self):
        signed = schema.sign_verdict(self.sk, self.fields)
        tampered = dict(signed)
        tampered["verdict"] = "Safe"
        self.assertFalse(schema.verify_verdict_signature(self.pk, tampered))

    def test_missing_dimension_rejected_at_build(self):
        incomplete = {d: TrustLevel.HIGH for d in DIMENSIONS if d != "Signal"}
        with self.assertRaises(schema.SchemaError):
            schema.build_verdict(
                window_id=7, evidence_root=b"\x00" * 32, effective_dims=incomplete,
                verdict=Verdict.Normal, policy_version="v1",
                crit_table_hash="a" * 64, ctpr_config_hash="b" * 64, roc_config_hash="c" * 64,
                claim_registry_hash="d" * 64, key_registry_hash="e" * 64,
                calibration_status="provisional", issued_at=1062, expires_at=1170,
            )


if __name__ == "__main__":
    unittest.main()
