"""Phase 8.5 driver: SBA (Session Budget Allocation) validation, run
BEFORE Phase 9. Produces the reportable results for the Phase 8.5 report:

  (1) Real-DAG exact validation at a nominal B=1%/8h budget: derived
      per-claim alpha, exact session-level restriction probability,
      naive-vs-exact agreement (predicted to match exactly per the proof
      in sba_validation/probability_model.py and tests_sba/).
  (2) CTPR on/off contrast at that alpha: predicted identical.
  (3) A basis-point wire-format quantization finding, discovered as a
      byproduct of (1): the alpha required by a tight session budget is
      far below CLAUDE.md 8's basis-point (0..10000) rate granularity.
      This is a SEPARATE, orthogonal issue from the CTPR question --
      flagged, not silently worked around, and explicitly NOT something
      this pass resolves (it touches SS8's FROZEN wire schema).
  (4) A Monte Carlo injection-based cross-check at a representable,
      inflated alpha: real signed statements built and admitted through
      the real trust_kernel pipeline, not just the closed-form formulas.
  (5) The cross-severity boundary-case result (naive fails, corrected
      passes), re-reported from tests_sba/ for the written record.
  (6) The illustrative budget sweep {0.1%, 1%, 5%} per 8h session.
  (7) Mutation kill rates: sba_validation/ (new code) and the frozen
      pure-core suite (unaffected by this pass).

This driver, and everything it imports, does NOT modify CLAUDE.md. See
the Phase 8.5 report for the proposed (not applied) diff.

Run: `python3 -m experiments.phase8_5_sba_validation` from the repo root
(pure Python, no bci_pipeline/sensors dependencies -- runs under the
plain interpreter like every other pure-core experiment).
"""

import json
import pathlib
import random
import subprocess
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from provenance import manifest as manifest_mod
from sba_validation import probability_model as pm
from trust_kernel import bands as bands_mod
from trust_kernel import ctpr as ctpr_mod
from trust_kernel import policy as policy_mod
from trust_kernel import schema, sign

ARTIFACTS_DIR = REPO_ROOT / "artifacts"
PROVENANCE_DIR = REPO_ROOT / "provenance"

WINDOW_PERIOD_S = 0.100  # CLAUDE.md 7: T = 100ms
SESSION_HOURS = 8
WINDOWS_PER_SESSION = int(SESSION_HOURS * 3600 / WINDOW_PERIOD_S)  # 288,000

NOMINAL_SESSION_BUDGET = 0.01  # 1% per 8h session -- validation input only, not a deployment value (task 3)
SWEEP_BUDGETS = [0.001, 0.01, 0.05]  # 0.1%, 1%, 5% -- illustrative research parameters (task 4)

DIMENSIONS = bands_mod.DIMENSIONS
STRICT = frozenset(["Signal", "Model", "Calibration", "FSI", "ActuationFidelity"])
LENIENT = frozenset(["Device"])
REAL_EDGES = (("FSI", "Signal"), ("FSI", "Model"))

BP_SCALE = bands_mod.BP_SCALE  # 10,000
MIN_REPRESENTABLE_RATE = 1 / BP_SCALE  # smallest nonzero basis-point rate: 1e-4


def _write_json(obj, path):
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n")


# ==========================================================================
# (1)/(2) Real-DAG exact validation at the nominal budget + CTPR on/off.
# ==========================================================================

