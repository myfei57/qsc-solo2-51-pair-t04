"""Versioned sensor-to-stage assignment for one membrane train.

An assignment version is immutable once published: changing which sensor feeds
which stage appends a new version, it never rewrites an old one. The migration
policy decides when a newly published version starts to govern an in-flight
round, and that policy is fixed per train.
"""

from dataclasses import dataclass, field
from typing import Any, Mapping

from ..errors import (
    AssignmentOrderError,
    InvalidAssignmentError,
    TrainPolicyFixedError,
)

ROUND_BOUNDARY = "round_boundary"
IMMEDIATE = "immediate"
POLICIES = (ROUND_BOUNDARY, IMMEDIATE)


@dataclass(frozen=True)
class AssignmentVersion:
    """One immutable snapshot of the sensor-to-stage ownership table."""

    train: str
    version: int
    effective_tick: int
    pressure_sensors: Mapping[str, str] = field(default_factory=dict)
    quality_sensors: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.train:
            raise InvalidAssignmentError("assignment must name a train")
        if self.version < 1:
            raise InvalidAssignmentError("assignment version starts at one")
        if self.effective_tick < 0:
            raise InvalidAssignmentError("effective tick must not be negative")
        pressure = dict(self.pressure_sensors)
        quality = dict(self.quality_sensors)
        stages = set(pressure.values()) | set(quality.values())
        if not pressure or not quality:
            raise InvalidAssignmentError("every assignment needs pressure and quality sensors")
        if set(pressure.values()) != stages or set(quality.values()) != stages:
            raise InvalidAssignmentError("pressure and quality sensors must cover the same stages")
        if any(not sensor for sensor in (pressure | quality)):
            raise InvalidAssignmentError("sensor ids must not be empty")
        if any(not stage for stage in stages):
            raise InvalidAssignmentError("stage names must not be empty")
        if len(set(quality.values())) != len(quality):
            raise InvalidAssignmentError("each stage owns exactly one quality sensor")
        # Frozen mappings still share references; copy them so callers cannot
        # mutate a published version through the objects they handed in.
        object.__setattr__(self, "pressure_sensors", pressure)
        object.__setattr__(self, "quality_sensors", quality)

    def stages(self) -> tuple[str, ...]:
        """Stages covered by this version, in stable name order."""
        return tuple(sorted(set(self.pressure_sensors.values())))

    def pressure_stage(self, sensor: str) -> str:
        """Stage a pressure sensor belongs to, or an empty string when unknown."""
        return self.pressure_sensors.get(sensor, "")

    def quality_stage(self, sensor: str) -> str:
        """Stage a quality sensor belongs to, or an empty string when unknown."""
        return self.quality_sensors.get(sensor, "")

    def stage_pressure_sensors(self, stage: str) -> tuple[str, ...]:
        """Pressure sensors feeding one stage."""
        return tuple(sorted(s for s, owner in self.pressure_sensors.items() if owner == stage))

    def stage_quality_sensor(self, stage: str) -> str:
        """Quality sensor feeding one stage, or an empty string when unmapped."""
        for sensor, owner in self.quality_sensors.items():
            if owner == stage:
                return sensor
        return ""

    def fingerprint(self) -> str:
        """Stable textual identity used to prove which version produced a verdict."""
        return f"v{self.version}@t{self.effective_tick}"

    def to_dict(self) -> dict[str, Any]:
        """JSON-friendly projection used by the store and the console."""
        return {
            "train": self.train,
            "version": self.version,
            "effective_tick": self.effective_tick,
            "pressure_sensors": dict(self.pressure_sensors),
            "quality_sensors": dict(self.quality_sensors),
        }

    @classmethod
    def from_dict(cls, row: Mapping[str, Any]) -> "AssignmentVersion":
        """Rebuild a version from a persisted row."""
        return cls(
            train=str(row["train"]),
            version=int(row["version"]),
            effective_tick=int(row.get("effective_tick", 0)),
            pressure_sensors=dict(row.get("pressure_sensors", {})),
            quality_sensors=dict(row.get("quality_sensors", {})),
        )


def resolve_policy(policy: str) -> str:
    """Validate a migration policy label."""
    if policy not in POLICIES:
        raise InvalidAssignmentError(f"unknown migration policy {policy}")
    return policy


class AssignmentHistory:
    """Append-only chain of assignment versions for one train."""

    def __init__(self, train: str) -> None:
        self.train = train
        self._versions: dict[int, AssignmentVersion] = {}

    def publish(self, candidate: AssignmentVersion) -> AssignmentVersion:
        """Append a version; its number and effective tick must advance."""
        if candidate.train != self.train:
            raise InvalidAssignmentError("assignment belongs to another train")
        newest = self.newest_version()
        if newest is not None:
            if candidate.version != newest.version + 1:
                raise AssignmentOrderError("assignment version must advance by one")
            if candidate.effective_tick < newest.effective_tick:
                raise AssignmentOrderError("assignment effective tick must not move backwards")
        self._versions[candidate.version] = candidate
        return candidate

    def newest_version(self) -> AssignmentVersion | None:
        """Latest published version, or ``None`` before the first publication."""
        if not self._versions:
            return None
        return self._versions[max(self._versions)]

    def at(self, version: int) -> AssignmentVersion | None:
        """Version with an explicit number, or ``None`` when it was never published."""
        return self._versions.get(version)

    def effective(self, tick: int) -> AssignmentVersion | None:
        """Newest version whose effective tick is not later than ``tick``."""
        chosen: AssignmentVersion | None = None
        for candidate in self._versions.values():
            if candidate.effective_tick <= tick and (
                chosen is None or candidate.version > chosen.version
            ):
                chosen = candidate
        return chosen

    def versions(self) -> tuple[AssignmentVersion, ...]:
        """Every published version, oldest first."""
        return tuple(self._versions[number] for number in sorted(self._versions))


def require_same_policy(train: str, stored: str, requested: str) -> str:
    """Reject an attempt to change a train's fixed migration policy."""
    if stored != requested:
        raise TrainPolicyFixedError(
            f"train {train} migration policy is fixed to {stored}, cannot set {requested}"
        )
    return stored
