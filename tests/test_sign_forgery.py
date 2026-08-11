"""Genuine (non-stubbed) forged-signature positive controls for the §9
R/A prime-order-subgroup checks, closing the gap the mutation harness
exposed: none of the 12 published speccheck vectors isolate either check
as uniquely load-bearing against this installed libsodium (only case 3
disagrees with our restricted verifier, and it has both R and A invalid
simultaneously -- disabling either check alone left the other to catch
it). GateNecessityTests (tests/test_sign.py) proves gate necessity by
stubbing the final equation check to always accept; the tests here prove
it again with a real signature that libsodium itself accepts, for the
one direction (A invalid) where that is mathematically possible.
"""

import hashlib
import json
import pathlib
import unittest

from trust_kernel import sign
from tests import forgery_support as fs

VECTORS_DIR = pathlib.Path(__file__).resolve().parent / "vectors"


class IsolatedAForgeryTests(unittest.TestCase):
    """A invalid (mixed-order), R valid (prime-order): a real signature
    libsodium accepts, that trust_kernel.sign.verify() must reject solely
    via the A-subgroup check."""

    @classmethod
    def setUpClass(cls):
        with open(VECTORS_DIR / "self_constructed_forgery_vectors.json") as f:
            cls.data = json.load(f)["isolate_a"]
        cls.pub_key = bytes.fromhex(cls.data["public_key"])
        cls.message = bytes.fromhex(cls.data["message"])
        cls.signature = bytes.fromhex(cls.data["signature"])

    def test_r_is_valid_prime_order(self):
        self.assertTrue(sign._is_valid_point(self.signature[:32]))

    def test_a_is_invalid_mixed_order(self):
        self.assertFalse(sign._is_valid_point(self.pub_key))

    def test_raw_libsodium_accepts_the_forgery(self):
        self.assertTrue(
            fs.raw_libsodium_verify(self.pub_key, self.message, self.signature)
        )

    def test_our_verify_rejects_the_forgery(self):
        self.assertFalse(sign.verify(self.pub_key, self.message, self.signature))


class IsolatedRForgeryIsImpossibleTests(unittest.TestCase):
    """R invalid (mixed-order) paired with A valid (prime-order) can never
    be accepted by libsodium's verification equation: s*B - h*A is confined
    to the prime-order subgroup whenever A is prime-order, for any s, so R
    is forced to be prime-order too whenever the equation holds. Checked
    here over a deterministic search grid as a standing invariant -- if a
    future libsodium version ever changed this, this test would fail, and
    CLAUDE.md §9's "the rule set is the spec, not the library" stance is
    exactly why verify()'s own R-check does not rely on this fact holding.
    """

    def test_no_mixed_order_r_forgery_is_ever_accepted(self):
        torsion = fs.torsion_subgroup()
        accepted = []
        for trial in range(6):
            seed_a0 = hashlib.sha256(
                f"CLAUDE.md-9-forgery-isolate-R-impossibility-{trial}".encode()
            ).digest()
            a0_pk, _ = sign.keypair_from_seed(seed_a0)
            a0_int = int.from_bytes(fs.derive_scalar(seed_a0), "little")

            r0_seed = hashlib.sha256(
                f"CLAUDE.md-9-forgery-isolate-R-impossibility-r0-{trial}".encode()
            ).digest()
            r0 = int.from_bytes(r0_seed, "little") % sign.L
            r0_point = fs.scalarmult_base(r0.to_bytes(32, "little"))
            message = f"isolate-R-impossibility-{trial}".encode()

            for i, t_r in enumerate(torsion):
                if i == 0:
                    continue  # identity: the non-forged, already-valid case
                r_mixed = fs.point_add(r0_point, t_r)
                k = int.from_bytes(
                    hashlib.sha512(r_mixed + a0_pk + message).digest(), "little"
                ) % sign.L
                s = (r0 + k * a0_int) % sign.L
                forged = r_mixed + s.to_bytes(32, "little")
                if fs.raw_libsodium_verify(a0_pk, message, forged):
                    accepted.append((trial, i))

        self.assertEqual(
            accepted, [],
            "a mixed-order-R forgery was accepted against a valid A -- the "
            "impossibility argument in this test's docstring no longer "
            "holds for the installed libsodium; escalate per CLAUDE.md §18 "
            "before relying on the R-check's mutation coverage via stubs",
        )


if __name__ == "__main__":
    unittest.main()
