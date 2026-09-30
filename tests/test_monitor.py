"""Versioned sensor assignment, rounds and per-stage cleaning verdicts."""

from dataclasses import FrozenInstanceError

import pytest

from desalplant.clock import LogicalClock
from desalplant.errors import (
    AssignmentOrderError,
    InvalidAssignmentError,
    RoundConflictError,
    TrainPolicyFixedError,
    UnknownRoundError,
    UnknownTrainError,
)
from desalplant.monitor import (
    IMMEDIATE,
    PRESSURE_CRITERION,
    QUALITY_CRITERION,
    AssignmentHistory,
    AssignmentVersion,
    CleanLimits,
    StageLimit,
    TrainMonitor,
    evaluate_round,
    evaluate_sweep,
    version_for_tick,
)
from desalplant.monitor.round import Round, Sweep
from desalplant.store.store import Store

STAGES = ("stage1", "stage2")
PRESSURE_LIMIT = 10.0
CONDUCTIVITY_LIMIT = 300.0


def limits():
    return CleanLimits.uniform(STAGES, PRESSURE_LIMIT, CONDUCTIVITY_LIMIT)


def version(number, tick=0, pressure=None, quality=None):
    return AssignmentVersion(
        train="RO-1",
        version=number,
        effective_tick=tick,
        pressure_sensors=pressure or {"dp1": "stage1", "dp2": "stage2"},
        quality_sensors=quality or {"q1": "stage1", "q2": "stage2"},
    )


def monitor(policy):
    store = Store()
    return TrainMonitor(store, LogicalClock(), None), store


# --------------------------------------------------------------- assignment


def test_assignment_version_is_immutable_and_projects():
    first = version(1)
    projected = first.to_dict()
    assert projected["version"] == 1
    assert AssignmentVersion.from_dict(projected) == first
    assert first.fingerprint() == "v1@t0"
    with pytest.raises(FrozenInstanceError):
        first.version = 2


def test_assignment_requires_every_stage_to_own_pressure_and_quality():
    with pytest.raises(InvalidAssignmentError):
        AssignmentVersion(
            train="RO-1",
            version=1,
            effective_tick=0,
            pressure_sensors={"dp1": "stage1"},
            quality_sensors={"q1": "stage1", "q2": "stage2"},
        )
    with pytest.raises(InvalidAssignmentError):
        AssignmentVersion(
            train="RO-1",
            version=1,
            effective_tick=0,
            pressure_sensors={"dp1": "stage1", "dp2": "stage2"},
            quality_sensors={"q": "stage1"},
        )


def test_assignment_history_only_accepts_advancing_versions():
    history = AssignmentHistory("RO-1")
    history.publish(version(1, tick=2))
    with pytest.raises(AssignmentOrderError):
        history.publish(version(3, tick=3))
    with pytest.raises(AssignmentOrderError):
        history.publish(version(2, tick=1))
    history.publish(
        version(
            2,
            tick=2,
            pressure={"dp1": "stage1", "dp3": "stage2"},
            quality={"qA": "stage1", "qB": "stage2"},
        )
    )
    assert history.newest_version().version == 2
    assert history.effective(1) is None
    assert history.effective(2).version == 2
    assert history.effective(5).version == 2
    assert [item.version for item in history.versions()] == [1, 2]


# ----------------------------------------------------------------- limits


def test_clean_limits_cover_and_rebuild():
    table = limits()
    assert table.covers(("stage1",))
    assert table.stages() == STAGES
    rebuilt = CleanLimits.from_dict(table.to_dict())
    assert rebuilt.for_stage("stage2").pressure == PRESSURE_LIMIT
    assert rebuilt.for_stage("stage2").conductivity == CONDUCTIVITY_LIMIT
    with pytest.raises(InvalidAssignmentError):
        CleanLimits({})
    with pytest.raises(InvalidAssignmentError):
        StageLimit(stage="stage1", pressure=0.0, conductivity=1.0)


# ------------------------------------------------------------- evaluation


def test_sweep_judges_pressure_and_quality_per_stage():
    assignment = version(1)
    sweep = Sweep(
        tick=1,
        values={"dp1": 12.0, "dp2": 5.0, "q1": 100.0, "q2": 350.0},
    )
    basis = evaluate_sweep(assignment, limits(), sweep)
    states = {(state.stage, state.criterion): state for state in basis.stages}
    assert states[("stage1", PRESSURE_CRITERION)].crossed is True
    assert states[("stage2", PRESSURE_CRITERION)].crossed is False
    assert states[("stage2", QUALITY_CRITERION)].crossed is True
    assert states[("stage1", QUALITY_CRITERION)].value == 100.0


