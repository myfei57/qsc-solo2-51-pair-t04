"""Request routing for the control console."""

from typing import Any, Callable

from ..errors import (
    AlarmNotActiveError,
    AssignmentOrderError,
    ContractError,
    FeedAlreadyStoppedError,
    FlushNotEffectiveError,
    FlowNotReadyError,
    HandoffIncompleteError,
    InvalidAssignmentError,
    InvalidEfficiencyError,
    InvalidStagesError,
    MediaNotReadyError,
    MembraneCrackedError,
    PermeateRejectedError,
    PumpAlreadyStoppedError,
    ResidualAntiscalantError,
    RinseFailedError,
    RoundConflictError,
    StoreError,
    SupplyInterruptedError,
    TrainPolicyFixedError,
    TransferFailedError,
    UnknownKeyError,
    UnknownRoundError,
    UnknownTrainError,
    ValveNotOpenError,
)
from . import handlers, operations, routes
from .http import Request, Response, error_response

Handler = Callable[["Console", Request], Response]

CONFLICT = (
    FlowNotReadyError,
    MembraneCrackedError,
    FlushNotEffectiveError,
    PumpAlreadyStoppedError,
    ValveNotOpenError,
    FeedAlreadyStoppedError,
    ResidualAntiscalantError,
    PermeateRejectedError,
    SupplyInterruptedError,
    HandoffIncompleteError,
    AlarmNotActiveError,
    TransferFailedError,
    RinseFailedError,
    MediaNotReadyError,
    RoundConflictError,
    TrainPolicyFixedError,
    AssignmentOrderError,
)
MALFORMED = (InvalidEfficiencyError, InvalidStagesError, InvalidAssignmentError)
MISSING = (UnknownKeyError, UnknownTrainError, UnknownRoundError)

ROUTES: tuple[tuple[str, str, Handler], ...] = (
    *((method, path, handler) for path, handler in handlers.ROUTE_TABLE for method in ("GET",)),
    ("POST", routes.START, operations.start),
    ("POST", routes.SHUTDOWN, operations.shutdown),
    ("POST", routes.SWITCH, operations.switch),
    ("POST", routes.MAINTAIN, operations.maintain),
    ("POST", routes.TRAINS, operations.train_register),
    ("POST", routes.TRAIN_ASSIGNMENTS, operations.train_assignment),
    ("POST", routes.TRAIN_ROUNDS, operations.train_round_open),
    ("POST", routes.TRAIN_ROUNDS + "/close", operations.train_round_close),
    ("POST", routes.TRAIN_SWEEPS, operations.train_sweep),
)


def status_for(error: ContractError) -> int:
    """Map a contract violation onto a response status."""
    if isinstance(error, CONFLICT):
        return 409
    if isinstance(error, MALFORMED):
        return 422
    if isinstance(error, MISSING):
        return 404
    if isinstance(error, StoreError):
        return 500
    return 400


class Console:
    """Routes requests onto the plant and renders JSON responses."""

    def __init__(self, plant: Any) -> None:
        self.plant = plant
        self._routes: dict[tuple[str, str], Handler] = {
            (method, path): handler for method, path, handler in ROUTES
        }

    def routes(self) -> tuple[tuple[str, str], ...]:
        """Registered method and path pairs."""
        return tuple(sorted(self._routes))

    def handle(self, request: Request) -> Response:
        """Dispatch a request, mapping contract violations onto statuses."""
        handler = self._routes.get((request.method, request.path))
        if handler is None:
            return error_response(f"no route for {request.method} {request.path}", status=404)
        try:
            return handler(self, request)
        except ContractError as error:
            return error_response(str(error), status=status_for(error))
        except (KeyError, ValueError, TypeError) as error:
            return error_response(f"malformed request: {error}", status=400)
