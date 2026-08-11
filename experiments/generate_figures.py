"""Figure/table generation (CLAUDE.md §13, Phase D of this session's plan):
renders every figure/table named in the Phase D task list from the
ALREADY-GENERATED, already-measured JSON artifacts in artifacts/ -- this
script performs no measurement, no derivation, and touches no frozen
config. It reads what phases 2-12 already produced and visualises it.

One-command regeneration:
    .venv-figures/bin/python -m experiments.generate_figures

Requires matplotlib only (requirements-figures.txt, its own venv --
.venv-figures -- kept separate from the zero-dependency pure core and from
bci_pipeline's heavier numpy/scipy/mne/moabb venv, since figure generation
needs neither of those, only matplotlib over already-computed JSON).

Every figure/table is stamped with a provenance caption: source artifact
path(s), calibration_status where applicable, and generation timestamp --
CLAUDE.md §13's rule ("no figure enters the dissertation that cannot be
regenerated from its manifest by one command") applies to every output here.

Color palette: reused verbatim from the validated reference palette (dataviz
skill, references/palette.md) -- categorical slots 1/2/3 (blue/orange/aqua)
for the Safe/Constrained/Normal ordinal, and the fixed status palette
(good/warning/critical) for pass-fail-shaped annotations. Every mark is also
text-labelled directly; color is never the sole carrier of meaning.
"""

import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import csv
import datetime
import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

ARTIFACTS_DIR = REPO_ROOT / "artifacts"
FIGURES_DIR = ARTIFACTS_DIR / "figures"

# Validated reference palette (dataviz skill references/palette.md) -- reused verbatim, not re-derived.
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
GOOD, WARNING, CRITICAL = "#0ca30c", "#fab219", "#d03b3b"
NEUTRAL_GRAY = "#8a8a86"
TEXT_PRIMARY, TEXT_SECONDARY = "#0b0b0b", "#52514e"
SURFACE = "#fcfcfb"

ORDINAL_VERDICT_COLOR = {"Safe": "#0d366b", "Constrained": BLUE, "Normal": "#9ec5f4"}  # blue ramp, dark->light = restrictive->permissive
RESOLUTION_COLOR = {"stable": GOOD, "tail_floor": WARNING, "pending": NEUTRAL_GRAY}

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": TEXT_SECONDARY, "axes.labelcolor": TEXT_PRIMARY,
    "text.color": TEXT_PRIMARY, "xtick.color": TEXT_SECONDARY, "ytick.color": TEXT_SECONDARY,
    "axes.spines.top": False, "axes.spines.right": False, "font.size": 10,
})


def _load(name):
    return json.loads((ARTIFACTS_DIR / name).read_text())


def _caption(ax, sources, extra=None):
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    text = f"Source: {', '.join(sources)} | Generated: {ts}"
    if extra:
        text += f" | {extra}"
    ax.figure.text(0.01, 0.01, text, fontsize=6.5, color=TEXT_SECONDARY, ha="left", va="bottom")


def _table_figure(cell_text, cell_colors, col_labels, title, col_widths=None):
    """Shared table renderer: sizes the figure to the content (avoiding
    both left-edge label clipping and excess blank canvas) and fills the
    axes with the table via an explicit bbox rather than matplotlib's
    default auto-placement, which left large gaps above/below in early
    drafts of these figures."""
    n_rows, n_cols = len(cell_text), len(col_labels)
    max_first_col_chars = max(len(str(row[0])) for row in cell_text + [col_labels])
    fig_w = max(7.5, 0.11 * max_first_col_chars + 0.09 * n_cols * 22)
    fig_h = 0.42 * n_rows + 1.3
    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    ax.axis("off")
    tbl = ax.table(cellText=cell_text, colLabels=col_labels, cellColours=cell_colors,
                    loc="center", cellLoc="center", colWidths=col_widths, bbox=[0, 0.02, 1, 0.85])
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(9)
    for (r, c), cell in tbl.get_celld().items():
        if c == 0:
            cell.set_text_props(ha="left")
            cell.PAD = 0.02
    ax.set_title(title, fontsize=11, pad=10)
    return fig, ax, tbl


