"""Per-train cleaning monitor behind console actions.

Every surface — real-time verdict, audit/history replay and external data —
goes through the same ``TrainMonitor`` methods, so the three can be checked
against one verdict fingerprint.
"""

from typing import Any

from ..errors import UnknownTrainError
from ..monitor import (
    IMMEDIATE,
    ROUND_BOUNDARY,
    CleanLimits,
    StageLimit,
)
from .http import Request

DEFAULT_PRESSURE_LIMIT = 10.0
DEFAULT_CONDUCTIVITY_LIMIT = 300.0


def _train(request: Request) -> str:
    train = request.param("train")
    if not train:
        raise ValueError("train is required")
    return train


def register(plant, request: Request) -> dict[str, Any]:
    """Fix one train's migration policy."""
    body = request.body()
    train = str(body.get("train") or _train(request))
    policy = str(body.get("policy", ROUND_BOUNDARY))
    if policy not in (ROUND_BOUNDARY, IMMEDIATE):
        raise ValueError(f"unknown migration policy {policy}")
    fixed = plant.train_monitor.register_train(train, policy)
    stages = tuple(str(stage) for stage in body.get("stages", ()))
    if stages and "limits" not in body:
        plant.train_monitor.store_limits(
            train,
            CleanLimits.uniform(
                stages, DEFAULT_PRESSURE_LIMIT, DEFAULT_CONDUCTIVITY_LIMIT
            ),
        )
    if isinstance(body.get("limits"), dict):
        plant.train_monitor.store_limits(train, _build_limits(body["limits"]))
    return {"train": train, "policy": fixed}


def publish_assignment(plant, request: Request) -> dict[str, Any]:
    """Append a new sensor-to-stage version for a train."""
    body = request.body()
    train = str(body.get("train") or _train(request))
    version = body.get("version")
    tick = body.get("tick")
    published = plant.train_monitor.publish_assignment(
        train,
        pressure_sensors={
            str(sensor): str(stage) for sensor, stage in body["pressure_sensors"].items()
        },
        quality_sensors={
            str(sensor): str(stage) for sensor, stage in body["quality_sensors"].items()
        },
        version=None if version is None else int(version),
        tick=None if tick is None else int(tick),
    )
    return {"assignment": published.to_dict()}


def open_round(plant, request: Request) -> dict[str, Any]:
    """Open a round pinned to the assignment in force at its start."""
    body = request.body()
    train = str(body.get("train") or _train(request))
    tick = body.get("tick")
    opened = plant.train_monitor.open_round(
        train, None if tick is None else int(tick)
    )
    return {"round": opened.to_dict()}


def record_sweep(plant, request: Request) -> dict[str, Any]:
    """Append one sensor sweep to the open round."""
    body = request.body()
    train = str(body.get("train") or _train(request))
    tick = body.get("tick")
    sweep = plant.train_monitor.record_sweep(
        train,
        {str(sensor): float(value) for sensor, value in body["values"].items()},
        None if tick is None else int(tick),
    )
    return {"sweep": sweep.to_dict()}


def close_round(plant, request: Request) -> dict[str, Any]:
    """Close the open round and freeze its verdict."""
    body = request.body()
    train = str(body.get("train") or _train(request))
    tick = body.get("tick")
    verdict = plant.train_monitor.close_round(train, None if tick is None else int(tick))
    return {"verdict": verdict.to_dict()}


def live_verdict(plant, request: Request) -> dict[str, Any]:
    """Real-time verdict of the round in flight (read side)."""
    train = _train(request)
    return {"verdict": plant.train_monitor.live_verdict(train).to_dict()}


def replay(plant, request: Request) -> dict[str, Any]:
    """Historical verdict reconstructed under the assignment version at the time."""
    train = _train(request)
    round_no = request.integer("round", 0)
    if round_no < 1:
        raise ValueError("round is required")
    return {"verdict": plant.train_monitor.replay(train, round_no).to_dict()}


def consistency(plant, request: Request) -> dict[str, Any]:
    """Cross-check token for realtime, audit and external consumers."""
    train = _train(request)
    round_no = request.integer("round", 0)
    if round_no < 1:
        raise ValueError("round is required")
    report = plant.train_monitor.verify_consistency(train, round_no)
    return dict(report)


def list_trains(plant, request: Request) -> dict[str, Any]:
    """Registered trains and their fixed policies."""
    monitor = plant.train_monitor
    return {
        "trains": [
            {"train": train, "policy": monitor.policy_of(train)}
            for train in monitor.trains()
        ]
    }


def list_assignments(plant, request: Request) -> dict[str, Any]:
    """Assignment version chain of one train."""
    train = _train(request)
    return {
        "train": train,
        "policy": plant.train_monitor.policy_of(train),
        "assignments": [
            version.to_dict()
            for version in plant.train_monitor.assignments(train)
        ],
    }


def list_rounds(plant, request: Request) -> dict[str, Any]:
    """Rounds of one train with their pinned assignment versions."""
    train = _train(request)
    return {
        "train": train,
        "rounds": [round_.to_dict() for round_ in plant.train_monitor.rounds(train)],
    }


def stored_verdict(plant, request: Request) -> dict[str, Any]:
    """Frozen verdict of a closed round, straight from the audit record."""
    train = _train(request)
    round_no = request.integer("round", 0)
    if round_no < 1:
        raise ValueError("round is required")
    frozen = plant.train_monitor.stored_verdict(train, round_no)
    if frozen is None:
        raise UnknownTrainError(f"train {train} round {round_no} has no frozen verdict")
    return {"verdict": frozen.to_dict()}


def _build_limits(raw: dict[str, Any]) -> CleanLimits:
    limits: dict[str, StageLimit] = {}
    for stage, values in raw.items():
        limits[str(stage)] = StageLimit(
            stage=str(stage),
            pressure=float(values["pressure"]),
            conductivity=float(values["conductivity"]),
        )
    return CleanLimits(limits)
