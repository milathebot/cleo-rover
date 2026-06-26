"""Pure top-level behavior arbitration — the 'decide what to do' brain stem.

This is what turns Pip's pile of operator-triggered behaviors into a self-directed
being: every tick a single function scores the situation (mood/energy/curiosity,
mode, battery, goals, people, time-of-day) and picks ONE behavior. It is pure and
side-effect-free; the async arbiter loop in rover/service.py maps the chosen
behavior onto existing safe primitives (little_being_loop, return_to_task,
vision_awareness) — so all motion still flows through grants + the reflex floor,
and the LLM mind/operator can always override.
"""

from __future__ import annotations

# Behaviors, each mapped by the service to an existing safe primitive.
BEHAVIOR_REST = "rest"
BEHAVIOR_RETURN_TO_CHARGER = "return_to_charger"
BEHAVIOR_PURSUE_GOAL = "pursue_goal"
BEHAVIOR_SOCIALIZE = "socialize"
BEHAVIOR_PATROL = "patrol"
BEHAVIOR_OBSERVE = "observe"
BEHAVIOR_HOLD = "hold"
BEHAVIOR_REQUEST_ASSIST = "request_assist"  # at an edge/stairs: hold + ask to be carried


def _hhmm_to_minutes(value: str) -> int | None:
    try:
        hours, minutes = str(value).split(":")
        return int(hours) * 60 + int(minutes)
    except (ValueError, AttributeError):
        return None


def in_quiet_hours(now_minutes: int, quiet: dict) -> bool:
    """True if now (minutes-into-day, 0-1439) is within configured quiet hours.

    Handles the midnight wrap (e.g. 23:30 -> 09:00). Pure for testing.
    """
    if not quiet or not quiet.get("enabled"):
        return False
    start = _hhmm_to_minutes(quiet.get("start", ""))
    end = _hhmm_to_minutes(quiet.get("end", ""))
    if start is None or end is None or start == end:
        return False
    if start < end:
        return start <= now_minutes < end
    return now_minutes >= start or now_minutes < end


def arbitrate(ctx: dict) -> dict:
    """Pick the next behavior from the current situation. Priority order matters.

    ctx keys (all optional, safe defaults): mode, awake, battery_recommendation,
    battery_percent, energy, curiosity, boredom, has_goal, person_present,
    hazards_present, quiet, do_not_disturb, movement_allowed, dock_known,
    return_to_charger_min_battery.
    Returns {behavior, reason}.
    """
    def out(behavior: str, reason: str) -> dict:
        return {"behavior": behavior, "reason": reason}

    mode = str(ctx.get("mode") or "social")
    if mode == "sleep" or ctx.get("awake") is False:
        return out(BEHAVIOR_REST, "asleep / sleep mode")

    # Physical edge/stairs is the most urgent state: a downward-drop reflex fired
    # (or we're sitting at a known no-go). Never self-move; hold and ask out loud
    # to be carried. Above battery so Pip never drives toward the stairs to charge.
    if ctx.get("edge_detected"):
        return out(BEHAVIOR_REQUEST_ASSIST, "edge/drop detected — holding and asking to be carried")

    # Self-preservation is the top non-safety priority. Skip it if already charging
    # (Pip is docked, so don't drive off looking for the charger).
    charging = bool(ctx.get("battery_charging"))
    if not charging and ctx.get("battery_recommendation") == "charge_before_movement":
        return out(BEHAVIOR_RETURN_TO_CHARGER, "battery critically low; seeking charger / asking for help")
    battery_percent = ctx.get("battery_percent")
    min_batt = float(ctx.get("return_to_charger_min_battery", 35.0))
    if (
        not charging
        and battery_percent is not None
        and float(battery_percent) <= min_batt
        and ctx.get("movement_allowed")
        and ctx.get("dock_known")
    ):
        return out(BEHAVIOR_RETURN_TO_CHARGER, f"battery {float(battery_percent):.0f}% <= {min_batt:.0f}%; heading to known charger")

    # A live hazard means wait/observe, never self-initiate motion.
    if ctx.get("hazards_present"):
        return out(BEHAVIOR_HOLD, "fresh hazard present; holding")

    # Obey the owner: quiet hours / do-not-disturb / quiet mode -> observe only.
    if ctx.get("do_not_disturb") or ctx.get("quiet") or mode == "quiet":
        return out(BEHAVIOR_OBSERVE, "quiet hours / do-not-disturb; observing only")

    # A person nearby is socially salient.
    if ctx.get("person_present"):
        return out(BEHAVIOR_SOCIALIZE, "a person is nearby")

    # An active goal/mission set by the owner or the LLM mind.
    if ctx.get("has_goal"):
        return out(BEHAVIOR_PURSUE_GOAL, "pursuing active goal")

    # Curiosity/boredom drive exploration when movement is allowed -- but never
    # wander while parked at a marked no-go (top of the stairs): just observe.
    if (
        ctx.get("movement_allowed")
        and not ctx.get("at_hazard")
        and (float(ctx.get("curiosity", 0.0) or 0.0) >= 0.68 or float(ctx.get("boredom", 0.0) or 0.0) >= 0.6)
    ):
        return out(BEHAVIOR_PATROL, "curious/bored and free to move; patrolling")

    return out(BEHAVIOR_OBSERVE, "calm presence; observing")
