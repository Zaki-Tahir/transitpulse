"""Wire format for vehicles, and the diff that keeps WebSocket traffic small.

A vehicle is sent as a compact array instead of an object with repeated keys:

    [id, route, from_stop, to_stop, depart, arrive]

and after the first snapshot a client only receives what changed:

    {"type": "delta", "t": 1794239645, "u": [[...changed vehicles...]], "r": ["removed ids"]}
"""

from __future__ import annotations

import json
from typing import Any

from .realtime import Motion

# Predictions jitter by a few seconds between polls. Rounding to this grid means a train whose
# prediction moved by 2 seconds isn't re-sent; the animation can't show a 2-second difference anyway.
TIME_GRID = 10

Packed = tuple[str, str, str, str, int, int]


def pack(m: Motion) -> Packed:
    def snap(t: int) -> int:
        return round(t / TIME_GRID) * TIME_GRID

    return (m.id, m.route_id, m.from_stop, m.to_stop, snap(m.depart), snap(m.arrive))


def diff(previous: dict[str, Packed], current: dict[str, Packed]) -> tuple[list[Packed], list[str]]:
    updated = [v for vid, v in current.items() if previous.get(vid) != v]
    removed = [vid for vid in previous if vid not in current]
    return updated, removed


def snapshot_message(t: int, vehicles: dict[str, Packed]) -> str:
    return dumps({"type": "snapshot", "t": t, "v": list(vehicles.values())})


def delta_message(t: int, updated: list[Packed], removed: list[str]) -> str:
    return dumps({"type": "delta", "t": t, "u": updated, "r": removed})


def naive_message(t: int, motions: list[Motion], coords: dict[str, tuple[float, float]]) -> str:
    """What the simple approach would send every poll: every vehicle, as an object, with its position.
    Only used to measure how much the delta format saves."""
    from .realtime import position_at

    vehicles = []
    for m in motions:
        lat, lon, heading = position_at(m, t, coords)
        vehicles.append(
            {
                "id": m.id,
                "route": m.route_id,
                "lat": round(lat, 6),
                "lon": round(lon, 6),
                "bearing": round(heading, 1),
                "stopped": m.stopped,
                "nextStop": m.to_stop,
                "updatedAt": t,
            }
        )
    return dumps({"type": "vehicles", "t": t, "vehicles": vehicles})


def dumps(obj: Any) -> str:
    return json.dumps(obj, separators=(",", ":"))
