"""Console routes for the versioned per-stage cleaning monitor."""

from support import call, ok, refused

REGISTER = {
    "train": "RO-1",
    "policy": "round_boundary",
    "stages": ["stage1", "stage2"],
    "limits": {
        "stage1": {"pressure": 10.0, "conductivity": 300.0},
        "stage2": {"pressure": 10.0, "conductivity": 300.0},
    },
}
V1 = {
    "train": "RO-1",
    "pressure_sensors": {"dp1": "stage1", "dp2": "stage2"},
    "quality_sensors": {"q1": "stage1", "q2": "stage2"},
    "tick": 0,
}


def _open_first_round(console):
    ok(console, "POST", "/api/trains", REGISTER)
    ok(console, "POST", "/api/trains/assignments", V1)
    ok(console, "POST", "/api/trains/rounds", {"train": "RO-1", "tick": 1})


def test_monitor_routes_are_registered(console):
    routes = console.routes()
    assert ("POST", "/api/trains") in routes
    assert ("POST", "/api/trains/assignments") in routes
    assert ("POST", "/api/trains/rounds") in routes
    assert ("POST", "/api/trains/sweeps") in routes
    assert ("GET", "/api/trains/replay") in routes
    assert ("GET", "/api/trains/consistency") in routes


def test_register_train_lists_the_fixed_policy(console):
    body = ok(console, "POST", "/api/trains", REGISTER)
    assert body == {"status": "registered", "train": "RO-1", "policy": "round_boundary"}
    trains = ok(console, "GET", "/api/trains")
    assert trains["trains"] == [{"train": "RO-1", "policy": "round_boundary"}]


def test_re_registering_with_another_policy_is_a_conflict(console):
    ok(console, "POST", "/api/trains", REGISTER)
    response = refused(console, "POST", "/api/trains", {"train": "RO-1", "policy": "immediate"})
    assert response.status == 409
    assert "fixed" in response.body["error"]


def test_unknown_policy_and_bad_assignment_are_unprocessable(console):
    response = refused(console, "POST", "/api/trains", {"train": "RO-9", "policy": "later"})
    assert response.status == 400
    ok(console, "POST", "/api/trains", {"train": "RO-2", "policy": "immediate", "stages": ["s1"]})
    response = refused(
        console,
        "POST",
        "/api/trains/assignments",
        {
            "train": "RO-2",
            "pressure_sensors": {"a": "s1"},
            "quality_sensors": {"q": "s2"},
        },
    )
    assert response.status == 422


def test_assignment_chain_is_listed(console):
    _open_first_round(console)
    ok(
        console,
        "POST",
        "/api/trains/assignments",
        {
            "train": "RO-1",
            "pressure_sensors": {"dp1": "stage1", "dp3": "stage2"},
            "quality_sensors": {"qA": "stage1", "qB": "stage2"},
            "tick": 3,
        },
    )
    body = ok(console, "GET", "/api/trains/assignments?train=RO-1")
    assert [item["version"] for item in body["assignments"]] == [1, 2]
    assert body["policy"] == "round_boundary"


def test_unknown_train_reads_are_not_found(console):
    assert refused(console, "GET", "/api/trains/assignments?train=missing").status == 404
    assert refused(console, "GET", "/api/trains/rounds?train=missing").status == 404


def test_rounds_list_their_pinned_assignment_versions(console):
    _open_first_round(console)
    body = ok(console, "GET", "/api/trains/rounds?train=RO-1")
    assert body["rounds"][0]["number"] == 1
    assert body["rounds"][0]["assignment_version"] == 1
    assert body["rounds"][0]["closed"] is False


def test_sweep_missing_train_param_is_a_bad_request(console):
    response = refused(console, "GET", "/api/trains/replay")
    assert response.status == 400


def test_live_verdict_reports_per_stage_state_under_the_pinned_version(console):
    _open_first_round(console)
    ok(
        console,
        "POST",
        "/api/trains/sweeps",
        {
            "train": "RO-1",
            "tick": 2,
            "values": {"dp1": 5.0, "dp2": 6.0, "q1": 100.0, "q2": 120.0},
        },
    )
    ok(
        console,
        "POST",
        "/api/trains/assignments",
        {
            "train": "RO-1",
            "pressure_sensors": {"dp1": "stage1", "dp3": "stage2"},
            "quality_sensors": {"qA": "stage1", "qB": "stage2"},
            "tick": 3,
        },
    )
    ok(
        console,
        "POST",
        "/api/trains/sweeps",
        {
            "train": "RO-1",
            "tick": 4,
            "values": {"dp1": 5.0, "dp3": 9.0, "qA": 100.0, "qB": 400.0},
        },
    )
    body = ok(console, "GET", "/api/trains/verdict/live?train=RO-1")
    verdict = body["verdict"]
    assert verdict["needs_clean"] is False
    assert verdict["policy"] == "round_boundary"
    assert verdict["basis"][-1]["assignment_version"] == 1
    assert {stage["stage"] for stage in verdict["stages"]} == {"stage1", "stage2"}


