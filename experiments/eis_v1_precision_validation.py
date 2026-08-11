"""eis.v1 precision-validation driver (CLAUDE.md prerequisite to Phase 9;
CLAUDE.md not modified by this work; no real ROC thresholds derived here).

Validates the Step 5 config-side representation fix proposed in
docs/EVENT-MODEL-INVESTIGATION.md 5 and implemented as a NEW versioned
config format (config/eis.v1.json, ppb scale) rather than an in-place
mutation of config/eis.v0.json. Four things, each independently falsifiable:

  (a) Sufficiency: every one of the 18 (subject x claim x budget)
      episode-based alpha values found by the event-model investigation
      (artifacts/event_model_investigation_report.json) is representable
      in ppb, with margin -- not just the closest case.
  (b) eis.v0 replay compatibility: verdicts issued and replayed under
      config/eis.v0.json still agree, unaffected by trust_kernel/bands.py's
      generalization -- re-runs the same replay-batch check as Phase 4
      (experiments/phase4_evidence_log.py), fresh, against the current code.
  (c) eis.v1 end-to-end wiring: the SAME statement -> verdict -> sign ->
      replay pipeline (tests/window_fixtures.py, unmodified) works when
      pointed at config/eis.v1.json instead of eis.v0.json, via the
      config_paths override every fixture function already accepts.
  (d) Off-crypto-path: trust_kernel/canon.py and trust_kernel/sign.py
      (the CBOR encoding + Ed25519 rule set, CLAUDE.md 8/9) are
      byte-identical before and after this change, and neither imports
      trust_kernel.bands or references ppb/eis_schema_version -- confirmed
      by source hash and by AST inspection, not just by claim.

Run: `python3 -m experiments.eis_v1_precision_validation` from the repo root.
"""

import ast
import hashlib
import json
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evidence_plane import replay as replay_mod
from provenance import manifest as manifest_mod
from trust_kernel import bands, schema
from tests import window_fixtures as wf

ARTIFACTS_DIR = REPO_ROOT / "artifacts"
PROVENANCE_DIR = REPO_ROOT / "provenance"
CONFIG_DIR = REPO_ROOT / "config"

EVENT_MODEL_REPORT = ARTIFACTS_DIR / "event_model_investigation_report.json"

# Pre-change hashes, taken before trust_kernel/bands.py, config/eis.v1.json,
# tests/test_bands.py, and the two new harnesses were written (recorded here
# rather than only asserted, so this check is falsifiable by re-running it
# after any future change to these two files).
PRE_CHANGE_HASHES = {
    "trust_kernel/canon.py": "af37de63b34a4b66222653a30e1ce038efeb2e9a822756f51bfcdeefb99bdb08",
    "trust_kernel/sign.py": "3dafa52825b4856edb52f2b8659ff516071b86a1840dc7aceb37e8f52e487415",
    "trust_kernel/schema.py": "c03c9c5a4701a10328a73c87c48013d3e053e334e01689241f0a9fee31f32883",
}

V1_CONFIG_PATHS = {**wf.CONFIG_PATHS, "eis": CONFIG_DIR / "eis.v1.json"}

BATCH_WINDOW_IDS = list(range(500, 510))


