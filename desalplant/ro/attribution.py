"""Versioned sensor-to-stage attribution for a membrane group.

The attribution (which measurement points belong to which stage) is versioned
configuration. A change to the attribution is a migration: the round that
started before the change is calculated with the version that was in effect
when it started, and historical replays use the version that was in effect at
the replayed time. History is immutable.

The migration policy is fixed per membrane group:
- ``continue_current_round``: the current round keeps the version that was in
  effect when it started; the new version applies to the next round.
- ``immediate``: the new version takes effect immediately, even for the current
  round.
"""

from dataclasses import dataclass
from typing import Any, Mapping

CONTINUE_CURRENT_ROUND = "continue_current_round"
IMMEDIATE = "immediate"
VALID_POLICIES = frozenset({CONTINUE_CURRENT_ROUND, IMMEDIATE})


@dataclass(frozen=True)
class AttributionVersion:
    """A single immutable version of the sensor-to-stage attribution."""

    version: int
    mapping: Mapping[str, str]
    created_tick: int
    policy: str

    def __post_init__(self) -> None:
        if self.policy not in VALID_POLICIES:
            raise ValueError(f"unknown migration policy: {self.policy}")

    def sensor_stage(self, sensor: str) -> str:
        """Stage a sensor belongs to in this version, or empty string."""
        return self.mapping.get(sensor, "")

    def stage_sensors(self, stage: str) -> tuple[str, ...]:
        """Sensors mapped onto a stage in this version, sorted by name."""
        return tuple(
            sorted(sensor for sensor, mapped in self.mapping.items() if mapped == stage)
        )

    def stages(self) -> tuple[str, ...]:
        """Distinct stage names in this version, sorted."""
        return tuple(sorted({stage for stage in self.mapping.values() if stage}))

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "mapping": dict(sorted(self.mapping.items())),
            "created_tick": self.created_tick,
            "policy": self.policy,
        }

    @classmethod
    def from_dict(cls, row: Mapping[str, Any]) -> "AttributionVersion":
        return cls(
            version=int(row["version"]),
            mapping=dict(row["mapping"]),
            created_tick=int(row.get("created_tick", 0)),
            policy=str(row.get("policy", CONTINUE_CURRENT_ROUND)),
        )


def initial_version(stages: int, tick: int, policy: str) -> AttributionVersion:
    """Build the first attribution version for a stage count."""
    mapping = {f"s{index}": f"stage{index}" for index in range(1, stages + 1)}
    return AttributionVersion(version=1, mapping=mapping, created_tick=tick, policy=policy)
