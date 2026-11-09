"""Helpers that build small GTFS files and GTFS-realtime feeds for tests."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

from google.transit import gtfs_realtime_pb2 as rt


def vehicle_feed(trips: list[dict[str, object]], timestamp: int = 1_000_000) -> bytes:
    """trips: [{"id", "route", "stop", "stopped", "upcoming": [(stop, time)], "position": (lat, lon)}]"""
    feed = rt.FeedMessage()
    feed.header.gtfs_realtime_version = "2.0"
    feed.header.timestamp = timestamp
    for t in trips:
        tu = feed.entity.add(id=f"tu-{t['id']}").trip_update
        tu.trip.trip_id = str(t["id"])
        tu.trip.route_id = str(t["route"])
        for stop, when in t.get("upcoming", []):  # type: ignore[attr-defined]
            stu = tu.stop_time_update.add(stop_id=stop)
            stu.arrival.time = when
        if "stop" in t:
            vp = feed.entity.add(id=f"vp-{t['id']}").vehicle
            vp.trip.trip_id = str(t["id"])
            vp.trip.route_id = str(t["route"])
            vp.stop_id = str(t["stop"])
            vp.current_status = (
                rt.VehiclePosition.STOPPED_AT if t.get("stopped") else rt.VehiclePosition.IN_TRANSIT_TO
            )
            if "position" in t:
                lat, lon = t["position"]  # type: ignore[misc]
                vp.position.latitude, vp.position.longitude = lat, lon
    return feed.SerializeToString()


def alerts_feed(alerts: list[dict[str, object]]) -> bytes:
    """alerts: [{"id", "routes": [...], "text", "periods": [(start, end)]}]"""
    feed = rt.FeedMessage()
    feed.header.gtfs_realtime_version = "2.0"
    for a in alerts:
        alert = feed.entity.add(id=str(a["id"])).alert
        for route in a["routes"]:  # type: ignore[attr-defined]
            alert.informed_entity.add(route_id=route)
        alert.header_text.translation.add(text=str(a["text"]), language="en")
        for start, end in a.get("periods", []):  # type: ignore[attr-defined]
            alert.active_period.add(start=start, end=end)
    return feed.SerializeToString()


# A tiny two-line network:
#   A line: 101N -> 102N -> 103N (northbound), 2 minutes then 3 minutes between stations
#   B line: 201N -> 102N (shares station 102)
STATIC_FILES = {
    "routes.txt": "route_id,route_short_name,route_long_name,route_color,route_text_color,route_sort_order\n"
    "A,A,8 Avenue Express,0062CF,FFFFFF,1\nB,B,6 Avenue Express,EB6800,FFFFFF,2\n",
    "trips.txt": "route_id,trip_id,service_id\nA,a1,wk\nA,a2,wk\nB,b1,wk\n",
    "stops.txt": "stop_id,stop_name,stop_lat,stop_lon,location_type,parent_station\n"
    "101,Alpha,40.700,-74.000,1,\n101N,Alpha,40.700,-74.000,,101\n"
    "102,Bravo,40.710,-74.000,1,\n102N,Bravo,40.710,-74.000,,102\n"
    "103,Charlie,40.720,-74.010,1,\n103N,Charlie,40.720,-74.010,,103\n"
    "201,Delta,40.705,-73.990,1,\n201N,Delta,40.705,-73.990,,201\n",
    "stop_times.txt": "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
    "a1,08:00:00,08:00:00,101N,1\na1,08:02:00,08:02:00,102N,2\na1,08:05:00,08:05:00,103N,3\n"
    "a2,25:00:00,25:00:00,101N,1\na2,25:02:00,25:02:00,102N,2\na2,25:05:00,25:05:00,103N,3\n"
    "b1,09:00:00,09:00:00,201N,1\nb1,09:04:00,09:04:00,102N,2\n",
}


def write_static_zip(path: Path) -> Path:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in STATIC_FILES.items():
            zf.writestr(name, content)
    path.write_bytes(buf.getvalue())
    return path
