from __future__ import annotations

from typing import Any

from .base import StepSpec, WorkflowDefinition


class LegacyWorkflowAdapter:
    """Adapter boundary for an externally supplied workflow object.

    The platform never imports a reference repository. A deployment may inject its
    own workflow implementation. Business methods are delegated; runtime state,
    attempts, checkpoints and audit events remain owned by this project. Lifecycle
    hooks are optional on older implementations and become no-op context hooks when
    absent, which keeps the adapter a compatibility boundary rather than a second
    workflow implementation.
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

    def start(self, context: dict[str, Any]) -> dict[str, Any]:
        return self._context_hook("start", context)

    def resume(self, context: dict[str, Any]) -> dict[str, Any]:
        return self._context_hook("resume", context)

    def execute_step(self, step_name: str, context: dict[str, Any]) -> Any:
        return self.workflow.execute_step(step_name, context)

    def recover(self, context: dict[str, Any]) -> dict[str, Any]:
        return self._context_hook("recover", context)

    def _context_hook(self, name: str, context: dict[str, Any]) -> dict[str, Any]:
        hook = getattr(self.workflow, name, None)
        if hook is None:
            return context
        result = hook(context)
        if result is None:
            return context
        if not isinstance(result, dict):
            raise TypeError(f"legacy workflow {name}() must return a context dict")
        return result
