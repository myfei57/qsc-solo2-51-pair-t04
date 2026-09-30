"""Store-backed per-train cleaning monitor.

The service is the single entry point used by real-time judgement, the audit
view and external data access, so all three necessarily agree. Every input
(rounds, sweeps, assignment versions, limits) lives in the append-only store;
a verdict is recomputed as a pure function of that record and frozen once the
round closes. Historical replay reads the same record, therefore a migration
can never alter an old conclusion.
"""

from ..clock import LogicalClock
from ..errors import (
    RoundConflictError,
    UnknownRoundError,
    UnknownTrainError,
)
from ..store import keys
from ..store.store import Store
from .assignment import (
    AssignmentHistory,
    AssignmentVersion,
    require_same_policy,
    resolve_policy,
)
from .evaluate import RoundVerdict, evaluate_round, fingerprint_verdict
from .limits import CleanLimits
from .resolution import version_for_tick
from .round import Round, Sweep


class TrainMonitor:
    """Owns assignment history, rounds and cleaning verdicts for every train."""

    def __init__(self, store: Store, clock: LogicalClock, recorder=None) -> None:
        self._store = store
        self._clock = clock
        self._recorder = recorder

    # ------------------------------------------------------------ registry

    def register_train(self, train: str, policy: str) -> str:
        """Fix the migration policy of a train once and for all."""
        resolve_policy(policy)
        key = keys.train_policy_key(train)
        stored = self._store.get(key)
        if stored is None:
            self._store.put(key, policy)
            self._audit("train-registered", f"train {train} policy {policy}")
            return policy
        return require_same_policy(train, str(stored), policy)

    def policy_of(self, train: str) -> str:
        """Migration policy fixed for a registered train."""
        stored = self._store.get(keys.train_policy_key(train))
        if stored is None:
            raise UnknownTrainError(f"train {train} was never registered")
        return str(stored)

    def trains(self) -> tuple[str, ...]:
        """Registered train ids."""
        prefix = keys.TRAIN_PREFIX
        names: set[str] = set()
        for key in self._store.keys(prefix):
            remainder = key[len(prefix) :]
            if remainder:
                names.add(remainder.split("/", 1)[0])
        return tuple(sorted(names))

    # --------------------------------------------------------- assignments

    def publish_assignment(
        self,
        train: str,
        pressure_sensors: dict[str, str],
        quality_sensors: dict[str, str],
        version: int | None = None,
        tick: int | None = None,
    ) -> AssignmentVersion:
        """Append a new sensor-ownership version for a registered train."""
        policy = self.policy_of(train)
        history = self._load_history(train)
        number = self._next_assignment_number(train, history) if version is None else int(version)
        effective_tick = self._clock.tick if tick is None else int(tick)
        candidate = AssignmentVersion(
            train=train,
            version=number,
            effective_tick=effective_tick,
            pressure_sensors=pressure_sensors,
            quality_sensors=quality_sensors,
        )
        history.publish(candidate)
        self._store.put(keys.train_assignment_seq_key(train), number)
        self._store.put(keys.train_assignment_version_key(train, number), candidate.to_dict())
        self._audit(
            "assignment-published",
            f"train {train} {candidate.fingerprint()} policy {policy}",
        )
        return candidate

    def assignments(self, train: str) -> tuple[AssignmentVersion, ...]:
        """Every published assignment version of a train, oldest first."""
        self.policy_of(train)
        return self._load_history(train).versions()

    def assignment_at(self, train: str, version: int) -> AssignmentVersion:
        """One published assignment version."""
        self.policy_of(train)
        found = self._load_history(train).at(version)
        if found is None:
            raise UnknownTrainError(f"train {train} has no assignment version {version}")
        return found

    def assignment_for_tick(self, train: str, round_no: int, tick: int) -> AssignmentVersion:
        """Version resolving a tick of a round under the train's fixed policy."""
        opened = self.round_at(train, round_no)
        return version_for_tick(self._load_history(train), opened, self.policy_of(train), tick)

    # --------------------------------------------------------------- rounds

    def open_round(self, train: str, tick: int | None = None) -> Round:
        """Open a round, pinning the assignment version it starts on."""
        policy = self.policy_of(train)
        history = self._load_history(train)
        current = history.newest_version()
        if current is None:
            raise RoundConflictError(f"train {train} needs an assignment before opening a round")
        active = self._active_round(train)
        if active is not None:
            raise RoundConflictError(f"train {train} round {active.number} is still open")
        start_tick = self._clock.tick if tick is None else int(tick)
        effective = history.effective(start_tick)
        if effective is None:
            raise RoundConflictError("no assignment version effective at the round start tick")
        number = self._next_round_number(train)
        opened = Round(
            train=train,
            number=number,
            start_tick=start_tick,
            assignment_version=effective.version,
        )
        self._store.put(keys.train_round_seq_key(train), number)
        self._store.put(keys.train_round_key(train, number), opened.to_dict())
        self._audit(
            "round-opened",
            f"train {train} round {number} pinned {effective.fingerprint()} policy {policy}",
        )
        return opened

    def record_sweep(
        self,
        train: str,
        values: dict[str, float],
        tick: int | None = None,
    ) -> Sweep:
        """Append one sweep to the open round."""
        opened = self._require_open_round(train)
        at = self._clock.tick if tick is None else int(tick)
        if at < opened.start_tick:
            raise RoundConflictError("sweep tick precedes the round start")
        if self._store.keys(keys.train_reading_key(train, opened.number, at)):
            raise RoundConflictError(f"train {train} already carries a sweep at tick {at}")
        sweep = Sweep(tick=at, values=values)
        self._store.put(keys.train_reading_key(train, opened.number, at), sweep.to_dict())
        return sweep

    def close_round(self, train: str, tick: int | None = None) -> RoundVerdict:
        """Close the open round and freeze its verdict."""
        opened = self._require_open_round(train)
        end_tick = self._clock.tick if tick is None else int(tick)
        closed = opened.closed_at(end_tick)
        self._store.put(keys.train_round_key(train, opened.number), closed.to_dict())
        verdict = self.evaluate_round(train, opened.number)
        self._audit(
            "round-closed",
            f"train {train} round {opened.number} verdict {verdict.fingerprint[:12]}",
        )
        return verdict

    def rounds(self, train: str) -> tuple[Round, ...]:
        """Every round of a train, oldest first."""
        self.policy_of(train)
        prefix = f"{keys.TRAIN_PREFIX}{train}{keys.TRAIN_ROUND_SUFFIX}"
        collected = []
        for key in self._store.keys(prefix):
            row = self._store.get(key)
            if isinstance(row, dict) and "number" in row:
                collected.append(Round.from_dict(row))
        return tuple(sorted(collected, key=lambda round_: round_.number))

    def round_at(self, train: str, round_no: int) -> Round:
        """One round of a train."""
        self.policy_of(train)
        row = self._store.get(keys.train_round_key(train, round_no))
        if not isinstance(row, dict):
            raise UnknownRoundError(f"train {train} has no round {round_no}")
        return Round.from_dict(row)

    # ------------------------------------------------------------- verdict

    def evaluate_round(
        self,
        train: str,
        round_no: int,
        limits: CleanLimits | None = None,
        freeze: bool = True,
    ) -> RoundVerdict:
        """Recompute the verdict of a closed round from the immutable record.

        A closed round already carrying a frozen verdict is checked against the
        recomputation before anything is rewritten, so a divergent history is
        surfaced instead of being silently overwritten.
        """
        opened = self.round_at(train, round_no)
        history = self._load_history(train)
        policy = self.policy_of(train)
        sweeps = self._load_sweeps(train, round_no)
        table = limits if limits is not None else self._stored_limits(train)
        verdict = evaluate_round(opened, history, policy, sweeps, table)
        if limits is None and opened.closed:
            self._freeze_verdict(train, round_no, verdict, overwrite=freeze)
        return verdict

    def live_verdict(self, train: str, limits: CleanLimits | None = None) -> RoundVerdict:
        """Verdict of the round still in flight; an error when none is open."""
        opened = self._require_open_round(train)
        return self.evaluate_round(train, opened.number, limits, freeze=False)

    def stored_verdict(self, train: str, round_no: int) -> RoundVerdict | None:
        """Frozen verdict row served straight from the audit record."""
        self.round_at(train, round_no)
        return self._stored_verdict(train, round_no)

    def replay(self, train: str, round_no: int) -> RoundVerdict:
        """Historical conclusion, recomputed exactly as the version-at-time gave it."""
        opened = self.round_at(train, round_no)
        if not opened.closed:
            raise RoundConflictError(f"train {train} round {round_no} is still open")
        frozen = self._stored_verdict(train, round_no)
        recomputed = self.evaluate_round(train, round_no, freeze=False)
        if not self._frozen_matches(train, round_no, frozen, recomputed):
            raise RoundConflictError(
                f"train {train} round {round_no} history is not reproducible"
            )
        return recomputed

    def verify_consistency(self, train: str, round_no: int) -> dict[str, object]:
        """Cross-check realtime evaluation, the frozen verdict and replay."""
        recomputed = self.evaluate_round(train, round_no, freeze=False)
        frozen = self._stored_verdict(train, round_no)
        consistent = self._frozen_matches(train, round_no, frozen, recomputed)
        return {
            "train": train,
            "round": round_no,
            "policy": self.policy_of(train),
            "fingerprint": recomputed.fingerprint,
            "frozen": None if frozen is None else frozen.fingerprint,
            "consistent": consistent,
            "needs_clean": recomputed.needs_clean,
            "leader_stage": None if recomputed.leader is None else recomputed.leader.stage,
        }

    # ------------------------------------------------------------- helpers

    def _frozen_matches(
        self,
        train: str,
        round_no: int,
        frozen: RoundVerdict | None,
        recomputed: RoundVerdict,
    ) -> bool:
        """Whether the frozen conclusion is intact and equals the replay."""
        if frozen is None:
            return not self.round_at(train, round_no).closed
        if fingerprint_verdict(frozen) != frozen.fingerprint:
            return False
        return frozen.fingerprint == recomputed.fingerprint

    def _freeze_verdict(
        self, train: str, round_no: int, verdict: RoundVerdict, overwrite: bool = True
    ) -> None:
        key = keys.train_verdict_key(train, round_no)
        existing = self._store.get(key)
        if existing is not None and existing.get("fingerprint") != verdict.fingerprint:
            if not overwrite:
                return
            raise RoundConflictError(
                f"train {train} round {round_no} verdict is frozen and must not change"
            )
        if existing is not None:
            return
        self._store.put(key, verdict.to_dict())

    def _stored_verdict(self, train: str, round_no: int) -> RoundVerdict | None:
        row = self._store.get(keys.train_verdict_key(train, round_no))
        if not isinstance(row, dict):
            return None
        from .evaluate import verdict_from_dict

        return verdict_from_dict(row)

    def _stored_limits(self, train: str) -> CleanLimits:
        raw = self._store.get(f"{keys.TRAIN_PREFIX}{train}/limits")
        if not isinstance(raw, dict):
            raise RoundConflictError(f"train {train} has no stored cleaning limits")
        return CleanLimits.from_dict(raw)

    def store_limits(self, train: str, limits: CleanLimits) -> None:
        """Persist the per-stage limits used when no explicit table is supplied."""
        self.policy_of(train)
        self._store.put(f"{keys.TRAIN_PREFIX}{train}/limits", limits.to_dict())

    def _load_history(self, train: str) -> AssignmentHistory:
        history = AssignmentHistory(train)
        for version_row in self._assignment_rows(train):
            history.publish(AssignmentVersion.from_dict(version_row))
        return history

    def _assignment_rows(self, train: str) -> list[dict]:
        prefix = f"{keys.TRAIN_PREFIX}{train}{keys.TRAIN_ASSIGNMENT_VERSION_SUFFIX}"
        rows = [
            row
            for key in self._store.keys(prefix)
            if isinstance((row := self._store.get(key)), dict)
        ]
        return sorted(rows, key=lambda row: int(row["version"]))

    def _load_sweeps(self, train: str, round_no: int) -> tuple[Sweep, ...]:
        prefix = f"{keys.TRAIN_PREFIX}{train}{keys.TRAIN_READING_SUFFIX}{round_no:04d}/"
        sweeps = [
            Sweep.from_dict(row)
            for key in self._store.keys(prefix)
            if isinstance((row := self._store.get(key)), dict)
        ]
        return tuple(sorted(sweeps, key=lambda sweep: sweep.tick))

    def _active_round(self, train: str) -> Round | None:
        rounds = self.rounds(train)
        return rounds[-1] if rounds and not rounds[-1].closed else None

    def _require_open_round(self, train: str) -> Round:
        active = self._active_round(train)
        if active is None:
            raise RoundConflictError(f"train {train} has no open round")
        return active

    def _next_round_number(self, train: str) -> int:
        return int(self._store.get(keys.train_round_seq_key(train), 0) or 0) + 1

    def _next_assignment_number(self, train: str, history: AssignmentHistory) -> int:
        newest = history.newest_version()
        return 1 if newest is None else newest.version + 1

    def _audit(self, kind: str, detail: str) -> None:
        if self._recorder is not None:
            self._recorder.log(kind, detail)
