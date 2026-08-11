"""Phase 4 driver (CLAUDE.md §14): evidence log + verdict replay.

Produces three reportable results (§12):
  (a) tamper-evidence -- mutate a statement at chain position k, confirm
      every entry from k forward breaks and no entry before k does.
  (b) replay agreement rate over a batch of verdicts.
  (c) config-mismatch detection -- replay under a mutated config and
      confirm the hash mismatch is caught before any recomputation.
Plus the mutation kill rate (reported by harnesses/mutation_check.py).

Label (§12): all three are falsifiable -- real hash chains, real replay
computation, real config hashing. They can come out wrong.

Run: `python3 -m experiments.phase4_evidence_log` from the repo root.
"""

import json
import pathlib
import shutil
import struct
import sys
import tempfile

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evidence_plane import log as evlog, replay as replay_mod
from trust_kernel import canon
from provenance import manifest as manifest_mod
from tests import window_fixtures as wf

ARTIFACTS_DIR = REPO_ROOT / "artifacts"
PROVENANCE_DIR = REPO_ROOT / "provenance"

BATCH_WINDOW_IDS = list(range(200, 210))  # 10 windows for the replay batch


def run_tamper_evidence_demo(tmpdir: pathlib.Path):
    path = tmpdir / "tamper_demo.log"
    log = evlog.EvidenceLog(path)
    statements = wf.healthy_window(window_id=300)
    for stmt in statements:
        log.append(stmt)
    log.fsync_window()
    log.close()

    baseline = evlog.verify_chain(evlog.read_all(path))

    k = 3
    entries = evlog.read_all(path)
    tampered = [dict(e) for e in entries]
    tampered[k] = dict(tampered[k])
    tampered_statement = dict(tampered[k]["statement"])
    tampered_statement["raw_measurement"] = 999999
    tampered[k]["statement"] = tampered_statement  # entry_hash left stale

    with open(path, "wb") as f:
        for e in tampered:
            record = canon.encode(e)
            f.write(struct.pack(">I", len(record)))
            f.write(record)

    after_tamper = evlog.verify_chain(evlog.read_all(path))

    return {
        "log_length": len(entries),
        "tampered_position_k": k,
        "baseline_valid": baseline.valid,
        "after_tamper_valid": after_tamper.valid,
        "first_broken_seq": after_tamper.first_broken_seq,
        "broken_seqs": after_tamper.broken_seqs,
        "clean_seqs": [e["seq"] for e in entries if e["seq"] < k],
        "correct": (
            baseline.valid
            and not after_tamper.valid
            and after_tamper.first_broken_seq == k
            and after_tamper.broken_seqs == list(range(k, len(entries)))
        ),
    }


def run_replay_batch():
    rows = []
    for i, window_id in enumerate(BATCH_WINDOW_IDS):
        raw = 50 + i * 5  # vary the measurement so verdicts aren't all identical
        statements = wf.healthy_window(window_id=window_id, raw_measurement=raw)
        verdict = wf.issue_signed_verdict(statements, window_id=window_id)
        result = replay_mod.replay_verdict(verdict, statements, config_paths=wf.CONFIG_PATHS)
        rows.append({
            "window_id": window_id,
            "raw_measurement": raw,
            "recorded_verdict": verdict["verdict"],
            "recomputed_verdict": result.recomputed_verdict,
            "agreement": result.agreement,
        })
    agreement_rate = sum(r["agreement"] for r in rows) / len(rows)
    return rows, agreement_rate


def run_config_mismatch_demo(tmpdir: pathlib.Path):
    mutated_paths = dict(wf.CONFIG_PATHS)
    for name, path in wf.CONFIG_PATHS.items():
        dst = tmpdir / path.name
        shutil.copy(path, dst)
        mutated_paths[name] = dst

    statements = wf.healthy_window(window_id=400)
    verdict = wf.issue_signed_verdict(statements, window_id=400)  # signed under the real config

    raw = json.loads(mutated_paths["eis"].read_text())
    raw["alpha_bp"] = 1  # mutate the interpretation config after issuance
    mutated_paths["eis"].write_text(json.dumps(raw))

    result = replay_mod.replay_verdict(verdict, statements, config_paths=mutated_paths)
    return {
        "mutation": "eis.v0.json alpha_bp: 500 -> 1 (post-issuance)",
        "config_mismatch_detected": result.config_mismatch,
        "mismatched_hashes": result.mismatched_hashes,
        "recomputation_attempted": result.recomputed_verdict is not None,
        "correct": (
            result.config_mismatch
            and "roc_config_hash" in result.mismatched_hashes
            and result.recomputed_verdict is None
        ),
    }