def test_close_freezes_a_verdict_and_the_three_views_agree(console):
    _open_first_round(console)
    ok(
        console,
        "POST",
        "/api/trains/sweeps",
        {
            "train": "RO-1",
            "tick": 2,
            "values": {"dp1": 5.0, "dp2": 6.0, "q1": 100.0, "q2": 120.0},
        },
    )
    closed = ok(console, "POST", "/api/trains/rounds/close", {"train": "RO-1", "tick": 3})
    fingerprint = closed["verdict"]["fingerprint"]

    external = ok(console, "GET", "/api/trains/verdict?train=RO-1&round=1")
    replayed = ok(console, "GET", "/api/trains/replay?train=RO-1&round=1")
    check = ok(console, "GET", "/api/trains/consistency?train=RO-1&round=1")
    assert external["verdict"]["fingerprint"] == fingerprint
    assert replayed["verdict"]["fingerprint"] == fingerprint
    assert check["fingerprint"] == fingerprint
    assert check["frozen"] == fingerprint
    assert check["consistent"] is True


def test_frozen_verdict_endpoint_404s_before_close(console):
    _open_first_round(console)
    response = refused(console, "GET", "/api/trains/verdict?train=RO-1&round=1")
    assert response.status == 404


def test_leader_names_the_stage_criterion_tick_version_and_sensor(console):
    _open_first_round(console)
    ok(
        console,
        "POST",
        "/api/trains/sweeps",
        {
            "train": "RO-1",
            "tick": 2,
            "values": {"dp1": 5.0, "dp2": 6.0, "q1": 100.0, "q2": 120.0},
        },
    )
    ok(console, "POST", "/api/trains/rounds/close", {"train": "RO-1", "tick": 3})
    ok(
        console,
        "POST",
        "/api/trains/assignments",
        {
            "train": "RO-1",
            "pressure_sensors": {"dp1": "stage1", "dp3": "stage2"},
            "quality_sensors": {"qA": "stage1", "qB": "stage2"},
            "tick": 4,
        },
    )
    ok(console, "POST", "/api/trains/rounds", {"train": "RO-1", "tick": 5})
    ok(
        console,
        "POST",
        "/api/trains/sweeps",
        {
            "train": "RO-1",
            "tick": 6,
            "values": {"dp1": 5.0, "dp3": 2.0, "qA": 100.0, "qB": 400.0},
        },
    )
    body = ok(console, "POST", "/api/trains/rounds/close", {"train": "RO-1", "tick": 7})
    leader = body["verdict"]["leader"]
    assert leader["stage"] == "stage2"
    assert leader["criterion"] == "permeate_conductivity"
    assert leader["sensors"] == ["qB"]
    assert leader["tick"] == 6
    assert leader["assignment_version"] == 2
    assert body["verdict"]["needs_clean"] is True


def test_immediate_policy_train_applies_a_mid_round_migration(console):
    ok(
        console,
        "POST",
        "/api/trains",
        {
            "train": "RO-2",
            "policy": "immediate",
            "stages": ["stage1"],
            "limits": {"stage1": {"pressure": 10.0, "conductivity": 300.0}},
        },
    )
    ok(
        console,
        "POST",
        "/api/trains/assignments",
        {
            "train": "RO-2",
            "pressure_sensors": {"a": "stage1"},
            "quality_sensors": {"qa": "stage1"},
            "tick": 0,
        },
    )
    ok(console, "POST", "/api/trains/rounds", {"train": "RO-2", "tick": 1})
    ok(console, "POST", "/api/trains/sweeps", {"train": "RO-2", "tick": 2, "values": {"a": 5.0, "qa": 100.0}})
    ok(
        console,
        "POST",
        "/api/trains/assignments",
        {
            "train": "RO-2",
            "pressure_sensors": {"b": "stage1"},
            "quality_sensors": {"qb": "stage1"},
            "tick": 3,
        },
    )
    ok(console, "POST", "/api/trains/sweeps", {"train": "RO-2", "tick": 4, "values": {"b": 12.0, "qb": 100.0}})
    body = ok(console, "POST", "/api/trains/rounds/close", {"train": "RO-2", "tick": 5})
    assert body["verdict"]["leader"]["sensors"] == ["b"]
    assert [item["assignment_version"] for item in body["verdict"]["basis"]] == [1, 2]


def test_history_replay_uses_the_version_at_the_time(console):
    _open_first_round(console)
    ok(
        console,
        "POST",
        "/api/trains/sweeps",
        {
            "train": "RO-1",
            "tick": 2,
            "values": {"dp1": 5.0, "dp2": 6.0, "q1": 100.0, "q2": 120.0},
        },
    )
    first = ok(console, "POST", "/api/trains/rounds/close", {"train": "RO-1", "tick": 3})
    # A later ownership migration cannot alter round one.
    ok(
        console,
        "POST",
        "/api/trains/assignments",
        {
            "train": "RO-1",
            "pressure_sensors": {"only": "stage1"},
            "quality_sensors": {"q": "stage1"},
            "tick": 4,
        },
    )
    replayed = ok(console, "GET", "/api/trains/replay?train=RO-1&round=1")
    assert replayed["verdict"]["fingerprint"] == first["verdict"]["fingerprint"]
    assert replayed["verdict"]["stages"][0]["stage"] == "stage1"


def test_audit_events_record_the_assignment_lifecycle(console):
    _open_first_round(console)
    ok(
        console,
        "POST",
        "/api/trains/sweeps",
        {"train": "RO-1", "tick": 2, "values": {"dp1": 1.0, "dp2": 1.0, "q1": 1.0, "q2": 1.0}},
    )
    ok(console, "POST", "/api/trains/rounds/close", {"train": "RO-1", "tick": 3})
    events = ok(console, "GET", "/api/events")["events"]
    kinds = {event["kind"] for event in events}
    assert {
        "train-registered",
        "assignment-published",
        "round-opened",
        "round-closed",
    } <= kinds
