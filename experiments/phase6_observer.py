"""Phase 6 driver (CLAUDE.md §14): the Observer and ActuationFidelity
evidence.

Produces the reportable results requested for Phase 6:
  (1) the AF evidence path: Observer -> signed statement -> Evidence Plane
      -> T4 admission -> Trust Kernel, demonstrated end to end on both a
      healthy feedback pair and a disagreeing one (observer disagreement /
      actuator manipulation, §3).
  (2) a structural check that the enforcer cannot originate AF evidence:
      (a) static -- an AST scan of enforcement/*.py for forbidden imports
          (evidence_plane, observer, sensors), forbidden signing-related
          attribute accesses (sign_statement, sign_verdict, build_statement,
          generate_keypair, keypair_from_seed), and forbidden AF-identity
          string constants, all excluding docstrings (so clamp.py's own
          documentation of this boundary is not a false positive);
      (b) dynamic -- spies on trust_kernel.schema.sign_statement and
          .build_statement across one full, realistic enforcement cycle
          (accept -> clamp -> slew -> capability-gated write) and confirms
          neither is ever called.
  Plus the mutation kill rate (reported by harnesses/mutation_check.py).

Honest scope (§3, printed verbatim below): this demonstrates that the
enforcer's own code, as written, has no call path to sign or append AF
evidence -- a property of the program under normal/honest operation and
under Position A's A_data (who has not compromised the Observer process
itself). It is not a hard sandboxing guarantee against A_code (arbitrary
code execution at host privilege, including inside the enforcer, §3) --
that adversary can reach any reachable Python object regardless of what
the enforcer's own source code calls. The Observer's independence is an
honest-evidence property; it is not the basis of T5 (§5).

Run: `python3 -m experiments.phase6_observer` from the repo root.
"""

import ast
import json
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from enforcement import clamp
from enforcement.capability import ActuatorCapability, SimulatedActuator
from enforcement.slew import SlewState
from evidence_plane import log as evlog
from observer.observer import AF_CLAIM_TYPE, Observer
from provenance import manifest as manifest_mod
from trust_kernel import schema
from tests import key_fixtures as kf
from tests import window_fixtures as wf

ARTIFACTS_DIR = REPO_ROOT / "artifacts"
PROVENANCE_DIR = REPO_ROOT / "provenance"
ENFORCEMENT_DIR = REPO_ROOT / "enforcement"

CEIL_PATH = REPO_ROOT / "config" / "ceil.json"
ENV_PATH = REPO_ROOT / "config" / "env.json"

STRUCTURAL_CHECK_TARGETS = ["clamp.py", "capability.py", "slew.py"]

FORBIDDEN_IMPORT_ROOTS = {"evidence_plane", "observer", "sensors"}
FORBIDDEN_SIGNING_ATTRS = {
    "sign_statement", "sign_verdict", "build_statement",
    "generate_keypair", "keypair_from_seed",
}
FORBIDDEN_AF_STRINGS = {
    "ActuationFidelity", "actuationfidelity",
    "actuationfidelity.provisional_v0", "actuationfidelity_sensor_v0",
}


# --------------------------------------------------------------------------
# (1) AF evidence path demo.
# --------------------------------------------------------------------------

