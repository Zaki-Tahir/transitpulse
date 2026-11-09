"""Writes deterministic data for the end-to-end tests: the tiny test network, a vehicle feed with
three trains, and an alert that delays the A line. Times are relative to "now", so the trains
stay in service for about 40 minutes after the files are generated.

    uv run python -m tests.e2e_fixtures ../data/e2e
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from .feeds import alerts_feed, vehicle_feed, write_static_zip


def main(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    now = int(time.time())
    write_static_zip(out / "gtfs.zip")
    (out / "vehicles.pb").write_bytes(
        vehicle_feed(
            [
                # Northbound A trains between stations, and a B train approaching Bravo.
                {"id": "a1", "route": "A", "upcoming": [("102N", now + 60), ("103N", now + 240)]},
                {"id": "a2", "route": "A", "upcoming": [("103N", now + 120)]},
                {"id": "b1", "route": "B", "upcoming": [("102N", now + 150)]},
                # Later departures so stations keep showing arrivals for a while.
                *[
                    {
                        "id": f"a-later-{i}",
                        "route": "A",
                        "upcoming": [("102N", now + 600 * i), ("103N", now + 600 * i + 180)],
                    }
                    for i in range(1, 5)
                ],
            ],
            timestamp=now,
        )
    )
    (out / "alerts.pb").write_bytes(
        alerts_feed(
            [
                {
                    "id": "lmm:alert:e2e",
                    "routes": ["A"],
                    "text": "[A] trains are running with delays",
                    "periods": [],
                }
            ]
        )
    )
    print(f"wrote e2e fixtures to {out}")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "../data/e2e"))
