"""Per-stage cleaning judgment from differential pressure and permeate quality.

A membrane group is judged stage by stage, never by total flow. Each stage has
a differential pressure (压差) reading and a permeate quality (产水水质)
reading. A stage reaches its cleaning condition when either reading crosses its
limit.

The first stage to reach the cleaning condition is reported together with the
measurement point (测点) that triggered it and the attribution version used.
"""

from dataclasses import dataclass
from typing import Any, Mapping

from .attribution import AttributionVersion

DIFFERENTIAL = "differential"
QUALITY = "quality"
NO_TRIGGER = ""


@dataclass(frozen=True)
class StageReading:
    """One stage's readings and the limits it is judged against."""

    stage: str
    differential: float
    conductivity: float
    differential_limit: float
    quality_limit: float

    def differential_due(self) -> bool:
        """Whether the differential pressure crosses its limit."""
        return self.differential > self.differential_limit

    def quality_due(self) -> bool:
        """Whether the permeate quality crosses its limit."""
        return self.conductivity > self.quality_limit

    def due(self) -> bool:
        """Whether either reading calls for a clean."""
        return self.differential_due() or self.quality_due()

    def trigger(self) -> str:
        """Which reading triggered the cleaning condition, or empty string."""
        if self.differential_due():
            return DIFFERENTIAL
        if self.quality_due():
            return QUALITY
        return NO_TRIGGER

    def trigger_value(self) -> float:
        """Value of the triggering reading (0 when not due)."""
        if self.differential_due():
            return self.differential
        if self.quality_due():
            return self.conductivity
        return 0.0

    def trigger_limit(self) -> float:
        """Limit of the triggering reading (0 when not due)."""
        if self.differential_due():
            return self.differential_limit
        if self.quality_due():
            return self.quality_limit
        return 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "differential": self.differential,
            "conductivity": self.conductivity,
            "differential_limit": self.differential_limit,
            "quality_limit": self.quality_limit,
            "due": self.due(),
            "trigger": self.trigger(),
        }

    @classmethod
    def from_dict(cls, row: Mapping[str, Any]) -> "StageReading":
        return cls(
            stage=str(row["stage"]),
            differential=float(row["differential"]),
            conductivity=float(row["conductivity"]),
            differential_limit=float(row["differential_limit"]),
            quality_limit=float(row["quality_limit"]),
        )


@dataclass(frozen=True)
class CleaningVerdict:
    """The first stage to reach cleaning condition and its basis."""

    stage: str
    sensor: str
    trigger: str
    value: float
    limit: float
    version: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "sensor": self.sensor,
            "trigger": self.trigger,
            "value": self.value,
            "limit": self.limit,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, row: Mapping[str, Any]) -> "CleaningVerdict":
        return cls(
            stage=str(row["stage"]),
            sensor=str(row.get("sensor", "")),
            trigger=str(row.get("trigger", "")),
            value=float(row.get("value", 0.0)),
            limit=float(row.get("limit", 0.0)),
            version=int(row.get("version", 0)),
        )


def first_due_stage(
    readings: tuple[StageReading, ...],
    version: AttributionVersion,
) -> CleaningVerdict | None:
    """Pick the first stage due for cleaning and the sensor that triggered it.

    Stages are considered in order; the first stage whose trigger is set wins.
    The sensor is the first sensor attributed to that stage in the version.
    """
    for reading in readings:
        if not reading.due():
            continue
        sensors = version.stage_sensors(reading.stage)
        sensor = sensors[0] if sensors else ""
        return CleaningVerdict(
            stage=reading.stage,
            sensor=sensor,
            trigger=reading.trigger(),
            value=reading.trigger_value(),
            limit=reading.trigger_limit(),
            version=version.version,
        )
    return None
