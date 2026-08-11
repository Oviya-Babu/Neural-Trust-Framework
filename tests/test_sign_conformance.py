"""Executable conformance test against published Ed25519 edge-case vectors
(CLAUDE.md §9, §14 Phase 1 deliverable).

Vectors are read from tests/vectors/*.json, fetched verbatim from their
sources (see each file's "_provenance" field) -- this test asserts nothing
about vector content, only about trust_kernel.sign's behaviour on it.

Per §12: this is a regression guard against a fixed, published, adversarial
test set, not independent empirical validation and not a proof.
"""

import json
import pathlib
import unittest

from trust_kernel import sign

VECTORS_DIR = pathlib.Path(__file__).resolve().parent / "vectors"


def _load(name):
    with open(VECTORS_DIR / name) as f:
        return json.load(f)


class EdCaseSpeccheckConformanceTests(unittest.TestCase):
    """"Taming the Many EdDSAs" (Chalkias, Garillot, Nikolaenko, SSR 2020)
    edge-case vectors. Every one of the 12 published vectors is constructed
    to have a small- or mixed-order A and/or R, or an out-of-range S -- i.e.
    every vector lies outside the domain CLAUDE.md §9 restricts verification
    to. A conformant verifier rejects all 12, unconditionally."""

    @classmethod
    def setUpClass(cls):
        cls.data = _load("ed25519_speccheck_vectors.json")

    def test_vector_count_is_twelve(self):
        self.assertEqual(len(self.data["cases"]), 12)

    def test_all_edge_case_vectors_rejected(self):
        failures = []
        for case in self.data["cases"]:
            message = bytes.fromhex(case["message"])
            pub_key = bytes.fromhex(case["pub_key"])
            signature = bytes.fromhex(case["signature"])
            accepted = sign.verify(pub_key, message, signature)
            if accepted:
                failures.append((case["index"], case["condition"]))
        self.assertEqual(
            failures, [],
            f"vectors accepted that should have been rejected: {failures}",
        )


def _rfc_case_test(case):
    def test(self):
        seed = bytes.fromhex(case["seed"])
        message = bytes.fromhex(case["message"])
        expected_pk = bytes.fromhex(case["public_key"])
        expected_sig = bytes.fromhex(case["signature"])

        pk, sk = sign.keypair_from_seed(seed)
        self.assertEqual(pk, expected_pk, "derived public key must match RFC 8032")

        produced_sig = sign.sign(sk, message)
        self.assertEqual(produced_sig, expected_sig, "signing must match RFC 8032 exactly")

        self.assertTrue(
            sign.verify(expected_pk, message, expected_sig),
            "published in-domain RFC 8032 vector must verify",
        )
    return test


class Rfc8032PositiveControlTests(unittest.TestCase):
    """Positive control: canonical, full-order, in-domain signatures must be
    accepted. Without this, 'reject everything' would trivially pass the
    edge-case-only suite above."""


for _case in _load("rfc8032_vectors.json")["cases"]:
    setattr(
        Rfc8032PositiveControlTests,
        f"test_rfc8032_vector_{_case['index']}",
        _rfc_case_test(_case),
    )


if __name__ == "__main__":
    unittest.main()
