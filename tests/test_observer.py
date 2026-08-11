"""Unit tests for observer/observer.py (CLAUDE.md §2, §10, P2)."""

import unittest

from observer.observer import AF_BOUNDARY, AF_CLAIM_TYPE, AF_SOURCE_ID, Observer, measure_actuation_fidelity
from evidence_plane import log as evlog
from trust_kernel import schema
from tests import key_fixtures as kf


class MeasureActuationFidelityTests(unittest.TestCase):
    def test_perfect_match_scores_the_ceiling(self):
        commanded = {"max_speed": 1000, "max_acceleration": 500}
        observed = {"max_speed": 1000, "max_acceleration": 500}
        self.assertEqual(measure_actuation_fidelity(commanded, observed), 100)

    def test_speed_discrepancy_reduces_the_score(self):
        commanded = {"max_speed": 1000, "max_acceleration": 500}
        observed = {"max_speed": 970, "max_acceleration": 500}
        self.assertEqual(measure_actuation_fidelity(commanded, observed), 70)

    def test_acceleration_discrepancy_alone_reduces_the_score(self):
        """Isolates the acceleration term from the speed term -- a mutant
        that drops one component from the discrepancy sum must be caught
        even when the other component matches exactly."""
        commanded = {"max_speed": 1000, "max_acceleration": 500}
        observed = {"max_speed": 1000, "max_acceleration": 470}
        self.assertEqual(measure_actuation_fidelity(commanded, observed), 70)

    def test_large_discrepancy_floors_at_minus_100(self):
        commanded = {"max_speed": 1600, "max_acceleration": 800}
        observed = {"max_speed": 0, "max_acceleration": 0}
        self.assertEqual(measure_actuation_fidelity(commanded, observed), -100)

    def test_direction_of_discrepancy_does_not_matter(self):
        commanded = {"max_speed": 500, "max_acceleration": 300}
        observed_low = {"max_speed": 470, "max_acceleration": 300}
        observed_high = {"max_speed": 530, "max_acceleration": 300}
        self.assertEqual(
            measure_actuation_fidelity(commanded, observed_low),
            measure_actuation_fidelity(commanded, observed_high),
        )


class ObserverIdentityGroundTruthTests(unittest.TestCase):
    """Hardcoded independently of observer.observer's own constants -- same
    class of gap as the L-constant / GENESIS_PREV_HASH self-reference
    fixes."""

    def test_af_claim_type_matches_the_registered_claim(self):
        self.assertEqual(AF_CLAIM_TYPE, "actuationfidelity.provisional_v0")

    def test_af_source_id_matches_the_registered_key(self):
        self.assertEqual(AF_SOURCE_ID, "actuationfidelity_sensor_v0")

    def test_af_boundary_is_tb2(self):
        self.assertEqual(AF_BOUNDARY, "TB2")


class ObserverBuildStatementTests(unittest.TestCase):
    def setUp(self):
        self.pk, self.sk = kf.keypair_for("actuationfidelity_sensor_v0")
        self.observer = Observer(self.sk)
        self.commanded = {"max_speed": 1000, "max_acceleration": 500}
        self.observed = {"max_speed": 1000, "max_acceleration": 500}

    def test_statement_carries_the_af_claim_type_and_dimension_identity(self):
        stmt = self.observer.build_statement(
            commanded=self.commanded, observed=self.observed, window_id=42, claimed_at=0,
        )
        self.assertEqual(stmt["claim_type"], AF_CLAIM_TYPE)
        self.assertEqual(stmt["source_id"], AF_SOURCE_ID)
        self.assertEqual(stmt["key_id"], AF_SOURCE_ID)
        self.assertEqual(stmt["window_id"], 42)
        self.assertEqual(stmt["raw_measurement"], 100)

    def test_window_id_and_claimed_at_are_threaded_through_exactly(self):
        stmt = self.observer.build_statement(
            commanded=self.commanded, observed=self.observed, window_id=77, claimed_at=123,
        )
        self.assertEqual(stmt["window_id"], 77)
        self.assertEqual(stmt["claimed_at"], 123)

    def test_statement_verifies_against_the_observers_own_public_key(self):
        stmt = self.observer.build_statement(
            commanded=self.commanded, observed=self.observed, window_id=42, claimed_at=0,
        )
        self.assertTrue(schema.verify_statement_signature(self.pk, stmt))

    def test_statement_does_not_verify_against_the_kernel_key(self):
        """Proves this is a genuinely distinct keypair, not a shared or
        reused one -- a validly-signed AF statement must fail verification
        under any key other than the Observer's own."""
        kernel_pk, _ = kf.kernel_keypair()
        stmt = self.observer.build_statement(
            commanded=self.commanded, observed=self.observed, window_id=42, claimed_at=0,
        )
        self.assertFalse(schema.verify_statement_signature(kernel_pk, stmt))

    def test_statement_does_not_verify_against_a_different_sensors_key(self):
        signal_pk, _ = kf.keypair_for("signal_sensor_v0")
        stmt = self.observer.build_statement(
            commanded=self.commanded, observed=self.observed, window_id=42, claimed_at=0,
        )
        self.assertFalse(schema.verify_statement_signature(signal_pk, stmt))


class ObserverAppendTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.path = tempfile.mktemp()
        import os
        self.addCleanup(lambda: os.path.exists(self.path) and os.remove(self.path))
        _, self.sk = kf.keypair_for("actuationfidelity_sensor_v0")
        self.observer = Observer(self.sk)

    def test_observe_and_append_grows_the_log_by_one_entry(self):
        log = evlog.EvidenceLog(self.path)
        self.observer.observe_and_append(
            log,
            commanded={"max_speed": 1000, "max_acceleration": 500},
            observed={"max_speed": 1000, "max_acceleration": 500},
            window_id=1, claimed_at=0,
        )
        log.fsync_window()
        log.close()
        entries = evlog.read_all(self.path)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["statement"]["claim_type"], AF_CLAIM_TYPE)

    def test_appended_statement_round_trips_and_still_verifies(self):
        log = evlog.EvidenceLog(self.path)
        self.observer.observe_and_append(
            log,
            commanded={"max_speed": 1000, "max_acceleration": 500},
            observed={"max_speed": 950, "max_acceleration": 500},
            window_id=1, claimed_at=0,
        )
        log.fsync_window()
        log.close()
        entries = evlog.read_all(self.path)
        pk, _ = kf.keypair_for("actuationfidelity_sensor_v0")
        self.assertTrue(schema.verify_statement_signature(pk, entries[0]["statement"]))


if __name__ == "__main__":
    unittest.main()