def _save(fig, name):
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    for ext in ("png", "svg"):
        fig.savefig(FIGURES_DIR / f"{name}.{ext}", dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote {name}.png / {name}.svg")


# ============================================================================
# 1. Figure [T5]: kernel-intended (Env) vs realised-clamped envelope
# ============================================================================

def fig_t5():
    d = _load("phase5_figure_t5.json")
    zones = [r["verdict_zone"] for r in d["rows"]]
    env_speed = [r["env_indicated_max_speed"] for r in d["rows"]]
    real_speed = [r["realised_max_speed"] for r in d["rows"]]
    env_accel = [r["env_indicated_max_acceleration"] for r in d["rows"]]
    real_accel = [r["realised_max_acceleration"] for r in d["rows"]]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(9, 3.6))
    x = range(len(zones))
    w = 0.32
    for ax, env_v, real_v, title, unit in [
        (ax1, env_speed, real_speed, "max_speed", "mm/s"),
        (ax2, env_accel, real_accel, "max_acceleration", "mm/s²"),
    ]:
        ax.bar([i - w / 2 for i in x], env_v, width=w, color=BLUE, label="Env(π̂(ν)) -- kernel-intended")
        ax.bar([i + w / 2 for i in x], real_v, width=w, color=ORANGE, label="realise(ν) = Env ⊓ Ceil -- actually commanded")
        for i, (e, r) in enumerate(zip(env_v, real_v)):
            ax.text(i - w / 2, e + 15, str(e), ha="center", fontsize=8, color=TEXT_SECONDARY)
            ax.text(i + w / 2, r + 15, str(r), ha="center", fontsize=8, color=TEXT_SECONDARY)
        ax.set_xticks(list(x)); ax.set_xticklabels(zones)
        ax.set_title(f"{title} ({unit})")
        ax.set_ylim(0, max(env_v) * 1.25)
    ax1.legend(loc="upper left", fontsize=7.5, frameon=False)
    fig.suptitle(f"Figure [T5]: realise(ν) ⊑ Ceil for every verdict zone, including forced Normal "
                 f"(Ceil = {d['ceil']['max_speed']} mm/s, {d['ceil']['max_acceleration']} mm/s²)", fontsize=10)
    _caption(ax1, ["artifacts/phase5_figure_t5.json"], "T5(a): Ceil is not a function of ν -- see docs/ENFORCEMENT-v1.md §6")
    _save(fig, "fig_t5_envelope")


# ============================================================================
# 2. Floor-dominance table
# ============================================================================

def table_floor_dominance():
    rows = _load("phase2_floor_dominance.json")
    csv_path = FIGURES_DIR / "table_floor_dominance.csv"
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["dimension", "class", "level", "floor"])
        w.writeheader()
        w.writerows(rows)

    dims = sorted(set(r["dimension"] for r in rows), key=lambda d: [r["dimension"] for r in rows].index(d))
    levels = ["LOW", "MED", "HIGH"]
    cell_text, cell_colors = [], []
    for dim in dims:
        row_cells, row_colors = [], []
        cls = next(r["class"] for r in rows if r["dimension"] == dim)
        for lvl in levels:
            floor = next(r["floor"] for r in rows if r["dimension"] == dim and r["level"] == lvl)
            row_cells.append(floor)
            row_colors.append(ORDINAL_VERDICT_COLOR[floor])
        cell_text.append([f"{dim} ({cls})"] + row_cells)
        cell_colors.append(["#ffffff"] + row_colors)
    fig, ax, tbl = _table_figure(cell_text, cell_colors, ["Dimension (class)"] + [f"crit_d({l})" for l in levels],
                                  "Floor-dominance table: π(e) ⊑ crit_d(effective_d[x]) ∀x (T2)",
                                  col_widths=[0.32, 0.22, 0.22, 0.22])
    for (r, c), cell in tbl.get_celld().items():
        if r > 0 and c > 0:
            cell.get_text().set_color("white")
    _caption(ax, ["artifacts/phase2_floor_dominance.json"], "Machine-checked implementation conformance, not independent empirical validation (CLAUDE.md §12)")
    _save(fig, "table_floor_dominance")


