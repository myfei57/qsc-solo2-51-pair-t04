"""A production round and the telemetry sweeps captured inside it.

A round is the stretch of running between two cleans. The assignment version
that judges the round is fixed when the round opens under the round-boundary
policy, so a later ownership migration can never rewrite a round already in
flight.
"""

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class Round:
    """One bounded stretch of production for one train."""

    train: str
    number: int
    start_tick: int
    assignment_version: int
    end_tick: int | None = None
    closed: bool = False

    def __post_init__(self) -> None:
        if not self.train:
            raise ValueError("round must name a train")
        if self.number < 1:
            raise ValueError("round number starts at one")
        if self.assignment_version < 1:
            raise ValueError("round must pin an assignment version")
        if self.end_tick is not None and self.end_tick < self.start_tick:
            raise ValueError("round cannot end before it started")

    def spans(self, tick: int) -> bool:
        """Whether ``tick`` belongs to this round."""
        if tick < self.start_tick:
            return False
        return self.end_tick is None or tick <= self.end_tick

    def closed_at(self, tick: int) -> "Round":
        """Return a closed copy ending at ``tick``."""
        if tick < self.start_tick:
            raise ValueError("round cannot end before it started")
        return Round(
            train=self.train,
            number=self.number,
            start_tick=self.start_tick,
            assignment_version=self.assignment_version,
            end_tick=tick,
            closed=True,
        )

    def to_dict(self) -> dict[str, Any]:
        """JSON-friendly projection used by the store."""
        return {
            "train": self.train,
            "number": self.number,
            "start_tick": self.start_tick,
            "assignment_version": self.assignment_version,
            "end_tick": self.end_tick,
            "closed": self.closed,
        }

    @classmethod
    def from_dict(cls, row: Mapping[str, Any]) -> "Round":
        """Rebuild a round from a persisted row."""
        raw_end = row.get("end_tick")
        return cls(
            train=str(row["train"]),
            number=int(row["number"]),
            start_tick=int(row["start_tick"]),
            assignment_version=int(row["assignment_version"]),
            end_tick=None if raw_end is None else int(raw_end),
            closed=bool(row.get("closed", False)),
        )


@dataclass(frozen=True)
class Sweep:
    """All raw sensor values captured in one sweep at one tick."""

    tick: int
    values: Mapping[str, float]

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", {str(k): float(v) for k, v in self.values.items()})

    def reading(self, sensor: str) -> float | None:
        """Value of one sensor, or ``None`` when the sweep did not carry it."""
        if sensor not in self.values:
            return None
        return self.values[sensor]

    def to_dict(self) -> dict[str, Any]:
        """JSON-friendly projection used by the store."""
        return {"tick": self.tick, "values": dict(self.values)}

    @classmethod
    def from_dict(cls, row: Mapping[str, Any]) -> "Sweep":
        """Rebuild a sweep from a persisted row."""
        return cls(tick=int(row["tick"]), values=dict(row.get("values", {})))
