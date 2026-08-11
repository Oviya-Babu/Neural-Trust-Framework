"""Phase 5 driver (CLAUDE.md §14): the enforcement plane and T5
(consequence-boundedness).

Produces the reportable results requested for Phase 5:
  (1) structural check -- static (AST) scan of enforcement/*.py confirming
      none of the nine forbidden verdict fields is ever used as a subscript
      or .get() key, plus a dynamic GuardedVerdictDict run of the real
      accept() path against a FULL verdict object.
  (2) adversarial forcing -- across every attack class (including the four
      with no detector), force the verdict to Normal and count envelope
      violations (realised > Ceil). Target: 0.
  (3) slew containment under forced Normal<->Safe oscillation: cmd ⊑
      realise(ν) at every step. Target: 0 violations.
  Figure [T5] data: Env(verdict) vs realise(verdict) = Env(verdict) ⊓ Ceil
      across the three verdict zones, plus the per-attack-class realised-
      envelope records.

Label (§12): (2) and (3) are falsifiable in the sense that they exercise
real code paths with real signatures and real arithmetic and could reveal
an implementation bug -- but the *result* they are expected to show
(0 violations) is not a discovery about detector quality, it is a
structural consequence of realise() never reading Ceil from ν (T5(a)).
See the printed "Stated limitation" block for what this experiment does and
does not establish.

Run: `python3 -m experiments.phase5_enforcement` from the repo root.
"""

import ast
import json
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from enforcement import clamp
from enforcement.slew import SlewState
from provenance import manifest as manifest_mod
from tests import window_fixtures as wf
from tests.enforcement_fixtures import GuardedVerdictDict

ARTIFACTS_DIR = REPO_ROOT / "artifacts"
PROVENANCE_DIR = REPO_ROOT / "provenance"
ENFORCEMENT_DIR = REPO_ROOT / "enforcement"

CEIL_PATH = REPO_ROOT / "config" / "ceil.json"
ENV_PATH = REPO_ROOT / "config" / "env.json"

STRUCTURAL_CHECK_TARGETS = ["clamp.py", "capability.py", "slew.py"]

FORBIDDEN_VERDICT_FIELDS = {
    "evidence_root", "effective_dims", "policy_version", "crit_table_hash",
    "ctpr_config_hash", "roc_config_hash", "claim_registry_hash",
    "key_registry_hash", "calibration_status", "issued_at",
}


# --------------------------------------------------------------------------
# (1) Structural check.
# --------------------------------------------------------------------------

def _subscript_and_get_string_keys(source: str) -> set:
    """Collects every string literal used as a dict subscript key
    (obj["key"]) or as the first argument to a .get("key") call, anywhere
    in `source`. Deliberately does NOT scan docstrings/comments as prose --
    ast.walk only visits actual expression nodes, so a docstring merely
    *mentioning* a forbidden field name (as enforcement/clamp.py's module
    docstring does, to document the boundary) is not a false positive."""
    tree = ast.parse(source)
    keys = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript):
            s = node.slice
            if isinstance(s, ast.Constant) and isinstance(s.value, str):
                keys.add(s.value)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get":
            if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                keys.add(node.args[0].value)
    return keys


def run_structural_check():
    per_file = {}
    for name in STRUCTURAL_CHECK_TARGETS:
        path = ENFORCEMENT_DIR / name
        keys = _subscript_and_get_string_keys(path.read_text())
        bad = sorted(keys & FORBIDDEN_VERDICT_FIELDS)
        per_file[name] = {"accessed_string_keys": sorted(keys), "forbidden_keys_found": bad}

    static_ok = all(not v["forbidden_keys_found"] for v in per_file.values())

    # Dynamic half: run the real accept() path against a GuardedVerdictDict
    # wrapping a FULL verdict object (all fourteen fields present).
    kernel_pk = wf.kernel_public_key()
    verdict_obj = wf.issue_forged_verdict("Normal", window_id=1000)
    guarded = GuardedVerdictDict(verdict_obj)
    dynamic_exception = None
    try:
        result = clamp.accept(guarded, kernel_pk, now_ms=100, cache=clamp.AcceptCache())
        dynamic_ok = result.accepted
    except AssertionError as e:
        dynamic_ok = False
        dynamic_exception = str(e)

    return {
        "static": per_file,
        "static_ok": static_ok,
        "dynamic_ok": dynamic_ok,
        "dynamic_exception": dynamic_exception,
        "correct": static_ok and dynamic_ok,
    }


