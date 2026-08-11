"""Pure stability statistics for the ROC-estimability diagnostic
(prerequisite to Phase 9's cohort decision; CLAUDE.md not modified by this
work; no real ROC threshold is derived or read off here -- see
experiments/roc_estimability_diagnostic.py's module docstring for the
full gate). Zero heavy dependencies (stdlib only), following the same
pattern as event_model/ and sba_validation/ -- pure functions over plain
lists, testable and mutation-testable without real EEG data.

EPHEMERALITY CONTRACT (load-bearing, not a style choice): a threshold on a
claim's raw_measurement scale is exactly the kind of value this diagnostic
must never persist, cache, serialize, or display (Phase-9-flavored
information, gated by the calling task). Every function here that must
locate such a threshold internally does so in a private helper (leading
underscore: _low_tail_threshold, _fpr_tpr_at) whose return value is NEVER
propagated by any PUBLIC function's return value. Public functions return
only: boolean/count class-support results, band WIDTHS (dispersion, not
location), swing MAGNITUDES (deltas, not the pre/post values themselves),
and GAP ratios between cohorts. No public function in this module can be
used to recover a raw_measurement threshold or an absolute FPR/TPR value
at a specific operating point -- by construction, not by caller discipline
alone: there is no code path from a private helper's return value to a
public function's return value other than through a width/delta/ratio
computation that discards the location.
"""

import math
import random
import statistics

CLASS_SUPPORT_MIN_SUBJECTS = 4  # of 6 held-out subjects (task's own sufficiency threshold)
MAX_BAND_WIDTH_RATIO = 2.0      # pre-committed before running on real data: held-out(6) band
                                 # width must not exceed 2x the full(9) band width
MAX_LOSO_SWING = 0.15           # pre-committed: no single held-out subject may swing the
                                 # low-tail FPR/TPR estimate by more than 0.15 (absolute)


def class_presence(honest, attack) -> bool:
    """Both classes have at least one real sample. Trivially true whenever
    the discriminating/attack condition is simulated per subject rather
    than organically observed (this project has no live deployment log to
    draw genuine attack incidence from) -- kept separate from
    class_separates(), which is the substantive per-subject check."""
    return len(honest) > 0 and len(attack) > 0


def class_separates(honest, attack, polarity: int = 1) -> bool:
    """The substantive 'exhibits both classes' check for a simulated
    discriminating condition: the attack-class median must fall on the
    more-attack-like side of the honest-class median. Mechanical, not a
    significance test -- consistent with this project's other
    pre-committed, non-tuned decision rules (the event-model
    investigation's falsification criterion)."""
    if not class_presence(honest, attack):
        return False
    h = statistics.median(honest)
    a = statistics.median(attack)
    return (polarity * a) < (polarity * h)


def _low_tail_threshold(honest, polarity: int = 1):
    """EPHEMERAL, PRIVATE. The smallest achievable nonzero-FPR threshold on
    the empirical honest-sample distribution: theta pinned just above the
    single most extreme (most attack-like) honest score, so FPR(theta) is
    the smallest nonzero rate this sample size can resolve (~1/N). Stands
    in for 'the operating region the swept session-availability budgets
    imply': at real per-subject trial counts, the literal budget-derived
    alpha (~1e-7..1e-9, docs/EVENT-MODEL-INVESTIGATION.md) is below 1/N
    for any cohort size reachable by this study, so the closest
    empirically-locatable proxy for that region is the smallest resolvable
    nonzero FPR. MUST NOT be returned by any public function in this
    module -- callers use it only to compute FPR/TPR at this point and
    discard it in the same expression.
    """
    if len(honest) < 2:
        return None
    scored = sorted(polarity * v for v in honest)
    return scored[1]  # strictly above the single minimum score


def _fpr_tpr_at(threshold, honest, attack, polarity: int = 1):
    """EPHEMERAL, PRIVATE. FPR/TPR of the 'flag as attack if
    polarity*raw_measurement < threshold' rule at one specific threshold.
    MUST NOT be returned by any public function in this module."""
    if threshold is None or not honest or not attack:
        return None, None
    fpr = sum(1 for v in honest if polarity * v < threshold) / len(honest)
    tpr = sum(1 for v in attack if polarity * v < threshold) / len(attack)
    return fpr, tpr


def _band_width(samples):
    """2.5th-to-97.5th-percentile width of a distribution of FPR or TPR
    values -- a dispersion statistic. Returns None (not a fabricated 0)
    when fewer than 2 samples are available to form a band at all."""
    if len(samples) < 2:
        return None
    s = sorted(samples)
    n = len(s)
    lo = s[int(0.025 * n)]
    hi = s[min(int(0.975 * n), n - 1)]
    return hi - lo


def bootstrap_band_widths(subject_ids, subjects_honest: dict, subjects_attack: dict, *,
                           polarity: int = 1, n_boot: int = 1000, seed: int = 0) -> dict:
    """Subject-level bootstrap (resample subject_ids WITH REPLACEMENT,
    n_boot >= 1000 by default): at each resample, pool the resampled
    subjects' honest and attack samples, locate the ephemeral low-tail
    threshold on the pooled honest samples, evaluate FPR/TPR there, and
    discard the threshold immediately (it is a local variable in this
    function's loop body and is never returned). Returns ONLY the width of
    the resulting bootstrap distributions for FPR and TPR -- never their
    center, mean, or any single resample's value.
    """
    if n_boot < 1000:
        raise ValueError("n_boot must be >= 1000 per the diagnostic's own requirement")
    rng = random.Random(seed)
    fpr_samples = []
    tpr_samples = []
    for _ in range(n_boot):
        resample = [rng.choice(subject_ids) for _ in subject_ids]
        pooled_honest = [v for sid in resample for v in subjects_honest.get(sid, [])]
        pooled_attack = [v for sid in resample for v in subjects_attack.get(sid, [])]
        theta = _low_tail_threshold(pooled_honest, polarity)  # ephemeral: local only
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