def run_af_evidence_path_demo(tmp_path):
    _, observer_sk = kf.keypair_for("actuationfidelity_sensor_v0")
    observer = Observer(observer_sk)

    log = evlog.EvidenceLog(tmp_path / "phase6_af_demo.log")

    # Healthy case: actuator reports exactly what was commanded.
    commanded = {"max_speed": 1000, "max_acceleration": 500}
    healthy_observed = {"max_speed": 1000, "max_acceleration": 500}
    healthy_stmt = observer.observe_and_append(
        log, commanded=commanded, observed=healthy_observed, window_id=1, claimed_at=0,
    )

    # Attack case: actuator manipulation / observer disagreement (§3) --
    # actual behaviour diverges sharply from what was commanded.
    attacked_observed = {"max_speed": 1600, "max_acceleration": 800}
    attacked_stmt = observer.observe_and_append(
        log, commanded=commanded, observed=attacked_observed, window_id=2, claimed_at=0,
    )
    log.fsync_window()
    log.close()

    key_registry = schema.load_key_registry(wf.CONFIG_PATHS["key_registry"])
    claim_registry = schema.load_claim_registry(wf.CONFIG_PATHS["claim_registry"])

    def admit(stmt, window_id):
        return schema.admit_statement(
            stmt, key_registry=key_registry, claim_registry=claim_registry,
            current_window_id=window_id, window_open_time_ms=0, arrival_time_ms=1,
        )

    healthy_admission = admit(healthy_stmt, 1)
    attacked_admission = admit(attacked_stmt, 2)

    # Fold each AF statement into an otherwise-healthy window and compute a
    # verdict, to show the AF claim actually reaches the kernel and moves
    # the ActuationFidelity dimension (and, since it's a strict dimension
    # per config/crit_table.json, moves pi itself on the attack case).
    healthy_window = [s for s in wf.healthy_window(window_id=1) if s["claim_type"] != AF_CLAIM_TYPE] + [healthy_stmt]
    attacked_window = [s for s in wf.healthy_window(window_id=2) if s["claim_type"] != AF_CLAIM_TYPE] + [attacked_stmt]

    healthy_effective, healthy_verdict = wf.compute_verdict(healthy_window)
    attacked_effective, attacked_verdict = wf.compute_verdict(attacked_window)

    return {
        "healthy": {
            "commanded": commanded, "observed": healthy_observed,
            "raw_measurement": healthy_stmt["raw_measurement"],
            "admitted": healthy_admission.accepted,
            "af_dimension_level": healthy_effective["ActuationFidelity"].name,
            "verdict": healthy_verdict.name,
        },
        "attacked": {
            "commanded": commanded, "observed": attacked_observed,
            "raw_measurement": attacked_stmt["raw_measurement"],
            "admitted": attacked_admission.accepted,
            "af_dimension_level": attacked_effective["ActuationFidelity"].name,
            "verdict": attacked_verdict.name,
        },
        "key_id": healthy_stmt["key_id"],
        "source_id": healthy_stmt["source_id"],
    }


# --------------------------------------------------------------------------
# (2a) Static structural check.
# --------------------------------------------------------------------------

def _docstring_node_ids(tree) -> set:
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                ids.add(id(body[0].value))
    return ids


def _non_docstring_string_constants(tree, docstring_ids) -> set:
    return {
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstring_ids
    }


def _imported_module_roots(tree) -> set:
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def _accessed_attribute_names(tree) -> set:
    return {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}


def run_static_structural_check():
    per_file = {}
    for name in STRUCTURAL_CHECK_TARGETS:
        path = ENFORCEMENT_DIR / name
        tree = ast.parse(path.read_text())
        docstring_ids = _docstring_node_ids(tree)

        strings = _non_docstring_string_constants(tree, docstring_ids)
        imports = _imported_module_roots(tree)
        attrs = _accessed_attribute_names(tree)

        per_file[name] = {
            "forbidden_imports_found": sorted(imports & FORBIDDEN_IMPORT_ROOTS),
            "forbidden_signing_attrs_found": sorted(attrs & FORBIDDEN_SIGNING_ATTRS),
            "forbidden_af_strings_found": sorted(strings & FORBIDDEN_AF_STRINGS),
        }

    ok = all(
        not v["forbidden_imports_found"] and not v["forbidden_signing_attrs_found"] and not v["forbidden_af_strings_found"]
        for v in per_file.values()
    )
    return {"per_file": per_file, "ok": ok}


# --------------------------------------------------------------------------
# (2b) Dynamic structural check: spy on the only two functions capable of
# producing a valid statement, run a full realistic enforcement cycle, and
# confirm neither is ever called.
# --------------------------------------------------------------------------

def run_dynamic_structural_check():
    calls = []
    orig_sign_statement = schema.sign_statement
    orig_build_statement = schema.build_statement

    def spy_sign_statement(*a, **kw):
        calls.append("sign_statement")
        return orig_sign_statement(*a, **kw)

    def spy_build_statement(*a, **kw):
        calls.append("build_statement")
        return orig_build_statement(*a, **kw)

    schema.sign_statement = spy_sign_statement
    schema.build_statement = spy_build_statement
    try:
        kernel_pk = wf.kernel_public_key()
        ceil, env = clamp.load_envelope_configs(CEIL_PATH, ENV_PATH)
        cache = clamp.AcceptCache()
        cap = ActuatorCapability()
        actuator = SimulatedActuator(cap)
        state = SlewState()

        for i in range(10):
            verdict_name = "Normal" if i % 3 != 0 else "Safe"
            verdict_obj = wf.issue_forged_verdict(verdict_name, window_id=8000 + i, issued_at=62, expires_at=170)
            decision = clamp.accept_and_clamp(
                verdict_obj, kernel_pk, now_ms=100, cache=cache, env=env, ceil=ceil,
            )
            if decision.accepted:
                cmd = state.step(decision.envelope)
                actuator.write(cap, cmd)
    finally:
        schema.sign_statement = orig_sign_statement
        schema.build_statement = orig_build_statement

    return {
        "calls_during_enforcement_cycle": calls,
        "actuator_writes": len(actuator.history),
        "ok": calls == [],
    }


