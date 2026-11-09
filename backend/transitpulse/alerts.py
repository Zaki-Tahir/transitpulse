"""Turns the MTA service alerts feed into one status per line, for the delay badges."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import IntEnum

from google.transit import gtfs_realtime_pb2 as rt


class Status(IntEnum):
    """Ordered by how much a rider cares; a line shows its worst current status."""

    GOOD = 0
    PLANNED_WORK = 1
    SERVICE_CHANGE = 2
    DELAYS = 3

    @property
    def label(self) -> str:
        return {0: "Good service", 1: "Planned work", 2: "Service change", 3: "Delays"}[self.value]


@dataclass(frozen=True, slots=True)
class LineStatus:
    route_id: str
    status: Status
    summary: str | None


_BRACKETS = re.compile(r"\[([^\]]+)\]")


def clean_text(text: str) -> str:
    """MTA writes line names as "[A]"; show them as plain "A"."""
    return " ".join(_BRACKETS.sub(r"\1", text).split())


def classify(alert_id: str, header: str) -> Status:
    text = header.lower()
    if "delay" in text or "running slow" in text:
        return Status.DELAYS
    if "planned_work" in alert_id or "planned" in text:
        return Status.PLANNED_WORK
    return Status.SERVICE_CHANGE


def _is_active(alert: rt.Alert, now: int) -> bool:
    if not alert.active_period:
        return True
    return any(p.start <= now and (p.end == 0 or now <= p.end) for p in alert.active_period)


def line_statuses(data: bytes, route_ids: list[str], now: int) -> dict[str, LineStatus]:
    feed = rt.FeedMessage()
    feed.ParseFromString(data)
    statuses = {r: LineStatus(r, Status.GOOD, None) for r in route_ids}

    for entity in feed.entity:
        if not entity.HasField("alert") or not _is_active(entity.alert, now):
            continue
        alert = entity.alert
        header = clean_text(alert.header_text.translation[0].text) if alert.header_text.translation else ""
        status = classify(entity.id, header)
        for route in {ie.route_id for ie in alert.informed_entity if ie.route_id}:
            current = statuses.get(route)
            if current is not None and status > current.status:
                statuses[route] = LineStatus(route, status, header or None)
    return statuses
