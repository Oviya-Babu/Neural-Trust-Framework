"""Unit tests for enforcement/clamp.py (CLAUDE.md §5, §6)."""

import inspect
import json
import pathlib
import shutil
import tempfile
import unittest

from enforcement import clamp
from tests import window_fixtures as wf
from tests.enforcement_fixtures import GuardedVerdictDict

CONFIG_DIR = pathlib.Path(__file__).resolve().parent.parent / "config"
CEIL_PATH = CONFIG_DIR / "ceil.json"
ENV_PATH = CONFIG_DIR / "env.json"


class ConfigLoadTests(unittest.TestCase):
    def test_real_ceil_and_env_load_and_bind(self):
        ceil, env = clamp.load_envelope_configs(CEIL_PATH, ENV_PATH)
        self.assertEqual(ceil, {"max_speed": 1000, "max_acceleration": 500})
        self.assertEqual(env["Normal"], {"max_speed": 1600, "max_acceleration": 800})
        self.assertEqual(env["Constrained"], {"max_speed": 600, "max_acceleration": 300})
        self.assertEqual(env["Safe"], {"max_speed": 0, "max_acceleration": 0})

    def test_ceil_rejects_float(self):
        raw = {"max_speed": 1000.0, "max_acceleration": 500}
        with self.assertRaises(clamp.EnforcementConfigError):
            clamp.validate_ceil(raw)

    def test_ceil_rejects_negative(self):
        with self.assertRaises(clamp.EnforcementConfigError):
            clamp.validate_ceil({"max_speed": -1, "max_acceleration": 500})

    def test_ceil_rejects_missing_field(self):
        with self.assertRaises(clamp.EnforcementConfigError):
            clamp.validate_ceil({"max_speed": 1000})

    def test_env_rejects_missing_zone(self):
        with self.assertRaises(clamp.EnforcementConfigError):
            clamp.validate_env({"Safe": {"max_speed": 0, "max_acceleration": 0},
                                "Constrained": {"max_speed": 600, "max_acceleration": 300}})

    def test_binding_condition_holds_for_reference_config(self):
        ceil = clamp.load_ceil(CEIL_PATH)
        env = clamp.load_env(ENV_PATH)
        clamp.validate_binding(ceil, env)  # must not raise

    def test_binding_condition_fails_closed_when_ceil_not_strictly_below_normal(self):
        """§6: 'a non-binding Ceil makes T5 true-but-empty and must be
        caught, not shipped.'"""
        ceil = {"max_speed": 1600, "max_acceleration": 500}  # equals Env(Normal).max_speed
        env = clamp.load_env(ENV_PATH)
        with self.assertRaises(clamp.EnforcementConfigError):
            clamp.validate_binding(ceil, env)

    def test_binding_condition_fails_closed_on_load_envelope_configs(self):
        tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmpdir, ignore_errors=True)
        bad_ceil = pathlib.Path(tmpdir) / "ceil.json"
        bad_ceil.write_text(json.dumps({"max_speed": 2000, "max_acceleration": 500}))
        with self.assertRaises(clamp.EnforcementConfigError):
            clamp.load_envelope_configs(bad_ceil, ENV_PATH)


class RealiseTests(unittest.TestCase):
    def setUp(self):
        self.ceil, self.env = clamp.load_envelope_configs(CEIL_PATH, ENV_PATH)

    def test_normal_is_clamped_by_ceil(self):
        """Figure [T5]: intended (1600, 800) vs realised (1000, 500)."""
        self.assertEqual(clamp.realise("Normal", self.env, self.ceil),
                          {"max_speed": 1000, "max_acceleration": 500})

    def test_constrained_is_not_clamped_reference_config(self):
        self.assertEqual(clamp.realise("Constrained", self.env, self.ceil),
                          {"max_speed": 600, "max_acceleration": 300})

    def test_safe_is_zero(self):
        self.assertEqual(clamp.realise("Safe", self.env, self.ceil),
                          {"max_speed": 0, "max_acceleration": 0})

    def test_realise_never_exceeds_ceil_regardless_of_env_indicated(self):
        for name in ("Safe", "Constrained", "Normal"):
            r = clamp.realise(name, self.env, self.ceil)
            self.assertLessEqual(r["max_speed"], self.ceil["max_speed"])
            self.assertLessEqual(r["max_acceleration"], self.ceil["max_acceleration"])

    def test_unknown_verdict_zone_rejected(self):
        with self.assertRaises(clamp.EnforcementConfigError):
            clamp.realise("Superuser", self.env, self.ceil)


