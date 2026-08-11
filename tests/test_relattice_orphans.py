"""L8->L6 relattice orphan check (CLAUDE.md changelog 2026-07-19).

Confirms no config file still references the removed Safety/Context
dimensions, claim types, or source_ids, and that trust_kernel.bands.
DIMENSIONS itself was actually shrunk to 6 -- both as a one-shot check now
and as a standing regression test so a future edit can't silently
reintroduce either dimension into one config while missing another.
"""

import pathlib
import unittest

from tests import orphan_check

CONFIG_DIR = pathlib.Path(__file__).resolve().parent.parent / "config"
ALL_CONFIG_PATHS = {
    "crit_table": CONFIG_DIR / "crit_table.json",
    "ctpr": CONFIG_DIR / "ctpr.json",
    "eis_v0": CONFIG_DIR / "eis.v0.json",
    "claim_registry": CONFIG_DIR / "claim_registry.json",
    "key_registry": CONFIG_DIR / "key_registry.json",
}


class DimensionsShrunkTests(unittest.TestCase):
    def test_dimensions_tuple_has_exactly_six_entries(self):
        from trust_kernel.bands import DIMENSIONS
        self.assertEqual(len(DIMENSIONS), 6)

    def test_safety_and_context_are_gone_from_dimensions(self):
        from trust_kernel.bands import DIMENSIONS
        self.assertNotIn("Safety", DIMENSIONS)
        self.assertNotIn("Context", DIMENSIONS)


class OrphanCheckTests(unittest.TestCase):
    def test_no_orphan_references_in_any_config(self):
        hits = orphan_check.find_orphan_references(ALL_CONFIG_PATHS)
        self.assertEqual(hits, {}, f"orphan references found: {hits}")

    def test_check_or_raise_passes_on_real_configs(self):
        orphan_check.check_or_raise(ALL_CONFIG_PATHS)  # must not raise

    def test_checker_is_not_vacuous_key_entry(self):
        """Proves the scan actually catches something -- a checker that
        always returns {} would pass the clean-config test above for the
        wrong reason."""
        planted = {"keys": {"safety_sensor_v0": {
            "public_key": "00" * 32, "source_id": "safety_sensor_v0",
            "boundary": "TB2", "authorized_claim_types": ["safety.provisional_v0"],
        }}}
        found = orphan_check._scan(planted)
        self.assertEqual(found, {"safety_sensor_v0", "safety.provisional_v0"})

    def test_checker_is_not_vacuous_dimension_string(self):
        found = orphan_check._scan({"strict": ["Signal", "Context"]})
        self.assertEqual(found, {"Context"})

    def test_check_or_raise_fails_loudly_on_planted_orphan(self):
        import json
        import shutil
        import tempfile
        tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmpdir, ignore_errors=True)

        mutated_paths = dict(ALL_CONFIG_PATHS)
        dst = pathlib.Path(tmpdir) / "crit_table.json"
        raw = json.loads(ALL_CONFIG_PATHS["crit_table"].read_text())
        raw["lenient"] = raw["lenient"] + ["Context"]
        dst.write_text(json.dumps(raw))
        mutated_paths["crit_table"] = dst

        with self.assertRaises(ValueError):
            orphan_check.check_or_raise(mutated_paths)


if __name__ == "__main__":
    unittest.main()
