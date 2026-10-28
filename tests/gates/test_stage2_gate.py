from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, select

from agent_platform.db import Database, WorkspaceModel
from agent_platform.repository import Repository

ROOT = Path(__file__).resolve().parents[2]
REQUIRED_TABLES = {
    "workspaces",
    "projects",
    "workflow_definitions",
    "workflow_versions",
    "runs",
    "tasks",
    "step_executions",
    "attempts",
    "checkpoints",
    "artifacts",
    "evidence",
    "review_tasks",
    "tool_calls",
    "external_calls",
    "run_events",
}


def _alembic_config(database_url: str) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def test_sqlite_domain_schema_contains_all_required_tables_and_columns(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'schema.db'}"
    database = Database(database_url=database_url)
    database.create_all()

    inspector = inspect(database.engine)
    assert set(inspector.get_table_names()) >= REQUIRED_TABLES
    required_columns = {
        "runs": {
            "id",
            "project_id",
            "workflow_version_id",
            "status",
            "input_artifact_id",
            "current_step",
            "correlation_id",
            "created_at",
            "updated_at",
        },
        "step_executions": {
            "step_id",
            "run_id",
            "step_name",
            "status",
            "input_hash",
            "current_attempt",
            "output_artifact_id",
            "error_code",
            "started_at",
            "finished_at",
        },
        "attempts": {
            "id",
            "step_id",
            "attempt_no",
            "input_snapshot",
            "output_artifact_id",
            "model_version",
            "prompt_version",
            "idempotency_key",
            "error_type",
            "started_at",
            "finished_at",
        },
        "artifacts": {
            "id",
            "artifact_type",
            "content_hash",
            "schema_version",
            "content_uri",
            "content",
            "parent_artifact_ids",
            "created_at",
        },
        "evidence": {
            "id",
            "script_id",
            "scene_id",
            "source_start",
            "source_end",
            "source_text",
            "content_hash",
        },
    }
    for table_name, expected in required_columns.items():
        assert expected <= {column["name"] for column in inspector.get_columns(table_name)}


def test_database_session_rolls_back_failed_transaction(tmp_path) -> None:
    database = Database(database_url=f"sqlite:///{tmp_path / 'transaction.db'}")
    database.create_all()

    with pytest.raises(RuntimeError, match="rollback sentinel"):
        with database.session() as session:
            session.add(WorkspaceModel(id="rolled-back", name="not committed"))
            raise RuntimeError("rollback sentinel")

    with database.session() as session:
        assert session.get(WorkspaceModel, "rolled-back") is None
        session.add(WorkspaceModel(id="committed", name="committed"))

    with database.session() as session:
        assert session.get(WorkspaceModel, "committed") is not None


def test_run_event_store_persists_ordered_structured_payload(tmp_path) -> None:
    database = Database(database_url=f"sqlite:///{tmp_path / 'events.db'}")
    database.create_all()
    repository = Repository(database)
    repository.ensure_defaults(["step"], workflow_name="event-demo", workflow_version="1.0.0")
    repository.ensure_project("event-project", "event-workspace")
    version = repository.ensure_defaults(
        ["step"], workflow_name="event-demo", workflow_version="1.0.0"
    )
    repository.create_run(
        run_id="event-run",
        project_id="event-project",
        workflow_version_id=version.id,
        input_artifact_id="input-artifact",
        input_hash="input-hash",
        correlation_id="corr-event",
        context={"source": "gate"},
        step_names=["step"],
    )

    repository.create_event("event-run", "run.created", {"sequence": 1})
    repository.create_event("event-run", "step.succeeded", {"sequence": 2}, step_name="step")
    events = repository.get_events("event-run")

    assert [event.event_type for event in events] == ["run.created", "step.succeeded"]
    assert events[1].step_name == "step"
    assert events[1].payload_json == {"sequence": 2}


def test_alembic_upgrade_creates_and_records_schema(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'alembic.db'}"
    config = _alembic_config(database_url)
    command.upgrade(config, "head")
    command.upgrade(config, "head")

    database = Database(database_url=database_url)
    assert set(inspect(database.engine).get_table_names()) >= REQUIRED_TABLES | {"alembic_version"}
    with database.engine.connect() as connection:
        assert connection.execute(select(1)).scalar_one() == 1


@pytest.mark.skipif(
    not os.getenv("STAGE2_POSTGRES_URL"),
    reason="set STAGE2_POSTGRES_URL to run the PostgreSQL integration evidence",
)
def test_postgresql_schema_and_transaction_contract() -> None:
    database = Database(database_url=os.environ["STAGE2_POSTGRES_URL"])
    database.create_all()
    assert set(inspect(database.engine).get_table_names()) >= REQUIRED_TABLES
    workspace_id = f"postgres-gate-{uuid.uuid4().hex[:12]}"
    with database.session() as session:
        session.add(WorkspaceModel(id=workspace_id, name="PostgreSQL Gate"))
    with database.session() as session:
        assert session.get(WorkspaceModel, workspace_id) is not None
