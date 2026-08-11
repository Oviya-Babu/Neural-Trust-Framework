"""Unit tests for trust_kernel/sign.py (CLAUDE.md §9).

Serves T4: each test isolates one clause of the §9 rule set so that a
mutant violating that clause is caught close to the source, independent of
whatever the underlying libsodium version happens to already enforce.
"""

import unittest
from unittest import mock

from trust_kernel import sign


class RoundTripTests(unittest.TestCase):
    def test_generated_keypair_round_trips(self):
        pk, sk = sign.generate_keypair()
        message = b"trust kernel verdict window 42"
        signature = sign.sign(sk, message)
        self.assertTrue(sign.verify(pk, message, signature))

    def test_seed_derivation_is_deterministic(self):
        seed = b"\x11" * sign.SEED_BYTES
        pk1, sk1 = sign.keypair_from_seed(seed)
        pk2, sk2 = sign.keypair_from_seed(seed)
        self.assertEqual(pk1, pk2)
        self.assertEqual(sk1, sk2)

    def test_empty_message_round_trips(self):
        pk, sk = sign.generate_keypair()
        signature = sign.sign(sk, b"")
        self.assertTrue(sign.verify(pk, b"", signature))


class RejectsTamperedSignaturesTests(unittest.TestCase):
    """Proves the final equation check is actually exercised: these
    signatures are all in-domain (canonical, prime-order, S < L) so they
    can only be rejected by the crypto_sign_verify_detached equation
    itself, not by the upfront structural gates."""

    def setUp(self):
        self.pk, self.sk = sign.generate_keypair()
        self.message = b"window_id=42;verdict=Normal"
        self.signature = sign.sign(self.sk, self.message)

    def test_wrong_message_rejected(self):
        self.assertFalse(sign.verify(self.pk, b"window_id=42;verdict=Safe", self.signature))

    def test_wrong_key_rejected(self):
        other_pk, _ = sign.generate_keypair()
        self.assertFalse(sign.verify(other_pk, self.message, self.signature))

    def test_flipped_low_bit_of_s_rejected(self):
        r, s = self.signature[:32], bytearray(self.signature[32:])
        s[0] ^= 0x01
        tampered = r + bytes(s)
        # still S < L for a low-bit flip on a canonical scalar; must be
        # rejected by the equation check, not the S >= L gate.
        self.assertTrue(sign._scalar_is_canonical(bytes(s)))
        self.assertFalse(sign.verify(self.pk, self.message, tampered))

    def test_flipped_bit_of_r_rejected(self):
        r, s = bytearray(self.signature[:32]), self.signature[32:]
        r[5] ^= 0x01
        tampered = bytes(r) + s
        self.assertFalse(sign.verify(self.pk, self.message, tampered))


class StructuralRejectionTests(unittest.TestCase):
    def setUp(self):
        self.pk, self.sk = sign.generate_keypair()
        self.message = b"m"
        self.signature = sign.sign(self.sk, self.message)

    def test_short_public_key_rejected(self):
        self.assertFalse(sign.verify(self.pk[:-1], self.message, self.signature))

    def test_long_signature_rejected(self):
        self.assertFalse(sign.verify(self.pk, self.message, self.signature + b"\x00"))

    def test_empty_inputs_rejected_not_raised(self):
        self.assertFalse(sign.verify(b"", self.message, b""))

    def test_scalar_at_L_rejected(self):
        l_bytes = sign.L.to_bytes(32, "little")
        forged = self.signature[:32] + l_bytes
        self.assertFalse(sign.verify(self.pk, self.message, forged))

    def test_scalar_above_L_rejected(self):
        above_l = (sign.L + 1).to_bytes(32, "little")
        forged = self.signature[:32] + above_l
        self.assertFalse(sign.verify(self.pk, self.message, forged))

    def test_identity_point_public_key_rejected(self):
        identity = bytes([0x01] + [0x00] * 31)
        self.assertFalse(sign.verify(identity, self.message, self.signature))


