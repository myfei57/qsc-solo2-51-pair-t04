"""Per-stage cleaning judgement over the sweeps of one round.

A stage is judged on two independent criteria: its summed differential-pressure
readings and its permeate conductivity. The stage that crosses a limit first is
the cleaning leader, and the basis records which sensor reading made it cross,
so the conclusion is replayable against the assignment version in force at the
time.
"""

from dataclasses import dataclass
import hashlib
from typing import Any, Mapping

from ..store.codec import canonical
from .assignment import AssignmentHistory, AssignmentVersion
from .limits import (
    PRESSURE_CRITERION,
    QUALITY_CRITERION,
    CleanLimits,
)
from .resolution import version_for_tick
from .round import Round, Sweep


@dataclass(frozen=True)
class CriterionState:
    """One criterion of one stage at the end of the round."""

    stage: str
    criterion: str
    value: float
    limit: float
    crossed: bool

    def to_dict(self) -> dict[str, Any]:
        """JSON-friendly projection."""
        return {
            "stage": self.stage,
            "criterion": self.criterion,
            "value": self.value,
            "limit": self.limit,
            "crossed": self.crossed,
        }


@dataclass(frozen=True)
class StageVerdict:
    """Independent pressure and quality judgement of one stage."""

    stage: str
    pressure: CriterionState
    quality: CriterionState
    needs_clean: bool

    def to_dict(self) -> dict[str, Any]:
        """JSON-friendly projection."""
        return {
            "stage": self.stage,
            "pressure": self.pressure.to_dict(),
            "quality": self.quality.to_dict(),
            "needs_clean": self.needs_clean,
        }


@dataclass(frozen=True)
class TickBasis:
    """One sweep evaluation, showing the exact version that resolved its sensors."""

    tick: int
    assignment_version: int
    assignment_fingerprint: str
    stages: tuple[CriterionState, ...]

    def to_dict(self) -> dict[str, Any]:
        """JSON-friendly projection."""
        return {
            "tick": self.tick,
            "assignment_version": self.assignment_version,
            "assignment_fingerprint": self.assignment_fingerprint,
            "stages": [state.to_dict() for state in self.stages],
        }


@dataclass(frozen=True)
class LeadingStage:
    """The first stage to reach a cleaning condition."""

    stage: str
    tick: int
    criterion: str
    value: float
    limit: float
    sensors: tuple[str, ...]
    assignment_version: int

    def to_dict(self) -> dict[str, Any]:
        """JSON-friendly projection."""
        return {
            "stage": self.stage,
            "tick": self.tick,
            "criterion": self.criterion,
            "value": self.value,
            "limit": self.limit,
            "sensors": list(self.sensors),
            "assignment_version": self.assignment_version,
        }


@dataclass(frozen=True)
class RoundVerdict:
    """Immutable conclusion for one round: leader, per-stage states and the basis."""

    train: str
    round: int
    policy: str
    needs_clean: bool
    leader: LeadingStage | None
    stages: tuple[StageVerdict, ...]
    basis: tuple[TickBasis, ...]
    limits: Mapping[str, Any]
    fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        """JSON-friendly projection used by every consumer."""
        return {
            "train": self.train,
            "round": self.round,
            "policy": self.policy,
            "needs_clean": self.needs_clean,
            "leader": None if self.leader is None else self.leader.to_dict(),
            "stages": [stage.to_dict() for stage in self.stages],
            "basis": [tick_basis.to_dict() for tick_basis in self.basis],
            "limits": dict(self.limits),
            "fingerprint": self.fingerprint,
        }


def evaluate_sweep(
    assignment: AssignmentVersion,
    limits: CleanLimits,
    sweep: Sweep,
) -> TickBasis:
    """Evaluate every stage of one sweep against one resolved assignment version."""
    states: list[CriterionState] = []
    for stage in assignment.stages():
        limit = limits.for_stage(stage)
        pressure_sensors = assignment.stage_pressure_sensors(stage)
        pressure_value = sum(
            (
                value
                for sensor in pressure_sensors
                if (value := sweep.reading(sensor)) is not None
            ),
            0.0,
        )
        states.append(
            CriterionState(
                stage=stage,
                criterion=PRESSURE_CRITERION,
                value=pressure_value,
                limit=limit.pressure,
                crossed=pressure_value > limit.pressure,
            )
        )
        quality_sensor = assignment.stage_quality_sensor(stage)
        quality_value = sweep.reading(quality_sensor) if quality_sensor else None
        states.append(
            CriterionState(
                stage=stage,
                criterion=QUALITY_CRITERION,
                value=0.0 if quality_value is None else quality_value,
                limit=limit.conductivity,
                crossed=quality_value is not None and quality_value > limit.conductivity,
            )
        )
    return TickBasis(
        tick=sweep.tick,
        assignment_version=assignment.version,
        assignment_fingerprint=assignment.fingerprint(),
        stages=tuple(states),
    )


