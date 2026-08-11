"""Asymmetric slew limiting on the realised envelope (CLAUDE.md §6, §7).
Tightening (a component decreasing) applies immediately and unlimited.
Loosening (a component increasing) is rate-limited to <=200 mm/s and
<=100 mm/s^2 per window. Safe(0,0) -> full realised Normal envelope
(1000 mm/s, 500 mm/s^2 after Ceil clamping) in exactly 5 windows = 500 ms
at these step sizes, matching the reference numbers in §7.

Strengthens T5 (§6: 'Strengthens T5: realised ⊆ Env(π), so the bound holds
a fortiori'): the command this module emits is always componentwise <= the
target envelope passed to step() for that same window, by construction of
_step_component's min() -- so cmd ⊑ realise(ν) at every instant regardless
of how ν oscillates.
"""

MAX_SPEED_STEP_MM_S = 200          # per-window loosening limit
MAX_ACCEL_STEP_MM_S2 = 100         # per-window loosening limit
WINDOWS_SAFE_TO_FULL = 5           # documented reference figure, not enforced by code


def _step_component(current: int, target: int, max_increase: int) -> int:
    """A single min() formula implements both halves of the asymmetric rule
    (§6): when target <= current (tightening), current + max_increase is
    always >= current >= target, so min() already selects target with no
    special case -- tightening is 'immediate and unlimited' as a
    consequence of the formula, not a separate branch. Loosening
    (target > current) is rate-limited by the same min()."""
    return min(target, current + max_increase)


class SlewState:
    """Holds the currently-commanded envelope across windows. Starts at
    (0, 0) -- a cold start is a loosening from Safe, not a discontinuity."""

    def __init__(self, initial: dict = None):
        self.current = dict(initial) if initial else {"max_speed": 0, "max_acceleration": 0}

    def step(self, target: dict) -> dict:
        """Advances one window toward `target` (the realised envelope for
        that window) and returns the newly-commanded envelope. Guaranteed
        cmd["max_speed"] <= target["max_speed"] and
        cmd["max_acceleration"] <= target["max_acceleration"]."""
        self.current = {
            "max_speed": _step_component(self.current["max_speed"], target["max_speed"], MAX_SPEED_STEP_MM_S),
            "max_acceleration": _step_component(
                self.current["max_acceleration"], target["max_acceleration"], MAX_ACCEL_STEP_MM_S2
            ),
        }
        return dict(self.current)
