"""Parses GTFS-realtime feeds and turns each subway trip into a "motion" the client can animate.

Instead of a position, each vehicle is described as: travelling from stop A (departed at T1) to
stop B (arriving at T2). The browser interpolates between the two stations itself, so a train only
needs to be re-sent when its prediction changes, not every time it moves.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from google.transit import gtfs_realtime_pb2 as rt

from .gtfs_static import SegmentIndex, parent_station

STOPPED_AT = rt.VehiclePosition.STOPPED_AT


@dataclass(slots=True)
class TripState:
    """What the feed says about one trip."""

    trip_id: str
    route_id: str
    # Stop the train is at (if stopped) or heading to.
    stop_id: str | None
    stopped: bool
    # Upcoming stops and their predicted arrival times (unix seconds).
    upcoming: list[tuple[str, int]] = field(default_factory=list)
    # For feeds that do report GPS (buses), the raw position.
    position: tuple[float, float, float | None] | None = None


@dataclass(frozen=True, slots=True)
class Motion:
    """A train going from `from_stop` (left at `depart`) to `to_stop` (arriving at `arrive`).
    When stopped, from_stop == to_stop."""

    id: str
    route_id: str
    from_stop: str
    to_stop: str
    depart: int
    arrive: int

    @property
    def stopped(self) -> bool:
        return self.from_stop == self.to_stop


def parse_feed(data: bytes) -> list[TripState]:
    feed = rt.FeedMessage()
    feed.ParseFromString(data)

    trips: dict[str, TripState] = {}

    def trip_for(trip_id: str, route_id: str) -> TripState:
        state = trips.get(trip_id)
        if state is None:
            state = trips[trip_id] = TripState(
                trip_id=trip_id, route_id=route_id, stop_id=None, stopped=False
            )
        return state

    for entity in feed.entity:
        if entity.HasField("trip_update"):
            tu = entity.trip_update
            state = trip_for(tu.trip.trip_id, tu.trip.route_id)
            for stu in tu.stop_time_update:
                when = stu.arrival.time or stu.departure.time
                if when:
                    state.upcoming.append((stu.stop_id, when))
        elif entity.HasField("vehicle"):
            vp = entity.vehicle
            state = trip_for(vp.trip.trip_id, vp.trip.route_id)
            state.stop_id = vp.stop_id or None
            state.stopped = vp.current_status == STOPPED_AT
            if vp.HasField("position"):
                state.position = (vp.position.latitude, vp.position.longitude, vp.position.bearing or None)

    for state in trips.values():
        state.upcoming.sort(key=lambda u: u[1])
        if state.stop_id is None and state.upcoming:
            state.stop_id = state.upcoming[0][0]
    return [t for t in trips.values() if t.route_id and t.stop_id]


def to_motion(trip: TripState, now: int, segments: SegmentIndex, known_stops: set[str]) -> Motion | None:
    """Works out where the train is coming from and when it left, using the schedule's typical hop time.

    The subway feed's vehicle status is unreliable (most running trains are reported as STOPPED_AT
    the last station), so this goes by the arrival predictions: the next stop is the first one
    still ahead, and how soon the train gets there says how far along the hop it is.
    """
    ahead = [(s, t) for s, t in trip.upcoming if t >= now - 30]
    if not ahead:
        return None  # trip already finished
    stop, arrive = ahead[0]
    if parent_station(stop) not in known_stops:
        return None

    if trip.stopped and trip.stop_id == stop and arrive <= now + 30:
        return Motion(trip.trip_id, trip.route_id, stop, stop, arrive, arrive)

    seg = segments.previous(trip.route_id, stop)
    if seg is None or parent_station(seg.from_stop) not in known_stops:
        # Heading to the first stop of its trip. MTA lists trips up to ~30 minutes before they
        # start; only show the ones about to leave, sitting at the terminal.
        if arrive - now > 120:
            return None
        return Motion(trip.trip_id, trip.route_id, stop, stop, arrive, arrive)

    # Assume it left the previous stop one typical hop before its predicted arrival. If that's still in
    # the future, the train hasn't left yet; position_at() keeps it at the previous station until then.
    return Motion(trip.trip_id, trip.route_id, seg.from_stop, stop, arrive - seg.typical_seconds, arrive)


def position_at(
    motion: Motion, t: float, coords: dict[str, tuple[float, float]]
) -> tuple[float, float, float]:
    """(lat, lon, bearing) of a train at time t. The dashboard does the same thing in TypeScript."""
    a = coords[parent_station(motion.from_stop)]
    b = coords[parent_station(motion.to_stop)]
    if motion.stopped or motion.arrive <= motion.depart:
        return (*b, 0.0)
    progress = min(1.0, max(0.0, (t - motion.depart) / (motion.arrive - motion.depart)))
    lat = a[0] + (b[0] - a[0]) * progress
    lon = a[1] + (b[1] - a[1]) * progress
    return lat, lon, bearing(a, b)


def bearing(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Compass bearing in degrees from a to b."""
    lat1, lat2 = math.radians(a[0]), math.radians(b[0])
    dlon = math.radians(b[1] - a[1])
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def arrivals_by_stop(
    trips: list[TripState], now: int, horizon: int = 3600
) -> dict[str, dict[str, list[int]]]:
    """{platform stop id: {route: [arrival times]}} for the next hour, for stop pages and commute alerts."""
    out: dict[str, dict[str, list[int]]] = {}
    for trip in trips:
        for stop_id, when in trip.upcoming:
            if now - 30 <= when <= now + horizon:
                out.setdefault(stop_id, {}).setdefault(trip.route_id, []).append(when)
    for routes in out.values():
        for times in routes.values():
            times.sort()
    return out