# --------------------------------------------------------------------------
# (2) Adversarial forcing across attack classes.
# --------------------------------------------------------------------------

# (name, mechanism, description). mechanism "direct" = wf.issue_forged_verdict:
# a validly-signed verdict declaring Normal is emitted with no honest
# evidence behind it at all, modeling A_data's "compromises... the Trust
# Kernel" capability (CLAUDE.md §3) -- the premise for this whole
# experiment ("π(state) is adversary-controlled").
ATTACK_CLASSES = [
    ("replay", "direct",
     "Behaviour-Based Attack Framework (§3): a stale verdict re-presented as current, forged fresh to pass freshness."),
    ("signal_injection", "direct",
     "§3: injected raw signal crafted to read as within-detector-range; modeled here as a forced Normal verdict."),
    ("adversarial_eeg", "direct",
     "§3: adversarial EEG crafted to evade the Signal/Model detectors."),
    ("firmware_modification", "direct",
     "§3: board-level firmware tamper below the software evidence layer -- structurally invisible to any sensor here."),
    ("model_replacement", "direct",
     "§3: classifier swapped for an attacker-controlled model that still emits plausible-looking predictions."),
    ("model_poisoning_training_pipeline", "direct",
     "No-detector class (explicit): training-pipeline poisoning corrupts the model before any runtime evidence exists."),
    ("communication_tampering", "direct",
     "§3: TB2/TB3 transport tampering that still arrives as a well-formed, validly-signed statement or verdict."),
    ("timing_attack", "direct",
     "§3: timing manipulation exploiting the [62,170]ms freshness window."),
    ("observer_disagreement", "direct",
     "§3: Observer-reported actuation fidelity disagrees with the commanded envelope; ActuationFidelity evidence forged to hide it."),
    ("actuator_manipulation_in_envelope_wrong_command", "direct",
     "No-detector class (explicit): in-envelope wrong command -- correct magnitude, wrong target; invisible to Φ, which bounds magnitude only."),
    ("calibration_poisoning_within_prior", "direct",
     "No-detector class (explicit): within-prior calibration poisoning keeps Calibration at MED/HIGH by construction (§4) -- uncovered, not undefended."),
    ("total_kernel_compromise_evidence_forgery", "direct",
     "No-detector class (explicit): evidence forgery via total kernel compromise -- A_data 'compromises... the Trust Kernel' (§3); kernel_sig itself is attacker-produced."),
]


def run_adversarial_forcing(kernel_pk, env, ceil):
    rows = []
    base_window = 2000
    for i, (name, mechanism, description) in enumerate(ATTACK_CLASSES):
        window_id = base_window + i
        verdict_obj = wf.issue_forged_verdict("Normal", window_id=window_id, issued_at=62, expires_at=170)

        decision = clamp.accept_and_clamp(
            verdict_obj, kernel_pk, now_ms=100, cache=clamp.AcceptCache(),
            env=env, ceil=ceil,
        )
        violation = False
        if decision.accepted and decision.envelope is not None:
            violation = (decision.envelope["max_speed"] > ceil["max_speed"]
                         or decision.envelope["max_acceleration"] > ceil["max_acceleration"])
        rows.append({
            "attack_class": name,
            "mechanism": mechanism,
            "description": description,
            "window_id": window_id,
            "recorded_verdict": verdict_obj["verdict"],
            "accepted": decision.accepted,
            "env_indicated": env.get(verdict_obj["verdict"]) if decision.accepted else None,
            "realised": decision.envelope,
            "ceil": ceil,
            "violation": violation,
        })

    # One honest-pipeline row for transparency: post-relattice (L^6, CLAUDE.md
    # 2026-07-19 changelog -- Context removed, it carried the deliberately-weak
    # detector that used to cap band_cap=MED and floor the honest verdict at
    # Constrained), the remaining six dimensions' provisional detectors clear
    # their respective theta_2, so the honest pipeline can legitimately reach
    # Normal on maximally-healthy-looking evidence. Included for the same
    # reason as before: to make explicit what the honest path actually
    # produces under the current provisional config, not to pad the
    # violation count.
    honest_statements = wf.healthy_window(window_id=base_window + len(ATTACK_CLASSES), raw_measurement=100)
    honest_verdict_obj = wf.issue_signed_verdict(
        honest_statements, window_id=base_window + len(ATTACK_CLASSES), issued_at=62, expires_at=170,
    )
    honest_decision = clamp.accept_and_clamp(
        honest_verdict_obj, kernel_pk, now_ms=100, cache=clamp.AcceptCache(), env=env, ceil=ceil,
    )
    honest_row = {
        "attack_class": "honest_pipeline_best_case",
        "mechanism": "evidence_through_honest_pi",
        "description": "Control row: the best-case honest computation from maximally-healthy-looking evidence, "
                        "run through the real pi. Post-relattice (L^6) the honest path legitimately reaches "
                        "Normal under the current provisional EIS config -- included to show what the honest "
                        "path actually produces, NOT to pad the violation count.",
        "window_id": honest_verdict_obj["window_id"],
        "recorded_verdict": honest_verdict_obj["verdict"],
        "accepted": honest_decision.accepted,
        "env_indicated": env.get(honest_verdict_obj["verdict"]) if honest_decision.accepted else None,
        "realised": honest_decision.envelope,
        "ceil": ceil,
        "violation": False if not honest_decision.accepted else (
            honest_decision.envelope["max_speed"] > ceil["max_speed"]
            or honest_decision.envelope["max_acceleration"] > ceil["max_acceleration"]
        ),
    }

    violation_count = sum(r["violation"] for r in rows)
    return rows, honest_row, violation_count


