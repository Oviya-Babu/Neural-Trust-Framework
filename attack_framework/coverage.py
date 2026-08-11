"""Pure evidence-coverage-matrix builder for Phase 11's Behaviour-Level
Attack Framework (CLAUDE.md §3; docs/THREAT-MODEL.md §5). Zero dependencies
-- testable and mutation-testable without the real pipeline/sensor/kernel
stack that produces the measurements this module classifies.

This module performs no measurement of its own and injects no behaviour. It
takes already-measured attack-result rows (produced by
experiments/phase11_attack_framework.py running real injected behaviour
against the real pipeline, sensors, kernel, and enforcement) and derives the
coverage classification -- detected / prevented / consequence-bounded /
residual -- per attack, per CLAUDE.md §3's rule: never assign trust or a
coverage verdict directly, only classify what real code already measured.
"""


def build_coverage_row(*, attack_name, detected, detection_mechanism,
                        prevented, consequence_bounded, residual_note):
    """Classifies one attack's already-measured results into the
    evidence-coverage-matrix row the Phase 11 gate requires.

    detected/detection_mechanism must agree: a detected attack must name the
    real mechanism that caught it (never left implicit); an undetected
    attack (CLAUDE.md's no-detector class -- e.g. training-pipeline
    poisoning) must not carry a mechanism name, since inventing one would
    misrepresent an uncovered case as covered."""
    if detected and not (isinstance(detection_mechanism, str) and detection_mechanism):
        raise ValueError("detected=True requires a non-empty detection_mechanism string")
    if not detected and detection_mechanism is not None:
        raise ValueError("detected=False requires detection_mechanism=None (no-detector class)")
    if not isinstance(residual_note, str) or not residual_note.strip():
        raise ValueError("residual_note must be a non-empty string -- what remains uncovered must always be stated")
    return {
        "attack": attack_name,
        "detected": bool(detected),
        "detection_mechanism": detection_mechanism,
        "prevented": bool(prevented),
        "consequence_bounded": bool(consequence_bounded),
        "residual": residual_note,
    }


def summarize_coverage(rows: list) -> dict:
    """Aggregate counts over a full coverage matrix -- for the Gate 2 report
    and Phase D's evidence-coverage figure. Every row's consequence_bounded
    is expected True (T5 is unconditional, CLAUDE.md §5) -- this function
    reports the actual count rather than assuming it, so a violation would
    surface here rather than being silently assumed away."""
    if not rows:
        raise ValueError("summarize_coverage requires at least one row")
    n = len(rows)
    detected = sum(1 for r in rows if r["detected"])
    prevented = sum(1 for r in rows if r["prevented"])
    consequence_bounded = sum(1 for r in rows if r["consequence_bounded"])
    return {
        "n_attacks": n,
        "detected_count": detected,
        "prevented_count": prevented,
        "consequence_bounded_count": consequence_bounded,
        "no_detector_count": n - detected,
        "consequence_bounded_fraction": consequence_bounded / n,
    }
