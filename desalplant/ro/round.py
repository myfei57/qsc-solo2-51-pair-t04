"""A production round of the membrane group.

A round locks in the attribution version that was in effect when it started.
Every sweep in the round is judged against that version, so a migration that
lands mid-round does not rewrite the round's conclusions.

Historical replays use the round's locked version, which makes history
immutable: replaying a past round always yields the conclusion it would have
yielded at the time.
"""

from dataclasses import dataclass, field
from typing import Any, Mapping

from .attribution import AttributionVersion
from .cleaning import CleaningVerdict, StageReading, first_due_stage


@dataclass(frozen=True)
class RoundSweep:
    """Per-stage readings captured at one tick."""

    tick: int
    readings: tuple[StageReading, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "tick": self.tick,
            "readings": [reading.to_dict() for reading in self.readings],
        }

    @classmethod
    def from_dict(cls, row: Mapping[str, Any]) -> "RoundSweep":
        return cls(
            tick=int(row["tick"]),
            readings=tuple(StageReading.from_dict(r) for r in row["readings"]),
        )


@dataclass
class Round:
    """A production round with a locked attribution version."""

    round_id: str
    version: AttributionVersion
    start_tick: int
    sweeps: list[RoundSweep] = field(default_factory=list)

    def record(self, tick: int, readings: tuple[StageReading, ...]) -> RoundSweep:
        """Append a sweep and return it."""
        sweep = RoundSweep(tick=tick, readings=readings)
        self.sweeps.append(sweep)
        return sweep

    def verdict(self) -> CleaningVerdict | None:
        """The first stage to reach cleaning condition across all sweeps.

        Sweeps are considered in order; the first stage whose trigger is set
        in the earliest sweep wins. The attribution version locked at round
        start is used throughout.
        """
        for sweep in self.sweeps:
            verdict = first_due_stage(sweep.readings, self.version)
            if verdict is not None:
                return verdict
        return None

    def sweep_count(self) -> int:
        """Number of sweeps recorded in this round."""
        return len(self.sweeps)

    def to_dict(self) -> dict[str, Any]:
        return {
            "round_id": self.round_id,
            "version": self.version.version,
            "start_tick": self.start_tick,
            "sweeps": [sweep.to_dict() for sweep in self.sweeps],
        }

    @classmethod
    def from_dict(
        cls,
        row: Mapping[str, Any],
        version: AttributionVersion,
    ) -> "Round":
        round_obj = cls(
            round_id=str(row["round_id"]),
            version=version,
            start_tick=int(row["start_tick"]),
        )
        for sweep_row in row.get("sweeps", []):
            round_obj.sweeps.append(RoundSweep.from_dict(sweep_row))
        return round_obj
