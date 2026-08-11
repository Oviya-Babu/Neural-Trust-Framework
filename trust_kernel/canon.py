"""Canonical serialization (CLAUDE.md §8, §9): deterministic CBOR (RFC 8949
§4.2) restricted to major types 0-5 (unsigned int, negative int, byte
string, text string, array, map). Floats and nulls are structurally
inexpressible -- encode() raises rather than silently coercing them.

Serves T4 (verdict authenticity) and the replay-hermeticity requirement in
§8: "if two honest verifiers can disagree on a signature, they can
disagree on a verdict." Shortest-form heads, definite lengths, bytewise-
sorted map keys; decode() rejects duplicate/out-of-order keys so a strict
decoder cannot be fed a non-canonical encoding that would re-encode to
something different. encode() has no separate duplicate-key guard: a
Python dict cannot contain two equal keys, and int/bytes/str encode
injectively both within and across those types, so no two distinct dict
keys can ever collide once encoded.

Domain-tagged signing (§8, §9): sign over encode([domain_tag, object]), not
a concatenated prefix -- CBOR's length-prefixed heads make the tagged pair
injective by construction, unlike prefix||body concatenation.
"""

MAJOR_UINT = 0
MAJOR_NINT = 1
MAJOR_BSTR = 2
MAJOR_TSTR = 3
MAJOR_ARRAY = 4
MAJOR_MAP = 5


class CanonError(ValueError):
    """Raised on any encode/decode violation of the canonical subset."""


def _encode_head(major: int, value: int) -> bytes:
    if value < 0:
        raise CanonError("head value must be non-negative")
    prefix = major << 5
    if value < 24:
        return bytes([prefix | value])
    if value < 256:
        return bytes([prefix | 24, value])
    if value < 65536:
        return bytes([prefix | 25]) + value.to_bytes(2, "big")
    if value < 2 ** 32:
        return bytes([prefix | 26]) + value.to_bytes(4, "big")
    if value < 2 ** 64:
        return bytes([prefix | 27]) + value.to_bytes(8, "big")
    raise CanonError("value too large for a CBOR head (max 8-byte length/argument)")


def encode(obj) -> bytes:
    """Encode obj as canonical CBOR, restricted to major types 0-5.
    Raises CanonError on any type outside that restriction, including
    bool, float, and None -- these are structurally inexpressible here,
    not merely disallowed by convention."""
    if isinstance(obj, bool):
        raise CanonError("bool is not representable (major type 7 is excluded)")
    if isinstance(obj, int):
        if obj >= 0:
            return _encode_head(MAJOR_UINT, obj)
        return _encode_head(MAJOR_NINT, -1 - obj)
    if isinstance(obj, (bytes, bytearray)):
        b = bytes(obj)
        return _encode_head(MAJOR_BSTR, len(b)) + b
    if isinstance(obj, str):
        b = obj.encode("utf-8")
        return _encode_head(MAJOR_TSTR, len(b)) + b
    if isinstance(obj, (list, tuple)):
        out = bytearray(_encode_head(MAJOR_ARRAY, len(obj)))
        for item in obj:
            out += encode(item)
        return bytes(out)
    if isinstance(obj, dict):
        # No duplicate-key guard needed here: a Python dict cannot itself
        # contain two equal keys, and encoding is injective within and
        # across the restricted key types (int/bytes/str each encode to
        # byte strings that cannot collide with a different value of the
        # same type or with any value of another type, since the major-
        # type bits differ). Duplicates are only reachable from untrusted
        # bytes, which is what the decode-side check below guards against.
        encoded_pairs = [(encode(k), encode(v)) for k, v in obj.items()]
        encoded_pairs.sort(key=lambda kv: kv[0])
        out = bytearray(_encode_head(MAJOR_MAP, len(encoded_pairs)))
        for k, v in encoded_pairs:
            out += k
            out += v
        return bytes(out)
    if isinstance(obj, float):
        raise CanonError("float is not representable (no floats in signed/hashed objects)")
    raise CanonError(f"unsupported type for canonical CBOR: {type(obj).__name__}")