# --------------------------------------------------------------------------
# (3) Slew containment under forced Normal<->Safe oscillation.
# --------------------------------------------------------------------------

def run_slew_containment(kernel_pk, env, ceil, n_windows=20):
    state = SlewState()
    steps = []
    violation_count = 0
    for i in range(n_windows):
        verdict_name = "Normal" if i % 2 == 0 else "Safe"
        verdict_obj = wf.issue_forged_verdict(verdict_name, window_id=3000 + i, issued_at=62, expires_at=170)
        decision = clamp.accept_and_clamp(
            verdict_obj, kernel_pk, now_ms=100, cache=clamp.AcceptCache(), env=env, ceil=ceil,
        )
        assert decision.accepted, "forced verdict unexpectedly rejected"
        target = decision.envelope
        cmd = state.step(target)
        violated = cmd["max_speed"] > target["max_speed"] or cmd["max_acceleration"] > target["max_acceleration"]
        if violated:
            violation_count += 1
        steps.append({"window_index": i, "verdict": verdict_name, "target": target, "cmd": cmd, "violation": violated})
    return steps, violation_count


# --------------------------------------------------------------------------
# Figure [T5] data.
# --------------------------------------------------------------------------

def build_figure_t5(env, ceil):
    rows = []
    for name in ("Safe", "Constrained", "Normal"):
        rows.append({
            "verdict_zone": name,
            "env_indicated_max_speed": env[name]["max_speed"],
            "realised_max_speed": clamp.realise(name, env, ceil)["max_speed"],
            "env_indicated_max_acceleration": env[name]["max_acceleration"],
            "realised_max_acceleration": clamp.realise(name, env, ceil)["max_acceleration"],
        })
    return rows


def _write_json(obj, path):
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n")


