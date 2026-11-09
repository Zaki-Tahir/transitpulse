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

# MTA predictions jitter by several seconds on almost every poll. A train is only re-sent when
# its stops change or its timing moves by more than this. The error is measured against what the
# browser last received, so it never accumulates past this bound: at subway speeds, 20 seconds is
# a fraction of a block on the map.
DEADBAND_SECONDS = 20

Packed = tuple[str, str, str, str, int, int]


def pack(m: Motion) -> Packed:
    return (m.id, m.route_id, m.from_stop, m.to_stop, m.depart, m.arrive)


def diff(
    sent: dict[str, Packed], current: dict[str, Packed]
) -> tuple[list[Packed], list[str], dict[str, Packed]]:
    """Compares this poll with what clients already have.

    Returns the vehicles to send, the ids to remove, and the new "what clients have" state, which
    keeps the previously sent version of any train whose change was within the deadband.
    """
    updated: list[Packed] = []
    state: dict[str, Packed] = {}
    for vid, v in current.items():
        old = sent.get(vid)
        if (
            old is not None
            and old[1:4] == v[1:4]
            and abs(old[4] - v[4]) <= DEADBAND_SECONDS
            and abs(old[5] - v[5]) <= DEADBAND_SECONDS
        ):
            state[vid] = old
        else:
            state[vid] = v
            updated.append(v)
    removed = [vid for vid in sent if vid not in current]
    return updated, removed, state


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
