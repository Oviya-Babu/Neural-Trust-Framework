"""Phase 3 driver (CLAUDE.md §14): T4 statement admission + verdict
issuance, wired against the fixed §10 verification order.

Produces the T4 failure-mode table (§12 reportable): a baseline all-valid
window plus five statements each violating exactly one admission step
(signature, schema, authorization, window_id, arrival), plus a
cross-domain replay demonstration (a statement's signed bytes presented as
a verdict must fail on the domain tag, §9). For each admission case:
the step that rejected it, the resulting Signal-dimension level, and the
resulting overall verdict.

Label (§12): unlike the T1/T2 conformance scan (Phase 2), this table is
falsifiable -- it exercises real signature verification, real canonical
encoding, and the actual fixed verification order, and it can come out
wrong (a bug could route a violation through a different step, or fail to
reject it at all). This is the first genuinely new number in the sense
CLAUDE.md's milestone table originally used that phrase for Phase 3.

T4 freshness is honest-evidence-conditional under Position A (§3): an
adversary who owns the host forges kernel_sig and controls all clocks, so
timing/authenticity checks here hold only against an honest evidence
producer. T4 is not the basis of the central claim -- T5 is (§5).

Run: `python3 -m experiments.phase3_t4_admission` from the repo root.
"""

import json
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from trust_kernel import schema, ctpr as ctpr_mod, policy as policy_mod
from trust_kernel.bands import DIMENSIONS, TrustLevel, band, load_eis_config, roc_config_hash
from trust_kernel.policy import Verdict
from provenance import manifest as manifest_mod
from tests import key_fixtures as kf

CONFIG_DIR = REPO_ROOT / "config"
ARTIFACTS_DIR = REPO_ROOT / "artifacts"
PROVENANCE_DIR = REPO_ROOT / "provenance"

CURRENT_WINDOW_ID = 7
WINDOW_OPEN_TIME_MS = 0
ON_TIME_ARRIVAL_MS = 10
HEALTHY_RAW_MEASUREMENT = 100  # scores HIGH under the strong provisional ROC (theta2=50)

CLAIM_TYPE_BY_DIM = {
    "Signal": "signal.provisional_v0", "Model": "model.provisional_v0",
    "Calibration": "calibration.provisional_v0",
    "Device": "device.provisional_v0", "FSI": "fsi.provisional_v0",
    "ActuationFidelity": "actuationfidelity.provisional_v0",
}
SOURCE_ID_BY_DIM = {
    "Signal": "signal_sensor_v0", "Model": "model_sensor_v0",
    "Calibration": "calibration_sensor_v0", "Device": "device_sensor_v0", "FSI": "fsi_sensor_v0",
    "ActuationFidelity": "actuationfidelity_sensor_v0",
}


def _healthy_signed_statement(dimension, window_id=CURRENT_WINDOW_ID):
    source_id = SOURCE_ID_BY_DIM[dimension]
    _, sk = kf.keypair_for(source_id)
    fields = schema.build_statement(
        key_id=source_id, source_id=source_id, boundary="TB2",
        claim_type=CLAIM_TYPE_BY_DIM[dimension], raw_measurement=HEALTHY_RAW_MEASUREMENT,
        window_id=window_id, claimed_at=WINDOW_OPEN_TIME_MS,
    )
    return schema.sign_statement(sk, fields)


def _dimension_level(dimension, admitted_statement, eis_derived):
    """None if the statement was rejected (missing -> LOW via reduce), else
    the banded level from its raw_measurement."""
    from trust_kernel.bands import score as score_fn, reduce_dimension, meet
    if admitted_statement is None:
        return reduce_dimension([None])
    claim_type = CLAIM_TYPE_BY_DIM[dimension]
    theta1, theta2, cap = eis_derived[claim_type]
    s = score_fn(1, admitted_statement["raw_measurement"])
    b = band(s, theta1, theta2, cap)
    return reduce_dimension([b])