def test_missing_sensors_do_not_cross_a_limit():
    basis = evaluate_sweep(
        version(1),
        limits(),
        Sweep(tick=1, values={"dp1": 12.0}),
    )
    for state in basis.stages:
        if state.stage == "stage1" and state.criterion == PRESSURE_CRITERION:
            assert state.crossed is True
        else:
            assert state.crossed is False
            assert state.value == 0.0


def test_round_marks_the_first_stage_and_names_its_sensor():
    opened = Round(
        train="RO-1",
        number=1,
        start_tick=1,
        assignment_version=1,
    )
    history = AssignmentHistory("RO-1")
    history.publish(version(1))
    sweeps = (
        Sweep(tick=1, values={"dp1": 5.0, "dp2": 6.0, "q1": 100.0, "q2": 120.0}),
        Sweep(tick=2, values={"dp1": 5.0, "dp2": 6.0, "q1": 100.0, "q2": 350.0}),
    )
    verdict = evaluate_round(opened, history, IMMEDIATE, sweeps, limits())
    assert verdict.needs_clean is True
    assert verdict.leader.stage == "stage2"
    assert verdict.leader.criterion == QUALITY_CRITERION
    assert verdict.leader.sensors == ("q2",)
    assert verdict.leader.tick == 2
    assert verdict.leader.assignment_version == 1
    by_stage = {stage.stage: stage for stage in verdict.stages}
    assert by_stage["stage1"].needs_clean is False
    assert by_stage["stage2"].needs_clean is True


def test_pressure_crossing_earlier_beats_a_later_quality_crossing():
    opened = Round(train="RO-1", number=1, start_tick=1, assignment_version=1)
    history = AssignmentHistory("RO-1")
    history.publish(version(1))
    sweeps = (
        Sweep(tick=1, values={"dp1": 12.0, "dp2": 1.0, "q1": 100.0, "q2": 100.0}),
        Sweep(tick=2, values={"dp1": 12.0, "dp2": 1.0, "q1": 100.0, "q2": 350.0}),
    )
    verdict = evaluate_round(opened, history, IMMEDIATE, sweeps, limits())
    assert verdict.leader.stage == "stage1"
    assert verdict.leader.criterion == PRESSURE_CRITERION
    assert verdict.leader.sensors == ("dp1",)
    assert verdict.leader.tick == 1


def test_sweeps_outside_the_round_are_ignored():
    opened = Round(train="RO-1", number=1, start_tick=2, assignment_version=1)
    history = AssignmentHistory("RO-1")
    history.publish(version(1))
    sweeps = (
        Sweep(tick=1, values={"dp1": 99.0, "dp2": 99.0, "q1": 999.0, "q2": 999.0}),
        Sweep(tick=2, values={"dp1": 1.0, "dp2": 1.0, "q1": 10.0, "q2": 10.0}),
    )
    verdict = evaluate_round(opened, history, IMMEDIATE, sweeps, limits())
    assert verdict.needs_clean is False


# --------------------------------------------------------- version policy


def test_round_boundary_policy_pins_the_starting_version():
    mon, _ = monitor("round_boundary")
    mon.register_train("RO-1", "round_boundary")
    mon.store_limits("RO-1", limits())
    mon.publish_assignment(
        "RO-1",
        {"dp1": "stage1", "dp2": "stage2"},
        {"q1": "stage1", "q2": "stage2"},
        tick=0,
    )
    opened = mon.open_round("RO-1", tick=1)
    mon.publish_assignment(
        "RO-1",
        {"dpA": "stage1", "dpB": "stage2"},
        {"qA": "stage1", "qB": "stage2"},
        tick=3,
    )
    resolved = version_for_tick(
        mon._load_history("RO-1"), opened, mon.policy_of("RO-1"), 4
    )
    assert resolved.version == 1


def test_immediate_policy_tracks_the_newest_effective_version():
    mon, _ = monitor(IMMEDIATE)
    mon.register_train("RO-1", IMMEDIATE)
    mon.store_limits("RO-1", limits())
    mon.publish_assignment(
        "RO-1",
        {"dp1": "stage1", "dp2": "stage2"},
        {"q1": "stage1", "q2": "stage2"},
        tick=0,
    )
    opened = mon.open_round("RO-1", tick=1)
    mon.publish_assignment(
        "RO-1",
        {"dpA": "stage1", "dpB": "stage2"},
        {"qA": "stage1", "qB": "stage2"},
        tick=3,
    )
    history = mon._load_history("RO-1")
    assert version_for_tick(history, opened, IMMEDIATE, 2).version == 1
    assert version_for_tick(history, opened, IMMEDIATE, 3).version == 2