def encode_tagged(domain_tag: str, obj) -> bytes:
    """encode([domain_tag, obj]) -- the injective tagged-pair form signed
    bytes are built over (§8, §9), never a concatenated prefix."""
    return encode([domain_tag, obj])


def _decode_uint_arg(data: bytes, offset: int, info: int):
    if info < 24:
        return info, offset
    if info == 24:
        if offset + 1 > len(data):
            raise CanonError("truncated 1-byte argument")
        v = data[offset]
        if v < 24:
            raise CanonError("non-shortest-form 1-byte argument")
        return v, offset + 1
    if info == 25:
        if offset + 2 > len(data):
            raise CanonError("truncated 2-byte argument")
        v = int.from_bytes(data[offset:offset + 2], "big")
        if v < 256:
            raise CanonError("non-shortest-form 2-byte argument")
        return v, offset + 2
    if info == 26:
        if offset + 4 > len(data):
            raise CanonError("truncated 4-byte argument")
        v = int.from_bytes(data[offset:offset + 4], "big")
        if v < 65536:
            raise CanonError("non-shortest-form 4-byte argument")
        return v, offset + 4
    if info == 27:
        if offset + 8 > len(data):
            raise CanonError("truncated 8-byte argument")
        v = int.from_bytes(data[offset:offset + 8], "big")
        if v < 2 ** 32:
            raise CanonError("non-shortest-form 8-byte argument")
        return v, offset + 8
    raise CanonError("indefinite length / reserved additional info not permitted")


def _decode_item(data: bytes, offset: int):
    if offset >= len(data):
        raise CanonError("unexpected end of input")
    initial = data[offset]
    major = initial >> 5
    info = initial & 0x1F
    offset += 1

    if major in (MAJOR_UINT, MAJOR_NINT):
        value, offset = _decode_uint_arg(data, offset, info)
        return (value if major == MAJOR_UINT else -1 - value), offset

    if major == MAJOR_BSTR:
        length, offset = _decode_uint_arg(data, offset, info)
        if offset + length > len(data):
            raise CanonError("byte string exceeds input")
        return bytes(data[offset:offset + length]), offset + length

    if major == MAJOR_TSTR:
        length, offset = _decode_uint_arg(data, offset, info)
        if offset + length > len(data):
            raise CanonError("text string exceeds input")
        raw = data[offset:offset + length]
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as e:
            raise CanonError(f"invalid utf-8 in text string: {e}")
        return text, offset + length

    if major == MAJOR_ARRAY:
        count, offset = _decode_uint_arg(data, offset, info)
        items = []
        for _ in range(count):
            item, offset = _decode_item(data, offset)
            items.append(item)
        return items, offset

    if major == MAJOR_MAP:
        count, offset = _decode_uint_arg(data, offset, info)
        items = []
        prev_key_bytes = None
        for _ in range(count):
            key_start = offset
            key, offset = _decode_item(data, offset)
            key_bytes = data[key_start:offset]
            val, offset = _decode_item(data, offset)
            if prev_key_bytes is not None:
                if key_bytes == prev_key_bytes:
                    raise CanonError("duplicate map key")
                if key_bytes < prev_key_bytes:
                    raise CanonError("map keys not in canonical bytewise order")
            prev_key_bytes = key_bytes
            items.append((key, val))
        return dict(items), offset

    raise CanonError(f"major type {major} not permitted (restricted to 0-5)")


def decode(data: bytes):
    """Strict decode: rejects non-canonical encodings (non-shortest-form
    heads, indefinite length, out-of-order or duplicate map keys, major
    types 6/7) and trailing bytes, rather than silently accepting and
    re-interpreting them (§8: acceptance is a downgrade vector)."""
    value, offset = _decode_item(data, 0)
    if offset != len(data):
        raise CanonError("trailing bytes after canonical CBOR item")
    return value
