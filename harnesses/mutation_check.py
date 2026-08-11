"""Mutation testing harness (CLAUDE.md §12), covering trust_kernel/sign.py
(§9), the Phase 2 kernel core: bands.py, ctpr.py, policy.py (§4), the Phase
3/4 wire schema and evidence plane, the Phase 5 enforcement plane (§6), and
the Phase 6 Observer (§2, P2).

Mutation testing is first-class, not an appendix. For each asserted
property, this harness injects a mutant that violates the property and
checks that `python3 -m unittest discover -s tests` fails against the
mutated copy. A surviving mutant means the property is untested.
Criterion: 100% kill rate.

Each mutant is a full-repository copy (trust_kernel/, tests/, config/) with
a single source substitution applied to one target module, run as a
separate `unittest discover` subprocess -- this avoids import-caching
artifacts from mutating an already-imported module in-process, and
exercises the mutant exactly the way CI would.
"""

import pathlib
import shutil
import subprocess
import sys
import tempfile

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

# (target module relative path, name, original snippet, mutated snippet, property under test)
MUTANTS = [
    # --- trust_kernel/sign.py (§9) ---
    (
        "trust_kernel/sign.py",
        "disable_scalar_canonicality_check",
        'if not _scalar_is_canonical(s):\n        return False',
        'if False:\n        return False',
        "§9: reject S >= L",
    ),
    (
        "trust_kernel/sign.py",
        "invert_scalar_canonicality_comparison",
        'return int.from_bytes(s, "little") < L',
        'return int.from_bytes(s, "little") >= L',
        "§9: reject S >= L (pure helper)",
    ),
    (
        "trust_kernel/sign.py",
        "disable_r_subgroup_check",
        'if not _is_valid_point(r):\n        return False',
        'if False:\n        return False',
        "§9: R canonical + prime-order subgroup",
    ),
    (
        "trust_kernel/sign.py",
        "disable_a_subgroup_check",
        'if not _is_valid_point(public_key):\n        return False',
        'if False:\n        return False',
        "§9: A canonical + prime-order subgroup",
    ),
    (
        "trust_kernel/sign.py",
        "invert_final_equation_result",
        "return rc == 0",
        "return rc != 0",
        "§9: verify the standard equation",
    ),
    (
        "trust_kernel/sign.py",
        "always_accept",
        "return rc == 0",
        "return True",
        "§9: verify the standard equation (always-true regression)",
    ),
    (
        "trust_kernel/sign.py",
        "swap_r_s_split",
        "r = signature[:32]\n    s = signature[32:]",
        "r = signature[32:]\n    s = signature[:32]",
        "§9: k = SHA-512(R || A || M); R/S must be the correct halves",
    ),
    (
        "trust_kernel/sign.py",
        "skip_length_check",
        "if len(public_key) != PUBLIC_KEY_BYTES or len(signature) != SIGNATURE_BYTES:\n        return False",
        "if False:\n        return False",
        "structural: fixed-size public key / signature",
    ),
    (
        "trust_kernel/sign.py",
        "off_by_one_l_constant",
        "L = 2 ** 252 + 27742317777372353535851937790883648493",
        "L = 2 ** 252 + 27742317777372353535851937790883648494",
        "§9: L is the exact prime subgroup order",
    ),
    # --- trust_kernel/bands.py (§4: bands + reduce stages) ---
    (
        "trust_kernel/bands.py",
        "drop_polarity_in_score",
        "return polarity * raw_measurement",
        "return raw_measurement",
        "§4: s = pol x raw_measurement",
    ),
    (
        "trust_kernel/bands.py",
        "meet_becomes_max",
        "return TrustLevel(min(int(l) for l in levels))",
        "return TrustLevel(max(int(l) for l in levels))",
        "§4: meet takes the worst level",
    ),
    (
        "trust_kernel/bands.py",
        "theta1_boundary_off_by_one",
        "if p[fpr_key] <= alpha_bp:",
        "if p[fpr_key] < alpha_bp:",
        "§4: theta1 = max{t : FPR(t) <= alpha}",
    ),
    (
        "trust_kernel/bands.py",
        "theta2_boundary_off_by_one",
        "if p[tpr_key] >= tpr_floor:",
        "if p[tpr_key] > tpr_floor:",
        "§4: theta2 = min{t : TPR(t) >= 1-beta}",
    ),
    (
        "trust_kernel/bands.py",
        "band_lower_boundary_off_by_one",
        "if s < theta1:",
        "if s <= theta1:",
        "§4: band(s) = LOW iff s < theta1",
    ),
    (
        "trust_kernel/bands.py",
        "band_skips_cap_meet",
        "return meet(raw, band_cap)",
        "return raw",
        "§4: band(s) is meet-capped by band_cap",
    ),
    (
        "trust_kernel/bands.py",
        "missing_claim_not_forced_low",
        "resolved = [TrustLevel.LOW if b is None else b for b in claim_bands]",
        "resolved = [b for b in claim_bands if b is not None]",
        "§4: a missing claim contributes LOW to the intra-dimension meet",
    ),
    (
        "trust_kernel/bands.py",
        "measured_placeholder_check_disabled",
        'if raw["calibration_status"] == "measured" and claim.get("placeholder"):',
        'if False:',
        "§13: validate_eis_config() refuses measured status with placeholder derivations",
    ),
    # --- trust_kernel/ctpr.py (§4: CTPR stage) ---
    (
        "trust_kernel/ctpr.py",
        "g_becomes_constant_high",
        "return parent_level",
        "return TrustLevel.HIGH",
        "§4: g is monotone in the parent's trust level (not a constant cap)",
    ),
    (
        "trust_kernel/ctpr.py",
        "ctpr_ignores_child_level",
        "effective[child] = meet(effective[child], g(effective[parent]))",
        "effective[child] = g(effective[parent])",
        "§4: effective_child = meet(child, g(parent))",
    ),
    # --- trust_kernel/policy.py (§4: pi stage) ---
    (
        "trust_kernel/policy.py",
        "strict_low_becomes_constrained",
        "TrustLevel.LOW: Verdict.Safe,\n            TrustLevel.MED: Verdict.Constrained,\n            TrustLevel.HIGH: Verdict.Normal,\n        }\n    elif dimension in lenient:",
        "TrustLevel.LOW: Verdict.Constrained,\n            TrustLevel.MED: Verdict.Constrained,\n            TrustLevel.HIGH: Verdict.Normal,\n        }\n    elif dimension in lenient:",
        "§4: strict dimensions floor to Safe on LOW alone",
    ),
    (
        "trust_kernel/policy.py",
        "lenient_low_becomes_safe",
        "TrustLevel.LOW: Verdict.Constrained,\n            TrustLevel.MED: Verdict.Constrained,\n            TrustLevel.HIGH: Verdict.Normal,\n        }\n    else:",
        "TrustLevel.LOW: Verdict.Safe,\n            TrustLevel.MED: Verdict.Constrained,\n            TrustLevel.HIGH: Verdict.Normal,\n        }\n    else:",
        "§4: lenient dimensions floor to Constrained (not Safe) on LOW alone",
    ),
    (
        "trust_kernel/policy.py",
        "policy_meet_becomes_max",
        "return min(crit(d, effective_dims[d], strict, lenient) for d in DIMENSIONS)",
        "return max(crit(d, effective_dims[d], strict, lenient) for d in DIMENSIONS)",
        "§4: pi(e) = meet_d crit_d(effective_d)",
    ),
    (
        "trust_kernel/policy.py",
        "stale_check_disabled",
        "if stale:\n        return Verdict.Safe",
        "if False:\n        return Verdict.Safe",
        "§4: stale evidence forces Safe",
    ),
    # --- trust_kernel/canon.py (§8, §9: canonical CBOR) ---
    (
        "trust_kernel/canon.py",
        "bool_rejection_disabled",
        'if isinstance(obj, bool):\n        raise CanonError("bool is not representable (major type 7 is excluded)")',
        "pass",
        "§8: floats/booleans/null are structurally inexpressible",
    ),
    (
        "trust_kernel/canon.py",
        "shortest_form_1byte_check_disabled",
        'v = data[offset]\n        if v < 24:\n            raise CanonError("non-shortest-form 1-byte argument")',
        "v = data[offset]",
        "§8: shortest-form heads only",
    ),
    (
        "trust_kernel/canon.py",
        "decode_side_map_order_check_disabled",
        "if key_bytes == prev_key_bytes:\n                    raise CanonError(\"duplicate map key\")\n                if key_bytes < prev_key_bytes:\n                    raise CanonError(\"map keys not in canonical bytewise order\")",
        "pass",
        "§8: bytewise-sorted map keys, duplicates rejected, on the decode path",
    ),
    (
        "trust_kernel/canon.py",
        "trailing_bytes_check_disabled",
        "if offset != len(data):\n        raise CanonError(\"trailing bytes after canonical CBOR item\")",
        "if False:\n        raise CanonError(\"trailing bytes after canonical CBOR item\")",
        "§8: definite-length items, no trailing garbage",
    ),
    (
        "trust_kernel/canon.py",
        "negative_int_off_by_one",
        "return (value if major == MAJOR_UINT else -1 - value), offset",
        "return (value if major == MAJOR_UINT else -value), offset",
        "§8: negative integers encoded as -1-n (RFC 8949 major type 1)",
    ),
    (
        "trust_kernel/canon.py",
        "encode_tagged_pair_order_swapped",
        "return encode([domain_tag, obj])",
        "return encode([obj, domain_tag])",
        "§9: sign over encode([domain_tag, object]), not [object, domain_tag]",
    ),
    # --- trust_kernel/schema.py (§8, §9, §10: T4 admission + verdict issuance) ---
    (
        "trust_kernel/schema.py",
        "statement_payload_includes_sig",
        'unsigned = {k: v for k, v in fields.items() if k != "sig"}\n    return canon.encode_tagged(DOMAIN_STATEMENT, unsigned)',
        'return canon.encode_tagged(DOMAIN_STATEMENT, fields)',
        "§9: sig itself is excluded from the bytes it signs over",
    ),
    (
        "trust_kernel/schema.py",
        "verdict_payload_includes_kernel_sig",
        'unsigned = {k: v for k, v in fields.items() if k != "kernel_sig"}\n    return canon.encode_tagged(DOMAIN_VERDICT, unsigned)',
        'return canon.encode_tagged(DOMAIN_VERDICT, fields)',
        "§9: kernel_sig itself is excluded from the bytes it signs over",
    ),
    (
        "trust_kernel/schema.py",
        "admission_order_signature_and_schema_swapped",
        "    # 2. schema / version\n    shape_error = _validate_statement_shape(statement, claim_registry)\n    if shape_error is not None:\n        return AdmissionResult(False, \"schema\", shape_error)\n\n    # 3. source authorised for boundary (+ claim type authorisation)\n    if statement[\"source_id\"] != key_entry[\"source_id\"]:",
        "    # 3. source authorised for boundary (+ claim type authorisation)\n    if statement[\"source_id\"] != key_entry[\"source_id\"]:",
        "§10: fixed verification order -- schema must be checked before authorization",
    ),
    (
        "trust_kernel/schema.py",
        "window_id_check_disabled",
        '    if statement["window_id"] != current_window_id:\n        return AdmissionResult(False, "window_id",',
        '    if False:\n        return AdmissionResult(False, "window_id",',
        "§10: window_id matches round",
    ),
    (
        "trust_kernel/schema.py",
        "arrival_deadline_off_by_one",
        "if arrival_time_ms >= deadline:",
        "if arrival_time_ms > deadline:",
        "§10: arrival strictly before Delta(w) -- exactly-at-deadline is late",
    ),
    (
        "trust_kernel/schema.py",
        "boundary_authorization_check_disabled",
        '    if statement["boundary"] != key_entry["boundary"]:\n        return AdmissionResult(False, "authorization",\n                                f"key_id {key_id!r} is not authorised at boundary {statement[\'boundary\']!r}")',
        "    pass",
        "§10: source authorised for the claimed boundary",
    ),
    (
        "trust_kernel/schema.py",
        "evidence_root_dedup_sort_disabled",
        "hashes = sorted(set(statement_hash(s) for s in admitted_statements))",
        "hashes = [statement_hash(s) for s in admitted_statements]",
        "§8: evidence_root dedupes by statement hash and sorts lexicographically",
    ),
    # --- evidence_plane/log.py (§2, §8: hash-chained evidence log) ---
    (
        "evidence_plane/log.py",
        "prev_hash_linkage_check_disabled",
        'entry["prev_hash"] == prev_hash\n            and entry["entry_hash"]',
        'True\n            and entry["entry_hash"]',
        "§8: entry_hash chains via prev_hash; deletion/reordering must break linkage",
    ),
    (
        "evidence_plane/log.py",
        "entry_hash_recompute_check_disabled",
        'and entry["entry_hash"] == compute_entry_hash(entry["seq"], entry["prev_hash"], entry["statement"])',
        "and True",
        "§8: entry_hash is recomputed and compared, not trusted as stored",
    ),
    (
        "evidence_plane/log.py",
        "first_broken_keeps_overwriting",
        "if not locally_valid and first_broken is None:",
        "if not locally_valid:",
        "§12: tamper-evidence reports the FIRST broken position, not the last",
    ),
    (
        "evidence_plane/log.py",
        "broken_seqs_off_by_one",
        'broken_seqs = [e["seq"] for e in entries if first_broken is not None and e["seq"] >= first_broken]',
        'broken_seqs = [e["seq"] for e in entries if first_broken is not None and e["seq"] > first_broken]',
        "§12: the tampered entry itself is reported broken, not just its successors",
    ),
    (
        "evidence_plane/log.py",
        "entry_hash_excludes_statement",
        'payload = canon.encode({"seq": seq, "prev_hash": prev_hash, "statement": statement})',
        'payload = canon.encode({"seq": seq, "prev_hash": prev_hash})',
        "§8: entry_hash covers the statement, so mutating it is detectable",
    ),
    (
        "evidence_plane/log.py",
        "seq_not_incremented",
        "self._next_seq += 1",
        "pass",
        "§8: seq is assigned sequentially by the single writer",
    ),
    # --- evidence_plane/replay.py (§8, §12, §13: verdict replay) ---
    (
        "evidence_plane/replay.py",
        "config_mismatch_short_circuit_disabled",
        "if mismatched:\n        return ReplayResult(agreement=False, config_mismatch=True, mismatched_hashes=mismatched)",
        "if False:\n        return ReplayResult(agreement=False, config_mismatch=True, mismatched_hashes=mismatched)",
        "§13: a config hash mismatch aborts replay before recomputing pi",
    ),
    (
        "evidence_plane/replay.py",
        "mismatch_comparison_inverted",
        "if current != verdict[field_name]",
        "if current == verdict[field_name]",
        "§13: mismatched_hashes reports hashes that DIFFER from the verdict",
    ),
    (
        "evidence_plane/replay.py",
        "evidence_root_check_disabled",
        'if recomputed_root != verdict["evidence_root"]:\n        return ReplayResult(agreement=False, config_mismatch=False, evidence_mismatch=True)',
        'if False:\n        return ReplayResult(agreement=False, config_mismatch=False, evidence_mismatch=True)',
        "§8: replay must use exactly the statement set evidence_root commits to",
    ),
    (
        "evidence_plane/replay.py",
        "agreement_and_becomes_or",
        'recomputed_verdict.name == verdict["verdict"]\n        and recomputed_effective_dims == verdict["effective_dims"]',
        'recomputed_verdict.name == verdict["verdict"]\n        or recomputed_effective_dims == verdict["effective_dims"]',
        "§12: verdict AND effective_dims must both match for agreement",
    ),
    # --- enforcement/clamp.py (§5, §6: realise, binding condition, accept) ---
    (
        "enforcement/clamp.py",
        "realise_meet_becomes_max",
        '"max_speed": min(e["max_speed"], ceil["max_speed"]),\n        "max_acceleration": min(e["max_acceleration"], ceil["max_acceleration"]),',
        '"max_speed": max(e["max_speed"], ceil["max_speed"]),\n        "max_acceleration": max(e["max_acceleration"], ceil["max_acceleration"]),',
        "§6: realise(ν) = Env(π̂(ν)) ⊓ Ceil, meet = componentwise min",
    ),
    (
        "enforcement/clamp.py",
        "binding_condition_check_disabled",
        'if not (ceil["max_speed"] < normal["max_speed"] and ceil["max_acceleration"] < normal["max_acceleration"]):',
        "if False:",
        "§6: Ceil ⊏ Env(Normal) componentwise, checked at load, fail-closed",
    ),
    (
        "enforcement/clamp.py",
        "signature_check_disabled",
        "if not schema.verify_verdict_signature(kernel_public_key, verdict_obj):\n        return AcceptResult(False, \"signature\", None)",
        "pass",
        "§6: accept(ν) requires sig valid",
    ),
    (
        "enforcement/clamp.py",
        "schema_support_check_disabled",
        "if view.schema_version not in SUPPORTED_SCHEMA_VERSIONS:\n        return AcceptResult(False, \"schema\", None)",
        "pass",
        "§6: accept(ν) requires schema supported",
    ),
    (
        "enforcement/clamp.py",
        "replay_cache_check_disabled",
        "if cache.contains(view.window_id):\n        return AcceptResult(False, \"replay\", None)",
        "pass",
        "§6: accept(ν) requires window_id not in accept_cache",
    ),
    (
        "enforcement/clamp.py",
        "expiry_check_inverted",
        "if not (now_ms < view.expires_at):",
        "if not (now_ms > view.expires_at):",
        "§6: accept(ν) requires now < expires_at",
    ),
    (
        "enforcement/clamp.py",
        "ring_eviction_disabled",
        "if len(self._seen) > self._size:\n            self._seen.pop(0)",
        "pass",
        "§6: accept_cache is a bounded 2-entry ring, not an unbounded set",
    ),
    (
        "enforcement/clamp.py",
        "rejected_verdict_gets_an_envelope",
        "if not result.accepted:\n        return EnforcementDecision(False, result.reason, None)",
        "if not result.accepted:\n        return EnforcementDecision(False, result.reason, {\"max_speed\": 0, \"max_acceleration\": 0})",
        "§6: a rejected verdict produces no envelope at all (capability.py: no token presented, no write)",
    ),
    # --- enforcement/capability.py (§2 P4, §6: capability-gated actuator write) ---
    (
        "enforcement/capability.py",
        "capability_identity_check_disabled",
        "if capability is not self._capability:",
        "if False:",
        "§6: only the exact capability object issued to the enforcer authorises a write",
    ),
    # --- enforcement/slew.py (§6, §7: asymmetric slew) ---
    (
        "enforcement/slew.py",
        "loosening_rate_limit_removed",
        "return min(target, current + max_increase)",
        "return target",
        "§6/§7: loosening is rate-limited to <=200 mm/s and <=100 mm/s^2 per window",
    ),
    (
        "enforcement/slew.py",
        "step_size_off_by_one",
        "MAX_SPEED_STEP_MM_S = 200          # per-window loosening limit",
        "MAX_SPEED_STEP_MM_S = 201          # per-window loosening limit",
        "§7: the per-window loosening step is exactly 200 mm/s, matching Safe->full = 5 windows",
    ),
    # --- observer/observer.py (§2, P2: sole origin of ActuationFidelity evidence) ---
    (
        "observer/observer.py",
        "fidelity_floor_clamp_disabled",
        "return max(FIDELITY_FLOOR, FIDELITY_CEIL - discrepancy)",
        "return FIDELITY_CEIL - discrepancy",
        "§2: raw_measurement is bounded at FIDELITY_FLOOR even under a large discrepancy",
    ),
    (
        "observer/observer.py",
        "acceleration_discrepancy_dropped",
        'abs(observed["max_speed"] - commanded["max_speed"])\n        + abs(observed["max_acceleration"] - commanded["max_acceleration"])',
        'abs(observed["max_speed"] - commanded["max_speed"])',
        "§2: the measurement covers both max_speed and max_acceleration, not speed alone",
    ),
    (
        "observer/observer.py",
        "window_id_not_threaded_through",
        "window_id=window_id, claimed_at=claimed_at,\n        )\n        return schema.sign_statement(self._secret_key, fields)",
        "window_id=0, claimed_at=claimed_at,\n        )\n        return schema.sign_statement(self._secret_key, fields)",
        "§8: the statement's window_id must be the caller-supplied window, not a constant",
    ),
    (
        "observer/observer.py",
        "observe_and_append_does_not_append",
        "        log.append(statement)\n        return statement",
        "        return statement",
        "§10: sensors append -- observe_and_append must actually append to the Evidence Plane",
    ),
]

