"""Verdict replay (CLAUDE.md §8, §12, §13): given a verdict and its
consumed statement set, an independent verifier recomputes π and confirms
exact agreement. Replay does not re-run T4 admission (signature/schema/
authorization/window/arrival) -- that decision was already made once, at
issuance time, and is what produced the admitted set the verdict's
evidence_root commits to. Replay's job is narrower and different: is the
recorded OUTCOME reproducible from the recorded EVIDENCE under the
recorded CONFIG? That is what "verdicts replayable from the log" (§2)
actually claims.

Fail-closed ordering, deliberately: config hashes are checked BEFORE any
attempt to recompute π. Replaying under a silently different config (a
rotated key, an edited threshold, a swapped scale) would "silently
reinterpret all history" (§8) -- so a hash mismatch must abort replay
outright, not fall through to a recomputation that used the wrong
config and merely happened to agree or disagree by chance.
"""

from dataclasses import dataclass, field
from typing import Optional

from trust_kernel import ctpr as ctpr_mod, policy as policy_mod, schema
from trust_kernel.bands import DIMENSIONS, band, load_eis_config, reduce_dimension, roc_config_hash, score as score_fn


@dataclass
class ReplayResult:
    agreement: bool
    config_mismatch: bool
    mismatched_hashes: list = field(default_factory=list)
    evidence_mismatch: bool = False
    recomputed_verdict: Optional[str] = None
    recorded_verdict: Optional[str] = None
    recomputed_effective_dims: Optional[dict] = None
    recorded_effective_dims: Optional[dict] = None


_HASH_FIELD_TO_CONFIG_KEY = {
    "crit_table_hash": "crit_table",
    "ctpr_config_hash": "ctpr",
    "roc_config_hash": "eis",
    "claim_registry_hash": "claim_registry",
    "key_registry_hash": "key_registry",
}


def _current_config_hashes(config_paths: dict) -> dict:
    return {
        "crit_table_hash": policy_mod.crit_table_hash(config_paths["crit_table"]),
        "ctpr_config_hash": ctpr_mod.ctpr_config_hash(config_paths["ctpr"]),
        "roc_config_hash": roc_config_hash(config_paths["eis"]),
        "claim_registry_hash": schema.claim_registry_hash(config_paths["claim_registry"]),
        "key_registry_hash": schema.key_registry_hash(config_paths["key_registry"]),
    }


def replay_verdict(verdict: dict, admitted_statements: list, *, config_paths: dict) -> ReplayResult:
    # 1. Config hashes -- checked first, fail-closed.
    current_hashes = _current_config_hashes(config_paths)
    mismatched = [
        field_name for field_name, current in current_hashes.items()
        if current != verdict[field_name]
    ]
    if mismatched:
        return ReplayResult(agreement=False, config_mismatch=True, mismatched_hashes=mismatched)

    # 2. Evidence set -- the statements actually presented must be exactly
    # the set the verdict's evidence_root commits to.
    recomputed_root = schema.build_evidence_root(admitted_statements)
    if recomputed_root != verdict["evidence_root"]:
        return ReplayResult(agreement=False, config_mismatch=False, evidence_mismatch=True)

    # 3. Recompute pi from the admitted statements under the (now-verified)
    # config.
    claim_registry = schema.load_claim_registry(config_paths["claim_registry"])
    _, eis_derived = load_eis_config(config_paths["eis"])
    _, edges = ctpr_mod.load_ctpr_config(config_paths["ctpr"])
    _, strict, lenient = policy_mod.load_crit_table(config_paths["crit_table"])

    by_dimension = {d: [] for d in DIMENSIONS}
    for stmt in admitted_statements:
        claim_entry = claim_registry["claims"][stmt["claim_type"]]
        dimension = claim_entry["dimension"]
        theta1, theta2, cap = eis_derived[stmt["claim_type"]]
        s = score_fn(1, stmt["raw_measurement"])
        by_dimension[dimension].append(band(s, theta1, theta2, cap))

    raw_dims = {
        d: reduce_dimension(claims) if claims else reduce_dimension([None])
        for d, claims in by_dimension.items()
    }
    effective = ctpr_mod.apply_ctpr(raw_dims, edges)
    recomputed_verdict = policy_mod.policy(effective, strict, lenient)

    recomputed_effective_dims = {d: effective[d].name for d in DIMENSIONS}
    agreement = (
        recomputed_verdict.name == verdict["verdict"]
        and recomputed_effective_dims == verdict["effective_dims"]
    )
    return ReplayResult(
        agreement=agreement, config_mismatch=False,
        recomputed_verdict=recomputed_verdict.name, recorded_verdict=verdict["verdict"],
        recomputed_effective_dims=recomputed_effective_dims,
        recorded_effective_dims=verdict["effective_dims"],
    )
