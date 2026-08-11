"""Unit tests for evidence_plane/log.py (CLAUDE.md §2, §8)."""

import os
import struct
import tempfile
import unittest

from evidence_plane import log as evlog
from trust_kernel import canon


class EvidenceLogTests(unittest.TestCase):
    def setUp(self):
        self.path = tempfile.mktemp()
        self.addCleanup(lambda: os.path.exists(self.path) and os.remove(self.path))

    def test_append_assigns_sequential_seq(self):
        log = evlog.EvidenceLog(self.path)
        e0 = log.append({"n": 0})
        e1 = log.append({"n": 1})
        self.assertEqual(e0["seq"], 0)
        self.assertEqual(e1["seq"], 1)
        log.close()

    def test_first_entry_chains_from_genesis(self):
        log = evlog.EvidenceLog(self.path)
        e0 = log.append({"n": 0})
        self.assertEqual(e0["prev_hash"], evlog.GENESIS_PREV_HASH)
        log.close()

    def test_genesis_prev_hash_ground_truth(self):
        """Hardcoded independently of evlog.GENESIS_PREV_HASH, so a
        corrupted constant can't make its own comparison vacuously pass
        (same class of gap as the L-constant mutation in trust_kernel/sign.py)."""
        self.assertEqual(evlog.GENESIS_PREV_HASH, b"\x00" * 32)

    def test_second_entry_chains_from_first(self):
        log = evlog.EvidenceLog(self.path)
        e0 = log.append({"n": 0})
        e1 = log.append({"n": 1})
        self.assertEqual(e1["prev_hash"], e0["entry_hash"])
        log.close()

    def test_reopen_resumes_seq_and_chain(self):
        log = evlog.EvidenceLog(self.path)
        e0 = log.append({"n": 0})
        log.fsync_window()
        log.close()

        reopened = evlog.EvidenceLog(self.path)
        e1 = reopened.append({"n": 1})
        self.assertEqual(e1["seq"], 1)
        self.assertEqual(e1["prev_hash"], e0["entry_hash"])
        reopened.close()

    def test_read_all_round_trips(self):
        log = evlog.EvidenceLog(self.path)
        for i in range(5):
            log.append({"n": i})
        log.fsync_window()
        log.close()

        entries = evlog.read_all(self.path)
        self.assertEqual([e["statement"]["n"] for e in entries], [0, 1, 2, 3, 4])


class ChainVerificationTests(unittest.TestCase):
    def setUp(self):
        self.path = tempfile.mktemp()
        self.addCleanup(lambda: os.path.exists(self.path) and os.remove(self.path))
        log = evlog.EvidenceLog(self.path)
        for i in range(5):
            log.append({"n": i})
        log.fsync_window()
        log.close()
        self.entries = evlog.read_all(self.path)

    def _rewrite(self, entries):
        with open(self.path, "wb") as f:
            for e in entries:
                record = canon.encode(e)
                f.write(struct.pack(">I", len(record)))
                f.write(record)

    def test_untampered_chain_is_valid(self):
        result = evlog.verify_chain(self.entries)
        self.assertTrue(result.valid)
        self.assertIsNone(result.first_broken_seq)
        self.assertEqual(result.broken_seqs, [])

    def test_tamper_at_position_k_breaks_k_and_everything_after(self):
        """§12/§17 deliverable (b): mutate a statement at chain position k,
        confirm every entry from k forward breaks and no entry before k
        does."""
        k = 2
        tampered = [dict(e) for e in self.entries]
        tampered[k] = dict(tampered[k])
        tampered[k]["statement"] = {"n": 999}  # entry_hash left stale
        self._rewrite(tampered)

        reloaded = evlog.read_all(self.path)
        result = evlog.verify_chain(reloaded)

        self.assertFalse(result.valid)
        self.assertEqual(result.first_broken_seq, k)
        self.assertEqual(result.broken_seqs, [2, 3, 4])

    def test_tamper_at_last_position_breaks_only_that_entry(self):
        k = 4
        tampered = [dict(e) for e in self.entries]
        tampered[k] = dict(tampered[k])
        tampered[k]["statement"] = {"n": 999}
        self._rewrite(tampered)

        reloaded = evlog.read_all(self.path)
        result = evlog.verify_chain(reloaded)
        self.assertEqual(result.broken_seqs, [4])

    def test_tamper_at_first_position_breaks_entire_chain(self):
        tampered = [dict(e) for e in self.entries]
        tampered[0] = dict(tampered[0])
        tampered[0]["statement"] = {"n": 999}
        self._rewrite(tampered)

        reloaded = evlog.read_all(self.path)
        result = evlog.verify_chain(reloaded)
        self.assertEqual(result.broken_seqs, [0, 1, 2, 3, 4])

    def test_two_separate_tamper_points_report_the_earliest(self):
        """Distinguishes 'report the first broken position' from 'report
        the last' -- a single tamper point can't, since first == last
        when there is only one break."""
        tampered = [dict(e) for e in self.entries]
        for k in (1, 3):
            tampered[k] = dict(tampered[k])
            tampered[k]["statement"] = {"n": 999 + k}
        self._rewrite(tampered)

        reloaded = evlog.read_all(self.path)
        result = evlog.verify_chain(reloaded)
        self.assertEqual(result.first_broken_seq, 1)

    def test_deleting_an_entry_breaks_the_chain(self):
        """Records may be appended, never altered or deleted (§2) --
        deletion must also be tamper-evident, not just content mutation."""
        without_middle = [self.entries[0], self.entries[1], self.entries[3], self.entries[4]]
        self._rewrite(without_middle)
        reloaded = evlog.read_all(self.path)
        result = evlog.verify_chain(reloaded)
        self.assertFalse(result.valid)


if __name__ == "__main__":
    unittest.main()