def _evaluate_window(admitted_by_dim, eis_derived, edges, strict, lenient):
    """admitted_by_dim: {dimension: signed_statement_or_None (post-admission)}."""
    raw_dims = {d: _dimension_level(d, admitted_by_dim.get(d), eis_derived) for d in DIMENSIONS}
    effective = ctpr_mod.apply_ctpr(raw_dims, edges)
    verdict = policy_mod.policy(effective, strict, lenient)
    return effective, verdict


def _run_case(name, description, key_registry, claim_registry, eis_derived, edges, strict, lenient,
              build_bad_statement, admit_kwargs_override=None):
    """Builds a full 8-dimension window where every dimension except Signal
    is healthy, Signal carries the injected violation, admits all 8
    statements, and evaluates the resulting effective dims + verdict."""
    admit_kwargs = dict(
        key_registry=key_registry, claim_registry=claim_registry,
        current_window_id=CURRENT_WINDOW_ID, window_open_time_ms=WINDOW_OPEN_TIME_MS,
        arrival_time_ms=ON_TIME_ARRIVAL_MS,
    )
    if admit_kwargs_override:
        admit_kwargs.update(admit_kwargs_override)

    healthy_admit_kwargs = dict(
        key_registry=key_registry, claim_registry=claim_registry,
        current_window_id=CURRENT_WINDOW_ID, window_open_time_ms=WINDOW_OPEN_TIME_MS,
        arrival_time_ms=ON_TIME_ARRIVAL_MS,
    )
    admitted_by_dim = {}
    admission_results = {}
    for d in DIMENSIONS:
        if d == "Signal":
            stmt = build_bad_statement()
            result = schema.admit_statement(stmt, **admit_kwargs)
        else:
            stmt = _healthy_signed_statement(d)
            result = schema.admit_statement(stmt, **healthy_admit_kwargs)
        admission_results[d] = result
        admitted_by_dim[d] = stmt if result.accepted else None

    effective, verdict = _evaluate_window(admitted_by_dim, eis_derived, edges, strict, lenient)
    signal_result = admission_results["Signal"]
    return {
        "case": name,
        "description": description,
        "failed_step": signal_result.failed_step,
        "reason": signal_result.reason,
        "signal_dimension_level": effective["Signal"].name,
        "resulting_verdict": verdict.name,
    }


def build_admission_table(key_registry, claim_registry, eis_derived, edges, strict, lenient):
    rows = []

    def valid_signal():
        return _healthy_signed_statement("Signal")

    rows.append(_run_case(
        "baseline_all_valid", "All 6 dimensions healthy, no violation",
        key_registry, claim_registry, eis_derived, edges, strict, lenient, valid_signal,
    ))

    def bad_signature():
        signed = _healthy_signed_statement("Signal")
        tampered = dict(signed)
        tampered["raw_measurement"] = 999  # invalidates signature, not re-signed
        return tampered
    rows.append(_run_case(
        "invalid_signature", "Signal statement tampered after signing (sig no longer valid)",
        key_registry, claim_registry, eis_derived, edges, strict, lenient, bad_signature,
    ))

    def bad_schema():
        signed = _healthy_signed_statement("Signal")
        tampered = dict(signed)
        tampered["schema_version"] = 999
        _, sk = kf.keypair_for("signal_sensor_v0")
        return schema.sign_statement(sk, {k: v for k, v in tampered.items() if k != "sig"})
    rows.append(_run_case(
        "unsupported_schema_version", "Signal statement declares schema_version=999",
        key_registry, claim_registry, eis_derived, edges, strict, lenient, bad_schema,
    ))

    def bad_authorization():
        signed = _healthy_signed_statement("Signal")
        tampered = dict(signed)
        tampered["boundary"] = "TB3"  # signal_sensor_v0 is only registered at TB2
        _, sk = kf.keypair_for("signal_sensor_v0")
        return schema.sign_statement(sk, {k: v for k, v in tampered.items() if k != "sig"})
    rows.append(_run_case(
        "source_unauthorised_for_boundary", "Signal statement claims boundary TB3 (key is registered only for TB2)",
        key_registry, claim_registry, eis_derived, edges, strict, lenient, bad_authorization,
    ))

    def bad_window():
        return _healthy_signed_statement("Signal", window_id=CURRENT_WINDOW_ID - 1)
    rows.append(_run_case(
        "window_id_mismatch", f"Signal statement carries window_id={CURRENT_WINDOW_ID - 1}, current round is {CURRENT_WINDOW_ID}",
        key_registry, claim_registry, eis_derived, edges, strict, lenient, bad_window,
    ))

    def late_arrival():
        return _healthy_signed_statement("Signal")
    rows.append(_run_case(
        "late_arrival", f"Signal statement arrives at {schema.EVIDENCE_DEADLINE_MS + 1}ms, deadline Delta(w) is {schema.EVIDENCE_DEADLINE_MS}ms",
        key_registry, claim_registry, eis_derived, edges, strict, lenient, late_arrival,
        admit_kwargs_override={"arrival_time_ms": schema.EVIDENCE_DEADLINE_MS + 1},
    ))

    return rows