def _write_json(obj, path):
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n")


def main():
    ARTIFACTS_DIR.mkdir(exist_ok=True)
    PROVENANCE_DIR.mkdir(exist_ok=True)

    with __import__("tempfile").TemporaryDirectory() as tmp:
        af_path_result = run_af_evidence_path_demo(pathlib.Path(tmp))

    static_result = run_static_structural_check()
    dynamic_result = run_dynamic_structural_check()

    af_path_json = ARTIFACTS_DIR / "phase6_af_evidence_path.json"
    structural_json = ARTIFACTS_DIR / "phase6_structural_check.json"

    _write_json(af_path_result, af_path_json)
    _write_json({"static": static_result, "dynamic": dynamic_result}, structural_json)

    m = manifest_mod.build_manifest(
        repo_root=REPO_ROOT,
        experiment_name="phase6_observer",
        config_paths={"crit_table": wf.CONFIG_PATHS["crit_table"], "ctpr": wf.CONFIG_PATHS["ctpr"],
                      "eis_v0": wf.CONFIG_PATHS["eis"], "key_registry": wf.CONFIG_PATHS["key_registry"],
                      "claim_registry": wf.CONFIG_PATHS["claim_registry"],
                      "ceil": CEIL_PATH, "env": ENV_PATH},
        params={"dynamic_check_windows": 10},
        artifact_paths={"af_evidence_path_json": af_path_json, "structural_check_json": structural_json},
        calibration_status="provisional",
        seeds={"note": "demo Observer/sensor/kernel keys derived from named seeds in tests/key_fixtures.py"},
    )
    manifest_path = PROVENANCE_DIR / "phase6_observer_manifest.json"
    manifest_mod.write_manifest(m, manifest_path)

    print("(1) AF evidence path: Observer -> statement -> Evidence Plane -> T4 admission -> Trust Kernel")
    print(f"    key_id/source_id: {af_path_result['key_id']}")
    for label in ("healthy", "attacked"):
        row = af_path_result[label]
        print(f"    [{label:9s}] commanded={row['commanded']} observed={row['observed']} "
              f"raw_measurement={row['raw_measurement']:4d} admitted={row['admitted']} "
              f"AF_dimension={row['af_dimension_level']:4s} verdict={row['verdict']}")

    print("\n(2a) Static structural check (AST scan of enforcement/*.py, docstrings excluded):")
    for name, v in static_result["per_file"].items():
        print(f"    enforcement/{name}: forbidden_imports={v['forbidden_imports_found']} "
              f"forbidden_signing_attrs={v['forbidden_signing_attrs_found']} "
              f"forbidden_af_strings={v['forbidden_af_strings_found']}")
    print(f"    static_ok: {static_result['ok']}")

    print("\n(2b) Dynamic structural check (spy on sign_statement/build_statement across a full enforcement cycle):")
    print(f"    actuator writes performed: {dynamic_result['actuator_writes']}")
    print(f"    sign_statement/build_statement calls observed: {dynamic_result['calls_during_enforcement_cycle']}")
    print(f"    dynamic_ok: {dynamic_result['ok']}")

    print(
        "\nHonest scope (§3): this demonstrates that the enforcer's own code, as written, has no "
        "call path to sign or append AF evidence -- a property of the program under normal/honest "
        "operation and under Position A's A_data (who has not compromised the Observer process "
        "itself). It is not a hard sandboxing guarantee against A_code (arbitrary code execution at "
        "host privilege, including inside the enforcer): that adversary can reach any reachable "
        "Python object regardless of what the enforcer's own source code calls. The Observer's "
        "independence is an honest-evidence property; it is not the basis of T5."
    )

    print(f"\nArtifacts written to {ARTIFACTS_DIR}")
    print(f"Manifest written to {manifest_path}")

    ok = (
        af_path_result["healthy"]["admitted"] and af_path_result["attacked"]["admitted"]
        and af_path_result["healthy"]["af_dimension_level"] == "HIGH"
        and af_path_result["attacked"]["af_dimension_level"] == "LOW"
        and af_path_result["attacked"]["verdict"] == "Safe"  # ActuationFidelity is strict (§4): LOW alone -> Safe
        and static_result["ok"] and dynamic_result["ok"]
    )
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