def test_migration_policy_is_fixed_per_train():
    mon, _ = monitor("round_boundary")
    mon.register_train("RO-1", "round_boundary")
    with pytest.raises(TrainPolicyFixedError):
        mon.register_train("RO-1", IMMEDIATE)
    with pytest.raises(InvalidAssignmentError):
        mon.register_train("RO-2", "later")


# ------------------------------------------------------------- lifecycle


def _bootstrap(mon, policy, pressure=None, quality=None):
    mon.register_train("RO-1", policy)
    mon.store_limits("RO-1", limits())
    mon.publish_assignment(
        "RO-1",
        pressure or {"dp1": "stage1", "dp2": "stage2"},
        quality or {"q1": "stage1", "q2": "stage2"},
        tick=0,
    )


def test_round_lifecycle_freezes_the_verdict_on_close():
    mon, _ = monitor(IMMEDIATE)
    _bootstrap(mon, IMMEDIATE)
    mon.open_round("RO-1", tick=1)
    mon.record_sweep("RO-1", {"dp1": 1.0, "dp2": 1.0, "q1": 10.0, "q2": 10.0}, tick=2)
    verdict = mon.close_round("RO-1", tick=3)
    assert verdict.needs_clean is False
    assert mon.rounds("RO-1")[0].closed is True
    assert mon.stored_verdict("RO-1", 1).fingerprint == verdict.fingerprint
    check = mon.verify_consistency("RO-1", 1)
    assert check["consistent"] is True


def test_a_round_cannot_open_while_one_is_active():
    mon, _ = monitor(IMMEDIATE)
    _bootstrap(mon, IMMEDIATE)
    mon.open_round("RO-1", tick=1)
    with pytest.raises(RoundConflictError):
        mon.open_round("RO-1", tick=2)


def test_sweeps_require_an_open_round_and_ordered_ticks():
    mon, _ = monitor(IMMEDIATE)
    _bootstrap(mon, IMMEDIATE)
    with pytest.raises(RoundConflictError):
        mon.record_sweep("RO-1", {"dp1": 1.0}, tick=1)
    mon.open_round("RO-1", tick=2)
    with pytest.raises(RoundConflictError):
        mon.record_sweep("RO-1", {"dp1": 1.0}, tick=1)
    mon.record_sweep("RO-1", {"dp1": 1.0}, tick=2)
    with pytest.raises(RoundConflictError):
        mon.record_sweep("RO-1", {"dp1": 1.0}, tick=2)


def test_open_round_requires_an_assignment_and_a_registered_train():
    mon, _ = monitor(IMMEDIATE)
    mon.register_train("RO-9", IMMEDIATE)
    with pytest.raises(RoundConflictError):
        mon.open_round("RO-9", tick=1)
    with pytest.raises(UnknownTrainError):
        mon.open_round("missing", tick=1)


def test_round_references_validate():
    mon, _ = monitor(IMMEDIATE)
    with pytest.raises(UnknownTrainError):
        mon.round_at("missing", 1)
    _bootstrap(mon, IMMEDIATE)
    mon.open_round("RO-1", tick=1)
    with pytest.raises(UnknownRoundError):
        mon.round_at("RO-1", 99)


# --------------------------------------------------------- immutability


def test_round_boundary_round_keeps_its_version_after_a_migration():
    mon, _ = monitor("round_boundary")
    _bootstrap(mon, "round_boundary")
    mon.open_round("RO-1", tick=1)
    mon.record_sweep(
        "RO-1", {"dp1": 5.0, "dp2": 6.0, "q1": 100.0, "q2": 120.0}, tick=2
    )
    mon.publish_assignment(
        "RO-1",
        {"dp1": "stage1", "dp3": "stage2"},
        {"qA": "stage1", "qB": "stage2"},
        tick=3,
    )
    # New sensors exist but the in-flight round still judges under version 1,
    # so the new quality sensor cannot trip stage 2.
    mon.record_sweep(
        "RO-1", {"dp1": 5.0, "dp3": 9.0, "qA": 100.0, "qB": 350.0}, tick=4
    )
    live = mon.live_verdict("RO-1")
    assert live.needs_clean is False
    assert live.basis[-1].assignment_version == 1
    first = mon.close_round("RO-1", tick=5)
    assert first.needs_clean is False