class EnforcerViewTests(unittest.TestCase):
    def test_five_fields_ground_truth(self):
        """Hardcoded independently of clamp.ENFORCER_FIELDS -- same class of
        gap as the L-constant / GENESIS_PREV_HASH self-reference fixes."""
        self.assertEqual(
            clamp.EnforcerView.__slots__,
            ("schema_version", "window_id", "verdict", "expires_at", "kernel_sig"),
        )

    def test_from_verdict_object_extracts_exactly_five_fields(self):
        statements = wf.healthy_window(window_id=1)
        verdict_obj = wf.issue_signed_verdict(statements, window_id=1)
        view = clamp.EnforcerView.from_verdict_object(verdict_obj)
        self.assertEqual(view.window_id, 1)
        self.assertEqual(view.verdict, verdict_obj["verdict"])
        self.assertEqual(view.expires_at, verdict_obj["expires_at"])
        self.assertEqual(view.kernel_sig, verdict_obj["kernel_sig"])

    def test_view_cannot_hold_a_forbidden_attribute(self):
        """__slots__ makes this a structural guarantee, not a convention:
        no code holding an EnforcerView can ever reach evidence_root through
        it, even by accident."""
        statements = wf.healthy_window(window_id=1)
        verdict_obj = wf.issue_signed_verdict(statements, window_id=1)
        view = clamp.EnforcerView.from_verdict_object(verdict_obj)
        with self.assertRaises(AttributeError):
            view.evidence_root = verdict_obj["evidence_root"]


class AcceptCacheTests(unittest.TestCase):
    def test_fresh_window_id_not_contained(self):
        cache = clamp.AcceptCache(size=2)
        self.assertFalse(cache.contains(1))

    def test_recorded_window_id_is_contained(self):
        cache = clamp.AcceptCache(size=2)
        cache.record(1)
        self.assertTrue(cache.contains(1))

    def test_ring_evicts_oldest_beyond_size(self):
        cache = clamp.AcceptCache(size=2)
        cache.record(1)
        cache.record(2)
        cache.record(3)
        self.assertFalse(cache.contains(1))  # evicted
        self.assertTrue(cache.contains(2))
        self.assertTrue(cache.contains(3))


