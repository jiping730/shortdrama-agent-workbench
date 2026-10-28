from pydantic import BaseModel

from agent_platform.tools import ToolDefinition, ToolRegistry


class Input(BaseModel):
    value: int


class Output(BaseModel):
    doubled: int


def test_tool_registry_validates_audits_and_deduplicates():
    registry = ToolRegistry()
    registry.register(ToolDefinition("double", "1", Input, Output, lambda item: {"doubled": item.value * 2}))
    assert registry.execute("double", {"value": 2}, idempotency_key="same") == {"doubled": 4}
    assert registry.execute("double", {"value": 2}, idempotency_key="same") == {"doubled": 4}
    assert len([event for event in registry.audit_log if event["status"] == "started"]) == 1
