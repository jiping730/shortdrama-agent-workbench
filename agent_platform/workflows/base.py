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
    definition: WorkflowDefinition

    def register(self) -> WorkflowDefinition: ...

    def validate(self, step_name: str, value: Any) -> Any: ...

    def execute_step(self, step_name: str, context: dict[str, Any]) -> Any: ...

    def recover(self, context: dict[str, Any]) -> dict[str, Any]: ...
