from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from pydantic import BaseModel, ValidationError

from .domain import ErrorCode, content_hash, stable_id


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    version: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    handler: Callable[[BaseModel], BaseModel]
    timeout_seconds: float = 30.0
    retryable: bool = False
    idempotent: bool = True


class ToolExecutionError(Exception):
    def __init__(self, code: str, message: str, *, tool_call_id: str) -> None:
        super().__init__(message)
        self.code = code
        self.tool_call_id = tool_call_id


class ToolRegistry:
    """Small in-process registry; a queue/worker can own the same contract later."""

    def __init__(self) -> None:
        self._definitions: Dict[str, ToolDefinition] = {}
        self.audit_log: list[dict[str, Any]] = []
        self._successful: dict[str, BaseModel] = {}

    def register(self, definition: ToolDefinition) -> None:
        if definition.name in self._definitions:
            raise ValueError(f"tool already registered: {definition.name}")
        self._definitions[definition.name] = definition

    def describe(self) -> list[dict[str, Any]]:
        return [{
            "name": item.name, "version": item.version, "timeout_seconds": item.timeout_seconds,
            "retryable": item.retryable, "idempotent": item.idempotent,
        } for item in self._definitions.values()]

    def execute(self, name: str, payload: dict[str, Any], *, idempotency_key: Optional[str] = None) -> dict[str, Any]:
        definition = self._definitions.get(name)
        if definition is None:
            raise ToolExecutionError(ErrorCode.TOOL_ERROR.value, f"unknown tool: {name}", tool_call_id="unknown")
        call_id = stable_id("toolcall", name, definition.version, idempotency_key or content_hash(payload))
        key = idempotency_key or call_id
        if definition.idempotent and key in self._successful:
            return self._successful[key].model_dump(mode="json")
        self.audit_log.append({"tool_call_id": call_id, "tool_name": name, "status": "started", "input_hash": content_hash(payload)})
        try:
            typed_input = definition.input_model.model_validate(payload)
            typed_output = definition.output_model.model_validate(definition.handler(typed_input))
        except ValidationError as exc:
            self.audit_log.append({"tool_call_id": call_id, "tool_name": name, "status": "failed", "error_code": ErrorCode.SCHEMA_VALIDATION_FAILED.value})
            raise ToolExecutionError(ErrorCode.SCHEMA_VALIDATION_FAILED.value, str(exc), tool_call_id=call_id) from exc
        except Exception as exc:
            self.audit_log.append({"tool_call_id": call_id, "tool_name": name, "status": "failed", "error_code": ErrorCode.TOOL_ERROR.value})
            raise ToolExecutionError(ErrorCode.TOOL_ERROR.value, str(exc), tool_call_id=call_id) from exc
        self._successful[key] = typed_output
        self.audit_log.append({"tool_call_id": call_id, "tool_name": name, "status": "succeeded", "output_hash": content_hash(typed_output.model_dump(mode="json"))})
        return typed_output.model_dump(mode="json")
