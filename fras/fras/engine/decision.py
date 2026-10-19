"""Terminal decision logic (spec H.2) — shared by the edge agent and server-side identification.

The biometric score is evidence, not a verdict: the border zone between
T_review and T_accept never opens the gate silently; it asks for a retry
and, if a later attempt passes, marks the event `review`.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Decision:
    result: str          # accepted | review | unknown | pad | denied | duplicate | retry
    state: str           # terminal state id TRM-xx
    code: str | None     # terminal error code shown small for technicians
    open_gate: bool
    employee_id: str | None = None


def decide(*, best_score: float | None, best_employee: str | None, second_score: float | None,
           liveness_score: float | None, thresholds: dict, liveness_required: bool, liveness_min: float,
           allowed: bool, duplicate: bool, attempt: int, max_border_retries: int = 2,
           direction: str = "in") -> Decision:
    if liveness_required and (liveness_score is None or liveness_score < liveness_min):
        return Decision("pad", "TRM-09", "T-209", False)
    accept, review = thresholds["accept"], thresholds["review"]
    if best_score is None or best_score < review:
        return Decision("unknown", "TRM-08", "T-208", False)
    # ambiguous: the two best candidates are too close to tell apart
    ambiguous = second_score is not None and best_score - second_score < 0.05
    if best_score < accept or ambiguous:
        if attempt < max_border_retries:
            return Decision("retry", "TRM-11", "T-211", False, best_employee)
        return Decision("review", "TRM-12", "T-211", False, best_employee)
    if not allowed:
        return Decision("denied", "TRM-10", "T-210", False, best_employee)
    if duplicate:
        return Decision("duplicate", "TRM-07", "T-207", True, best_employee)
    result = "review" if attempt > 0 else "accepted"
    return Decision(result, "TRM-05" if direction == "in" else "TRM-06", None, True, best_employee)
