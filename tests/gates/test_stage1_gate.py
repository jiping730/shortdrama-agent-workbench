from __future__ import annotations

import pytest

from agent_platform.config import Settings
from agent_platform.db import Database
from agent_platform.domain import RunStatus
from agent_platform.providers import FakeModel
from agent_platform.runtime import SimulatedInterruption, WorkflowRuntime
from agent_platform.workflows.base import (
    REQUIRED_ADAPTER_METHODS,
    StepSpec,
    WorkflowDefinition,
    assert_workflow_adapter,
)
from agent_platform.workflows.legacy import LegacyWorkflowAdapter


class InjectedWorkflow:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def start(self, context: dict) -> dict:
        self.calls.append(("start", context.copy()))
        return {**context, "started_by": "injected-workflow"}

    def resume(self, context: dict) -> dict:
        self.calls.append(("resume", context.copy()))
        return {**context, "resumed_by": "injected-workflow"}

    def validate(self, step_name: str, value: object) -> object:
        self.calls.append(("validate", step_name))
        return value

    def execute_step(self, step_name: str, context: dict) -> dict:
        self.calls.append(("execute_step", step_name))
        return {"step": step_name, "value": context["script_id"]}

    def recover(self, context: dict) -> dict:
        self.calls.append(("recover", context.copy()))
        return {**context, "recovered_by": "injected-workflow"}


def test_workflow_adapter_contract_contains_all_runtime_hooks() -> None:
    assert set(REQUIRED_ADAPTER_METHODS) == {
        "register",
        "validate",
        "start",
        "resume",
        "execute_step",
        "recover",
    }

    injected = InjectedWorkflow()
    adapter = LegacyWorkflowAdapter(
        injected,
        name="injected-demo",
        version="1.0.0",
        steps=["demo_step"],
    )
    assert_workflow_adapter(adapter)
    assert adapter.start({"x": 1})["started_by"] == "injected-workflow"
    assert adapter.resume({"x": 1})["resumed_by"] == "injected-workflow"
    assert adapter.validate("demo_step", {"ok": True}) == {"ok": True}
    assert adapter.execute_step("demo_step", {"script_id": "s-1"})["value"] == "s-1"
    assert adapter.recover({"x": 1})["recovered_by"] == "injected-workflow"
    assert [name for name, _ in injected.calls] == [
        "start",
        "resume",
        "validate",
        "execute_step",
        "recover",
    ]


def test_runtime_persists_and_executes_an_injected_workflow(tmp_path) -> None:
    injected = InjectedWorkflow()
    adapter = LegacyWorkflowAdapter(
        injected,
        name="injected-demo",
        version="1.0.0",
        steps=["demo_step"],
    )
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'adapter.db'}",
        artifact_dir=tmp_path / "artifacts",
    )
    runtime = WorkflowRuntime(
        database=Database(settings),
        settings=settings,
        model=FakeModel(),
        adapter=adapter,
    )

    result = runtime.create_run(project_id="adapter-project", script="hello")

    assert result.status == RunStatus.COMPLETED.value
    assert [name for name, _ in injected.calls] == [
        "start",
        "execute_step",
        "validate",
    ]
    assert runtime.workflow_definition.name == "injected-demo"
    assert any(
        definition.name == "injected-demo" for definition, _ in runtime.repository.list_workflows()
    )
    assert runtime.repository.get_events(result.run_id)[1].event_type == "workflow.started"


def test_runtime_calls_resume_and_recover_hooks_at_the_durable_boundary(tmp_path) -> None:
    first = InjectedWorkflow()
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'lifecycle.db'}",
        artifact_dir=tmp_path / "artifacts",
    )
    adapter = LegacyWorkflowAdapter(
        first,
        name="injected-demo",
        version="1.0.0",
        steps=["demo_step"],
    )
    runtime = WorkflowRuntime(
        database=Database(settings),
        settings=settings,
        model=FakeModel(),
        adapter=adapter,
    )
    with pytest.raises(SimulatedInterruption):
        runtime.create_run(
            project_id="lifecycle-project",
            script="hello",
            stop_after_step="demo_step",
        )

    resumed = runtime.resume(runtime.repository.list_runs(project_id="lifecycle-project")[0].id)
    assert resumed.status == RunStatus.COMPLETED.value
    assert any(name == "resume" for name, _ in first.calls)

    second = InjectedWorkflow()
    adapter2 = LegacyWorkflowAdapter(
        second,
        name="recover-demo",
        version="1.0.0",
        steps=["demo_step"],
    )
    settings2 = Settings(
        database_url=f"sqlite:///{tmp_path / 'recover.db'}",
        artifact_dir=tmp_path / "recover-artifacts",
    )
    runtime2 = WorkflowRuntime(
        database=Database(settings2),
        settings=settings2,
        model=FakeModel(),
        adapter=adapter2,
    )
    with pytest.raises(SimulatedInterruption):
        runtime2.create_run(
            project_id="recover-project",
            script="hello",
            stop_after_step="demo_step",
        )
    recover_run_id = runtime2.repository.list_runs(project_id="recover-project")[0].id
    recovered = runtime2.recover(recover_run_id)
    assert recovered.status == RunStatus.COMPLETED.value
    assert any(name == "recover" for name, _ in second.calls)


def test_invalid_injected_adapter_is_rejected_before_runtime_start() -> None:
    class Incomplete:
        definition = WorkflowDefinition("bad", "1", "", (StepSpec("step", "Step"),))

        def register(self):
            return self.definition

        def validate(self, step_name, value):
            return value

        def execute_step(self, step_name, context):
            return context

        def recover(self, context):
            return context

    with pytest.raises(TypeError, match="start, resume"):
        assert_workflow_adapter(Incomplete())
