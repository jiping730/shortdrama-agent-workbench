from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_platform.artifact_storage import LocalArtifactStore, S3ArtifactStore
from agent_platform.config import Settings
from agent_platform.db import Database
from agent_platform.domain import ErrorCode, RunStatus, WorkflowStepError
from agent_platform.providers import AnthropicModelAdapter, FakeModel, build_model_provider
from agent_platform.queue import InMemoryTaskQueue, LocalWorker, SQLiteTaskQueue
from agent_platform.runtime import WorkflowRuntime
from agent_platform.schemas import Fact, Scene
from agent_platform.workflows.script_to_shotlist import ScriptToShotlistAdapter

SCRIPT = "SCENE 1: Room\nA enters.\n\nSCENE 2: Hall\nB waits."


class _FakeMessages:
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return SimpleNamespace(content=[SimpleNamespace(text=json.dumps(self.payload))])


class _FakeAnthropicClient:
    def __init__(self, payload: object) -> None:
        self.messages = _FakeMessages(payload)


def _scene() -> Scene:
    return Scene(
        scene_id="scene-1",
        scene_no=1,
        title="Room",
        source_start=0,
        source_end=10,
        source_text="Room: A enters",
        evidence_ids=["evidence-1"],
    )


def test_anthropic_adapter_uses_official_sdk_boundary_and_structured_models() -> None:
    client = _FakeAnthropicClient(
        [
            {
                "fact_id": "fact-1",
                "kind": "character",
                "value": "A",
                "evidence_ids": ["evidence-1"],
            }
        ]
    )
    adapter = AnthropicModelAdapter(api_key="test-key", model="claude-test", client=client)
    facts = adapter.generate_facts(script_text=SCRIPT, scenes=[_scene()])
    assert facts == [
        Fact(
            fact_id="fact-1",
            kind="character",
            value="A",
            evidence_ids=["evidence-1"],
        )
    ]
    call = client.messages.calls[0]
    assert call["model"] == "claude-test"
    assert call["max_tokens"] == 4096
    assert "messages" in call and "system" in call


def test_anthropic_invalid_json_is_a_structured_schema_error() -> None:
    class BadMessages(_FakeMessages):
        def create(self, **kwargs: object) -> object:
            return SimpleNamespace(content=[SimpleNamespace(text="not-json")])

    client = SimpleNamespace(messages=BadMessages([]))
    adapter = AnthropicModelAdapter(api_key="test-key", model="claude-test", client=client)
    with pytest.raises(WorkflowStepError) as exc_info:
        adapter.generate_facts(script_text=SCRIPT, scenes=[_scene()])
    assert exc_info.value.code == ErrorCode.SCHEMA_VALIDATION_FAILED


def test_model_provider_selection_is_explicit_and_offline_by_default() -> None:
    assert isinstance(build_model_provider(Settings()), FakeModel)
    settings = Settings(
        model_provider="anthropic",
        anthropic_api_key="test-key",
        anthropic_model="claude-test",
    )
    client = _FakeAnthropicClient([])
    provider = build_model_provider(settings, client=client)
    assert isinstance(provider, AnthropicModelAdapter)
    assert provider.name == "anthropic"


def test_sqlite_queue_survives_reopen_and_worker_executes_deferred_run(tmp_path: Path) -> None:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'queue-runtime.db'}",
        artifact_dir=tmp_path / "artifacts",
    )
    runtime = WorkflowRuntime(database=Database(settings), settings=settings, model=FakeModel())
    result = runtime.create_run(project_id="queued-project", script=SCRIPT, defer_execution=True)
    assert result.status == RunStatus.QUEUED.value

    queue_path = tmp_path / "queue.db"
    queue = SQLiteTaskQueue(queue_path)
    message = queue.enqueue("run.execute", {"run_id": result.run_id}, idempotency_key="run-once")
    reopened = SQLiteTaskQueue(queue_path)
    assert reopened.get(message.message_id).status == "queued"

    worker = LocalWorker(runtime, reopened)
    processed = worker.run_once()
    assert processed is not None
    assert processed.status == RunStatus.WAITING_REVIEW.value
    assert reopened.get(message.message_id).status == "succeeded"
    assert worker.run_once() is None