# ============================================================================
# 3. CTPR propagation table (summary counts, 18/18)
# ============================================================================

def table_ctpr():
    rows = _load("phase2_ctpr_table.json")
    csv_path = FIGURES_DIR / "table_ctpr_propagation.csv"
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["edge", "fsi_level", "child_level", "effective_child", "matches_expected"])
        w.writeheader()
        w.writerows(rows)

    n_match = sum(1 for r in rows if r["matches_expected"])
    edges = sorted(set(r["edge"] for r in rows))
    fig, ax = plt.subplots(figsize=(5, 3))
    counts = [sum(1 for r in rows if r["edge"] == e and r["matches_expected"]) for e in edges]
    totals = [sum(1 for r in rows if r["edge"] == e) for e in edges]
    bars = ax.bar(edges, counts, color=GOOD)
    for i, (c, t) in enumerate(zip(counts, totals)):
        ax.text(i, c + 0.2, f"{c}/{t}", ha="center", fontsize=9)
    ax.set_ylim(0, max(totals) * 1.3)
    ax.set_ylabel("cases matching expected meet(child, g(FSI))")
    ax.set_title(f"CTPR propagation: {n_match}/{len(rows)} cases correct")
    _caption(ax, ["artifacts/phase2_ctpr_table.json"], "Machine-checked implementation conformance (CLAUDE.md §12)")
    _save(fig, "fig_ctpr_propagation")


# ============================================================================
# 4. T4 failure-mode table
# ============================================================================

def table_t4_failure_modes():
    rows = _load("phase3_t4_failure_modes.json")
    csv_path = FIGURES_DIR / "table_t4_failure_modes.csv"
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["case", "description", "failed_step", "reason", "resulting_verdict", "signal_dimension_level"])
        w.writeheader()
        w.writerows(rows)

    cell_text = [[r["case"], r["failed_step"] or "(none)", r["resulting_verdict"]] for r in rows]
    cell_colors = [["#ffffff", "#ffffff", ORDINAL_VERDICT_COLOR[r["resulting_verdict"]]] for r in rows]
    fig, ax, tbl = _table_figure(cell_text, cell_colors, ["Case", "Failed admission step", "Resulting verdict"],
                                  "T4 admission failure modes: any failure ⇒ that dimension LOW, never \"record absent\"",
                                  col_widths=[0.42, 0.32, 0.26])
    for (r, c), cell in tbl.get_celld().items():
        if r > 0 and c == 2:
            cell.get_text().set_color("white")
    _caption(ax, ["artifacts/phase3_t4_failure_modes.json"])
    _save(fig, "table_t4_failure_modes")


# ============================================================================
# 5. Per-claim ROC curves, stable/tail_floor labelled
# ============================================================================

