from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.types import JSON

from .config import Settings
from .domain import utcnow


class Base(DeclarativeBase):
    pass


class WorkspaceModel(Base):
    __tablename__ = "workspaces"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProjectModel(Base):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WorkflowDefinitionModel(Base):
    __tablename__ = "workflow_definitions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WorkflowVersionModel(Base):
    __tablename__ = "workflow_versions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workflow_definition_id: Mapped[str] = mapped_column(ForeignKey("workflow_definitions.id"), index=True)
    version: Mapped[str] = mapped_column(String(50))
    step_names: Mapped[list] = mapped_column(JSON, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RunModel(Base):
    __tablename__ = "runs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    workflow_version_id: Mapped[str] = mapped_column(ForeignKey("workflow_versions.id"), index=True)
    status: Mapped[str] = mapped_column(String(40), index=True)
    input_artifact_id: Mapped[str] = mapped_column(String(64), nullable=True)
    current_step: Mapped[str] = mapped_column(String(120), nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(64), index=True)
    input_hash: Mapped[str] = mapped_column(String(64), index=True)
    context_json: Mapped[dict] = mapped_column(JSON, default=dict)
    error_code: Mapped[str] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class TaskModel(Base):
    __tablename__ = "tasks"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(40), index=True)
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class StepExecutionModel(Base):
    __tablename__ = "step_executions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    step_id: Mapped[str] = mapped_column(String(64), index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    step_name: Mapped[str] = mapped_column(String(120), index=True)
    status: Mapped[str] = mapped_column(String(40), index=True)
    input_hash: Mapped[str] = mapped_column(String(64))
    current_attempt: Mapped[int] = mapped_column(Integer, default=0)
    output_artifact_id: Mapped[str] = mapped_column(String(64), nullable=True)
    error_code: Mapped[str] = mapped_column(String(80), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)


class AttemptModel(Base):
    __tablename__ = "attempts"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    step_id: Mapped[str] = mapped_column(String(64), index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    attempt_no: Mapped[int] = mapped_column(Integer)
    input_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    output_artifact_id: Mapped[str] = mapped_column(String(64), nullable=True)
    model_version: Mapped[str] = mapped_column(String(120), nullable=True)
    prompt_version: Mapped[str] = mapped_column(String(120), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), index=True)
    status: Mapped[str] = mapped_column(String(40), index=True)
    error_type: Mapped[str] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)


class CheckpointModel(Base):
    __tablename__ = "checkpoints"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    sequence_no: Mapped[int] = mapped_column(Integer)
    step_name: Mapped[str] = mapped_column(String(120))
    snapshot_json: Mapped[dict] = mapped_column(JSON, default=dict)
    artifact_ids: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ArtifactModel(Base):
    __tablename__ = "artifacts"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), nullable=True, index=True)
    artifact_type: Mapped[str] = mapped_column(String(120), index=True)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    schema_version: Mapped[str] = mapped_column(String(50))
    content_uri: Mapped[str] = mapped_column(Text, nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=True)
    parent_artifact_ids: Mapped[list] = mapped_column(JSON, default=list)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EvidenceModel(Base):
    __tablename__ = "evidence"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    script_id: Mapped[str] = mapped_column(String(64), index=True)
    scene_id: Mapped[str] = mapped_column(String(64), nullable=True, index=True)
    source_start: Mapped[int] = mapped_column(Integer)
    source_end: Mapped[int] = mapped_column(Integer)
    source_text: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))


class ReviewTaskModel(Base):
    __tablename__ = "review_tasks"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    scene_id: Mapped[str] = mapped_column(String(64), nullable=True, index=True)
    artifact_id: Mapped[str] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(40), index=True)
    reviewer: Mapped[str] = mapped_column(String(120), nullable=True)
    comment: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)


class ToolCallModel(Base):
    __tablename__ = "tool_calls"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    tool_name: Mapped[str] = mapped_column(String(160))
    tool_version: Mapped[str] = mapped_column(String(50))
    input_json: Mapped[dict] = mapped_column(JSON, default=dict)
    output_json: Mapped[dict] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(40))
    error_code: Mapped[str] = mapped_column(String(80), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)


class ExternalCallModel(Base):
    __tablename__ = "external_calls"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    provider: Mapped[str] = mapped_column(String(120))
    operation: Mapped[str] = mapped_column(String(120))
    request_json: Mapped[dict] = mapped_column(JSON, default=dict)
    response_json: Mapped[dict] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(40), index=True)
    error_code: Mapped[str] = mapped_column(String(80), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class RunEventModel(Base):
    __tablename__ = "run_events"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(120), index=True)
    step_name: Mapped[str] = mapped_column(String(120), nullable=True)
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Database:
    def __init__(self, settings: Settings | None = None, *, database_url: str | None = None) -> None:
        self.settings = settings or Settings.from_env()
        url = database_url or self.settings.database_url
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        self.engine = create_engine(url, future=True, pool_pre_ping=True, connect_args=connect_args)
        self.SessionLocal = sessionmaker(self.engine, expire_on_commit=False, class_=Session)

    def create_all(self) -> None:
        Base.metadata.create_all(self.engine)

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def table_counts(self) -> dict[str, int]:
        tables = [
            WorkspaceModel, ProjectModel, WorkflowDefinitionModel, WorkflowVersionModel, RunModel,
            TaskModel, StepExecutionModel, AttemptModel, CheckpointModel, ArtifactModel,
            EvidenceModel, ReviewTaskModel, ToolCallModel, ExternalCallModel, RunEventModel,
        ]
        with self.session() as session:
            return {model.__tablename__: len(session.execute(select(model.id)).all()) for model in tables}