def main():
    ARTIFACTS_DIR.mkdir(exist_ok=True)
    PROVENANCE_DIR.mkdir(exist_ok=True)

    ceil, env = clamp.load_envelope_configs(CEIL_PATH, ENV_PATH)
    kernel_pk = wf.kernel_public_key()

    structural_result = run_structural_check()
    forcing_rows, honest_row, forcing_violations = run_adversarial_forcing(kernel_pk, env, ceil)
    slew_steps, slew_violations = run_slew_containment(kernel_pk, env, ceil)
    figure_t5 = build_figure_t5(env, ceil)

    structural_json = ARTIFACTS_DIR / "phase5_structural_check.json"
    forcing_json = ARTIFACTS_DIR / "phase5_adversarial_forcing.json"
    slew_json = ARTIFACTS_DIR / "phase5_slew_containment.json"
    figure_json = ARTIFACTS_DIR / "phase5_figure_t5.json"

    _write_json(structural_result, structural_json)
    _write_json({"rows": forcing_rows, "honest_pipeline_control_row": honest_row,
                 "violation_count": forcing_violations, "attack_class_count": len(forcing_rows)}, forcing_json)
    _write_json({"steps": slew_steps, "violation_count": slew_violations}, slew_json)
    _write_json({"rows": figure_t5, "ceil": ceil}, figure_json)

    m = manifest_mod.build_manifest(
        repo_root=REPO_ROOT,
        experiment_name="phase5_enforcement",
        config_paths={"ceil": CEIL_PATH, "env": ENV_PATH,
                      "crit_table": wf.CONFIG_PATHS["crit_table"], "ctpr": wf.CONFIG_PATHS["ctpr"],
                      "eis_v0": wf.CONFIG_PATHS["eis"], "key_registry": wf.CONFIG_PATHS["key_registry"],
                      "claim_registry": wf.CONFIG_PATHS["claim_registry"]},
        params={"attack_class_count": len(ATTACK_CLASSES), "slew_windows": len(slew_steps)},
        artifact_paths={
            "structural_check_json": structural_json, "adversarial_forcing_json": forcing_json,
            "slew_containment_json": slew_json, "figure_t5_json": figure_json,
        },
        calibration_status="provisional",
        seeds={"note": "demo sensor/kernel keys derived from named seeds in tests/key_fixtures.py"},
    )
    manifest_path = PROVENANCE_DIR / "phase5_enforcement_manifest.json"
    manifest_mod.write_manifest(m, manifest_path)

    print("(1) Structural check (dependency analysis, §6):")
    for name, v in structural_result["static"].items():
        print(f"    enforcement/{name}: forbidden keys found = {v['forbidden_keys_found']}")
    print(f"    static_ok={structural_result['static_ok']}  dynamic_ok(GuardedVerdictDict run)={structural_result['dynamic_ok']}")
    print(f"    correct: {structural_result['correct']}")

    print(f"\n(2) Adversarial forcing across {len(forcing_rows)} attack classes (target: 0 violations):")
    for r in forcing_rows:
        print(f"    [{r['mechanism']:26s}] {r['attack_class']:45s} verdict={r['recorded_verdict']:11s} "
              f"realised={r['realised']}  violation={r['violation']}")
    print(f"    control row (honest pipeline): recorded_verdict={honest_row['recorded_verdict']} "
          f"realised={honest_row['realised']} violation={honest_row['violation']}")
    print(f"    envelope-violation count: {forcing_violations}/{len(forcing_rows)}")

    print(f"\n(3) Slew containment under forced Normal<->Safe oscillation over {len(slew_steps)} windows "
          f"(target: 0 violations of cmd ⊑ realise(ν)):")
    print(f"    violation count: {slew_violations}/{len(slew_steps)}")
    print("    first 6 steps:")
    for s in slew_steps[:6]:
        print(f"      window={s['window_index']} verdict={s['verdict']:11s} target={s['target']} cmd={s['cmd']}")

    print("\nFigure [T5] data (Env(verdict) vs realise(verdict) = Env(verdict) ⊓ Ceil):")
    for row in figure_t5:
        print(f"    {row['verdict_zone']:11s} env_indicated_max_speed={row['env_indicated_max_speed']:5d}  "
              f"realised_max_speed={row['realised_max_speed']:5d}")

    print(
        "\nLabel (§12): (2) and (3) exercise real signatures, real cache/expiry logic, and real "
        "arithmetic against concrete attack-shaped inputs -- they can reveal an implementation bug. "
        "The *result* they are expected to show (0 violations) is not a discovery about detector "
        "quality; it is a structural consequence of realise() never reading Ceil from ν (T5(a))."
    )
    print(
        "\nStated limitation: this experiment validates T5(a) as a structural property of the program "
        "under TA1's first clause (Ceil is not a function of ν), which holds vs A_data and A_code. It "
        "does NOT validate TA1's second clause (Ceil is not adversary-writable), which holds only vs "
        "A_data and requires the in-path hardware ceiling MCU against A_code. It does not measure "
        "hardware termination latency. The software ceiling's unforgeability is a program property, "
        "not a physical one."
    )
    print("\nthe adversary who forges everything still gets 1 m/s. T5 bounds consequence; it does not confer safety.")

    print(f"\nArtifacts written to {ARTIFACTS_DIR}")
    print(f"Manifest written to {manifest_path}")

    ok = structural_result["correct"] and forcing_violations == 0 and slew_violations == 0
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
