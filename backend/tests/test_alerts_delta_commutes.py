import json

from transitpulse.alerts import Status, clean_text, line_statuses
from transitpulse.commutes import Commute, CommuteState, evaluate, should_notify
from transitpulse.delta import delta_message, diff, naive_message, pack, snapshot_message
from transitpulse.realtime import Motion

from .feeds import alerts_feed

NOW = 1_000_000


def test_line_status_takes_the_worst_active_alert():
    data = alerts_feed(
        [
            {
                "id": "lmm:planned_work:1",
                "routes": ["A", "C"],
                "text": "[A] runs local",
                "periods": [(NOW - 10, 0)],
            },
            {
                "id": "lmm:alert:2",
                "routes": ["A"],
                "text": "[A] trains are running with delays",
                "periods": [],
            },
            {
                "id": "lmm:alert:3",
                "routes": ["E"],
                "text": "[E] trains are delayed",
                "periods": [(NOW - 100, NOW - 1)],
            },
            {
                "id": "lmm:alert:4",
                "routes": ["G"],
                "text": "Some [G] trains end at Court Sq",
                "periods": [(NOW, 0)],
            },
        ]
    )
    s = line_statuses(data, ["A", "C", "E", "G"], NOW)

    assert s["A"].status is Status.DELAYS
    assert s["A"].summary == "A trains are running with delays"
    assert s["C"].status is Status.PLANNED_WORK
    assert s["E"].status is Status.GOOD  # that alert already ended
    assert s["G"].status is Status.SERVICE_CHANGE
    assert Status.DELAYS.label == "Delays"


def test_clean_text():
    assert clean_text("[4][5]  trains are\nrunning slow") == "45 trains are running slow"


def motion(vid: str, depart: int, arrive: int, to: str = "102N") -> Motion:
    return Motion(vid, "A", "101N", to, depart, arrive)


def test_delta_sends_only_what_changed():
    before = {m.id: pack(m) for m in [motion("1", 100, 220), motion("2", 100, 220), motion("3", 100, 220)]}
    after = {
        m.id: pack(m)
        for m in [
            motion("1", 102, 223),  # prediction jittered by a few seconds: not re-sent
            motion("2", 160, 280),  # delayed by a minute: re-sent
            motion("4", 100, 220),  # new train
        ]
    }
    updated, removed = diff(before, after)
    assert [u[0] for u in updated] == ["2", "4"]
    assert removed == ["3"]

    msg = json.loads(delta_message(NOW, updated, removed))
    assert msg == {"type": "delta", "t": NOW, "u": [list(u) for u in updated], "r": ["3"]}
    assert json.loads(snapshot_message(NOW, after))["v"][0] == ["1", "A", "101N", "102N", 100, 220]


def test_compact_delta_is_much_smaller_than_resending_everything():
    coords = {"101": (40.7, -74.0), "102": (40.71, -74.0)}
    motions = [motion(str(i), NOW - 60, NOW + 60) for i in range(300)]
    packed = {m.id: pack(m) for m in motions}
    changed = dict(list(packed.items())[:30])  # 10% of trains got a new prediction
    naive = naive_message(NOW, motions, coords)
    delta = delta_message(NOW, list(changed.values()), [])
    assert len(delta) < len(naive) * 0.1


def commute(**kw: object) -> Commute:
    return Commute(
        **{"id": "c1", "client_id": "u1", "route_id": "A", "stop_id": "102N", "label": "Work", **kw}
    )  # type: ignore[arg-type]


def test_commute_states():
    lines_ok = {}
    soon = {"102N": {"A": [NOW + 240, NOW + 600, NOW + 900, NOW + 1200]}}
    far = {"102N": {"A": [NOW + 20 * 60]}}

    ok = evaluate(commute(), NOW, soon, lines_ok)
    assert ok.state is CommuteState.ON_TIME and ok.next_minutes == [4, 10, 15]

    gap = evaluate(commute(), NOW, far, lines_ok)
    assert gap.state is CommuteState.LATE and gap.reason == "Next train in 20 min"

    from transitpulse.alerts import LineStatus

    delayed = evaluate(commute(), NOW, soon, {"A": LineStatus("A", Status.DELAYS, "A trains are delayed")})
    assert delayed.state is CommuteState.LATE and delayed.reason == "A trains are delayed"

    assert evaluate(commute(), NOW, {}, lines_ok).state is CommuteState.NO_TRAINS


def test_notifies_only_when_a_commute_becomes_late():
    assert should_notify(None, CommuteState.LATE)
    assert should_notify(CommuteState.ON_TIME, CommuteState.LATE)
    assert not should_notify(CommuteState.LATE, CommuteState.LATE)
    assert not should_notify(CommuteState.LATE, CommuteState.ON_TIME)
