"""Decides whether a rider's saved commute is running late."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .alerts import LineStatus, Status


class CommuteState(StrEnum):
    ON_TIME = "on_time"
    LATE = "late"
    NO_TRAINS = "no_trains"


@dataclass(frozen=True, slots=True)
class Commute:
    id: str
    client_id: str
    route_id: str
    # Platform stop with direction, e.g. "A27N" for northbound at 59 St-Columbus Circle.
    stop_id: str
    label: str
    threshold_minutes: int = 12


@dataclass(frozen=True, slots=True)
class CommuteStatus:
    state: CommuteState
    next_minutes: list[int]
    reason: str


def evaluate(
    commute: Commute,
    now: int,
    arrivals: dict[str, dict[str, list[int]]],
    lines: dict[str, LineStatus],
) -> CommuteStatus:
    times = [t for t in arrivals.get(commute.stop_id, {}).get(commute.route_id, []) if t >= now - 30]
    minutes = [max(0, round((t - now) / 60)) for t in times[:3]]
    line = lines.get(commute.route_id)

    if not minutes:
        return CommuteStatus(CommuteState.NO_TRAINS, [], "No trains predicted in the next hour")
    if line is not None and line.status == Status.DELAYS:
        return CommuteStatus(
            CommuteState.LATE, minutes, line.summary or f"{commute.route_id} trains are delayed"
        )
    if minutes[0] > commute.threshold_minutes:
        return CommuteStatus(CommuteState.LATE, minutes, f"Next train in {minutes[0]} min")
    return CommuteStatus(CommuteState.ON_TIME, minutes, f"Next train in {minutes[0]} min")


def should_notify(previous: CommuteState | None, current: CommuteState) -> bool:
    """Alert when a commute *becomes* late, not on every poll while it stays late."""
    return current is CommuteState.LATE and previous is not CommuteState.LATE