def fig_roc_curves():
    d = _load("phase9_measured_roc_report.json")
    claims = d["claims"]
    fig, axes = plt.subplots(2, 3, figsize=(13, 8))
    axes = axes.flatten()
    for ax, (claim, v) in zip(axes, claims.items()):
        pts = sorted(v["roc_points"], key=lambda p: p["threshold"])
        fpr = [p["fpr_ppb"] / 1e9 for p in pts]
        tpr = [p["tpr_ppb"] / 1e9 for p in pts]
        ax.plot(fpr, tpr, color=BLUE, lw=2)
        ax.plot([0, 1], [0, 1], color=NEUTRAL_GRAY, lw=1, ls=":")
        for budget in ("0.1%", "1%", "5%"):
            b = v["budgets"][budget]
            status = b["resolution_status"]
            marker = "o" if status == "stable" else ("^" if status == "tail_floor" else "s")
            t1 = next((p for p in pts if p["threshold"] == b["theta1"]), None)
            if t1:
                ax.scatter([t1["fpr_ppb"] / 1e9], [t1["tpr_ppb"] / 1e9], color=RESOLUTION_COLOR[status],
                           marker=marker, s=70, zorder=5, edgecolor="white", linewidth=0.8)
        ax.set_xlim(-0.02, 1.02); ax.set_ylim(-0.02, 1.02)
        ax.set_xlabel("FPR"); ax.set_ylabel("TPR")
        cohort = v.get("cohort", "?")
        ax.set_title(f"{claim}\n(cohort: {cohort})", fontsize=9)
    for ax in axes[len(claims):]:
        ax.axis("off")
    legend_elems = [
        plt.Line2D([0], [0], marker="o", color="w", markerfacecolor=GOOD, markersize=9, label="θ1 stable"),
        plt.Line2D([0], [0], marker="^", color="w", markerfacecolor=WARNING, markersize=9, label="θ1 tail_floor"),
    ]
    fig.legend(handles=legend_elems, loc="lower center", ncol=2, frameon=False, fontsize=9, bbox_to_anchor=(0.78, 0.02))
    fig.suptitle("Per-claim measured ROC (Phase 9), θ1 operating point at each swept budget", fontsize=13, y=1.02)
    fig.subplots_adjust(hspace=0.55, wspace=0.35, bottom=0.13, top=0.9)
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    fig.text(0.01, 0.02, f"Source: artifacts/phase9_measured_roc_report.json | Generated: {ts} | "
                          f"calibration_status: provisional (CLAUDE.md §14)", fontsize=6.5, color=TEXT_SECONDARY, ha="left", va="bottom")
    _save(fig, "fig_roc_curves")


# ============================================================================
# 6. (alpha, beta) feasibility region across the three swept budgets
# ============================================================================

def fig_budget_feasibility():
    d = _load("phase9_measured_roc_report.json")
    claims = d["claims"]
    budgets = ["0.1%", "1%", "5%"]
    fig, ax = plt.subplots(figsize=(8, 5.5))
    # Fixed validated categorical order (dataviz skill references/palette.md), first 5 slots --
    # NOT an ad-hoc list: an earlier draft picked two near-identical oranges for two different
    # claims and made them visually indistinguishable where their curves also happened to overlap.
    validated_order = [BLUE, ORANGE, AQUA, "#eda100", "#e87ba4"]  # blue, orange, aqua, yellow, magenta
    colors = {c: validated_order[i % len(validated_order)] for i, c in enumerate(claims)}
    overlap_groups = {}
    for claim, v in claims.items():
        alphas = [v["budgets"][b]["alpha"] for b in budgets]
        betas = [v["budgets"][b]["beta"] for b in budgets]
        overlap_groups.setdefault(tuple(zip(alphas, betas)), []).append(claim)
        ax.plot(alphas, betas, "o-", color=colors[claim], label=claim.replace(".provisional_v0", ""),
                markersize=8, alpha=0.85, linewidth=2)
    # Where multiple claims land on IDENTICAL (alpha, beta) at every budget (same flat
    # apportionment + same degenerate ROC), the curves are drawn exactly on top of each
    # other -- annotate this explicitly rather than leaving overlapping series to look like
    # only one series exists.
    for coords, members in overlap_groups.items():
        if len(members) > 1:
            a0, b0 = coords[-1]
            ax.annotate(" = ".join(m.replace(".provisional_v0", "") for m in members),
                        (a0, b0), fontsize=7.5, color=TEXT_SECONDARY, textcoords="offset points", xytext=(6, -10))
    for claim, v in claims.items():
        for b in budgets:
            a, be = v["budgets"][b]["alpha"], v["budgets"][b]["beta"]
            ax.annotate(b, (a, be), fontsize=6.5, color=TEXT_SECONDARY, textcoords="offset points", xytext=(4, 6))
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlabel("α (per-claim, apportioned from session-availability budget)")
    ax.set_ylabel("β (per-dimension, consequence-exposure-derived)")
    ax.set_title("Swept feasible region across the three illustrative budgets {0.1%, 1%, 5%}\n(not a point value -- CLAUDE.md §28)")
    ax.legend(fontsize=8, frameon=False, loc="upper left")
    fig.subplots_adjust(bottom=0.22)
    _caption(ax, ["artifacts/phase9_measured_roc_report.json"], "Illustrative research parameters, no clinical stakeholder (CLAUDE.md §28)")
    _save(fig, "fig_budget_feasibility_region")