class ScalarCanonicalityUnitTests(unittest.TestCase):
    """Direct tests of the pure helper, independent of libsodium, so a
    mutant of the S >= L comparison is caught even if libsodium's own
    internal check would otherwise mask it (defense-in-depth per the
    §9 framing: 'the rule set is the spec, not the library')."""

    def test_l_minus_one_is_canonical(self):
        self.assertTrue(sign._scalar_is_canonical((sign.L - 1).to_bytes(32, "little")))

    def test_zero_is_canonical(self):
        self.assertTrue(sign._scalar_is_canonical((0).to_bytes(32, "little")))

    def test_l_is_not_canonical(self):
        self.assertFalse(sign._scalar_is_canonical(sign.L.to_bytes(32, "little")))

    def test_l_plus_one_is_not_canonical(self):
        self.assertFalse(sign._scalar_is_canonical((sign.L + 1).to_bytes(32, "little")))


class ScalarCanonicalityGroundTruthTests(unittest.TestCase):
    """L hardcoded independently of trust_kernel.sign (RFC 8032 §5.1), so a
    corrupted L constant in the module under test cannot make its own
    boundary tests vacuously self-consistent."""

    L_GROUND_TRUTH = 2 ** 252 + 27742317777372353535851937790883648493

    def test_l_ground_truth_is_not_canonical(self):
        self.assertFalse(
            sign._scalar_is_canonical(self.L_GROUND_TRUTH.to_bytes(32, "little"))
        )

    def test_l_ground_truth_minus_one_is_canonical(self):
        self.assertTrue(
            sign._scalar_is_canonical((self.L_GROUND_TRUTH - 1).to_bytes(32, "little"))
        )


class ProvisioningTests(unittest.TestCase):
    def test_valid_key_passes_provisioning(self):
        pk, _ = sign.generate_keypair()
        self.assertEqual(sign.validate_public_key(pk), pk)

    def test_identity_point_fails_provisioning(self):
        identity = bytes([0x01] + [0x00] * 31)
        with self.assertRaises(sign.SigningError):
            sign.validate_public_key(identity)

    def test_wrong_length_fails_provisioning(self):
        with self.assertRaises(sign.SigningError):
            sign.validate_public_key(b"\x00" * 31)


class _AlwaysAcceptEquation:
    """Forwards point-validity checks to the real libsodium handle but makes
    the final signature-equation check always succeed. Used to prove that
    verify()'s own structural gates (S < L; R, A canonical + prime-order)
    are independently sufficient to reject malformed input, regardless of
    whatever this particular libsodium version already enforces internally
    -- per §9's framing, "the rule set is the spec, not the library"."""

    def __init__(self, real_lib):
        self._real = real_lib

    def crypto_core_ed25519_is_valid_point(self, *args, **kwargs):
        return self._real.crypto_core_ed25519_is_valid_point(*args, **kwargs)

    def crypto_sign_verify_detached(self, *args, **kwargs):
        return 0


class GateNecessityTests(unittest.TestCase):
    """Each structural gate must independently reject its malformed input
    even when the final equation check is stubbed to always accept."""

    def setUp(self):
        real_lib = sign._load()
        self.stub = _AlwaysAcceptEquation(real_lib)
        self.pk, self.sk = sign.generate_keypair()
        self.message = b"m"
        self.signature = sign.sign(self.sk, self.message)

    def test_s_ge_l_rejected_even_if_equation_would_accept(self):
        forged = self.signature[:32] + sign.L.to_bytes(32, "little")
        with mock.patch.object(sign, "_load", return_value=self.stub):
            self.assertFalse(sign.verify(self.pk, self.message, forged))

    def test_invalid_r_rejected_even_if_equation_would_accept(self):
        identity = bytes([0x01] + [0x00] * 31)
        forged = identity + self.signature[32:]
        with mock.patch.object(sign, "_load", return_value=self.stub):
            self.assertFalse(sign.verify(self.pk, self.message, forged))

    def test_invalid_a_rejected_even_if_equation_would_accept(self):
        identity = bytes([0x01] + [0x00] * 31)
        with mock.patch.object(sign, "_load", return_value=self.stub):
            self.assertFalse(sign.verify(identity, self.message, self.signature))


if __name__ == "__main__":
    unittest.main()
