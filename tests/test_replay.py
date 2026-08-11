"""Unit tests for evidence_plane/replay.py (CLAUDE.md §8, §12, §13)."""

import json
import pathlib
import shutil
import tempfile
import unittest

from evidence_plane import replay as replay_mod
from tests import window_fixtures as wf


class ReplayAgreementTests(unittest.TestCase):
    def test_honest_replay_agrees(self):
        statements = wf.healthy_window(window_id=7)
        verdict = wf.issue_signed_verdict(statements, window_id=7)
        result = replay_mod.replay_verdict(verdict, statements, config_paths=wf.CONFIG_PATHS)
        self.assertTrue(result.agreement)
        self.assertFalse(result.config_mismatch)
        self.assertFalse(result.evidence_mismatch)

    def test_replay_over_a_batch_agrees_for_every_verdict(self):
        """§12/§17 deliverable (b): replay agreement rate over a batch."""
        batch = []
        for i, raw in enumerate([50, 60, 70, 80, 90, 100]):
            statements = wf.healthy_window(window_id=100 + i, raw_measurement=raw)
            verdict = wf.issue_signed_verdict(statements, window_id=100 + i)
            batch.append((verdict, statements))

        results = [
            replay_mod.replay_verdict(v, s, config_paths=wf.CONFIG_PATHS)
            for v, s in batch
        ]
        agreement_rate = sum(r.agreement for r in results) / len(results)
        self.assertEqual(agreement_rate, 1.0)

    def test_wrong_statement_set_is_evidence_mismatch(self):
        statements = wf.healthy_window(window_id=7)
        verdict = wf.issue_signed_verdict(statements, window_id=7)
        wrong_statements = wf.healthy_window(window_id=7, raw_measurement=1)  # different content
        result = replay_mod.replay_verdict(verdict, wrong_statements, config_paths=wf.CONFIG_PATHS)
        self.assertFalse(result.agreement)
        self.assertTrue(result.evidence_mismatch)

    def test_tampered_verdict_field_disagrees(self):
        statements = wf.healthy_window(window_id=7)
        verdict = wf.issue_signed_verdict(statements, window_id=7)
        tampered = dict(verdict)
        tampered["verdict"] = "Normal" if verdict["verdict"] != "Normal" else "Safe"
        result = replay_mod.replay_verdict(tampered, statements, config_paths=wf.CONFIG_PATHS)
        self.assertFalse(result.agreement)

    def test_tampered_effective_dims_disagrees_even_if_verdict_field_matches(self):
        """Isolates the effective_dims comparison from the verdict-name
        comparison: both must hold for agreement, not either."""
        statements = wf.healthy_window(window_id=7)
        verdict = wf.issue_signed_verdict(statements, window_id=7)
        tampered = dict(verdict)
        tampered["effective_dims"] = dict(verdict["effective_dims"])
        tampered["effective_dims"]["Signal"] = "LOW"  # verdict field left untouched
        result = replay_mod.replay_verdict(tampered, statements, config_paths=wf.CONFIG_PATHS)
        self.assertFalse(result.agreement)

    def test_window_missing_a_dimension_entirely_replays_as_low_for_it(self):
        """No statement was ever submitted for ActuationFidelity (not a
        rejected one -- an absent one). reduce_dimension's missing-claim
        fallback must be exercised without crashing, and replay must still
        reproduce the same (LOW-for-that-dimension) outcome."""
        from trust_kernel.bands import DIMENSIONS
        statements = [s for s in wf.healthy_window(window_id=7) if s["claim_type"] != "actuationfidelity.provisional_v0"]
        verdict = wf.issue_signed_verdict(statements, window_id=7)
        self.assertEqual(verdict["effective_dims"]["ActuationFidelity"], "LOW")
        result = replay_mod.replay_verdict(verdict, statements, config_paths=wf.CONFIG_PATHS)
        self.assertTrue(result.agreement)


class ConfigMismatchTests(unittest.TestCase):
    """§12/§17 deliverable (c): replay under a mutated config, confirm the
    hash mismatch is caught before any attempt to recompute pi."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmpdir, ignore_errors=True)
        self.mutated_paths = dict(wf.CONFIG_PATHS)
        for name, path in wf.CONFIG_PATHS.items():
            dst = pathlib.Path(self.tmpdir) / path.name
            shutil.copy(path, dst)
            self.mutated_paths[name] = dst

    def test_mutated_crit_table_is_caught(self):
        statements = wf.healthy_window(window_id=7)
        verdict = wf.issue_signed_verdict(statements, window_id=7)  # signed against the REAL config

        raw = json.loads(self.mutated_paths["crit_table"].read_text())
        raw["strict"], raw["lenient"] = raw["lenient"] + [raw["strict"][0]], raw["strict"][1:]
        self.mutated_paths["crit_table"].write_text(json.dumps(raw))

        result = replay_mod.replay_verdict(verdict, statements, config_paths=self.mutated_paths)
        self.assertFalse(result.agreement)
        self.assertTrue(result.config_mismatch)
        self.assertIn("crit_table_hash", result.mismatched_hashes)

    def test_mutated_alpha_beta_is_caught(self):
        statements = wf.healthy_window(window_id=7)
        verdict = wf.issue_signed_verdict(statements, window_id=7)

        raw = json.loads(self.mutated_paths["eis"].read_text())
        raw["alpha_bp"] = 1
        self.mutated_paths["eis"].write_text(json.dumps(raw))

        result = replay_mod.replay_verdict(verdict, statements, config_paths=self.mutated_paths)
        self.assertFalse(result.agreement)
        self.assertTrue(result.config_mismatch)
        self.assertIn("roc_config_hash", result.mismatched_hashes)

    def test_config_mismatch_does_not_attempt_recomputation(self):
        statements = wf.healthy_window(window_id=7)
        verdict = wf.issue_signed_verdict(statements, window_id=7)

        raw = json.loads(self.mutated_paths["eis"].read_text())
        raw["beta_bp"] = 1
        self.mutated_paths["eis"].write_text(json.dumps(raw))

        result = replay_mod.replay_verdict(verdict, statements, config_paths=self.mutated_paths)
        self.assertIsNone(result.recomputed_verdict)
        self.assertIsNone(result.recomputed_effective_dims)


if __name__ == "__main__":
    unittest.main()
