"""Evidence Plane: append-only, content-addressed, hash-chained log
(CLAUDE.md §2, §8). Entries {seq, prev_hash, entry_hash, statement},
single writer.

The chain is over entries, not statements: entry_hash = H(seq, prev_hash,
statement). Sensor signatures cover only the statement; they never cover
prev_hash or any other chain state (§8: "Never readmit prev_hash,
trust_level, or confidence to a statement" -- the statement/entry split is
exactly what keeps a sensor's signed bytes independent of log position, so
a sensor never needs to know the chain to produce a valid statement, and
the chain's integrity is a property of the log alone).

Tamper-evidence, not tamper-prevention: an entry's own entry_hash can
always be recomputed by anyone (it is a public hash, not a signature), so
a tamperer can rewrite entry_hash to stay locally self-consistent with a
mutated statement -- what they cannot do is make that new entry_hash equal
the value already recorded as prev_hash in every entry appended after it,
without also rewriting all of those. That cascading requirement is the
tamper-evidence property: once entry k fails its own recomputed-hash
check, every entry from k onward is untrusted, regardless of whether a
later entry's own local linkage happens to still nominally check out.

fsync discipline (§7): fsync the window batch before the kernel reads it
-- 2ms of 100ms, closes the crash-window hole where a verdict references
non-durable evidence. Per-record fsync is not used (append() does not
fsync); call fsync_window() once per window batch.
"""

import os
import struct

from trust_kernel import canon

GENESIS_PREV_HASH = b"\x00" * 32


class LogError(ValueError):
    pass


def compute_entry_hash(seq: int, prev_hash: bytes, statement: dict) -> bytes:
    import hashlib
    payload = canon.encode({"seq": seq, "prev_hash": prev_hash, "statement": statement})
    return hashlib.sha256(payload).digest()


def build_entry(seq: int, prev_hash: bytes, statement: dict) -> dict:
    return {
        "seq": seq,
        "prev_hash": prev_hash,
        "entry_hash": compute_entry_hash(seq, prev_hash, statement),
        "statement": statement,
    }


def read_all(path) -> list:
    """Reads a log file from disk. Standalone (no write handle opened) --
    a verifier or replay caller needs no write access to inspect a log."""
    entries = []
    with open(path, "rb") as f:
        while True:
            header = f.read(4)
            if not header:
                break
            if len(header) != 4:
                raise LogError("truncated length header")
            (length,) = struct.unpack(">I", header)
            record = f.read(length)
            if len(record) != length:
                raise LogError("truncated record")
            entry = canon.decode(record)
            entries.append(entry)
    return entries


class EvidenceLog:
    """Single-writer append-only log backed by a length-prefixed canonical-
    CBOR file. Each record is a 4-byte big-endian length followed by
    canon.encode(entry)."""

    def __init__(self, path):
        self._path = path
        if not os.path.exists(path):
            open(path, "xb").close()
        self._file = open(path, "ab")
        existing = read_all(path)
        if existing:
            self._next_seq = existing[-1]["seq"] + 1
            self._last_hash = existing[-1]["entry_hash"]
        else:
            self._next_seq = 0
            self._last_hash = GENESIS_PREV_HASH

    def append(self, statement: dict) -> dict:
        entry = build_entry(self._next_seq, self._last_hash, statement)
        record = canon.encode(entry)
        self._file.write(struct.pack(">I", len(record)))
        self._file.write(record)
        self._next_seq += 1
        self._last_hash = entry["entry_hash"]
        return entry

    def fsync_window(self):
        """Call once per window batch, before the kernel reads it (§7)."""
        self._file.flush()
        os.fsync(self._file.fileno())

    def close(self):
        self._file.close()

    def read_all(self) -> list:
        """Reads the log from disk independently of this instance's
        in-memory write state."""
        return read_all(self._path)


class ChainVerification:
    def __init__(self, valid: bool, first_broken_seq, broken_seqs: list, checked: int):
        self.valid = valid
        self.first_broken_seq = first_broken_seq
        self.broken_seqs = broken_seqs
        self.checked = checked

    def __repr__(self):
        return (f"ChainVerification(valid={self.valid}, "
                f"first_broken_seq={self.first_broken_seq}, checked={self.checked})")


def verify_chain(entries: list) -> ChainVerification:
    """Recomputes entry_hash for every entry and checks prev_hash linkage.
    Once entry k fails its own recomputed-hash check, every entry from k
    onward is reported broken -- see module docstring for why a later
    entry's own local linkage passing is not sufficient to trust it."""
    first_broken = None
    prev_hash = GENESIS_PREV_HASH
    for entry in entries:
        locally_valid = (
            entry["prev_hash"] == prev_hash
            and entry["entry_hash"] == compute_entry_hash(entry["seq"], entry["prev_hash"], entry["statement"])
        )
        if not locally_valid and first_broken is None:
            first_broken = entry["seq"]
        prev_hash = entry["entry_hash"]

    broken_seqs = [e["seq"] for e in entries if first_broken is not None and e["seq"] >= first_broken]
    return ChainVerification(
        valid=first_broken is None, first_broken_seq=first_broken,
        broken_seqs=broken_seqs, checked=len(entries),
    )
