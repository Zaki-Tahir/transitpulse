from pathlib import Path

import pytest

from transitpulse.gtfs_static import SegmentIndex, parent_station, parse_gtfs_time, read_static
from transitpulse.realtime import arrivals_by_stop, bearing, parse_feed, position_at, to_motion

from .feeds import vehicle_feed, write_static_zip

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def static(tmp_path: Path):
    return read_static(write_static_zip(tmp_path / "gtfs.zip"))


@pytest.fixture
def coords(static) -> dict[str, tuple[float, float]]:
    return {s.stop_id: (s.lat, s.lon) for s in static.stations}


def test_gtfs_helpers():
    assert parse_gtfs_time("25:10:30") == 25 * 3600 + 630
    assert parent_station("A27N") == "A27"
    assert parent_station("A27") == "A27"


def test_read_static_builds_stations_routes_and_hops(static):
    assert [r.route_id for r in static.routes] == ["A", "B"]
    assert {s.stop_id for s in static.stations} == {"101", "102", "103", "201"}
    assert next(s for s in static.stations if s.stop_id == "102").routes == ("A", "B")

    hops = {(s.route_id, s.from_stop, s.to_stop): s for s in static.segments}
    # Times past midnight ("25:00:00") are handled; both A trips agree on 120s and 180s.
    assert hops[("A", "101N", "102N")].typical_seconds == 120
    assert hops[("A", "102N", "103N")].typical_seconds == 180
    assert hops[("A", "101N", "102N")].trips == 2


def test_segment_index_is_per_line(static):
    index = SegmentIndex(static.segments)
    # Station 102 is reached from 101 on the A but from 201 on the B.
    assert index.previous("A", "102N").from_stop == "101N"  # type: ignore[union-attr]
    assert index.previous("B", "102N").from_stop == "201N"  # type: ignore[union-attr]
    assert index.previous("A", "101N") is None


def test_moving_train_is_placed_between_stations(static, coords):
    now = 10_000
    [trip] = parse_feed(
        vehicle_feed([{"id": "t1", "route": "A", "stop": "103N", "upcoming": [("103N", now + 60)]}])
    )
    motion = to_motion(trip, now, SegmentIndex(static.segments), set(coords))

    assert motion is not None
    assert (motion.from_stop, motion.to_stop) == ("102N", "103N")
    # Hop takes 180s and it arrives in 60s, so it left 120s ago: two thirds of the way.
    assert motion.depart == now - 120
    lat, lon, heading = position_at(motion, now, coords)
    assert lat == pytest.approx(40.710 + (40.720 - 40.710) * 2 / 3)
    assert lon == pytest.approx(-74.000 + (-74.010 + 74.000) * 2 / 3)
    assert 300 < heading < 360  # heading north-west


def test_train_that_has_not_left_yet_waits_at_the_previous_station(static, coords):
    now = 10_000
    [trip] = parse_feed(
        vehicle_feed([{"id": "t1", "route": "A", "stop": "103N", "upcoming": [("103N", now + 600)]}])
    )
    motion = to_motion(trip, now, SegmentIndex(static.segments), set(coords))
    assert motion is not None
    assert position_at(motion, now, coords)[:2] == coords["102"]


def motions_by_id(static, coords, trips_spec, now):
    index = SegmentIndex(static.segments)
    return {t.trip_id: to_motion(t, now, index, set(coords)) for t in parse_feed(vehicle_feed(trips_spec))}


def test_trusts_predictions_over_the_reported_status(static, coords):
    """MTA reports most running trains as STOPPED_AT their last station; the predictions say otherwise."""
    now = 10_000
    m = motions_by_id(
        static,
        coords,
        [
            # "Stopped at 102" but the next prediction is 103 in 60s: actually two thirds of the way there.
            {"id": "moving", "route": "A", "stop": "102N", "stopped": True, "upcoming": [("103N", now + 60)]},
            # Genuinely dwelling: stopped at 102 and 102 is the next stop, due now.
            {"id": "dwell", "route": "A", "stop": "102N", "stopped": True, "upcoming": [("102N", now)]},
            # Past stops are ignored; the next stop still ahead wins.
            {"id": "past", "route": "A", "upcoming": [("102N", now - 300), ("103N", now + 90)]},
        ],
        now,
    )
    assert (m["moving"].from_stop, m["moving"].to_stop) == ("102N", "103N")  # type: ignore[union-attr]
    assert m["dwell"].stopped and m["dwell"].to_stop == "102N"  # type: ignore[union-attr]
    assert m["past"].to_stop == "103N"  # type: ignore[union-attr]


def test_trips_at_their_first_stop_show_only_when_about_to_leave(static, coords):
    now = 10_000
    m = motions_by_id(
        static,
        coords,
        [
            {"id": "leaving", "route": "A", "upcoming": [("101N", now + 30), ("102N", now + 150)]},
            {"id": "later", "route": "A", "upcoming": [("101N", now + 1200), ("102N", now + 1320)]},
            {"id": "done", "route": "A", "upcoming": [("103N", now - 600)]},
        ],
        now,
    )
    assert m["leaving"] is not None and m["leaving"].stopped and m["leaving"].to_stop == "101N"
    assert m["later"] is None  # scheduled, not in service yet
    assert m["done"] is None  # already finished


def test_unknown_stops_are_skipped(static, coords):
    [trip] = parse_feed(vehicle_feed([{"id": "x", "route": "A", "stop": "999N", "upcoming": [("999N", 5)]}]))
    assert to_motion(trip, 0, SegmentIndex(static.segments), set(coords)) is None


def test_arrivals_by_stop_groups_and_sorts():
    trips = parse_feed(
        vehicle_feed(
            [
                {"id": "1", "route": "A", "upcoming": [("102N", 1300), ("103N", 1500)]},
                {"id": "2", "route": "A", "upcoming": [("102N", 1100)]},
                {"id": "3", "route": "B", "upcoming": [("102N", 9999)]},  # beyond the one-hour horizon
            ]
        )
    )
    assert arrivals_by_stop(trips, now=1000) == {"102N": {"A": [1100, 1300]}, "103N": {"A": [1500]}}


def test_bearing():
    assert bearing((40.0, -74.0), (41.0, -74.0)) == pytest.approx(0, abs=0.01)
    assert bearing((40.0, -74.0), (40.0, -73.0)) == pytest.approx(90, abs=0.5)


def test_parses_a_real_recorded_mta_feed():
    trips = parse_feed((FIXTURES / "nyct-gtfs-ace.pb").read_bytes())
    assert len(trips) > 50
    assert {t.route_id for t in trips} >= {"A", "C", "E"}
    assert all(t.stop_id and t.stop_id[-1] in "NS" for t in trips)
    assert any(t.stopped for t in trips) and any(not t.stopped for t in trips)