# ============================================================================
# 7. Per-stage latency, FSI budget violation shown honestly
# ============================================================================

def fig_latency():
    d = _load("phase10_latency_evaluation_report.json")
    arch = d["architecture_per_stage"]
    fsi = d["fsi_per_stage"]

    stage_order = [s for s in arch.keys() if s not in ("end_to_end_total",)]
    p99 = [arch[s]["p99_ms"] for s in stage_order]
    fsi_stage_order = list(fsi.keys())
    fsi_p99 = [fsi[s]["p99_ms"] for s in fsi_stage_order]
    all_stages = stage_order + fsi_stage_order
    all_p99 = p99 + fsi_p99

    fig, ax = plt.subplots(figsize=(9.5, 6))
    y = range(len(all_stages))
    bar_colors = [CRITICAL if s in fsi_stage_order else (WARNING if "kernel" in s else BLUE) for s in all_stages]
    ax.barh(list(y), all_p99, color=bar_colors)
    ax.set_yticks(list(y)); ax.set_yticklabels(all_stages, fontsize=8)
    ax.set_xlabel("p99 latency (ms)")
    ax.invert_yaxis()

    # Authoritative FSI-inclusive totals: read directly from the already-computed,
    # already-reported budget_verification.fsi_inclusion_correction (Phase 10) --
    # NEVER recompute by summing architecture_per_stage, which also contains
    # non-decision-path baseline BCI stages (artifact_detection, feature_extraction,
    # ...) and would silently inflate the total past the real, precise figure.
    fsi_corr = d["budget_verification"]["fsi_inclusion_correction"]
    incl_fsi_decision_path = fsi_corr["decision_path_le_67ms_INCLUDING_FSI"]["measured_p99_ms"]
    incl_fsi_admission = fsi_corr["evidence_generation_and_signing_le_delta_60ms_INCLUDING_FSI"]["measured_p99_ms"]

    xmax = incl_fsi_decision_path * 1.2
    ax.set_xlim(0, xmax)
    ax.axvline(60, color=WARNING, lw=1.5, ls="--")
    ax.axvline(67, color=WARNING, lw=1.5, ls=":")
    ax.axvline(incl_fsi_decision_path, color=CRITICAL, lw=2, ls="--")
    ax.text(incl_fsi_decision_path + xmax * 0.01, len(all_stages) - 2.5,
            f"decision path incl. FSI\n= {incl_fsi_decision_path:.1f}ms\nVIOLATES both budgets\n(admission incl. FSI = {incl_fsi_admission:.1f}ms)",
            fontsize=8, color=CRITICAL, ha="left", va="top", fontweight="bold")

    legend_elems = [
        Patch(facecolor=BLUE, label="4-producer path (excl. FSI)"),
        Patch(facecolor=WARNING, label="kernel_decision"),
        Patch(facecolor=CRITICAL, label="FSI (real swtpm quote, measured separately, N=30)"),
        plt.Line2D([0], [0], color=WARNING, lw=1.5, ls="--", label="Δ(w)=60ms admission deadline (excl. FSI)"),
        plt.Line2D([0], [0], color=WARNING, lw=1.5, ls=":", label="67ms decision-path budget (excl. FSI)"),
    ]
    ax.legend(handles=legend_elems, fontsize=7, frameon=True, facecolor=SURFACE, edgecolor="none", loc="center right")
    ax.set_title("Per-stage p99 latency, FSI included honestly: real cost exceeds both frozen budgets\n"
                 "(see docs/PHASE10-LATENCY-EVALUATION.md §4 -- not a security issue, see docs/THREAT-MODEL.md §4)", fontsize=10)
    fig.subplots_adjust(left=0.28, top=0.85, bottom=0.1)
    _caption(ax, ["artifacts/phase10_latency_evaluation_report.json"])
    _save(fig, "fig_latency_per_stage")


