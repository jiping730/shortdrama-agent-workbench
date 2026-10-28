from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class RunStatus(str, Enum):
    CREATED = "created"
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    WAITING_REVIEW = "waiting_review"
    FAILED = "failed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    NEEDS_RECOVERY = "needs_recovery"


class StepStatus(str, Enum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    WAITING_REVIEW = "waiting_review"
    UNKNOWN = "unknown"


class ErrorCode(str, Enum):
    INVALID_INPUT = "invalid_input"
    SCHEMA_VALIDATION_FAILED = "schema_validation_failed"
    EVIDENCE_MISSING = "evidence_missing"
    MODEL_ERROR = "model_error"
    TOOL_ERROR = "tool_error"
    TIMEOUT = "timeout"
    EXTERNAL_RESULT_UNKNOWN = "external_result_unknown"
    REVIEW_REJECTED = "review_rejected"
    PERSISTENCE_ERROR = "persistence_error"
    UNEXPECTED_ERROR = "unexpected_error"


RUN_TRANSITIONS: dict[RunStatus, set[RunStatus]] = {
    RunStatus.CREATED: {RunStatus.QUEUED, RunStatus.CANCELLED},
    RunStatus.QUEUED: {RunStatus.RUNNING, RunStatus.PAUSED, RunStatus.CANCELLED},
    RunStatus.RUNNING: {
        RunStatus.PAUSED,
        RunStatus.WAITING_REVIEW,
        RunStatus.FAILED,
        RunStatus.COMPLETED,
        RunStatus.CANCELLED,
        RunStatus.NEEDS_RECOVERY,
    },
    RunStatus.PAUSED: {RunStatus.QUEUED, RunStatus.RUNNING, RunStatus.CANCELLED, RunStatus.NEEDS_RECOVERY},
    RunStatus.WAITING_REVIEW: {RunStatus.QUEUED, RunStatus.PAUSED, RunStatus.CANCELLED, RunStatus.NEEDS_RECOVERY},
    RunStatus.FAILED: {RunStatus.QUEUED, RunStatus.CANCELLED, RunStatus.NEEDS_RECOVERY},
    RunStatus.NEEDS_RECOVERY: {RunStatus.QUEUED, RunStatus.PAUSED, RunStatus.CANCELLED, RunStatus.FAILED},
    RunStatus.COMPLETED: set(),
    RunStatus.CANCELLED: set(),
}

STEP_TRANSITIONS: dict[StepStatus, set[StepStatus]] = {
    StepStatus.PENDING: {StepStatus.QUEUED, StepStatus.RUNNING, StepStatus.SKIPPED, StepStatus.FAILED},
    StepStatus.QUEUED: {StepStatus.RUNNING, StepStatus.FAILED, StepStatus.SKIPPED},
    StepStatus.RUNNING: {StepStatus.SUCCEEDED, StepStatus.FAILED, StepStatus.WAITING_REVIEW, StepStatus.UNKNOWN},
    StepStatus.SUCCEEDED: {StepStatus.PENDING, StepStatus.WAITING_REVIEW},
    StepStatus.FAILED: {StepStatus.QUEUED, StepStatus.RUNNING, StepStatus.UNKNOWN},
    StepStatus.SKIPPED: set(),
    StepStatus.WAITING_REVIEW: {StepStatus.QUEUED, StepStatus.RUNNING, StepStatus.SUCCEEDED, StepStatus.FAILED},
    StepStatus.UNKNOWN: {StepStatus.QUEUED, StepStatus.FAILED},
}


class DomainError(Exception):
    """Base domain error."""


class InvalidTransition(DomainError):
    def __init__(self, entity: str, current: str, target: str) -> None:
        super().__init__(f"illegal {entity} transition: {current} -> {target}")
        self.entity = entity
        self.current = current
        self.target = target


class WorkflowStepError(DomainError):
    def __init__(self, code: ErrorCode, message: str, *, retriable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retriable = retriable


class UnknownExternalCall(DomainError):
    def __init__(self, message: str = "external result is unknown") -> None:
        super().__init__(message)
        self.code = ErrorCode.EXTERNAL_RESULT_UNKNOWN


class PauseForReview(DomainError):
    """Internal control-flow signal, not an error."""


def assert_run_transition(current: RunStatus | str, target: RunStatus | str) -> None:
    current_status = RunStatus(current)
    target_status = RunStatus(target)
    if target_status not in RUN_TRANSITIONS[current_status]:
        raise InvalidTransition("run", current_status.value, target_status.value)


def assert_step_transition(current: StepStatus | str, target: StepStatus | str) -> None:
    current_status = StepStatus(current)
    target_status = StepStatus(target)
    if target_status not in STEP_TRANSITIONS[current_status]:
        raise InvalidTransition("step", current_status.value, target_status.value)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def content_hash(value: Any) -> str:
    raw = value if isinstance(value, bytes) else canonical_json(value).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def stable_id(prefix: str, *parts: object) -> str:
    joined = "|".join(str(part) for part in parts)
    return f"{prefix}_{hashlib.sha256(joined.encode('utf-8')).hexdigest()[:16]}"