def real_dag_validation_at_budget(session_budget: float):
    p_window_safe_target = pm.session_to_window_budget(session_budget, WINDOWS_PER_SESSION)
    alpha_target = pm.flat_split_alpha(p_window_safe_target, len(STRICT))

    level_dist = {d: pm.level_distribution(alpha_target, min(1.0, alpha_target * 4)) for d in DIMENSIONS}
    with_ctpr = pm.exact_window_probabilities(DIMENSIONS, level_dist, REAL_EDGES, STRICT, LENIENT)
    without_ctpr = pm.exact_window_probabilities(DIMENSIONS, level_dist, (), STRICT, LENIENT)

    naive_safe = pm.naive_p_safe({d: alpha_target for d in STRICT})

    session_p_safe_exact = 1 - (1 - with_ctpr["p_safe"]) ** WINDOWS_PER_SESSION
    session_p_safe_naive = 1 - (1 - naive_safe) ** WINDOWS_PER_SESSION

    return {
        "session_budget_target": session_budget,
        "windows_per_session": WINDOWS_PER_SESSION,
        "p_window_safe_target": p_window_safe_target,
        "alpha_target_per_strict_claim": alpha_target,
        "alpha_target_in_basis_points": alpha_target * BP_SCALE,
        "representable_at_current_bp_granularity": alpha_target * BP_SCALE >= 1.0,
        "exact_p_window_safe_with_ctpr": with_ctpr["p_safe"],
        "exact_p_window_safe_without_ctpr": without_ctpr["p_safe"],
        "naive_p_window_safe": naive_safe,
        "ctpr_on_off_identical": with_ctpr["p_safe"] == without_ctpr["p_safe"],
        "naive_matches_exact": abs(naive_safe - with_ctpr["p_safe"]) < 1e-15,
        "session_p_safe_exact_with_ctpr": session_p_safe_exact,
        "session_p_safe_naive": session_p_safe_naive,
        "session_budget_held": session_p_safe_exact <= session_budget * 1.0000001,
    }


# ==========================================================================
# (3) Basis-point quantization finding.
# ==========================================================================

def quantization_finding():
    """What session-level P(restrict) results from the SMALLEST nonzero
    per-claim alpha the current basis-point wire format can represent
    (CLAUDE.md 8: rates are fixed-point basis points 0..10000, i.e. a
    minimum nonzero rate of 1/10000)."""
    alpha_min = MIN_REPRESENTABLE_RATE
    p_window_safe = pm.naive_p_safe({d: alpha_min for d in STRICT})
    session_p_safe = 1 - (1 - p_window_safe) ** WINDOWS_PER_SESSION
    return {
        "min_representable_alpha": alpha_min,
        "p_window_safe_at_min_alpha": p_window_safe,
        "session_p_safe_at_min_alpha": session_p_safe,
        "note": (
            "Even the smallest nonzero per-claim alpha representable in the current basis-point "
            "wire format (CLAUDE.md 8) yields a session-level halt probability of essentially 1.0 "
            "over an 8h/288000-window session -- the wire format's rate granularity is far too coarse "
            "for any tight session-availability target, independent of CTPR entirely. This is a "
            "separate, orthogonal finding to the CTPR question this pass was asked to validate, not "
            "something this pass resolves (it touches CLAUDE.md 8's FROZEN wire schema and would "
            "require a separate PI-escalated change, CLAUDE.md 18)."
        ),
    }


# ==========================================================================
# (4) Monte Carlo injection-based cross-check (real signed statements,
# real admission, real bands/CTPR/policy pipeline) at a representable,
# inflated alpha where sampling noise is small relative to effect size.
# ==========================================================================

MC_ALPHA = 0.01
MC_ALPHA2 = 0.03
MC_BETA_BP = 500
MC_N_WINDOWS = 20_000

CLAIM_TYPE_BY_DIM = {d: f"{d.lower()}.sba_validation_v0" for d in DIMENSIONS}
SOURCE_ID_BY_DIM = {d: f"{d.lower()}_sba_validation_sensor_v0" for d in DIMENSIONS}


def _synthetic_roc_and_thresholds(alpha: float, alpha2: float, beta_bp: int = MC_BETA_BP):
    """A 3-point ROC whose derive_thresholds() yields theta1=0 with
    FPR(theta1)=alpha exactly, and theta2=50 with FPR(theta2)=alpha2
    exactly (band_cap=HIGH) -- see the Phase 8.5 report for the
    construction. Basis-point-quantized like the real system (CLAUDE.md
    8), so this also surfaces the (3) quantization effect if alpha is too
    small to round to a nonzero basis-point value."""
    alpha_bp = round(alpha * BP_SCALE)
    alpha2_bp = round(alpha2 * BP_SCALE)
    if alpha2_bp <= alpha_bp:
        raise ValueError("alpha2 must be strictly greater than alpha at basis-point resolution")
    roc = [
        {"threshold": -100, "fpr_bp": 0, "tpr_bp": 0},
        {"threshold": 0, "fpr_bp": alpha_bp, "tpr_bp": 8000},
        {"threshold": 50, "fpr_bp": alpha2_bp, "tpr_bp": BP_SCALE - beta_bp},
    ]
    theta1, theta2, band_cap = bands_mod.derive_thresholds(roc, alpha_bp=alpha_bp, beta_bp=beta_bp)
    return roc, theta1, theta2, band_cap


