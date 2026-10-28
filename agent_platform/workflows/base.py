from __future__ import annotations

from dataclasses import dataclass
from typing import Any

try:
    from typing import Protocol
except ImportError:  # Python 3.7 compatibility
    from typing_extensions import Protocol


@dataclass(frozen=True)
class StepSpec:
    name: str
    description: str
    human_gate: bool = False


@dataclass(frozen=True)
class WorkflowDefinition:
    name: str
    version: str
    description: str
    steps: tuple[StepSpec, ...]


class WorkflowAdapter(Protocol):
    """Contract between a workflow implementation and the durable runtime.

    Implementations own business orchestration and schema validation. The runtime
    owns persistence, attempts, checkpoints, state transitions and audit events.
    Lifecycle hooks must return a context mapping and must not persist runtime
    state themselves.
    """

    definition: WorkflowDefinition

    def register(self) -> WorkflowDefinition: ...

    def validate(self, step_name: str, value: Any) -> Any: ...

    def start(self, context: dict[str, Any]) -> dict[str, Any]: ...

    def resume(self, context: dict[str, Any]) -> dict[str, Any]: ...

    def execute_step(self, step_name: str, context: dict[str, Any]) -> Any: ...

    def recover(self, context: dict[str, Any]) -> dict[str, Any]: ...


REQUIRED_ADAPTER_METHODS = (
    "register",
    "validate",
    "start",
    "resume",
    "execute_step",
    "recover",
)


def assert_workflow_adapter(adapter: Any) -> None:
    """Fail fast when an injected workflow does not implement the platform contract."""

    missing = [name for name in REQUIRED_ADAPTER_METHODS if not callable(getattr(adapter, name, None))]
    if missing:
        raise TypeError(f"workflow adapter is missing required methods: {', '.join(missing)}")
    definition = adapter.register()
    if not isinstance(definition, WorkflowDefinition):
        raise TypeError("workflow adapter register() must return WorkflowDefinition")
    if not definition.steps:
        raise ValueError("workflow definition must contain at least one step")
