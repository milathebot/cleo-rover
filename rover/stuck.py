"""Pure stuck-detection + escalation ladder.

Consolidates the scattered "I'm not getting anywhere" signals (blocked streak,
stride stalls, no range progress) into one escalation level so behaviors react
consistently: nudge -> search -> reverse -> give up + ask for rescue. Pure for
testing; no encoders/IMU needed (uses range-delta + reflex/blocked tallies).
"""

from __future__ import annotations

LEVEL_ACTIONS = {0: "continue", 1: "nudge", 2: "search", 3: "reverse", 4: "give_up_rescue"}


def stuck_level(*, blocked_streak: int = 0, stall_count: int = 0, no_progress_cycles: int = 0, thresholds: tuple[int, int, int, int] = (2, 4, 6, 8)) -> int:
    """Escalation level 0..4 from the worst of the stuck signals."""
    worst = max(int(blocked_streak), int(stall_count), int(no_progress_cycles))
    level = 0
    for index, threshold in enumerate(thresholds, start=1):
        if worst >= threshold:
            level = index
    return level


def escalation_action(level: int) -> str:
    return LEVEL_ACTIONS.get(max(0, min(4, int(level))), "continue")