def _write_json(obj, path):
    path.write_text(json.dumps(
        obj, indent=2, sort_keys=True,
        default=lambda o: o.hex() if isinstance(o, bytes) else str(o),
    ) + "\n")


def main():
    ARTIFACTS_DIR.mkdir(exist_ok=True)
    PROVENANCE_DIR.mkdir(exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp)
        tamper_result = run_tamper_evidence_demo(tmp_path)
        config_mismatch_result = run_config_mismatch_demo(tmp_path)

    replay_rows, agreement_rate = run_replay_batch()

    tamper_json = ARTIFACTS_DIR / "phase4_tamper_evidence.json"
    replay_json = ARTIFACTS_DIR / "phase4_replay_batch.json"
    config_mismatch_json = ARTIFACTS_DIR / "phase4_config_mismatch.json"

    _write_json(tamper_result, tamper_json)
    _write_json({"rows": replay_rows, "agreement_rate": agreement_rate}, replay_json)
    _write_json(config_mismatch_result, config_mismatch_json)

    m = manifest_mod.build_manifest(
        repo_root=REPO_ROOT,
        experiment_name="phase4_evidence_log",
        config_paths={
            "crit_table": wf.CONFIG_PATHS["crit_table"], "ctpr": wf.CONFIG_PATHS["ctpr"],
            "eis_v0": wf.CONFIG_PATHS["eis"], "key_registry": wf.CONFIG_PATHS["key_registry"],
            "claim_registry": wf.CONFIG_PATHS["claim_registry"],
        },
        params={"batch_window_ids": BATCH_WINDOW_IDS, "tamper_position_k": tamper_result["tampered_position_k"]},
        artifact_paths={
            "tamper_evidence_json": tamper_json,
            "replay_batch_json": replay_json,
            "config_mismatch_json": config_mismatch_json,
        },
        calibration_status="provisional",
        seeds={"note": "demo sensor/kernel keys derived from named seeds in tests/key_fixtures.py"},
    )
    manifest_path = PROVENANCE_DIR / "phase4_evidence_log_manifest.json"
    manifest_mod.write_manifest(m, manifest_path)

    print("(a) Tamper-evidence:")
    print(f"    log length={tamper_result['log_length']}, tampered at k={tamper_result['tampered_position_k']}")
    print(f"    baseline_valid={tamper_result['baseline_valid']} after_tamper_valid={tamper_result['after_tamper_valid']}")
    print(f"    clean seqs (< k): {tamper_result['clean_seqs']}")
    print(f"    broken seqs (>= k): {tamper_result['broken_seqs']}")
    print(f"    correct: {tamper_result['correct']}")

    print(f"\n(b) Replay agreement rate over {len(replay_rows)} verdicts: {agreement_rate:.0%}")
    for row in replay_rows:
        print(f"    window={row['window_id']} raw={row['raw_measurement']:4d} "
              f"recorded={row['recorded_verdict']:12s} recomputed={row['recomputed_verdict']:12s} "
              f"agree={row['agreement']}")

    print("\n(c) Config-mismatch detection:")
    print(f"    mutation: {config_mismatch_result['mutation']}")
    print(f"    detected: {config_mismatch_result['config_mismatch_detected']}")
    print(f"    mismatched hashes: {config_mismatch_result['mismatched_hashes']}")
    print(f"    recomputation attempted despite mismatch: {config_mismatch_result['recomputation_attempted']}")

    print(
        "\nLabel (§12): all three results above are falsifiable (real hash "
        "chains, real replay computation, real config hashing), unlike the "
        "Phase 2 T1/T2 conformance scan."
    )
    print(f"\nArtifacts written to {ARTIFACTS_DIR}")
    print(f"Manifest written to {manifest_path}")

    ok = tamper_result["correct"] and agreement_rate == 1.0 and config_mismatch_result["correct"]
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
