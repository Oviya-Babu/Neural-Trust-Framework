"""Per-window vs. episode-based availability equations (event-model
investigation, prerequisite to Phase 9; CLAUDE.md not modified by this
work). Both formulations, side by side, per the task; assumptions stated
explicitly in each function's docstring, not buried in prose elsewhere.
"""

BP_SCALE = 10_000
MIN_REPRESENTABLE_RATE = 1 / BP_SCALE


def per_window_alpha(session_budget: float, f_hz: float = 10.0, session_hours: float = 8.0):
    """alpha = 1 - (1-B)^(1/fT), fT = f_hz * session_hours * 3600.

    Window-independence assumption (stated explicitly, per the task):
    this formula treats each of the fT windows in a session as an
    independent Bernoulli trial. This is a SEPARATE assumption from the
    CTPR-dependence question addressed in Phase 8.5's SBA validation
    (docs/PHASE8.5-SBA-VALIDATION.md) -- this module's caller is
    responsible for reporting whether the event-model investigation's own
    Step 1 measurement (autocorrelation of the restriction indicator)
    supports or falsifies it.

    Returns (alpha, fT).
    """
    if not (0 < session_budget < 1):
        raise ValueError("session_budget must be in (0, 1)")
    if f_hz <= 0 or session_hours <= 0:
        raise ValueError("f_hz and session_hours must be positive")
    fT = f_hz * session_hours * 3600
    alpha = 1 - (1 - session_budget) ** (1 / fT)
    return alpha, fT


def n_onsets_per_session(mean_episode_length_windows: float, mean_gap_windows: float,
                          f_hz: float = 10.0, session_hours: float = 8.0) -> float:
    """N_onsets = fT / (mean episode length + mean gap) -- the expected
    number of spurious-restriction EPISODES (not windows) per session,
    from the empirically measured, Step-2-merged episode/gap statistics.
    Assumes the measured mean episode length and mean gap are
    representative of the FULL session (stationarity across the session),
    not just the measurement window used to estimate them -- a real,
    separate assumption from window-independence, stated here rather than
    left implicit.
    """
    if mean_episode_length_windows <= 0:
        raise ValueError("mean_episode_length_windows must be positive")
    if mean_gap_windows <= 0:
        raise ValueError("mean_gap_windows must be positive")
    fT = f_hz * session_hours * 3600
    cycle_length = mean_episode_length_windows + mean_gap_windows
    return fT / cycle_length


def episode_alpha(session_budget: float, n_onsets: float) -> float:
    """alpha_onset = B / N_onsets -- the per-episode false-alarm
    probability an episode-counted availability budget allocates,
    apportioned flat across the expected number of episodes per session
    (the direct episode-based analogue of per_window_alpha's flat
    per-window split)."""
    if not (0 < session_budget < 1):
        raise ValueError("session_budget must be in (0, 1)")
    if n_onsets <= 0:
        raise ValueError("n_onsets must be positive")
    return session_budget / n_onsets


def alpha_to_basis_points(alpha: float) -> float:
    return alpha * BP_SCALE


def representable_at_current_granularity(alpha: float) -> bool:
    """CLAUDE.md 8: rates are fixed-point basis points (0..10000) -- the
    smallest nonzero representable rate is 1/10000."""
    return alpha * BP_SCALE >= 1.0


def windows_needed_for_representability(target_bp: float = 1.0, session_budget: float = 0.01,
                                         f_hz: float = 10.0, session_hours: float = 8.0) -> float:
    """How large would the mean episode+gap cycle length (in windows) need
    to be for episode_alpha to reach `target_bp` basis points at the given
    session_budget -- i.e. how much 'compression' from window-counting to
    episode-counting would be required. Solved by inverting
    n_onsets_per_session + episode_alpha: alpha_onset = B / (fT / cycle)
    = B * cycle / fT >= target_bp/BP_SCALE  =>  cycle >= target_bp * fT / (BP_SCALE * B).
    """
    if session_budget <= 0:
        raise ValueError("session_budget must be positive")
    fT = f_hz * session_hours * 3600
    return (target_bp / BP_SCALE) * fT / session_budget
