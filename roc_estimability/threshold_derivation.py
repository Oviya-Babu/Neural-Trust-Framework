"""Phase 9 measured-ROC threshold derivation (CLAUDE.md 14 Phase 9, 20's
SBA methodology and Tail-Floor Rule).

This is NOT roc_estimability/stability.py. That module answers a single
prerequisite question (is the held-out {4-9} cohort sufficient?) under a
strict ephemerality contract: no threshold or operating-point location may
ever be returned by any of its public functions. This module is Phase 9
itself -- its whole purpose is to derive and persist real theta1/theta2/
band_cap values into config/eis.v1-measured.json. The two modules are
deliberately kept separate rather than relaxing stability.py's contract in
place, so that the diagnostic's already-reviewed ephemerality guarantee
stays intact and inspectable on its own.

Reuses, never reimplements:
  - trust_kernel.bands.derive_thresholds()/validate_roc_points() for the
    theta1/theta2/band_cap formula itself (CLAUDE.md 4: "same formula, no
    special case", regardless of whether the ROC is the Phase 2 placeholder
    or a real measured curve).
  - roc_estimability.stability's public functions (class_separates,
    bootstrap_band_widths, leave_one_subject_out_swing,
    cohort_stability_gap, claim_sufficiency_verdict) directly, for
    evaluating the Tail-Floor Rule at theta1 (the low-FPR end) -- these
    functions return only widths/swings/counts, never a threshold
    location, so reusing them here does not require touching that module's
    ephemerality-locked internals.

Adds, new in this module:
  - build_roc_points(): a real, empirical step-function ROC curve from
    honest/attack raw_measurement samples (no parametric tail model fitted,
    per CLAUDE.md 20's Tail-Floor Rule justification (a)).
  - Symmetric HIGH-tail counterparts of stability.py's low-tail bootstrap/
    LOSO functions, for evaluating the Tail-Floor Rule at theta2 (the
    high-TPR/1-beta end) -- CLAUDE.md 20: "The rule applies identically to
    theta1 (low-FPR end) and theta2 (high-TPR/1-beta end)". stability.py's
    _low_tail_threshold is deliberately one-sided (built only for the
    diagnostic's low-FPR question); rather than touch that ephemerality-
    locked file, the high-tail mirror lives here, in the module that
    actually needs it and is not under that contract.
"""

import random

from roc_estimability import stability as low_tail_stability
from trust_kernel.bands import PPB_SCALE, TrustLevel, derive_thresholds, validate_roc_points


def build_roc_points(honest, attack, *, polarity: int = 1, scale: int = PPB_SCALE):
    """Real, empirical ROC curve from honest/attack raw_measurement
    samples. Same 'flag as attack if polarity*raw_measurement < threshold'
    convention as trust_kernel.bands.band()/score() (CLAUDE.md 4: lower
    score is uniformly more attack-like once oriented by polarity).
    Candidate thresholds are every distinct oriented score actually
    observed in honest+attack, plus one sentinel strictly below the
    minimum -- a step function over only what was measured, never smoothed
    or interpolated (CLAUDE.md 20's Tail-Floor Rule: "no parametric tail
    model is fitted").
    """
    if not honest or not attack:
        raise ValueError("build_roc_points requires at least one honest and one attack sample")
    oriented_all = sorted(set([polarity * v for v in honest] + [polarity * v for v in attack]))
    n_honest, n_attack = len(honest), len(attack)

    thresholds = [oriented_all[0] - 1] + oriented_all
    points = []
    for t in thresholds:
        fpr = sum(1 for v in honest if polarity * v < t) / n_honest
        tpr = sum(1 for v in attack if polarity * v < t) / n_attack
        points.append({"threshold": t, "fpr_ppb": round(fpr * scale), "tpr_ppb": round(tpr * scale)})
    return points


# --------------------------------------------------------------------------
# High-tail (theta2 / high-TPR end) mirror of stability.py's low-tail
# machinery. Not ephemeral here (Phase 9 persists real thetas elsewhere via
# build_roc_points + derive_thresholds) -- but these specific functions
# still only ever return widths/swings/counts, the same discipline
# stability.py uses, because that is what the Tail-Floor Rule's criteria
# are actually defined over.
# --------------------------------------------------------------------------

def _high_tail_threshold(attack, polarity: int = 1):
    """Mirror of stability.py's _low_tail_threshold for the high-TPR/
    1-beta end: pinned at the single most extreme (least attack-like)
    attack score, so TPR(theta) = (N-1)/N is the largest value strictly
    below 1 this sample size can resolve -- the closest empirically
    locatable proxy for 'TPR >= 1-beta' when beta is far below 1/N
    (CLAUDE.md 20's measured-resolution note), same role
    _low_tail_threshold plays for FPR <= alpha."""
    if len(attack) < 2:
        return None
    scored = sorted(polarity * v for v in attack)
    return scored[-1]


def _fpr_tpr_at(threshold, honest, attack, polarity: int = 1):
    if threshold is None or not honest or not attack:
        return None, None
    fpr = sum(1 for v in honest if polarity * v < threshold) / len(honest)
    tpr = sum(1 for v in attack if polarity * v < threshold) / len(attack)
    return fpr, tpr