def test_in_memory_queue_is_idempotent_and_requeues_failures() -> None:
    queue = InMemoryTaskQueue()
    first = queue.enqueue("demo", {"value": 1}, idempotency_key="same")
    duplicate = queue.enqueue("demo", {"value": 1}, idempotency_key="same")
    assert first.message_id == duplicate.message_id
    leased = queue.lease()
    assert leased is not None
    queue.nack(leased.message_id, "transient", requeue=True)
    assert queue.lease().message_id == first.message_id


def test_local_and_s3_artifact_stores_share_put_contract(tmp_path: Path) -> None:
    local = LocalArtifactStore(tmp_path / "local")
    local_uri = local.put("artifact-1", '{"ok": true}')
    assert Path(local_uri).read_text(encoding="utf-8") == '{"ok": true}'

    class FakeS3:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def put_object(self, **kwargs: object) -> None:
            self.calls.append(kwargs)

    client = FakeS3()
    s3 = S3ArtifactStore(bucket="demo-bucket", prefix="runs", client=client)
    uri = s3.put("artifact-1", '{"ok": true}')
    assert uri == "s3://demo-bucket/runs/artifact-1.json"
    assert client.calls[0]["Bucket"] == "demo-bucket"
    assert client.calls[0]["Key"] == "runs/artifact-1.json"


def test_runtime_can_use_configured_s3_store_without_changing_domain_records(
    tmp_path: Path,
) -> None:
    class FakeS3:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def put_object(self, **kwargs: object) -> None:
            self.calls.append(kwargs)

    client = FakeS3()
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 's3-runtime.db'}",
        artifact_dir=tmp_path / "unused-local-artifacts",
        artifact_backend="s3",
        s3_bucket="demo-bucket",
        s3_prefix="runs",
    )
    store = S3ArtifactStore(bucket="demo-bucket", prefix="runs", client=client)
    runtime = WorkflowRuntime(
        database=Database(settings), settings=settings, model=FakeModel(), artifact_store=store
    )
    result = runtime.create_run(project_id="s3-project", script=SCRIPT)
    input_artifact = runtime.repository.get_run(result.run_id).input_artifact_id
    assert input_artifact is not None
    assert runtime.repository.get_artifact(input_artifact).content_uri.startswith(
        "s3://demo-bucket/runs/"
    )
    assert len(client.calls) >= 1


def test_script_to_shotlist_is_a_real_adapter_extension(tmp_path: Path) -> None:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'shotlist.db'}",
        artifact_dir=tmp_path / "artifacts",
    )
    runtime = WorkflowRuntime(
        database=Database(settings),
        settings=settings,
        adapter=ScriptToShotlistAdapter(),
        model=FakeModel(),
    )
    result = runtime.create_run(project_id="shotlist-project", script=SCRIPT)
    assert result.status == RunStatus.COMPLETED.value
    assert runtime.workflow_definition.name == "script-to-shotlist"
    assert {item.artifact_type for item in runtime.repository.get_artifacts(result.run_id)} >= {
        "split_script",
        "generate_shotlist",
        "validate_shotlist",
        "export_artifacts",
    }


def test_stage7_files_and_docs_are_explicit_about_optional_boundaries() -> None:
    root = Path(__file__).resolve().parents[2]
    for relative in [
        "agent_platform/artifact_storage.py",
        "agent_platform/queue.py",
        "agent_platform/workflows/script_to_shotlist.py",
        "docs/stage-gates.md",
    ]:
        assert (root / relative).exists(), relative
    readme = (root / "README.md").read_text(encoding="utf-8")
    assert all(token in readme for token in ("Anthropic", "S3", "队列", "script-to-shotlist"))
    gates = (root / "docs/stage-gates.md").read_text(encoding="utf-8")
    assert "| 7 可选扩展 |" in gates and "已通过" in gates
