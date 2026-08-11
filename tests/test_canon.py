"""Unit tests for trust_kernel/canon.py (CLAUDE.md §8, §9)."""

import unittest

from trust_kernel import canon


class RoundTripTests(unittest.TestCase):
    def test_integers(self):
        for n in [0, 1, 23, 24, 255, 256, 65535, 65536, 2**32 - 1, 2**32, 2**64 - 1,
                  -1, -24, -25, -256, -257, -65536, -65537]:
            self.assertEqual(canon.decode(canon.encode(n)), n)

    def test_bytes_and_str(self):
        for v in [b"", b"hello", "", "hello", "utf8-é中"]:
            self.assertEqual(canon.decode(canon.encode(v)), v)

    def test_arrays_and_maps(self):
        for v in [[], [1, 2, 3], {}, {"a": 1, "b": 2},
                  [1, {"x": [1, 2, {"y": b"z"}]}]]:
            self.assertEqual(canon.decode(canon.encode(v)), v)

    def test_map_key_order_is_canonicalized(self):
        d1 = {"b": 1, "a": 2}
        d2 = {"a": 2, "b": 1}
        self.assertEqual(canon.encode(d1), canon.encode(d2))

    def test_encode_tagged_is_domain_pair(self):
        tagged = canon.encode_tagged("statement", {"a": 1})
        self.assertEqual(canon.decode(tagged), ["statement", {"a": 1}])

    def test_different_domain_tags_produce_different_bytes(self):
        a = canon.encode_tagged("statement", {"a": 1})
        b = canon.encode_tagged("verdict", {"a": 1})
        self.assertNotEqual(a, b)

    def test_encode_tagged_matches_independently_built_array(self):
        """Ground truth built via canon.decode(), independent of
        encode_tagged's own [domain_tag, obj] ordering -- catches a mutant
        that silently swaps the pair order (which a pure round-trip test
        cannot, since signing and verifying both go through the same
        mutated function consistently)."""
        tagged = canon.encode_tagged("statement", {"a": 1})
        decoded = canon.decode(tagged)
        self.assertEqual(decoded[0], "statement")
        self.assertEqual(decoded[1], {"a": 1})


class ForbiddenTypeTests(unittest.TestCase):
    def test_bool_rejected(self):
        with self.assertRaises(canon.CanonError):
            canon.encode(True)

    def test_none_rejected(self):
        with self.assertRaises(canon.CanonError):
            canon.encode(None)

    def test_float_rejected(self):
        with self.assertRaises(canon.CanonError):
            canon.encode(1.5)


class StrictDecodeTests(unittest.TestCase):
    def test_non_shortest_form_uint_rejected(self):
        # major=0, additional-info=24 (1-byte arg), value=5 -- should have
        # been embedded directly in the initial byte.
        with self.assertRaises(canon.CanonError):
            canon.decode(bytes([0x18, 0x05]))

    def test_non_shortest_form_2byte_rejected(self):
        with self.assertRaises(canon.CanonError):
            canon.decode(bytes([0x19, 0x00, 0x05]))

    def test_out_of_order_map_keys_rejected(self):
        raw = bytes([0xA2]) + canon.encode("b") + canon.encode(1) + canon.encode("a") + canon.encode(2)
        with self.assertRaises(canon.CanonError):
            canon.decode(raw)

    def test_duplicate_map_keys_rejected(self):
        raw = bytes([0xA2]) + canon.encode("a") + canon.encode(1) + canon.encode("a") + canon.encode(2)
        with self.assertRaises(canon.CanonError):
            canon.decode(raw)

    def test_trailing_bytes_rejected(self):
        with self.assertRaises(canon.CanonError):
            canon.decode(canon.encode(1) + b"\x00")

    def test_truncated_input_rejected(self):
        with self.assertRaises(canon.CanonError):
            canon.decode(bytes([0x19, 0x01]))  # claims a 2-byte arg, only 1 present

    def test_major_type_6_and_7_rejected(self):
        # major=6 (tag), info=0
        with self.assertRaises(canon.CanonError):
            canon.decode(bytes([0xC0]))
        # major=7 (float/simple), info=20 (false)
        with self.assertRaises(canon.CanonError):
            canon.decode(bytes([0xF4]))

    def test_empty_input_rejected(self):
        with self.assertRaises(canon.CanonError):
            canon.decode(b"")


if __name__ == "__main__":
    unittest.main()