def _band_width(samples):
    if len(samples) < 2:
        return None
    s = sorted(samples)
    n = len(s)
    lo = s[int(0.025 * n)]
    hi = s[min(int(0.975 * n), n - 1)]
    return hi - lo


def bootstrap_band_widths_high_tail(subject_ids, subjects_honest: dict, subjects_attack: dict, *,
                                     polarity: int = 1, n_boot: int = 1000, seed: int = 0) -> dict:
    """High-tail mirror of stability.bootstrap_band_widths: subject-level
    bootstrap, threshold located via _high_tail_threshold (on the pooled
    ATTACK samples, not honest) each resample, discarded immediately.
    Returns only FPR/TPR band widths."""
    if n_boot < 1000:
        raise ValueError("n_boot must be >= 1000")
    rng = random.Random(seed)
    fpr_samples, tpr_samples = [], []
    for _ in range(n_boot):
        resample = [rng.choice(subject_ids) for _ in subject_ids]
        pooled_honest = [v for sid in resample for v in subjects_honest.get(sid, [])]
        pooled_attack = [v for sid in resample for v in subjects_attack.get(sid, [])]
        theta = _high_tail_threshold(pooled_attack, polarity)
        fpr, tpr = _fpr_tpr_at(theta, pooled_honest, pooled_attack, polarity)
        if fpr is not None:
            fpr_samples.append(fpr)
        if tpr is not None:
            tpr_samples.append(tpr)
    return {
        "n_boot": n_boot,
        "n_resamples_with_data": len(tpr_samples),
        "fpr_band_width": _band_width(fpr_samples),
        "tpr_band_width": _band_width(tpr_samples),
    }


def leave_one_subject_out_swing_high_tail(subject_ids, subjects_honest: dict, subjects_attack: dict, *,
                                           polarity: int = 1) -> dict:
    """High-tail mirror of stability.leave_one_subject_out_swing."""
    full_honest = [v for sid in subject_ids for v in subjects_honest.get(sid, [])]
    full_attack = [v for sid in subject_ids for v in subjects_attack.get(sid, [])]
    theta_full = _high_tail_threshold(full_attack, polarity)
    fpr_full, tpr_full = _fpr_tpr_at(theta_full, full_honest, full_attack, polarity)
    if fpr_full is None:
        return {"max_fpr_swing": None, "max_tpr_swing": None, "n_subjects": len(subject_ids)}

    max_fpr_swing = 0.0
    max_tpr_swing = 0.0
    for dropped in subject_ids:
        remaining = [s for s in subject_ids if s != dropped]
        h = [v for sid in remaining for v in subjects_honest.get(sid, [])]
        a = [v for sid in remaining for v in subjects_attack.get(sid, [])]
        theta = _high_tail_threshold(a, polarity)
        fpr, tpr = _fpr_tpr_at(theta, h, a, polarity)
        if fpr is None:
            continue
        max_fpr_swing = max(max_fpr_swing, abs(fpr - fpr_full))
        max_tpr_swing = max(max_tpr_swing, abs(tpr - tpr_full))
    return {"max_fpr_swing": max_fpr_swing, "max_tpr_swing": max_tpr_swing, "n_subjects": len(subject_ids)}


# --------------------------------------------------------------------------
# Tail-Floor Rule evaluation (CLAUDE.md 20, verbatim criteria) and the
# combined per-(claim, budget) operating-point derivation.
# --------------------------------------------------------------------------

