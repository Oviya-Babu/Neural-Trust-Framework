"""Pure statistics for the event-model investigation (prerequisite to
Phase 9; CLAUDE.md not modified by this work). No real-data dependency --
operates on any numeric or boolean sequence; tested against synthetic
sequences with known properties in tests_event_model/. This module makes
NO threshold/ROC decisions of its own -- it measures whatever binary or
real-valued sequence it is given.
"""


def lag_k_autocorrelation(x, k: int) -> float:
    """Pearson autocorrelation of x at lag k (standard ACF formula,
    denominator over the FULL-series variance, not a lag-truncated one):
        sum((x[i]-mean)(x[i+k]-mean)) / sum((x[i]-mean)^2),  i=0..n-k-1
    """
    n = len(x)
    if k <= 0:
        raise ValueError("k must be positive")
    if k >= n:
        raise ValueError("k must be less than len(x)")
    mean = sum(x) / n
    num = sum((x[i] - mean) * (x[i + k] - mean) for i in range(n - k))
    den = sum((v - mean) ** 2 for v in x)
    if den == 0:
        return 0.0
    return num / den


def _one_runs(binary_seq):
    """Maximal runs of truthy values in binary_seq, as (start, end_exclusive)."""
    runs = []
    start = None
    for i, v in enumerate(binary_seq):
        if v and start is None:
            start = i
        elif not v and start is not None:
            runs.append((start, i))
            start = None
    if start is not None:
        runs.append((start, len(binary_seq)))
    return runs


def run_lengths(binary_seq) -> list:
    """Lengths of maximal contiguous runs of 1s (restricted-window runs)."""
    return [end - start for start, end in _one_runs(binary_seq)]


def gap_lengths(binary_seq) -> list:
    """Lengths of maximal contiguous runs of 0s STRICTLY BETWEEN two runs
    of 1s -- i.e. inter-restriction gaps. A leading or trailing all-zero
    stretch is not a 'gap between restrictions' (there is no restriction
    on at least one side), so it is excluded, matching the task's framing
    ('gap lengths between restricted runs')."""
    runs = _one_runs(binary_seq)
    return [start_next - end_prev for (_, end_prev), (start_next, _) in zip(runs, runs[1:])]


def geometric_mean_run_length(alpha: float) -> float:
    """Mean restricted-run length under i.i.d. Bernoulli(alpha) per-window
    draws: a run continues with probability alpha at each step
    (Geometric, support {1,2,...}), mean = 1/(1-alpha)."""
    if not (0 <= alpha < 1):
        raise ValueError("alpha must be in [0, 1)")
    return 1.0 / (1 - alpha)


def geometric_mean_gap_length(alpha: float) -> float:
    """Mean inter-restriction gap length under i.i.d. Bernoulli(alpha):
    a gap ends with probability alpha at each step (Geometric, support
    {1,2,...}), mean = 1/alpha."""
    if not (0 < alpha <= 1):
        raise ValueError("alpha must be in (0, 1]")
    return 1.0 / alpha


def geometric_run_length_pmf(alpha: float, k: int) -> float:
    """P(run length = k) under i.i.d. Bernoulli(alpha): (alpha)^(k-1)*(1-alpha)."""
    if k < 1:
        raise ValueError("k must be >= 1")
    return (alpha ** (k - 1)) * (1 - alpha)


def percentile_debounce_interval(gaps, percentile: float = 5.0) -> int:
    """D = the smallest number of consecutive Normal windows at which the
    fraction of measured inter-restriction gaps STRICTLY SHORTER than D
    first reaches (or exceeds) `percentile`% -- i.e. D lands at the
    `percentile`-th-percentile boundary of the observed gap distribution.

    Read maximally literally, 'the smallest D such that fewer than 5% of
    gaps are shorter than D' is satisfied trivially at D=1 (no gap is
    shorter than 1), which would make the rule vacuous and 'the resulting
    D varies with the data' meaningless. This function instead implements
    the standard, non-trivial percentile-boundary reading -- flagged here
    for PI confirmation (CLAUDE.md 18's pattern for an underspecified
    formula, e.g. CTPR's g=identity), not silently assumed to be obviously
    correct.

    Pre-committed per the task: this function and `percentile` are fixed
    before looking at the data; only the resulting D varies with it.
    """
    if not gaps:
        raise ValueError("no gaps measured -- cannot compute a debounce interval "
                          "(fewer than two restricted runs observed)")
    if not (0 < percentile < 100):
        raise ValueError("percentile must be in (0, 100)")
    sorted_gaps = sorted(gaps)
    n = len(sorted_gaps)
    threshold_fraction = percentile / 100.0
    max_gap = sorted_gaps[-1]
    D = 1
    while D <= max_gap:
        frac_shorter = sum(1 for g in sorted_gaps if g < D) / n
        if frac_shorter >= threshold_fraction:
            return D
        D += 1
    return max_gap + 1


def merge_episodes(binary_seq, debounce_interval: int) -> list:
    """Applies the Step-2 merge rule: two restricted runs separated by
    fewer than `debounce_interval` Normal windows merge into one episode;
    `debounce_interval` or more, they stay separate. Returns episode
    (start, end_exclusive) pairs -- a spurious episode is a maximal run of
    restricted windows under this merge rule."""
    runs = _one_runs(binary_seq)
    if not runs:
        return []
    episodes = [list(runs[0])]
    for start, end in runs[1:]:
        gap = start - episodes[-1][1]
        if gap < debounce_interval:
            episodes[-1][1] = end
        else:
            episodes.append([start, end])
    return [tuple(e) for e in episodes]


def episode_statistics(episodes, n_windows: int) -> dict:
    """Mean episode length and mean gap AFTER the Step-2 merge (used by
    Step 3's N_onsets formula). Mirrors run_lengths/gap_lengths but over
    the merged episode list, plus leading/trailing boundary windows folded
    into the cycle length so mean_episode+mean_gap tiles the session
    (fT / (mean_episode+mean_gap) = N_onsets requires this)."""
    if not episodes:
        return {"n_episodes": 0, "mean_episode_length": None, "mean_gap": None}
    lengths = [end - start for start, end in episodes]
    gaps = [nxt_start - cur_end for (_, cur_end), (nxt_start, _) in zip(episodes, episodes[1:])]
    mean_episode_length = sum(lengths) / len(lengths)
    if gaps:
        mean_gap = sum(gaps) / len(gaps)
    else:
        # A single episode: no internal gap observed -- fall back to the
        # windows outside the episode as the only available gap estimate.
        mean_gap = max(n_windows - sum(lengths), 0) / 1
    return {
        "n_episodes": len(episodes),
        "mean_episode_length": mean_episode_length,
        "mean_gap": mean_gap,
        "episode_lengths": lengths,
        "gaps": gaps,
    }
