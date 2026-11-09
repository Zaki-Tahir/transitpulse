"""Reads the static GTFS schedule: stations, lines, and how long each hop between stations takes.

The realtime subway feed says which station a train is heading to and when it should arrive,
but not where it is. To place a train between two stations we need to know which station it
came from and how long that hop normally takes. Both come from the static schedule.
"""

from __future__ import annotations

import csv
import io
import itertools
import statistics
import zipfile
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Station:
    stop_id: str
    name: str
    lat: float
    lon: float
    routes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Route:
    route_id: str
    short_name: str
    long_name: str
    color: str
    text_color: str
    sort_order: int


@dataclass(frozen=True, slots=True)
class Segment:
    """One hop between consecutive stops on a line, in one direction (stop ids keep their N/S suffix)."""

    route_id: str
    from_stop: str
    to_stop: str
    typical_seconds: int
    trips: int


@dataclass(slots=True)
class StaticData:
    stations: list[Station]
    routes: list[Route]
    segments: list[Segment]


def parse_gtfs_time(value: str) -> int:
    """GTFS times can pass midnight, e.g. "25:10:00" for 1:10 AM the next day."""
    h, m, s = value.split(":")
    return int(h) * 3600 + int(m) * 60 + int(s)


def parent_station(stop_id: str) -> str:
    """Platform ids carry a direction suffix: "A27N" and "A27S" both belong to station "A27"."""
    return stop_id[:-1] if stop_id[-1:] in ("N", "S") else stop_id


def _rows(zf: zipfile.ZipFile, name: str) -> Iterator[dict[str, str]]:
    with zf.open(name) as f:
        yield from csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))


def build_segments(
    trip_routes: dict[str, str], stop_times: Iterable[dict[str, str]], sample_limit: int = 200
) -> tuple[list[Segment], dict[str, set[str]]]:
    """Turns stop_times into per-line hops with their median travel time.

    Also returns which routes serve each station, for the map legend and stop search.
    """
    by_trip: dict[str, list[tuple[int, str, int]]] = defaultdict(list)
    for row in stop_times:
        time = row["arrival_time"] or row["departure_time"]
        if time:
            by_trip[row["trip_id"]].append((int(row["stop_sequence"]), row["stop_id"], parse_gtfs_time(time)))

    durations: dict[tuple[str, str, str], list[int]] = defaultdict(list)
    counts: Counter[tuple[str, str, str]] = Counter()
    station_routes: dict[str, set[str]] = defaultdict(set)

    for trip_id, stops in by_trip.items():
        route = trip_routes.get(trip_id)
        if route is None:
            continue
        stops.sort()
        for _, stop_id, _ in stops:
            station_routes[parent_station(stop_id)].add(route)
        for (_, a, ta), (_, b, tb) in itertools.pairwise(stops):
            key = (route, a, b)
            counts[key] += 1
            if len(durations[key]) < sample_limit:
                durations[key].append(tb - ta)

    segments = [
        Segment(route, a, b, max(30, int(statistics.median(durations[(route, a, b)]))), n)
        for (route, a, b), n in counts.items()
    ]
    return segments, station_routes


def read_static(path: Path) -> StaticData:
    with zipfile.ZipFile(path) as zf:
        routes = [
            Route(
                route_id=r["route_id"],
                short_name=r["route_short_name"] or r["route_id"],
                long_name=r["route_long_name"],
                color=(r.get("route_color") or "808183").upper(),
                text_color=(r.get("route_text_color") or "FFFFFF").upper(),
                sort_order=int(r.get("route_sort_order") or 999),
            )
            for r in _rows(zf, "routes.txt")
        ]
        trip_routes = {t["trip_id"]: t["route_id"] for t in _rows(zf, "trips.txt")}
        segments, station_routes = build_segments(trip_routes, _rows(zf, "stop_times.txt"))

        stations = [
            Station(
                stop_id=s["stop_id"],
                name=s["stop_name"],
                lat=float(s["stop_lat"]),
                lon=float(s["stop_lon"]),
                routes=tuple(sorted(station_routes.get(s["stop_id"], ()))),
            )
            for s in _rows(zf, "stops.txt")
            # location_type 1 = parent station; platforms share its coordinates.
            if s.get("location_type") == "1" or not s.get("parent_station")
        ]
    return StaticData(stations=stations, routes=sorted(routes, key=lambda r: r.sort_order), segments=segments)


class SegmentIndex:
    """For a train on route R heading to stop X: which stop it came from, and how long that hop takes."""

    def __init__(self, segments: Iterable[Segment]) -> None:
        best: dict[tuple[str, str], Segment] = {}
        for seg in segments:
            key = (seg.route_id, seg.to_stop)
            # Where branches merge, several stops lead to X. Use the most common one.
            if key not in best or seg.trips > best[key].trips:
                best[key] = seg
        self._previous = best

    def previous(self, route_id: str, to_stop: str) -> Segment | None:
        return self._previous.get((route_id, to_stop))

    def __len__(self) -> int:
        return len(self._previous)
