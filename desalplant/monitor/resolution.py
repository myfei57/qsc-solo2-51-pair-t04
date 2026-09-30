"""Resolve which assignment version governs each tick of a round.

Two migration policies are supported and fixed per train:

* ``round_boundary``: a round opened before a migration keeps the version it
  started on until it closes; the new version governs the next round.
* ``immediate``: the newest effective version governs every tick, including a
  round that was already in flight.

Either way, historical replay only ever reads versions published at the time:
the resolution is a pure function over the append-only history.
"""

from .assignment import (
    IMMEDIATE,
    ROUND_BOUNDARY,
    AssignmentHistory,
    AssignmentVersion,
)
from .round import Round


def version_for_tick(
    history: AssignmentHistory,
    opened: Round,
    policy: str,
    tick: int,
) -> AssignmentVersion:
    """Version judging ``tick`` of a round under the train's fixed policy."""
    if policy == ROUND_BOUNDARY:
        pinned = history.at(opened.assignment_version)
        if pinned is None:  # pragma: no cover - history never drops versions
            raise ValueError(f"round pinned version {opened.assignment_version} is missing")
        return pinned
    if policy == IMMEDIATE:
        current = history.effective(tick)
        if current is None:
            raise ValueError("no assignment version effective at the recorded tick")
        return current
    raise ValueError(f"unknown migration policy {policy}")
