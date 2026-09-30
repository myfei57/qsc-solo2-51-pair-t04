"""Operations that change the state of the line."""

from . import trains
from .http import Request, Response, json_response


def start(console, request: Request) -> Response:
    """Bring the line up."""
    request.body()
    event = console.plant.start()
    return json_response({"status": "started", "event": event.to_dict()})


def shutdown(console, request: Request) -> Response:
    """Stop the line."""
    request.body()
    event = console.plant.shutdown()
    return json_response({"status": "stopped", "event": event.to_dict()})


def switch(console, request: Request) -> Response:
    """Move production to the standby tank."""
    request.body()
    event = console.plant.switch_tank()
    return json_response({"status": "switched", "event": event.to_dict()})


def maintain(console, request: Request) -> Response:
    """Run the maintenance routine."""
    request.body()
    event = console.plant.maintain()
    return json_response({"status": "maintained", "event": event.to_dict()})


def train_register(console, request: Request) -> Response:
    """Fix a train's migration policy once."""
    return json_response({"status": "registered", **trains.register(console.plant, request)})


def train_assignment(console, request: Request) -> Response:
    """Publish a new sensor-to-stage assignment version."""
    return json_response({"status": "published", **trains.publish_assignment(console.plant, request)})


def train_round_open(console, request: Request) -> Response:
    """Open a production round pinned to its starting assignment."""
    return json_response({"status": "opened", **trains.open_round(console.plant, request)})


def train_sweep(console, request: Request) -> Response:
    """Record one sensor sweep into the open round."""
    return json_response({"status": "recorded", **trains.record_sweep(console.plant, request)})


def train_round_close(console, request: Request) -> Response:
    """Close the round and freeze the per-stage cleaning verdict."""
    return json_response({"status": "closed", **trains.close_round(console.plant, request)})
