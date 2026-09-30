"""Per-stage cleaning limits.

Each stage is judged independently: its differential pressure must stay under
``pressure`` and its permeate conductivity must stay under ``conductivity``.
The limits are carried in the verdict so a historical conclusion never depends
on today's thresholds.
"""

from dataclasses import dataclass
from typing import Any, Mapping

from ..errors import InvalidAssignmentError

PRESSURE_CRITERION = "differential_pressure"
QUALITY_CRITERION = "permeate_conductivity"


@dataclass(frozen=True)
class StageLimit:
    """Cleaning thresholds for one stage."""

    stage: str
    pressure: float
    conductivity: float

    def __post_init__(self) -> None:
        if not self.stage:
            raise InvalidAssignmentError("limit must name a stage")
        if self.pressure <= 0 or self.conductivity <= 0:
            raise InvalidAssignmentError("cleaning limits must be positive")

    def to_dict(self) -> dict[str, Any]:
        """JSON-friendly projection."""
        return {"stage": self.stage, "pressure": self.pressure, "conductivity": self.conductivity}


class CleanLimits:
    """Immutable per-stage limit table used by one evaluation."""

    def __init__(self, stages: Mapping[str, StageLimit]) -> None:
        table = dict(stages)
        if not table:
            raise InvalidAssignmentError("cleaning limits must cover at least one stage")
        if any(not stage for stage in table):
            raise InvalidAssignmentError("stage names must not be empty")
        self._stages = table

    def for_stage(self, stage: str) -> StageLimit:
        """Limits of one stage."""
        return self._stages[stage]

    def stages(self) -> tuple[str, ...]:
        """Stages carrying limits, in stable name order."""
        return tuple(sorted(self._stages))

    def covers(self, stages: tuple[str, ...]) -> bool:
        """Whether every assignment stage carries a limit."""
        return set(stages) <= set(self._stages)

    def to_dict(self) -> dict[str, Any]:
        """JSON-friendly projection, keyed by stage."""
        return {stage: limit.to_dict() for stage, limit in self._stages.items()}

    @classmethod
    def from_dict(cls, row: Mapping[str, Any]) -> "CleanLimits":
        """Rebuild a limit table from a JSON projection."""
        stages = {}
        for stage, raw in row.items():
            stages[str(stage)] = StageLimit(
                stage=str(stage),
                pressure=float(raw["pressure"]),
                conductivity=float(raw["conductivity"]),
            )
        return cls(stages)

    @classmethod
    def uniform(cls, stages: tuple[str, ...], pressure: float, conductivity: float) -> "CleanLimits":
        """Build a table applying the same pair of limits to every stage."""
        if not stages:
            raise InvalidAssignmentError("cleaning limits must cover at least one stage")
        return cls(
            {stage: StageLimit(stage, pressure, conductivity) for stage in stages}
        )