def _draw_raw_measurement(rng, level, theta1, theta2):
    if level == bands_mod.TrustLevel.LOW:
        return theta1 - 1
    if level == bands_mod.TrustLevel.MED:
        return (theta1 + theta2) // 2
    return theta2 + 1


def _sensor_keypairs():
    return {d: sign.keypair_from_seed(f"sba-validation-mc-seed:{d}".encode().ljust(32, b"0")[:32]) for d in DIMENSIONS}


def monte_carlo_injection(n_windows: int = MC_N_WINDOWS, seed: int = 20260720):
    rng = random.Random(seed)
    keypairs = _sensor_keypairs()

    per_dim_thresholds = {}
    per_dim_level_dist = {}
    for d in DIMENSIONS:
        alpha, alpha2 = (MC_ALPHA, MC_ALPHA2)
        _, theta1, theta2, band_cap = _synthetic_roc_and_thresholds(alpha, alpha2)
        per_dim_thresholds[d] = (theta1, theta2, band_cap)
        per_dim_level_dist[d] = pm.level_distribution(alpha, alpha2)

    predicted = pm.exact_window_probabilities(DIMENSIONS, per_dim_level_dist, REAL_EDGES, STRICT, LENIENT)

    safe_count = 0
    below_normal_count = 0
    for w in range(n_windows):
        raw_dims = {}
        for d in DIMENSIONS:
            level = rng.choices(
                [bands_mod.TrustLevel.LOW, bands_mod.TrustLevel.MED, bands_mod.TrustLevel.HIGH],
                weights=[per_dim_level_dist[d][lvl] for lvl in
                         (bands_mod.TrustLevel.LOW, bands_mod.TrustLevel.MED, bands_mod.TrustLevel.HIGH)],
            )[0]
            theta1, theta2, _band_cap = per_dim_thresholds[d]
            raw_measurement = _draw_raw_measurement(rng, level, theta1, theta2)

            pk, sk = keypairs[d]
            fields = schema.build_statement(
                key_id=SOURCE_ID_BY_DIM[d], source_id=SOURCE_ID_BY_DIM[d], boundary="TB2",
                claim_type=CLAIM_TYPE_BY_DIM[d], raw_measurement=raw_measurement,
                window_id=w, claimed_at=0,
            )
            stmt = schema.sign_statement(sk, fields)
            assert schema.verify_statement_signature(pk, stmt)  # exercise the real signature path, not just build it
            raw_dims[d] = stmt

        bands = {}
        for d, stmt in raw_dims.items():
            _theta1, theta2_, band_cap = per_dim_thresholds[d]
            s = bands_mod.score(1, stmt["raw_measurement"])
            bands[d] = bands_mod.reduce_dimension([bands_mod.band(s, _theta1, theta2_, band_cap)])
        effective = ctpr_mod.apply_ctpr(bands, REAL_EDGES)
        verdict = policy_mod.policy(effective, STRICT, LENIENT)

        if verdict == policy_mod.Verdict.Safe:
            safe_count += 1
        if verdict != policy_mod.Verdict.Normal:
            below_normal_count += 1

    measured_p_safe = safe_count / n_windows
    measured_p_below_normal = below_normal_count / n_windows

    return {
        "n_windows": n_windows,
        "alpha": MC_ALPHA, "alpha2": MC_ALPHA2,
        "predicted_p_safe": predicted["p_safe"],
        "measured_p_safe": measured_p_safe,
        "predicted_p_below_normal": predicted["p_below_normal"],
        "measured_p_below_normal": measured_p_below_normal,
        "p_safe_relative_error": abs(measured_p_safe - predicted["p_safe"]) / predicted["p_safe"],
        "p_below_normal_relative_error": abs(measured_p_below_normal - predicted["p_below_normal"]) / predicted["p_below_normal"],
        "note": (
            "Real trust_kernel.schema.build_statement/sign_statement/verify_statement_signature, "
            "trust_kernel.bands.score/band/reduce_dimension, trust_kernel.ctpr.apply_ctpr, and "
            "trust_kernel.policy.policy exercised per simulated window -- this is the real code path, "
            "not a reimplementation, run at a representable (not session-target-tiny) alpha so sampling "
            "noise stays small relative to the effect size."
        ),
    }