def test_next_round_after_migration_uses_the_new_assignment():
    mon, _ = monitor("round_boundary")
    _bootstrap(mon, "round_boundary")
    mon.open_round("RO-1", tick=1)
    mon.record_sweep(
        "RO-1", {"dp1": 1.0, "dp2": 1.0, "q1": 10.0, "q2": 10.0}, tick=2
    )
    mon.close_round("RO-1", tick=3)
    mon.publish_assignment(
        "RO-1",
        {"dp1": "stage1", "dp3": "stage2"},
        {"qA": "stage1", "qB": "stage2"},
        tick=4,
    )
    mon.open_round("RO-1", tick=5)
    mon.record_sweep(
        "RO-1", {"dp1": 1.0, "dp3": 1.0, "qA": 10.0, "qB": 350.0}, tick=6
    )
    second = mon.close_round("RO-1", tick=7)
    assert second.leader.stage == "stage2"
    assert second.leader.sensors == ("qB",)
    assert second.leader.assignment_version == 2


def test_immediate_migration_applies_to_the_round_in_flight():
    mon, _ = monitor(IMMEDIATE)
    _bootstrap(mon, IMMEDIATE)
    mon.open_round("RO-1", tick=1)
    mon.record_sweep("RO-1", {"dp1": 5.0, "dp2": 1.0, "q1": 10.0, "q2": 10.0}, tick=2)
    mon.publish_assignment(
        "RO-1",
        {"dpA": "stage1", "dpB": "stage2"},
        {"qA": "stage1", "qB": "stage2"},
        tick=3,
    )
    mon.record_sweep("RO-1", {"dpA": 12.0, "dpB": 1.0, "qA": 10.0, "qB": 10.0}, tick=4)
    verdict = mon.close_round("RO-1", tick=5)
    assert verdict.leader.sensors == ("dpA",)
    assert [item.assignment_version for item in verdict.basis] == [1, 2]


def test_historical_replay_is_immune_to_later_migrations():
    mon, _ = monitor("round_boundary")
    _bootstrap(mon, "round_boundary")
    mon.open_round("RO-1", tick=1)
    mon.record_sweep(
        "RO-1", {"dp1": 5.0, "dp2": 6.0, "q1": 100.0, "q2": 120.0}, tick=2
    )
    first = mon.close_round("RO-1", tick=3)
    mon.publish_assignment(
        "RO-1", {"only": "stage1"}, {"quality": "stage1"}, tick=4
    )
    replayed = mon.replay("RO-1", 1)
    assert replayed.fingerprint == first.fingerprint
    assert replayed.basis[0].assignment_version == 1


def test_replay_refuses_an_open_round_and_reproducible_history_only():
    mon, _ = monitor(IMMEDIATE)
    _bootstrap(mon, IMMEDIATE)
    mon.open_round("RO-1", tick=1)
    with pytest.raises(RoundConflictError):
        mon.replay("RO-1", 1)
    mon.record_sweep("RO-1", {"dp1": 1.0, "dp2": 1.0, "q1": 1.0, "q2": 1.0}, tick=2)
    mon.close_round("RO-1", tick=3)
    assert mon.replay("RO-1", 1).needs_clean is False


def test_tampering_with_a_frozen_verdict_breaks_consistency():
    mon, store = monitor(IMMEDIATE)
    _bootstrap(mon, IMMEDIATE)
    mon.open_round("RO-1", tick=1)
    mon.record_sweep(
        "RO-1", {"dp1": 12.0, "dp2": 1.0, "q1": 10.0, "q2": 10.0}, tick=2
    )
    mon.close_round("RO-1", tick=3)
    key = "membrane/train/RO-1/verdicts/0001"
    row = store.get(key)
    row["leader"]["stage"] = "stage2"
    store.put(key, row)
    assert mon.verify_consistency("RO-1", 1)["consistent"] is False
    with pytest.raises(RoundConflictError):
        mon.replay("RO-1", 1)


def test_verdict_persists_across_a_restart(tmp_path):
    from desalplant.audit.recorder import Recorder

    path = str(tmp_path / "plant.json")
    store = Store(path)
    first = TrainMonitor(store, LogicalClock(), Recorder(store))
    _bootstrap(first, IMMEDIATE)
    first.open_round("RO-1", tick=1)
    first.record_sweep(
        "RO-1", {"dp1": 12.0, "dp2": 1.0, "q1": 10.0, "q2": 10.0}, tick=2
    )
    verdict = first.close_round("RO-1", tick=3)

    restarted_store = Store(path)
    restarted = TrainMonitor(
        restarted_store, LogicalClock(4), Recorder(restarted_store)
    )
    restarted.publish_assignment(
        "RO-1", {"x": "stage1", "y": "stage2"}, {"u": "stage1", "v": "stage2"}, tick=5
    )
    assert restarted.policy_of("RO-1") == IMMEDIATE
    assert restarted.replay("RO-1", 1).fingerprint == verdict.fingerprint
    assert restarted.verify_consistency("RO-1", 1)["consistent"] is True