# ============================================================================
# 8. Evidence-coverage matrix (Phase 11)
# ============================================================================

def fig_evidence_coverage():
    d = _load("phase11_attack_framework_report.json")
    rows = d["evidence_coverage_matrix"]
    cell_text, cell_colors = [], []
    for r in rows:
        detected = "YES" if r["detected"] else "NO (no-detector)"
        prevented = "YES" if r["prevented"] else "NO"
        bounded = "YES" if r["consequence_bounded"] else "NO"
        cell_text.append([r["attack"].replace("_", " "), detected, prevented, bounded])
        cell_colors.append(["#ffffff", GOOD if r["detected"] else WARNING,
                             GOOD if r["prevented"] else "#ffffff", GOOD if r["consequence_bounded"] else CRITICAL])
    n_detected = sum(1 for r in rows if r["detected"])
    fig, ax, tbl = _table_figure(
        cell_text, cell_colors, ["Attack", "Detected", "Prevented", "Consequence-bounded (T5)"],
        f"Evidence-coverage matrix: {n_detected}/{len(rows)} detected, {len(rows)}/{len(rows)} consequence-bounded regardless (T5)",
        col_widths=[0.46, 0.19, 0.16, 0.24],
    )
    for (r, c), cell in tbl.get_celld().items():
        if r > 0 and c in (1, 2, 3):
            cell.get_text().set_color("white")
    _caption(ax, ["artifacts/phase11_attack_framework_report.json"], "Under Position A, only the T5 column is unconditional -- docs/THREAT-MODEL.md §3")
    _save(fig, "fig_evidence_coverage_matrix")

    csv_path = FIGURES_DIR / "table_evidence_coverage.csv"
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["attack", "detected", "detection_mechanism", "prevented", "consequence_bounded", "residual"])
        w.writeheader()
        w.writerows(rows)


# ============================================================================
# 9. Attack-propagation summary (Phase 11 reasoning-correctness rows)
# ============================================================================

def fig_attack_propagation():
    d = _load("phase11_attack_framework_report.json")
    results = d["attack_results"]
    names, verdicts = [], []
    for r in results:
        rc = r["reasoning_correctness"]
        v = None
        for key in ("controlled_six_dim_verdict", "next_window_controlled_verdict"):
            if key in rc:
                v = rc[key]["verdict"]
        if v is None and "verdict_level" in rc:
            v = rc["verdict_level"]
        names.append(r["attack"])
        verdicts.append(v)

    fig, ax = plt.subplots(figsize=(9, 4))
    plotted = [(n, v) for n, v in zip(names, verdicts) if v is not None]
    y = range(len(plotted))
    colors = [ORDINAL_VERDICT_COLOR.get(v, NEUTRAL_GRAY) for _, v in plotted]
    ax.barh(list(y), [1] * len(plotted), color=colors)
    ax.set_yticks(list(y)); ax.set_yticklabels([n for n, _ in plotted], fontsize=8)
    ax.set_xticks([])
    ax.invert_yaxis()
    for i, (_, v) in enumerate(plotted):
        ax.text(0.5, i, v, ha="center", va="center", color="white", fontsize=9, fontweight="bold")
    ax.set_title("Attack propagation: resulting verdict under the real, unmodified band→reduce→CTPR→π path\n"
                 "(controlled: other 5 dimensions held at the Phase 3/5/8 healthy fixture, per attack's own isolation design)", fontsize=9)
    _caption(ax, ["artifacts/phase11_attack_framework_report.json"])
    _save(fig, "fig_attack_propagation")


def main():
    print("Generating figures/tables from already-measured artifacts (no new measurement)...")
    fig_t5()
    table_floor_dominance()
    table_ctpr()
    table_t4_failure_modes()
    fig_roc_curves()
    fig_budget_feasibility()
    fig_latency()
    fig_evidence_coverage()
    fig_attack_propagation()
    print(f"\nAll figures/tables written to {FIGURES_DIR}")


if __name__ == "__main__":
    main()
