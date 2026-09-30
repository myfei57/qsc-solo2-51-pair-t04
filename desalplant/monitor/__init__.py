"""Per-stage cleaning monitor with versioned sensor ownership.

The package answers one question — which membrane stage reaches a cleaning
condition first — from differential pressure and permeate quality, while
keeping historical conclusions stable across sensor-assignment migrations.
"""

from .assignment import (
    IMMEDIATE,
    ROUND_BOUNDARY,
    AssignmentHistory,
    AssignmentVersion,
)
from .evaluate import (
    CriterionState,
    LeadingStage,
    RoundVerdict,
    StageVerdict,
    TickBasis,
    evaluate_round,
    evaluate_sweep,
    verdict_from_dict,
)
from .limits import (
    PRESSURE_CRITERION,
    QUALITY_CRITERION,
    CleanLimits,
    StageLimit,
)
from .resolution import version_for_tick
from .round import Round, Sweep
from .service import TrainMonitor

__all__ = [
    "IMMEDIATE",
    "PRESSURE_CRITERION",
    "QUALITY_CRITERION",
    "ROUND_BOUNDARY",
    "AssignmentHistory",
    "AssignmentVersion",
    "CleanLimits",
    "CriterionState",
    "LeadingStage",
    "Round",
    "RoundVerdict",
    "StageLimit",
    "StageVerdict",
    "Sweep",
    "TickBasis",
    "TrainMonitor",
    "evaluate_round",
    "evaluate_sweep",
    "verdict_from_dict",
    "version_for_tick",
]
