"""Key layout of the persisted control state."""

PLANT_STATE = "plant/state"
PLANT_STARTED_AT = "plant/started_at"
PLANT_STOPPED_AT = "plant/stopped_at"
PLANT_MAINTAINED_AT = "plant/maintained_at"

AUDIT_SEQUENCE = "audit/sequence"
AUDIT_EVENT_PREFIX = "audit/event/"
AUDIT_LAST_PREFIX = "audit/last/"

TRAIN_PREFIX = "membrane/train/"
TRAIN_POLICY_SUFFIX = "/policy"
TRAIN_ASSIGNMENT_SEQUENCE_SUFFIX = "/assignments/seq"
TRAIN_ASSIGNMENT_VERSION_SUFFIX = "/assignments/v/"
TRAIN_ROUND_SEQUENCE_SUFFIX = "/rounds/seq"
TRAIN_ROUND_SUFFIX = "/rounds/"
TRAIN_READING_SUFFIX = "/readings/"
TRAIN_VERDICT_SUFFIX = "/verdicts/"


def audit_event_key(sequence: int) -> str:
    """Key holding the event written at ``sequence``."""
    if sequence < 1:
        raise ValueError("audit sequence starts at one")
    return f"{AUDIT_EVENT_PREFIX}{sequence:06d}"


def audit_last_key(kind: str) -> str:
    """Key holding the sequence of the latest event of ``kind``."""
    return f"{AUDIT_LAST_PREFIX}{kind}"


def train_policy_key(train: str) -> str:
    """Key holding the migration policy fixed for one train."""
    return f"{TRAIN_PREFIX}{train}{TRAIN_POLICY_SUFFIX}"


def train_assignment_seq_key(train: str) -> str:
    """Key holding the newest assignment version number of one train."""
    return f"{TRAIN_PREFIX}{train}{TRAIN_ASSIGNMENT_SEQUENCE_SUFFIX}"


def train_assignment_version_key(train: str, version: int) -> str:
    """Key holding one numbered sensor-to-stage assignment version."""
    if version < 1:
        raise ValueError("assignment version starts at one")
    return f"{TRAIN_PREFIX}{train}{TRAIN_ASSIGNMENT_VERSION_SUFFIX}{version:03d}"


def train_round_seq_key(train: str) -> str:
    """Key holding the newest round number of one train."""
    return f"{TRAIN_PREFIX}{train}{TRAIN_ROUND_SEQUENCE_SUFFIX}"


def train_round_key(train: str, round_no: int) -> str:
    """Key holding one production round."""
    if round_no < 1:
        raise ValueError("round number starts at one")
    return f"{TRAIN_PREFIX}{train}{TRAIN_ROUND_SUFFIX}{round_no:04d}"


def train_reading_key(train: str, round_no: int, tick: int) -> str:
    """Key holding one sweep recorded for a round at a tick."""
    if round_no < 1 or tick < 0:
        raise ValueError("reading needs a positive round and a non-negative tick")
    return f"{TRAIN_PREFIX}{train}{TRAIN_READING_SUFFIX}{round_no:04d}/{tick:06d}"


def train_verdict_key(train: str, round_no: int) -> str:
    """Key holding the immutable cleaning verdict committed for a round."""
    if round_no < 1:
        raise ValueError("round number starts at one")
    return f"{TRAIN_PREFIX}{train}{TRAIN_VERDICT_SUFFIX}{round_no:04d}"
