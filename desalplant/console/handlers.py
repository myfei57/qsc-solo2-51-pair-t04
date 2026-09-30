"""Read-only console handlers."""

from . import probes, routes, trains
from .http import Request, Response, json_response


def health(console, request: Request) -> Response:
    """Liveness probe."""
    return json_response({"status": "ok"})


def status(console, request: Request) -> Response:
    """Current state of the line."""
    return json_response(console.plant.status())


def telemetry(console, request: Request) -> Response:
    """One telemetry sweep."""
    return json_response(console.plant.telemetry().to_dict())


def events(console, request: Request) -> Response:
    """Newest-first audit events."""
    limit = request.integer("limit", 100)
    return json_response(
        {
            "count": console.plant.event_count(),
            "events": [event.to_dict() for event in console.plant.events(limit)],
        }
    )


def alarms(console, request: Request) -> Response:
    """Current component alarms."""
    return json_response([alarm.to_dict() for alarm in console.plant.alarms()])


def diagnostics(console, request: Request) -> Response:
    """Structural diagnostics."""
    return json_response(console.plant.diagnostics())


def ramp(console, request: Request) -> Response:
    """Walk a stepped pressure ramp."""
    return json_response(probes.run_ramp_profile(console.plant))


def backwash(console, request: Request) -> Response:
    """Measure the media head loss."""
    return json_response(probes.run_backwash_check(console.plant))


def feed(console, request: Request) -> Response:
    """Ramp the feed and clean the screen."""
    return json_response(probes.run_feed_ramp(console.plant))


def recovery(console, request: Request) -> Response:
    """Position the brine valve from the recovery figure."""
    return json_response(probes.run_recovery_control(console.plant))


def flush(console, request: Request) -> Response:
    """Advance a flush program."""
    return json_response(probes.run_flush_program(console.plant))


def dosing(console, request: Request) -> Response:
    """Size a dose."""
    return json_response(probes.run_dosing_control(console.plant))


def hydraulics(console, request: Request) -> Response:
    """Report flux and vessel load."""
    return json_response(probes.run_hydraulics(console.plant))


def tank(console, request: Request) -> Response:
    """Fill the product tank and report the tank set."""
    return json_response(probes.run_tank_level(console.plant))


def report(console, request: Request) -> Response:
    """Numeric report."""
    return json_response(console.plant.report())


def audit(console, request: Request) -> Response:
    """Audit report."""
    return json_response(console.plant.audit_report())


def summary(console, request: Request) -> Response:
    """Summary over the curves and stream."""
    return json_response(console.plant.summary())


def selftest(console, request: Request) -> Response:
    """Full-cycle self test."""
    return json_response(console.plant.selftest())


def version(console, request: Request) -> Response:
    """Build label of the running service."""
    return json_response({"label": console.plant.build().label()})


def train_list(console, request: Request) -> Response:
    """Registered trains and their fixed migration policies."""
    return json_response(trains.list_trains(console.plant, request))


def train_assignments(console, request: Request) -> Response:
    """Assignment version chain of one train."""
    return json_response(trains.list_assignments(console.plant, request))


def train_rounds(console, request: Request) -> Response:
    """Rounds of one train with their pinned assignment versions."""
    return json_response(trains.list_rounds(console.plant, request))


def train_verdict(console, request: Request) -> Response:
    """Frozen verdict of a closed round from the audit record (external data)."""
    return json_response(trains.stored_verdict(console.plant, request))


def train_replay(console, request: Request) -> Response:
    """Historical verdict reconstructed under the version in force at the time."""
    return json_response(trains.replay(console.plant, request))


def train_live(console, request: Request) -> Response:
    """Real-time verdict of the round still in flight."""
    return json_response(trains.live_verdict(console.plant, request))


def train_consistency(console, request: Request) -> Response:
    """Fingerprint cross-check across the realtime, audit and replay views."""
    return json_response(trains.consistency(console.plant, request))


ROUTE_TABLE = (
    (routes.HEALTH, health),
    (routes.STATUS, status),
    (routes.TELEMETRY, telemetry),
    (routes.EVENTS, events),
    (routes.ALARMS, alarms),
    (routes.DIAGNOSTICS, diagnostics),
    (routes.OPS_RAMP, ramp),
    (routes.OPS_BACKWASH, backwash),
    (routes.OPS_FEED, feed),
    (routes.OPS_RECOVERY, recovery),
    (routes.OPS_FLUSH, flush),
    (routes.OPS_DOSING, dosing),
    (routes.OPS_HYDRAULICS, hydraulics),
    (routes.OPS_TANK, tank),
    (routes.REPORT, report),
    (routes.AUDIT, audit),
    (routes.SUMMARY, summary),
    (routes.SELFTEST, selftest),
    (routes.VERSION, version),
    (routes.TRAINS, train_list),
    (routes.TRAIN_ASSIGNMENTS, train_assignments),
    (routes.TRAIN_ROUNDS, train_rounds),
    (routes.TRAIN_VERDICT, train_verdict),
    (routes.TRAIN_REPLAY, train_replay),
    (routes.TRAIN_VERDICT + "/live", train_live),
    (routes.TRAIN_CONSISTENCY, train_consistency),
)
