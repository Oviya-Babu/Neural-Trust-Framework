"""Shared test helper for Phase 5 (enforcement plane): a dynamic guard that
turns "the enforcer reads exactly five fields" (CLAUDE.md §6) into a live
assertion instead of a documentation claim.
"""

from enforcement.clamp import ENFORCER_FIELDS


class GuardedVerdictDict(dict):
    """Wraps a real, full verdict dict. Raises AssertionError the instant
    any code subscripts, .get()s, or `in`-checks a key outside the five
    allowed enforcement fields.

    .items() / .keys() / .values() are deliberately left unguarded:
    trust_kernel.schema.verify_verdict_signature() legitimately needs the
    complete signed object to recompute the exact payload bytes the kernel
    signed over -- that is a single bytewise/opaque re-hash of the whole
    blob, not a decision that branches on any individual field's meaning
    (see enforcement/clamp.py's module docstring). Python's built-in
    dict.items()/keys()/values() do not route through a subclass's
    __getitem__/__contains__ override, so this guard cannot see or block
    that call -- which is exactly the boundary we want to test: everything
    the enforcement *decision logic* touches by name must be one of the
    five fields, while the opaque signature re-hash remains untouched by
    this guard.
    """

    def _check(self, key):
        if key not in ENFORCER_FIELDS:
            raise AssertionError(f"enforcement path accessed forbidden verdict field: {key!r}")

    def __getitem__(self, key):
        self._check(key)
        return super().__getitem__(key)

    def get(self, key, default=None):
        self._check(key)
        return super().get(key, default)

    def __contains__(self, key):
        self._check(key)
        return super().__contains__(key)