def evaluate_tail_floor_rule(*, cohort_subjects, subjects_honest, subjects_attack,
                              full_pool_subjects, min_subjects_separating,
                              n_boot: int = 1000, seed: int = 0) -> dict:
    """Evaluates CLAUDE.md 20's three fixed bars independently for theta1
    (low-FPR end) and theta2 (high-TPR end), on the cohort actually used to
    derive that claim's threshold: fewer than min_subjects_separating of
    the cohort separating both classes, OR bootstrap band-width ratio > 2x
    vs. the full-pool reference, OR LOSO swing > 0.15. When the cohort
    being evaluated IS the full pool, the gap ratio is the trivial 1.0
    self-comparison (stability.claim_sufficiency_verdict's own documented
    convention -- there is no larger reference to degrade against).
    """
    is_full_pool = set(cohort_subjects) == set(full_pool_subjects)

    n_separating = sum(
        1 for s in cohort_subjects
        if low_tail_stability.class_separates(subjects_honest.get(s, []), subjects_attack.get(s, []))
    )

    low_cohort_widths = low_tail_stability.bootstrap_band_widths(
        cohort_subjects, subjects_honest, subjects_attack, n_boot=n_boot, seed=seed)
    high_cohort_widths = bootstrap_band_widths_high_tail(
        cohort_subjects, subjects_honest, subjects_attack, n_boot=n_boot, seed=seed)

    if is_full_pool:
        low_gap = {"fpr_band_width_ratio_6_over_9": 1.0, "tpr_band_width_ratio_6_over_9": 1.0}
        high_gap = dict(low_gap)
    else:
        low_full_widths = low_tail_stability.bootstrap_band_widths(
            full_pool_subjects, subjects_honest, subjects_attack, n_boot=n_boot, seed=seed)
        high_full_widths = bootstrap_band_widths_high_tail(
            full_pool_subjects, subjects_honest, subjects_attack, n_boot=n_boot, seed=seed)
        low_gap = low_tail_stability.cohort_stability_gap(low_cohort_widths, low_full_widths)
        high_gap = low_tail_stability.cohort_stability_gap(high_cohort_widths, high_full_widths)

    low_loso = low_tail_stability.leave_one_subject_out_swing(cohort_subjects, subjects_honest, subjects_attack)
    high_loso = leave_one_subject_out_swing_high_tail(cohort_subjects, subjects_honest, subjects_attack)

    low_verdict = low_tail_stability.claim_sufficiency_verdict(
        n_subjects_separating=n_separating, bootstrap_widths=low_cohort_widths,
        loso_swing=low_loso, gap=low_gap, min_subjects_separating=min_subjects_separating)
    high_verdict = low_tail_stability.claim_sufficiency_verdict(
        n_subjects_separating=n_separating, bootstrap_widths=high_cohort_widths,
        loso_swing=high_loso, gap=high_gap, min_subjects_separating=min_subjects_separating)

    return {
        "theta1_resolution_status": "stable" if low_verdict["sufficient_on_held_out"] else "tail_floor",
        "theta1_failed_tests": low_verdict["failed_tests"],
        "theta2_resolution_status": "stable" if high_verdict["sufficient_on_held_out"] else "tail_floor",
        "theta2_failed_tests": high_verdict["failed_tests"],
        "class_support_n_separating": n_separating,
        "class_support_cohort_size": len(cohort_subjects),
        "class_support_floor": min_subjects_separating,
        "theta1_bootstrap_band_widths": low_cohort_widths,
        "theta2_bootstrap_band_widths": high_cohort_widths,
        "theta1_loso_swing": low_loso,
        "theta2_loso_swing": high_loso,
        "theta1_cohort_stability_gap": low_gap,
        "theta2_cohort_stability_gap": high_gap,
    }


def derive_claim_operating_point(*, honest, attack, alpha_ppb: int, beta_ppb: int,
                                  cohort_subjects, subjects_honest, subjects_attack,
                                  full_pool_subjects, min_subjects_separating,
                                  n_boot: int = 1000, seed: int = 0, polarity: int = 1) -> dict:
    """The full Phase 9 per-(claim, budget) derivation: real ROC -> real
    theta1/theta2/band_cap (trust_kernel.bands.derive_thresholds, never
    reimplemented) -> Tail-Floor Rule evaluation at both ends ->
    resolution_status. `honest`/`attack` are the pooled samples from
    `cohort_subjects` (the cohort actually used to derive this claim's
    threshold, per CLAUDE.md 20's per-claim cohort table); the wider
    `subjects_honest`/`subjects_attack` dicts (keyed by subject id) are
    used only for the Tail-Floor Rule's own stability checks (which need
    per-subject structure), never to change which samples the threshold
    itself is derived from.

    resolution_status folds theta1's and theta2's independent verdicts
    into the single value config/eis.v1-measured.json's per-(claim,budget)
    schema field can hold (trust_kernel/bands.py's
    RESOLUTION_STATUS_VALUES / SWEPT_BUDGET_LABELS predate a two-sided
    representation): 'tail_floor' if EITHER end triggers, 'stable' only if
    both do not -- the conservative direction, consistent with this
    architecture's fail-closed discipline (CLAUDE.md 10). The per-side
    detail is preserved in tail_floor_detail for the full report/artifact,
    not discarded.
    """
    roc_points = build_roc_points(honest, attack, polarity=polarity, scale=PPB_SCALE)
    validate_roc_points(roc_points, scale=PPB_SCALE, fpr_key="fpr_ppb", tpr_key="tpr_ppb")
    theta1, theta2, band_cap = derive_thresholds(
        roc_points, alpha_ppb, beta_ppb, scale=PPB_SCALE, fpr_key="fpr_ppb", tpr_key="tpr_ppb")

    tail = evaluate_tail_floor_rule(
        cohort_subjects=cohort_subjects, subjects_honest=subjects_honest, subjects_attack=subjects_attack,
        full_pool_subjects=full_pool_subjects, min_subjects_separating=min_subjects_separating,
        n_boot=n_boot, seed=seed)

    theta2_applicable = band_cap == TrustLevel.HIGH
    resolution_status = "tail_floor" if (
        tail["theta1_resolution_status"] == "tail_floor"
        or (theta2_applicable and tail["theta2_resolution_status"] == "tail_floor")
    ) else "stable"

    return {
        "n_roc_points": len(roc_points),
        "roc_points": roc_points,
        "theta1": theta1,
        "theta2": theta2,
        "theta2_applicable": theta2_applicable,
        "band_cap": band_cap.name,
        "resolution_status": resolution_status,
        "tail_floor_detail": tail,
    }