def build_cross_domain_replay_demo():
    pk, sk = kf.keypair_for("signal_sensor_v0")
    fields = schema.build_statement(
        key_id="signal_sensor_v0", source_id="signal_sensor_v0", boundary="TB2",
        claim_type="signal.provisional_v0", raw_measurement=HEALTHY_RAW_MEASUREMENT,
        window_id=CURRENT_WINDOW_ID, claimed_at=WINDOW_OPEN_TIME_MS,
    )
    signed_statement = schema.sign_statement(sk, fields)

    relabelled_as_verdict = dict(signed_statement)
    relabelled_as_verdict["kernel_sig"] = relabelled_as_verdict.pop("sig")

    accepted_as_verdict = schema.verify_verdict_signature(pk, relabelled_as_verdict)
    return {
        "attack": "statement's signed bytes presented as a verdict",
        "same_signature_bytes_reused": True,
        "accepted_as_verdict": accepted_as_verdict,
        "rejected": not accepted_as_verdict,
        "reason": "encode_tagged('statement', fields) != encode_tagged('verdict', fields); "
                  "the domain tag is part of the signed payload, so the signature cannot "
                  "validate against a different domain even with identical field content.",
    }


def _write_json(obj, path):
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, default=lambda o: o.hex() if isinstance(o, bytes) else str(o)) + "\n")


def _write_markdown_table(rows, columns, path, title):
    lines = [f"# {title}", ""]
    lines.append("| " + " | ".join(columns) + " |")
    lines.append("|" + "|".join(["---"] * len(columns)) + "|")
    for row in rows:
        lines.append("| " + " | ".join(str(row[c]) for c in columns) + " |")
    path.write_text("\n".join(lines) + "\n")