# ==========================================================================
# (5) Cross-severity boundary case -- re-reported from tests_sba/ (already
# validated there; recomputed here for the written record's numbers).
# ==========================================================================

def boundary_case_result():
    dims = ["P", "C"]
    strict, lenient = frozenset(["C"]), frozenset(["P"])
    edges = (("P", "C"),)
    alpha = {"P": 0.10, "C": 0.02}
    alpha2 = {"P": 0.20, "C": 0.05}
    level_dist = {d: pm.level_distribution(alpha[d], alpha2[d]) for d in dims}

    exact = pm.exact_window_probabilities(dims, level_dist, edges, strict, lenient)
    naive = pm.naive_p_safe({"C": alpha["C"]})
    corrected = pm.corrected_p_safe_with_ancestor_closure(alpha, strict, ancestors_of_strict={"C": {"P"}})

    return {
        "scenario": "hypothetical lenient-parent(P) -> strict-child(C) edge -- NOT the deployed architecture",
        "alpha": alpha, "alpha2": alpha2,
        "exact_p_safe": exact["p_safe"],
        "naive_p_safe": naive,
        "naive_underestimate": exact["p_safe"] - naive,
        "corrected_p_safe": corrected,
        "corrected_matches_exact": abs(corrected - exact["p_safe"]) < 1e-12,
    }


# ==========================================================================
# (6) Illustrative budget sweep.
# ==========================================================================

def budget_sweep(budgets):
    rows = []
    for b in budgets:
        r = real_dag_validation_at_budget(b)
        halts_per_minute = r["p_window_safe_target"] * (60 / WINDOW_PERIOD_S)
        rows.append({
            "session_budget": b,
            "alpha_target_per_strict_claim": r["alpha_target_per_strict_claim"],
            "alpha_target_bp": r["alpha_target_in_basis_points"],
            "representable_at_1bp_granularity": r["representable_at_current_bp_granularity"],
            "implied_spurious_halts_per_minute_at_target": halts_per_minute,
            "naive_matches_exact": r["naive_matches_exact"],
            "session_budget_held_by_naive_formula": r["session_budget_held"],
        })
    return rows


# ==========================================================================
# Mutation kill rates.
# ==========================================================================