def leave_one_subject_out_swing(subject_ids, subjects_honest: dict, subjects_attack: dict, *,
                                 polarity: int = 1) -> dict:
    """A full-cohort reference FPR/TPR at the ephemeral low-tail threshold
    is computed once as a LOCAL variable, then each subject is dropped in
    turn and the same metric recomputed; returns only the MAXIMUM absolute
    swing (delta) across all leave-one-out variants for FPR and TPR --
    never the reference value or any individual leave-one-out value.
    """
    full_honest = [v for sid in subject_ids for v in subjects_honest.get(sid, [])]
    full_attack = [v for sid in subject_ids for v in subjects_attack.get(sid, [])]
    theta_full = _low_tail_threshold(full_honest, polarity)
    fpr_full, tpr_full = _fpr_tpr_at(theta_full, full_honest, full_attack, polarity)
    if fpr_full is None:
        return {"max_fpr_swing": None, "max_tpr_swing": None, "n_subjects": len(subject_ids)}

    max_fpr_swing = 0.0
    max_tpr_swing = 0.0
    for dropped in subject_ids:
        remaining = [s for s in subject_ids if s != dropped]
        h = [v for sid in remaining for v in subjects_honest.get(sid, [])]
        a = [v for sid in remaining for v in subjects_attack.get(sid, [])]
        theta = _low_tail_threshold(h, polarity)
        fpr, tpr = _fpr_tpr_at(theta, h, a, polarity)
        if fpr is None:
            continue
        max_fpr_swing = max(max_fpr_swing, abs(fpr - fpr_full))
        max_tpr_swing = max(max_tpr_swing, abs(tpr - tpr_full))
    return {"max_fpr_swing": max_fpr_swing, "max_tpr_swing": max_tpr_swing, "n_subjects": len(subject_ids)}


def _ratio(a, b):
    if a is None or b is None:
        return None
    if b == 0:
        return None if a == 0 else math.inf
    return a / b


def cohort_stability_gap(held_out_widths: dict, full_widths: dict) -> dict:
    """Ratio of held-out(6) band width to full(9) band width, per metric --
    reports the GAP in stability between cohorts, not either cohort's
    absolute band location (there is none to report; widths are already
    dispersion, not location)."""
    return {
        "fpr_band_width_ratio_6_over_9": _ratio(
            held_out_widths.get("fpr_band_width"), full_widths.get("fpr_band_width")),
        "tpr_band_width_ratio_6_over_9": _ratio(
            held_out_widths.get("tpr_band_width"), full_widths.get("tpr_band_width")),
    }


def claim_sufficiency_verdict(*, n_subjects_separating: int, bootstrap_widths: dict,
                               loso_swing: dict, gap: dict,
                               min_subjects_separating: int = CLASS_SUPPORT_MIN_SUBJECTS) -> dict:
    """Applies the pre-committed sufficiency criteria (module-level
    constants above, fixed before any real data was analysed) to one
    claim's results on a given cohort. A claim is sufficient on that
    cohort iff ALL of: (1) at least min_subjects_separating of the
    cohort's subjects show genuine class separation (default
    CLASS_SUPPORT_MIN_SUBJECTS = 4, the held-out(6) bar; pass e.g. 6 for
    the equivalent proportion on a 9-subject pool -- both are 2/3, the
    same bar, not a loosened one); (2) the evaluated cohort's bootstrap
    band is not more than MAX_BAND_WIDTH_RATIO times wider than the
    reference band supplied via `gap` (when the cohort being evaluated
    IS the largest available pool, the caller passes a self-comparison
    gap of 1.0 -- there is no larger reference to degrade against, and
    this is not a loosened check, it is the honest absence of a coarser
    check at the top of the cohort-size hierarchy); (3) no single
    subject's removal swings the low-tail FPR or TPR estimate by more
    than MAX_LOSO_SWING. Returns which specific tests failed, not a bare
    boolean, so the recommendation logic can distinguish 'passes cleanly'
    from 'fails on exactly this evidence'."""
    failed = []
    if n_subjects_separating < min_subjects_separating:
        failed.append("class_support")

    fpr_w = bootstrap_widths.get("fpr_band_width")
    tpr_w = bootstrap_widths.get("tpr_band_width")
    fpr_ratio = gap.get("fpr_band_width_ratio_6_over_9")
    tpr_ratio = gap.get("tpr_band_width_ratio_6_over_9")
    if fpr_w is not None and fpr_w > 0 and fpr_ratio is not None and fpr_ratio > MAX_BAND_WIDTH_RATIO:
        failed.append("bootstrap_band_ratio_fpr")
    if tpr_w is not None and tpr_w > 0 and tpr_ratio is not None and tpr_ratio > MAX_BAND_WIDTH_RATIO:
        failed.append("bootstrap_band_ratio_tpr")

    max_fpr_swing = loso_swing.get("max_fpr_swing")
    max_tpr_swing = loso_swing.get("max_tpr_swing")
    if max_fpr_swing is not None and max_fpr_swing > MAX_LOSO_SWING:
        failed.append("loso_fpr_swing")
    if max_tpr_swing is not None and max_tpr_swing > MAX_LOSO_SWING:
        failed.append("loso_tpr_swing")

    return {"sufficient_on_held_out": len(failed) == 0, "failed_tests": failed}