def evaluate_round(
    opened: Round,
    history: AssignmentHistory,
    policy: str,
    sweeps: tuple[Sweep, ...],
    limits: CleanLimits,
) -> RoundVerdict:
    """Judge a whole round, pinning the version policy says governs each tick."""
    ordered = tuple(sorted(sweeps, key=lambda sweep: sweep.tick))
    basis: list[TickBasis] = []
    final_pressure: dict[str, CriterionState] = {}
    final_quality: dict[str, CriterionState] = {}
    leader: LeadingStage | None = None
    for sweep in ordered:
        if not opened.spans(sweep.tick):
            continue
        assignment = version_for_tick(history, opened, policy, sweep.tick)
        if not limits.covers(assignment.stages()):
            raise ValueError("cleaning limits do not cover every assigned stage")
        tick_basis = evaluate_sweep(assignment, limits, sweep)
        basis.append(tick_basis)
        for state in tick_basis.stages:
            target = final_pressure if state.criterion == PRESSURE_CRITERION else final_quality
            target[state.stage] = state
            if state.crossed:
                candidate = _leading_from(tick_basis, state, assignment)
                leader = _earlier(leader, candidate)

    stages = tuple(
        StageVerdict(
            stage=stage,
            pressure=final_pressure[stage],
            quality=final_quality[stage],
            needs_clean=final_pressure[stage].crossed or final_quality[stage].crossed,
        )
        for stage in sorted(set(final_pressure) | set(final_quality))
    )
    verdict = RoundVerdict(
        train=opened.train,
        round=opened.number,
        policy=policy,
        needs_clean=leader is not None,
        leader=leader,
        stages=stages,
        basis=tuple(basis),
        limits=limits.to_dict(),
        fingerprint="",
    )
    return _with_fingerprint(verdict)


def _leading_from(
    tick_basis: TickBasis, state: CriterionState, assignment: AssignmentVersion
) -> LeadingStage:
    if state.criterion == PRESSURE_CRITERION:
        sensors = assignment.stage_pressure_sensors(state.stage)
    else:
        sensor = assignment.stage_quality_sensor(state.stage)
        sensors = (sensor,) if sensor else ()
    return LeadingStage(
        stage=state.stage,
        tick=tick_basis.tick,
        criterion=state.criterion,
        value=state.value,
        limit=state.limit,
        sensors=sensors,
        assignment_version=tick_basis.assignment_version,
    )


def _earlier(current: LeadingStage | None, candidate: LeadingStage) -> LeadingStage:
    if current is None:
        return candidate
    candidate_key = (candidate.tick, candidate.stage, 0 if candidate.criterion == PRESSURE_CRITERION else 1)
    current_key = (current.tick, current.stage, 0 if current.criterion == PRESSURE_CRITERION else 1)
    return candidate if candidate_key < current_key else current


def fingerprint_verdict(verdict: RoundVerdict) -> str:
    """Recompute the fingerprint a verdict's own content ought to carry."""
    leader = None
    if verdict.leader is not None:
        leader = {
            "stage": verdict.leader.stage,
            "tick": verdict.leader.tick,
            "criterion": verdict.leader.criterion,
            "value": verdict.leader.value,
            "limit": verdict.leader.limit,
            "sensors": list(verdict.leader.sensors),
            "assignment_version": verdict.leader.assignment_version,
        }
    payload = {
        "train": verdict.train,
        "round": verdict.round,
        "policy": verdict.policy,
        "limits": verdict.limits,
        "needs_clean": verdict.needs_clean,
        "leader": leader,
        "stages": [stage.to_dict() for stage in verdict.stages],
        "basis": [
            {
                "tick": item.tick,
                "assignment_version": item.assignment_version,
                "stages": [state.to_dict() for state in item.stages],
            }
            for item in verdict.basis
        ],
    }
    return hashlib.sha256(canonical(payload).encode("utf-8")).hexdigest()


def _with_fingerprint(verdict: RoundVerdict) -> RoundVerdict:
    digest = fingerprint_verdict(verdict)
    return RoundVerdict(
        train=verdict.train,
        round=verdict.round,
        policy=verdict.policy,
        needs_clean=verdict.needs_clean,
        leader=verdict.leader,
        stages=verdict.stages,
        basis=verdict.basis,
        limits=verdict.limits,
        fingerprint=digest,
    )


def _criterion_from_dict(row: Mapping[str, Any]) -> CriterionState:
    return CriterionState(
        stage=str(row["stage"]),
        criterion=str(row["criterion"]),
        value=float(row["value"]),
        limit=float(row["limit"]),
        crossed=bool(row["crossed"]),
    )


def verdict_from_dict(row: Mapping[str, Any]) -> RoundVerdict:
    """Rebuild a verdict from a JSON projection, keeping its frozen fingerprint."""
    stage_rows = {item["stage"]: item for item in row.get("stages", [])}
    stages = tuple(
        StageVerdict(
            stage=stage,
            pressure=_criterion_from_dict(stage_rows[stage]["pressure"]),
            quality=_criterion_from_dict(stage_rows[stage]["quality"]),
            needs_clean=bool(stage_rows[stage]["needs_clean"]),
        )
        for stage in sorted(stage_rows)
    )
    leader_row = row.get("leader")
    leader = None if leader_row is None else LeadingStage(
        stage=str(leader_row["stage"]),
        tick=int(leader_row["tick"]),
        criterion=str(leader_row["criterion"]),
        value=float(leader_row["value"]),
        limit=float(leader_row["limit"]),
        sensors=tuple(str(sensor) for sensor in leader_row.get("sensors", [])),
        assignment_version=int(leader_row["assignment_version"]),
    )
    basis = tuple(
        TickBasis(
            tick=int(item["tick"]),
            assignment_version=int(item["assignment_version"]),
            assignment_fingerprint=str(item.get("assignment_fingerprint", "")),
            stages=tuple(_criterion_from_dict(state) for state in item.get("stages", [])),
        )
        for item in row.get("basis", [])
    )
    return RoundVerdict(
        train=str(row["train"]),
        round=int(row["round"]),
        policy=str(row["policy"]),
        needs_clean=bool(row["needs_clean"]),
        leader=leader,
        stages=stages,
        basis=basis,
        limits=dict(row.get("limits", {})),
        fingerprint=str(row.get("fingerprint", "")),
    )