def main():
    ARTIFACTS_DIR.mkdir(exist_ok=True)
    PROVENANCE_DIR.mkdir(exist_ok=True)

    key_registry = schema.load_key_registry(CONFIG_DIR / "key_registry.json")
    claim_registry = schema.load_claim_registry(CONFIG_DIR / "claim_registry.json")
    eis_raw, eis_derived = load_eis_config(CONFIG_DIR / "eis.v0.json")
    ctpr_raw, edges = ctpr_mod.load_ctpr_config(CONFIG_DIR / "ctpr.json")
    _, strict, lenient = policy_mod.load_crit_table(CONFIG_DIR / "crit_table.json")

    admission_table = build_admission_table(key_registry, claim_registry, eis_derived, edges, strict, lenient)
    cross_domain = build_cross_domain_replay_demo()

    admission_json = ARTIFACTS_DIR / "phase3_t4_failure_modes.json"
    admission_md = ARTIFACTS_DIR / "phase3_t4_failure_modes.md"
    cross_domain_json = ARTIFACTS_DIR / "phase3_cross_domain_replay.json"

    _write_json(admission_table, admission_json)
    _write_markdown_table(
        admission_table,
        ["case", "description", "failed_step", "signal_dimension_level", "resulting_verdict"],
        admission_md, "T4 failure-mode table (§10, §12)",
    )
    _write_json(cross_domain, cross_domain_json)

    # Also issue one real signed verdict end-to-end, to exercise verdict
    # issuance itself (not just the failure-mode admission table).
    healthy_by_dim = {d: _healthy_signed_statement(d) for d in DIMENSIONS}
    effective, verdict = _evaluate_window(healthy_by_dim, eis_derived, edges, strict, lenient)
    evidence_root = schema.build_evidence_root(list(healthy_by_dim.values()))
    vfields = schema.build_verdict(
        window_id=CURRENT_WINDOW_ID, evidence_root=evidence_root, effective_dims=effective,
        verdict=verdict, policy_version="v1",
        crit_table_hash=policy_mod.crit_table_hash(CONFIG_DIR / "crit_table.json"),
        ctpr_config_hash=ctpr_mod.ctpr_config_hash(CONFIG_DIR / "ctpr.json"),
        roc_config_hash=roc_config_hash(CONFIG_DIR / "eis.v0.json"),
        claim_registry_hash=schema.claim_registry_hash(CONFIG_DIR / "claim_registry.json"),
        key_registry_hash=schema.key_registry_hash(CONFIG_DIR / "key_registry.json"),
        calibration_status=eis_raw["calibration_status"],
        issued_at=WINDOW_OPEN_TIME_MS + schema.ISSUED_AT_OFFSET_MS,
        expires_at=WINDOW_OPEN_TIME_MS + schema.EXPIRES_AT_OFFSET_MS,
    )
    _, kernel_sk = kf.kernel_keypair()
    signed_verdict = schema.sign_verdict(kernel_sk, vfields)
    verdict_json = ARTIFACTS_DIR / "phase3_sample_verdict.json"
    _write_json(signed_verdict, verdict_json)

    m = manifest_mod.build_manifest(
        repo_root=REPO_ROOT,
        experiment_name="phase3_t4_admission",
        config_paths={
            "crit_table": CONFIG_DIR / "crit_table.json",
            "ctpr": CONFIG_DIR / "ctpr.json",
            "eis_v0": CONFIG_DIR / "eis.v0.json",
            "key_registry": CONFIG_DIR / "key_registry.json",
            "claim_registry": CONFIG_DIR / "claim_registry.json",
        },
        params={
            "current_window_id": CURRENT_WINDOW_ID,
            "window_open_time_ms": WINDOW_OPEN_TIME_MS,
            "evidence_deadline_ms": schema.EVIDENCE_DEADLINE_MS,
            "on_time_arrival_ms": ON_TIME_ARRIVAL_MS,
        },
        artifact_paths={
            "t4_failure_modes_json": admission_json,
            "t4_failure_modes_md": admission_md,
            "cross_domain_replay_json": cross_domain_json,
            "sample_verdict_json": verdict_json,
        },
        calibration_status=eis_raw["calibration_status"],
        seeds={"note": "demo sensor/kernel keys derived from named seeds in tests/key_fixtures.py -- "
                        "provisional, no real hardware provisioning yet"},
    )
    manifest_path = PROVENANCE_DIR / "phase3_t4_admission_manifest.json"
    manifest_mod.write_manifest(m, manifest_path)

    print("T4 failure-mode table:")
    for row in admission_table:
        print(f"  {row['case']:30s} failed_step={str(row['failed_step']):12s} "
              f"signal_level={row['signal_dimension_level']:12s} verdict={row['resulting_verdict']}")
    print(f"\nCross-domain replay: accepted_as_verdict={cross_domain['accepted_as_verdict']} "
          f"(expected False -- {cross_domain['reason']})")
    print(
        "\nLabel (§12): this is a falsifiable failure-mode table (real signature "
        "verification, real canonical encoding, real fixed verification order) -- "
        "unlike the T1/T2 conformance scan, it can come out wrong."
    )
    print(
        "\nT4 freshness is honest-evidence-conditional under Position A (§3): an "
        "adversary who owns the host forges kernel_sig and controls clocks. T4 is "
        "not the basis of the central claim; T5 is."
    )
    print(f"\nArtifacts written to {ARTIFACTS_DIR}")
    print(f"Manifest written to {manifest_path}")

    ok = (
        all(r["case"] == "baseline_all_valid" or r["failed_step"] is not None for r in admission_table)
        and admission_table[0]["failed_step"] is None
        and not cross_domain["accepted_as_verdict"]
    )
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