class AcceptTests(unittest.TestCase):
    def setUp(self):
        self.kernel_pk = wf.kernel_public_key()
        self.cache = clamp.AcceptCache(size=2)
        statements = wf.healthy_window(window_id=7)
        self.verdict_obj = wf.issue_signed_verdict(statements, window_id=7, issued_at=62, expires_at=170)

    def test_honest_verdict_is_accepted(self):
        result = clamp.accept(self.verdict_obj, self.kernel_pk, now_ms=100, cache=self.cache)
        self.assertTrue(result.accepted)
        self.assertIsNotNone(result.view)

    def test_invalid_signature_rejected_at_signature_step(self):
        tampered = dict(self.verdict_obj)
        tampered["window_id"] = 8  # any post-signature mutation invalidates kernel_sig
        result = clamp.accept(tampered, self.kernel_pk, now_ms=100, cache=self.cache)
        self.assertFalse(result.accepted)
        self.assertEqual(result.reason, "signature")

    def test_unsupported_schema_version_rejected_when_validly_signed(self):
        """schema_version must be checked as its own step, distinct from
        signature validity: sign a verdict whose schema_version is itself
        wrong, so the signature covers exactly that bad value."""
        statements = wf.healthy_window(window_id=9)
        effective, verdict = wf.compute_verdict(statements)
        from trust_kernel import schema
        from trust_kernel import policy as policy_mod, ctpr as ctpr_mod
        from trust_kernel.bands import roc_config_hash
        evidence_root = schema.build_evidence_root(statements)
        vfields = schema.build_verdict(
            window_id=9, evidence_root=evidence_root, effective_dims=effective, verdict=verdict,
            policy_version="v1",
            crit_table_hash=policy_mod.crit_table_hash(wf.CONFIG_PATHS["crit_table"]),
            ctpr_config_hash=ctpr_mod.ctpr_config_hash(wf.CONFIG_PATHS["ctpr"]),
            roc_config_hash=roc_config_hash(wf.CONFIG_PATHS["eis"]),
            claim_registry_hash=schema.claim_registry_hash(wf.CONFIG_PATHS["claim_registry"]),
            key_registry_hash=schema.key_registry_hash(wf.CONFIG_PATHS["key_registry"]),
            calibration_status="provisional", issued_at=62, expires_at=170,
        )
        vfields = dict(vfields)
        vfields["schema_version"] = 99
        from tests import key_fixtures as kf
        _, kernel_sk = kf.kernel_keypair()
        bad_schema_verdict = schema.sign_verdict(kernel_sk, vfields)

        result = clamp.accept(bad_schema_verdict, self.kernel_pk, now_ms=100, cache=self.cache)
        self.assertFalse(result.accepted)
        self.assertEqual(result.reason, "schema")

    def test_replayed_window_id_rejected(self):
        first = clamp.accept(self.verdict_obj, self.kernel_pk, now_ms=100, cache=self.cache)
        self.assertTrue(first.accepted)
        second = clamp.accept(self.verdict_obj, self.kernel_pk, now_ms=101, cache=self.cache)
        self.assertFalse(second.accepted)
        self.assertEqual(second.reason, "replay")

    def test_expired_verdict_rejected(self):
        result = clamp.accept(self.verdict_obj, self.kernel_pk, now_ms=170, cache=self.cache)
        self.assertFalse(result.accepted)
        self.assertEqual(result.reason, "expired")

    def test_accept_touches_no_field_outside_the_five(self):
        """Dynamic instantiation of the §6 field-boundary property: run the
        real accept() against a GuardedVerdictDict wrapping a FULL verdict
        object (including evidence_root, effective_dims, policy_version,
        and every other forbidden field) and confirm no forbidden field is
        ever subscripted."""
        guarded = GuardedVerdictDict(self.verdict_obj)
        result = clamp.accept(guarded, self.kernel_pk, now_ms=100, cache=clamp.AcceptCache(size=2))
        self.assertTrue(result.accepted)

    def test_accept_has_no_round_knowledge_parameter(self):
        """§6: 'the enforcer must never learn the round from a host-
        controlled input.' Guards against a future regression that adds a
        current_window_id-style parameter to accept()."""
        params = set(inspect.signature(clamp.accept).parameters)
        self.assertEqual(params, {"verdict_obj", "kernel_public_key", "now_ms", "cache"})


class AcceptAndClampTests(unittest.TestCase):
    def setUp(self):
        self.kernel_pk = wf.kernel_public_key()
        self.ceil, self.env = clamp.load_envelope_configs(CEIL_PATH, ENV_PATH)

    def test_accepted_normal_produces_ceil_clamped_envelope(self):
        forged = wf.issue_forged_verdict("Normal", window_id=50)
        decision = clamp.accept_and_clamp(
            forged, self.kernel_pk, now_ms=100, cache=clamp.AcceptCache(),
            env=self.env, ceil=self.ceil,
        )
        self.assertTrue(decision.accepted)
        self.assertEqual(decision.envelope, {"max_speed": 1000, "max_acceleration": 500})

    def test_rejected_verdict_produces_no_envelope_at_all(self):
        forged = wf.issue_forged_verdict("Normal", window_id=51)
        tampered = dict(forged)
        tampered["window_id"] = 999
        decision = clamp.accept_and_clamp(
            tampered, self.kernel_pk, now_ms=100, cache=clamp.AcceptCache(),
            env=self.env, ceil=self.ceil,
        )
        self.assertFalse(decision.accepted)
        self.assertIsNone(decision.envelope)


if __name__ == "__main__":
    unittest.main()