def _file_hash(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --------------------------------------------------------------------------
# (a) Sufficiency across all 18 combinations.
# --------------------------------------------------------------------------

def check_ppb_sufficiency():
    if not EVENT_MODEL_REPORT.exists():
        raise SystemExit(
            f"{EVENT_MODEL_REPORT} not found -- run experiments/event_model_investigation.py first"
        )
    report = json.loads(EVENT_MODEL_REPORT.read_text())

    rows = []
    for subject, subject_report in zip(report["subjects"], report["subject_reports"]):
        for claim, claim_table in subject_report["availability_table"].items():
            for budget_row in claim_table["budget_rows"]:
                alpha = budget_row["alpha_episode"]
                rows.append({
                    "subject": subject,
                    "claim": claim,
                    "session_budget": budget_row["session_budget"],
                    "alpha_episode": alpha,
                    "representable_bp": bands.representable_at_scale(alpha, bands.BP_SCALE),
                    "representable_ppb": bands.representable_at_scale(alpha, bands.PPB_SCALE),
                    "margin_ppb": bands.representability_margin(alpha, bands.PPB_SCALE),
                })

    all_representable_ppb = all(r["representable_ppb"] for r in rows)
    none_representable_bp = not any(r["representable_bp"] for r in rows)
    min_margin = min(r["margin_ppb"] for r in rows)
    return {
        "n_combinations": len(rows),
        "rows": rows,
        "all_representable_ppb": all_representable_ppb,
        "none_representable_bp": none_representable_bp,
        "min_margin_ppb": min_margin,
        "correct": all_representable_ppb and len(rows) == 18,
    }


# --------------------------------------------------------------------------
# (b) eis.v0 replay compatibility (re-run of Phase 4's replay-batch check).
# --------------------------------------------------------------------------

def check_v0_replay_unaffected():
    rows = []
    for i, window_id in enumerate(BATCH_WINDOW_IDS):
        raw = 40 + i * 5
        statements = wf.healthy_window(window_id=window_id, raw_measurement=raw)
        verdict = wf.issue_signed_verdict(statements, window_id=window_id, config_paths=wf.CONFIG_PATHS)
        result = replay_mod.replay_verdict(verdict, statements, config_paths=wf.CONFIG_PATHS)
        rows.append({
            "window_id": window_id, "recorded_verdict": verdict["verdict"],
            "recomputed_verdict": result.recomputed_verdict, "agreement": result.agreement,
            "config_mismatch": result.config_mismatch,
        })
    agreement_rate = sum(r["agreement"] for r in rows) / len(rows)
    return {
        "rows": rows, "agreement_rate": agreement_rate,
        "roc_config_hash_v0": bands.roc_config_hash(wf.CONFIG_PATHS["eis"]),
        "correct": agreement_rate == 1.0 and all(not r["config_mismatch"] for r in rows),
    }


# --------------------------------------------------------------------------
# (c) eis.v1 end-to-end wiring (same fixtures, config_paths override).
# --------------------------------------------------------------------------

def check_v1_end_to_end():
    rows = []
    for i, window_id in enumerate(BATCH_WINDOW_IDS):
        raw = 40 + i * 5
        statements = wf.healthy_window(window_id=window_id, raw_measurement=raw)
        verdict = wf.issue_signed_verdict(statements, window_id=window_id, config_paths=V1_CONFIG_PATHS)
        result = replay_mod.replay_verdict(verdict, statements, config_paths=V1_CONFIG_PATHS)
        rows.append({
            "window_id": window_id, "recorded_verdict": verdict["verdict"],
            "recomputed_verdict": result.recomputed_verdict, "agreement": result.agreement,
            "config_mismatch": result.config_mismatch,
        })
    agreement_rate = sum(r["agreement"] for r in rows) / len(rows)

    # A v1 verdict replayed against the v0 config path must fail closed
    # (wrong config version loaded) -- the same mechanism a genuinely
    # mismatched deployment would hit, exercised deliberately here.
    cross_check_statements = wf.healthy_window(window_id=9999, raw_measurement=60)
    v1_verdict = wf.issue_signed_verdict(cross_check_statements, window_id=9999, config_paths=V1_CONFIG_PATHS)
    cross_result = replay_mod.replay_verdict(v1_verdict, cross_check_statements,
                                              config_paths=wf.CONFIG_PATHS)

    return {
        "rows": rows, "agreement_rate": agreement_rate,
        "roc_config_hash_v1": bands.roc_config_hash(V1_CONFIG_PATHS["eis"]),
        "cross_version_replay_fails_closed": (
            cross_result.config_mismatch and "roc_config_hash" in cross_result.mismatched_hashes
        ),
        "correct": (
            agreement_rate == 1.0
            and all(not r["config_mismatch"] for r in rows)
            and cross_result.config_mismatch
            and "roc_config_hash" in cross_result.mismatched_hashes
        ),
    }


# --------------------------------------------------------------------------
# (d) Off-crypto-path confirmation: hash + AST.
# --------------------------------------------------------------------------

def check_off_crypto_path():
    current_hashes = {name: _file_hash(REPO_ROOT / name) for name in PRE_CHANGE_HASHES}
    hash_unchanged = {name: current_hashes[name] == PRE_CHANGE_HASHES[name] for name in PRE_CHANGE_HASHES}

    forbidden_tokens = ("ppb", "eis_schema_version", "trust_kernel.bands", "PPB_SCALE")
    ast_clean = {}
    token_hits = {}
    for name in ("trust_kernel/canon.py", "trust_kernel/sign.py"):
        source = (REPO_ROOT / name).read_text()
        tree = ast.parse(source)
        imports_bands = any(
            (isinstance(node, ast.ImportFrom) and node.module and "bands" in node.module)
            or (isinstance(node, ast.Import) and any("bands" in alias.name for alias in node.names))
            for node in ast.walk(tree)
        )
        hits = [t for t in forbidden_tokens if t in source]
        ast_clean[name] = not imports_bands
        token_hits[name] = hits

    verdict_fields_unchanged = schema.VERDICT_FIELDS == {
        "schema_version", "window_id", "evidence_root", "effective_dims", "verdict",
        "policy_version", "crit_table_hash", "ctpr_config_hash", "roc_config_hash",
        "claim_registry_hash", "key_registry_hash", "calibration_status",
        "issued_at", "expires_at",
    }
    statement_fields_unchanged = (
        schema.STATEMENT_REQUIRED_FIELDS == {
            "schema_version", "key_id", "source_id", "boundary", "claim_type",
            "raw_measurement", "window_id", "claimed_at",
        }
        and schema.STATEMENT_OPTIONAL_FIELDS == {"window_hash"}
    )

    return {
        "pre_change_hashes": PRE_CHANGE_HASHES,
        "current_hashes": current_hashes,
        "hash_unchanged": hash_unchanged,
        "ast_no_bands_import": ast_clean,
        "forbidden_token_hits": token_hits,
        "verdict_wire_fields_unchanged": verdict_fields_unchanged,
        "statement_wire_fields_unchanged": statement_fields_unchanged,
        "correct": (
            all(hash_unchanged.values())
            and all(ast_clean.values())
            and all(not hits for hits in token_hits.values())
            and verdict_fields_unchanged
            and statement_fields_unchanged
        ),
    }


def _write_json(obj, path):
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n")


def main():
    ARTIFACTS_DIR.mkdir(exist_ok=True)
    PROVENANCE_DIR.mkdir(exist_ok=True)

    sufficiency = check_ppb_sufficiency()
    v0_replay = check_v0_replay_unaffected()
    v1_e2e = check_v1_end_to_end()
    off_crypto = check_off_crypto_path()

    report = {
        "sufficiency": sufficiency,
        "v0_replay_unaffected": v0_replay,
        "v1_end_to_end": v1_e2e,
        "off_crypto_path": off_crypto,
    }
    report_path = ARTIFACTS_DIR / "eis_v1_precision_validation_report.json"
    _write_json(report, report_path)

    m = manifest_mod.build_manifest(
        repo_root=REPO_ROOT,
        experiment_name="eis_v1_precision_validation",
        config_paths={
            "eis_v0": wf.CONFIG_PATHS["eis"], "eis_v1": V1_CONFIG_PATHS["eis"],
            "crit_table": wf.CONFIG_PATHS["crit_table"], "ctpr": wf.CONFIG_PATHS["ctpr"],
            "claim_registry": wf.CONFIG_PATHS["claim_registry"], "key_registry": wf.CONFIG_PATHS["key_registry"],
        },
        params={"batch_window_ids": BATCH_WINDOW_IDS, "source_report": str(EVENT_MODEL_REPORT)},
        artifact_paths={"report": report_path},
        calibration_status="provisional",
        seeds={"note": "demo sensor/kernel keys derived from named seeds in tests/key_fixtures.py"},
    )
    manifest_path = PROVENANCE_DIR / "eis_v1_precision_validation_manifest.json"
    manifest_mod.write_manifest(m, manifest_path)

    print("(a) ppb sufficiency across all 18 (subject x claim x budget) combinations:")
    print(f"    combinations checked: {sufficiency['n_combinations']}")
    print(f"    all representable in ppb: {sufficiency['all_representable_ppb']}")
    print(f"    none representable in bp: {sufficiency['none_representable_bp']}")
    print(f"    minimum margin (multiples of the ppb floor): {sufficiency['min_margin_ppb']:.1f}x")
    worst = min(sufficiency["rows"], key=lambda r: r["margin_ppb"])
    print(f"    closest case: subject={worst['subject']} claim={worst['claim']} "
          f"budget={worst['session_budget']} alpha={worst['alpha_episode']:.3e} margin={worst['margin_ppb']:.1f}x")

    print(f"\n(b) eis.v0 replay agreement (fresh, post-change): {v0_replay['agreement_rate']:.0%} "
          f"over {len(v0_replay['rows'])} verdicts, roc_config_hash={v0_replay['roc_config_hash_v0'][:16]}...")

    print(f"\n(c) eis.v1 end-to-end replay agreement: {v1_e2e['agreement_rate']:.0%} "
          f"over {len(v1_e2e['rows'])} verdicts, roc_config_hash={v1_e2e['roc_config_hash_v1'][:16]}...")
    print(f"    cross-version replay (v1 verdict against v0 config) fails closed: "
          f"{v1_e2e['cross_version_replay_fails_closed']}")

    print("\n(d) Off-crypto-path confirmation:")
    for name, unchanged in off_crypto["hash_unchanged"].items():
        print(f"    {name}: hash unchanged = {unchanged}")
    for name, clean in off_crypto["ast_no_bands_import"].items():
        print(f"    {name}: no trust_kernel.bands import = {clean}, forbidden tokens present = "
              f"{off_crypto['forbidden_token_hits'][name]}")
    print(f"    verdict wire field set unchanged: {off_crypto['verdict_wire_fields_unchanged']}")
    print(f"    statement wire field set unchanged: {off_crypto['statement_wire_fields_unchanged']}")

    print(f"\nReport written to {report_path}")
    print(f"Manifest written to {manifest_path}")

    ok = (
        sufficiency["correct"] and v0_replay["correct"]
        and v1_e2e["correct"] and off_crypto["correct"]
    )
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
