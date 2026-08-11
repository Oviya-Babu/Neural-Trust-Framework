"""Tests for bci_pipeline/loader.py (CLAUDE.md §17a, Phase 7).

Run with the pipeline venv, not the pure-core suite:
    .venv-pipeline/bin/python -m unittest discover -s tests_bci_pipeline

Requires subject 1's files to already be cached locally (see
bci_pipeline.loader.DEFAULT_CACHE_DIR) -- the happy-path tests here do not
re-download if the cache is already populated, but will download
(~85 MB) on a clean cache.
"""

import copy
import json
import pathlib
import shutil
import tempfile
import unittest

from bci_pipeline import loader


class ValidatePinsTests(unittest.TestCase):
    def setUp(self):
        self.real_pins = loader.load_pins()

    def test_real_pin_config_loads_and_validates(self):
        loader.validate_pins(self.real_pins)  # must not raise

    def test_missing_field_rejected(self):
        bad = copy.deepcopy(self.real_pins)
        del bad["resolved_base_url"]
        with self.assertRaises(loader.DatasetIntegrityError):
            loader.validate_pins(bad)

    def test_wrong_dataset_code_rejected(self):
        bad = copy.deepcopy(self.real_pins)
        bad["dataset_code"] = "NOT-THE-RIGHT-DATASET"
        with self.assertRaises(loader.DatasetIntegrityError):
            loader.validate_pins(bad)

    def test_no_files_rejected(self):
        bad = copy.deepcopy(self.real_pins)
        bad["files"] = {}
        with self.assertRaises(loader.DatasetIntegrityError):
            loader.validate_pins(bad)

    def test_file_missing_sha256_rejected(self):
        bad = copy.deepcopy(self.real_pins)
        del bad["files"]["A01T"]["sha256"]
        with self.assertRaises(loader.DatasetIntegrityError):
            loader.validate_pins(bad)

    def test_url_outside_resolved_base_url_rejected(self):
        bad = copy.deepcopy(self.real_pins)
        bad["files"]["A01T"]["url"] = "https://evil.example.com/A01T.mat"
        with self.assertRaises(loader.DatasetIntegrityError):
            loader.validate_pins(bad)


class VerifyFileTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmpdir, ignore_errors=True)
        self.path = pathlib.Path(self.tmpdir) / "sample.bin"
        self.path.write_bytes(b"hello world")
        import hashlib
        self.correct_sha256 = hashlib.sha256(b"hello world").hexdigest()

    def test_matching_hash_passes(self):
        actual = loader.verify_file(self.path, self.correct_sha256, "sample")
        self.assertEqual(actual, self.correct_sha256)

    def test_mismatched_hash_fails_closed(self):
        with self.assertRaises(loader.DatasetIntegrityError):
            loader.verify_file(self.path, "0" * 64, "sample")

    def test_missing_file_fails_closed(self):
        with self.assertRaises(loader.DatasetIntegrityError):
            loader.verify_file(pathlib.Path(self.tmpdir) / "does_not_exist.bin", self.correct_sha256, "sample")


class HappyPathAgainstCachedSubjectOneTests(unittest.TestCase):
    """Subject 1's files are expected to already be present in
    bci_pipeline.loader.DEFAULT_CACHE_DIR (downloaded once for Phase 7's
    end-to-end run) -- these tests use the cache, no fresh network fetch
    should be needed."""

    def test_resolve_and_verify_real_subject_one(self):
        verified = loader.resolve_and_verify_subject_files(1)
        self.assertEqual(set(verified), {"T", "E"})
        pins = loader.load_pins()
        self.assertEqual(verified["T"]["sha256"], pins["files"]["A01T"]["sha256"])
        self.assertEqual(verified["E"]["sha256"], pins["files"]["A01E"]["sha256"])


class FailClosedOnWrongHashTests(unittest.TestCase):
    """The explicit deliverable: 'point at a wrong hash, confirm the
    loader refuses to run.' Uses the real, already-downloaded subject 1
    file with a deliberately corrupted pinned hash -- the file itself is
    fine, only the expectation is wrong, isolating the check from any
    real data-integrity question."""

    def setUp(self):
        self.real_pins = loader.load_pins()

    def test_wrong_pinned_hash_for_existing_file_refuses_to_load(self):
        bad_pins = copy.deepcopy(self.real_pins)
        bad_pins["files"]["A01T"]["sha256"] = "0" * 64
        with self.assertRaises(loader.DatasetIntegrityError):
            loader.resolve_and_verify_subject_files(1, pins=bad_pins)

    def test_wrong_hash_error_names_the_offending_key(self):
        bad_pins = copy.deepcopy(self.real_pins)
        bad_pins["files"]["A01T"]["sha256"] = "0" * 64
        with self.assertRaises(loader.DatasetIntegrityError) as ctx:
            loader.resolve_and_verify_subject_files(1, pins=bad_pins)
        self.assertIn("A01T", str(ctx.exception))

    def test_unpinned_subject_refuses_to_load(self):
        """A subject with no pin entry at all must also refuse, not just a
        subject with a wrong hash -- 'refuse to fetch an unpinned file.'"""
        bad_pins = copy.deepcopy(self.real_pins)
        del bad_pins["files"]["A01T"]
        with self.assertRaises(loader.DatasetIntegrityError):
            loader.resolve_and_verify_subject_files(1, pins=bad_pins)


if __name__ == "__main__":
    unittest.main()