COPY_DIRS = ["trust_kernel", "evidence_plane", "enforcement", "observer", "tests", "config"]


def _run_suite(root):
    proc = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return proc.returncode == 0, proc


def _run_baseline():
    passed, proc = _run_suite(REPO_ROOT)
    if not passed:
        raise SystemExit(
            "baseline test suite does not pass on unmutated source; "
            "fix tests before running mutation analysis\n" + proc.stdout + proc.stderr
        )


def main():
    _run_baseline()

    results = []
    for target, name, old, new, prop in MUTANTS:
        target_path = REPO_ROOT / target
        source = target_path.read_text()
        if old not in source:
            raise SystemExit(f"mutant '{name}': anchor text not found in {target} (source drifted)")
        mutated_source = source.replace(old, new, 1)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            for d in COPY_DIRS:
                shutil.copytree(REPO_ROOT / d, tmp_path / d)
            (tmp_path / target).write_text(mutated_source)

            passed, proc = _run_suite(tmp_path)
            killed = not passed
            killing_tests = _extract_failed_tests(proc.stderr) if killed else []
            results.append((target, name, prop, killed, killing_tests))

    total = len(results)
    killed_count = sum(1 for *_, killed, _ in results if killed)

    print(f"Mutation kill rate: {killed_count}/{total} ({100 * killed_count // total}%)\n")
    current_target = None
    for target, name, prop, killed, killing_tests in results:
        if target != current_target:
            print(f"-- {target} --")
            current_target = target
        status = "KILLED  " if killed else "SURVIVED"
        print(f"  [{status}] {name}  ({prop})")
        if killed:
            for t in killing_tests:
                print(f"             caught by: {t}")
        else:
            print("             *** no test asserts this property ***")

    if killed_count < total:
        sys.exit(1)


def _extract_failed_tests(stderr):
    names = []
    for line in stderr.splitlines():
        line = line.strip()
        if line.startswith("FAIL:") or line.startswith("ERROR:"):
            names.append(line.split(" ", 1)[1].split(" ")[0])
    return names


if __name__ == "__main__":
    main()