def run_mutation_checks():
    sba_proc = subprocess.run(
        [sys.executable, "-m", "harnesses.mutation_check_sba"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300,
    )
    core_proc = subprocess.run(
        [sys.executable, "-m", "harnesses.mutation_check"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300,
    )
    return {
        "sba_validation_kill_rate_line": sba_proc.stdout.splitlines()[0] if sba_proc.stdout else None,
        "sba_validation_passed": sba_proc.returncode == 0,
        "pure_core_kill_rate_line": core_proc.stdout.splitlines()[0] if core_proc.stdout else None,
        "pure_core_unaffected": core_proc.returncode == 0,
    }


def main():
    ARTIFACTS_DIR.mkdir(exist_ok=True)
    PROVENANCE_DIR.mkdir(exist_ok=True)

    print(f"Session: {SESSION_HOURS}h @ {1/WINDOW_PERIOD_S:.0f}Hz -> {WINDOWS_PER_SESSION} windows/session\n")

    nominal = real_dag_validation_at_budget(NOMINAL_SESSION_BUDGET)
    print(f"(1)/(2) Real DAG at nominal B={NOMINAL_SESSION_BUDGET:.4%}:")
    print(f"    alpha_target per strict claim = {nominal['alpha_target_per_strict_claim']:.3e} "
          f"({nominal['alpha_target_in_basis_points']:.6f} bp; representable at 1bp granularity: "
          f"{nominal['representable_at_current_bp_granularity']})")
    print(f"    exact p_window_safe: with_ctpr={nominal['exact_p_window_safe_with_ctpr']:.6e} "
          f"without_ctpr={nominal['exact_p_window_safe_without_ctpr']:.6e} "
          f"naive={nominal['naive_p_window_safe']:.6e}")
    print(f"    CTPR on/off identical: {nominal['ctpr_on_off_identical']}   "
          f"naive matches exact: {nominal['naive_matches_exact']}")
    print(f"    session P(Safe) exact={nominal['session_p_safe_exact_with_ctpr']:.6f} "
          f"naive={nominal['session_p_safe_naive']:.6f}  budget_held={nominal['session_budget_held']}")

    quant = quantization_finding()
    print(f"\n(3) Basis-point quantization finding: min representable alpha={quant['min_representable_alpha']:.4f}, "
          f"resulting session P(Safe)={quant['session_p_safe_at_min_alpha']:.6f}")

    print(f"\n(4) Monte Carlo injection cross-check (N={MC_N_WINDOWS} windows, real signed statements)...")
    mc = monte_carlo_injection()
    print(f"    p_safe: predicted={mc['predicted_p_safe']:.5f} measured={mc['measured_p_safe']:.5f} "
          f"rel_err={mc['p_safe_relative_error']:.3%}")
    print(f"    p_below_normal: predicted={mc['predicted_p_below_normal']:.5f} "
          f"measured={mc['measured_p_below_normal']:.5f} rel_err={mc['p_below_normal_relative_error']:.3%}")

    boundary = boundary_case_result()
    print(f"\n(5) Cross-severity boundary case (hypothetical, NOT deployed): "
          f"exact_p_safe={boundary['exact_p_safe']:.4f} naive_p_safe={boundary['naive_p_safe']:.4f} "
          f"(underestimate={boundary['naive_underestimate']:.4f}) "
          f"corrected_p_safe={boundary['corrected_p_safe']:.4f} "
          f"(matches exact: {boundary['corrected_matches_exact']})")

    sweep = budget_sweep(SWEEP_BUDGETS)
    print("\n(6) Illustrative budget sweep (research parameters, not deployment recommendations):")
    for row in sweep:
        print(f"    B={row['session_budget']:.3%}  alpha_target={row['alpha_target_per_strict_claim']:.3e} "
              f"({row['alpha_target_bp']:.5f} bp, representable={row['representable_at_1bp_granularity']})  "
              f"implied_halts/min={row['implied_spurious_halts_per_minute_at_target']:.3e}  "
              f"naive_matches_exact={row['naive_matches_exact']}")

    print("\n(7) Mutation kill rates...")
    mutation = run_mutation_checks()
    print(f"    {mutation['sba_validation_kill_rate_line']}  (passed={mutation['sba_validation_passed']})")
    print(f"    pure core: {mutation['pure_core_kill_rate_line']}  (unaffected={mutation['pure_core_unaffected']})")

    report = {
        "windows_per_session": WINDOWS_PER_SESSION,
        "nominal_budget_result": nominal,
        "quantization_finding": quant,
        "monte_carlo": mc,
        "boundary_case": boundary,
        "budget_sweep": sweep,
        "mutation": mutation,
    }
    report_path = ARTIFACTS_DIR / "phase8_5_sba_validation_report.json"
    _write_json(report, report_path)

    m = manifest_mod.build_manifest(
        repo_root=REPO_ROOT,
        experiment_name="phase8_5_sba_validation",
        config_paths={"crit_table": REPO_ROOT / "config" / "crit_table.json",
                      "ctpr": REPO_ROOT / "config" / "ctpr.json"},
        params={
            "windows_per_session": WINDOWS_PER_SESSION, "nominal_session_budget": NOMINAL_SESSION_BUDGET,
            "sweep_budgets": SWEEP_BUDGETS, "mc_alpha": MC_ALPHA, "mc_alpha2": MC_ALPHA2,
            "mc_n_windows": MC_N_WINDOWS,
        },
        artifact_paths={"report_json": report_path},
        calibration_status="provisional",
        seeds={"monte_carlo_seed": 20260720},
    )
    manifest_path = PROVENANCE_DIR / "phase8_5_sba_validation_manifest.json"
    manifest_mod.write_manifest(m, manifest_path)

    print(f"\nReport written to {report_path}")
    print(f"Manifest written to {manifest_path}")


if __name__ == "__main__":
    main()
