from __future__ import annotations

from typing import Any

from .base import StepSpec, WorkflowDefinition


class LegacyWorkflowAdapter:
    """Adapter boundary for an externally supplied workflow object.

    The platform never imports a reference repository. A deployment may inject its
    own workflow implementation if it exposes these three operations. Runtime state,
    attempts, checkpoints and audit events remain owned by this project.
    """

    def __init__(self, workflow: Any, *, name: str, version: str, steps: list[str], description: str = "") -> None:
        self.workflow = workflow
        self.definition = WorkflowDefinition(
            name=name, version=version, description=description,
            steps=tuple(StepSpec(step, step.replace("_", " ").title()) for step in steps),
        )

    def register(self) -> WorkflowDefinition:
        return self.definition

    def validate(self, step_name: str, value: Any) -> Any:
        validator = getattr(self.workflow, "validate", None)
        return validator(step_name, value) if validator else value

    def execute_step(self, step_name: str, context: dict[str, Any]) -> Any:
        return self.workflow.execute_step(step_name, context)

    def recover(self, context: dict[str, Any]) -> dict[str, Any]:
        recover = getattr(self.workflow, "recover", None)
        return recover(context) if recover else context
