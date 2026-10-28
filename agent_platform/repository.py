from __future__ import annotations

import json
from typing import Any, Iterable

from sqlalchemy import desc, select

from .artifact_storage import ArtifactStore
from .db import (
    ArtifactModel, AttemptModel, CheckpointModel, Database, EvidenceModel,
    ExternalCallModel, ProjectModel, ReviewTaskModel, RunEventModel, RunModel,
    StepExecutionModel, TaskModel, ToolCallModel, WorkflowDefinitionModel,
    WorkflowVersionModel, WorkspaceModel,
)
from .domain import content_hash, stable_id, utcnow


class Repository:
    def __init__(self, database: Database) -> None:
        self.db = database

    def ensure_defaults(
        self,
        workflow_steps: list[str],
        *,
        workflow_name: str = "script-to-storyboard",
        workflow_version: str = "1.0.0",
        workflow_description: str = "Deterministic, evidence-backed script to storyboard workflow",
        definition_id: str | None = None,
        version_id: str | None = None,
    ) -> WorkflowVersionModel:
        """Ensure the registered workflow definition/version exists.

        The default values preserve the original storyboard identifiers. Named
        adapters receive deterministic identifiers so the runtime can persist an
        injected workflow without coupling the repository to one business plugin.
        """
        with self.db.session() as session:
            workspace = session.get(WorkspaceModel, "default-workspace")
            if workspace is None:
                session.add(WorkspaceModel(id="default-workspace", name="Default Workspace"))
            definition = session.execute(
                select(WorkflowDefinitionModel).where(WorkflowDefinitionModel.name == workflow_name)
            ).scalar_one_or_none()
            if definition is None:
                definition = WorkflowDefinitionModel(
                    id=definition_id or (
                        "workflow_script_to_storyboard"
                        if workflow_name == "script-to-storyboard" else stable_id("workflow", workflow_name)
                    ),
                    name=workflow_name,
                    description=workflow_description,
                )
                session.add(definition)
                session.flush()
            version = session.execute(
                select(WorkflowVersionModel).where(
                    WorkflowVersionModel.workflow_definition_id == definition.id,
                    WorkflowVersionModel.version == workflow_version,
                )
            ).scalar_one_or_none()
            if version is None:
                version = WorkflowVersionModel(
                    id=version_id or (
                        "workflow_script_to_storyboard_v1"
                        if workflow_name == "script-to-storyboard" and workflow_version == "1.0.0"
                        else stable_id("workflow-version", workflow_name, workflow_version)
                    ),
                    workflow_definition_id=definition.id, version=workflow_version,
                    step_names=workflow_steps, is_active=True,
                )
                session.add(version)
            return version

    def ensure_project(self, project_id: str, workspace_id: str, name: str | None = None) -> ProjectModel:
        with self.db.session() as session:
            workspace = session.get(WorkspaceModel, workspace_id)
            if workspace is None:
                session.add(WorkspaceModel(id=workspace_id, name=workspace_id))
            project = session.get(ProjectModel, project_id)
            if project is None:
                project = ProjectModel(
                    id=project_id, workspace_id=workspace_id, name=name or project_id,
                )
                session.add(project)
            return project

    def create_run(
        self, *, run_id: str, project_id: str, workflow_version_id: str,
        input_artifact_id: str | None, input_hash: str, correlation_id: str,
        context: dict[str, Any], step_names: Iterable[str],
    ) -> RunModel:
        step_names = list(step_names)
        with self.db.session() as session:
            run = RunModel(
                id=run_id, project_id=project_id, workflow_version_id=workflow_version_id,
                status="created", input_artifact_id=input_artifact_id,
                current_step=step_names[0] if step_names else None, correlation_id=correlation_id,
                input_hash=input_hash, context_json=context,
            )
            session.add(run)
            for step_name in step_names:
                step_id = stable_id("step", run_id, step_name)
                session.add(StepExecutionModel(
                    id=step_id, step_id=step_id,
                    run_id=run_id, step_name=step_name, status="pending", input_hash=input_hash,
                ))
                session.add(TaskModel(
                    id=stable_id("task", run_id, step_name), run_id=run_id, name=step_name,
                    status="pending", payload_json={"step_id": step_id},
                ))
            session.flush()
            return run

    def get_run(self, run_id: str) -> RunModel | None:
        with self.db.session() as session:
            return session.get(RunModel, run_id)

    def list_runs(self, *, project_id: str | None = None) -> list[RunModel]:
        with self.db.session() as session:
            stmt = select(RunModel).order_by(desc(RunModel.created_at))
            if project_id:
                stmt = stmt.where(RunModel.project_id == project_id)
            return list(session.execute(stmt).scalars())

    def find_completed_by_fingerprint(self, project_id: str, workflow_version_id: str, input_hash: str) -> RunModel | None:
        with self.db.session() as session:
            stmt = select(RunModel).where(
                RunModel.project_id == project_id,
                RunModel.workflow_version_id == workflow_version_id,
                RunModel.input_hash == input_hash,
                RunModel.status == "completed",
            ).order_by(desc(RunModel.created_at)).limit(1)
            return session.execute(stmt).scalar_one_or_none()

    def update_run(self, run_id: str, **fields: Any) -> RunModel:
        with self.db.session() as session:
            run = session.get(RunModel, run_id)
            if run is None:
                raise KeyError(run_id)
            for key, value in fields.items():
                setattr(run, key, value)
            run.updated_at = utcnow()
            session.flush()
            return run

    def get_steps(self, run_id: str) -> list[StepExecutionModel]:
        with self.db.session() as session:
            return list(session.execute(select(StepExecutionModel).where(StepExecutionModel.run_id == run_id).order_by(StepExecutionModel.id)).scalars())

    def get_step(self, run_id: str, step_name: str) -> StepExecutionModel | None:
        with self.db.session() as session:
            return session.execute(select(StepExecutionModel).where(
                StepExecutionModel.run_id == run_id, StepExecutionModel.step_name == step_name,
            )).scalar_one_or_none()

    def update_step(self, step_id: str, **fields: Any) -> StepExecutionModel:
        with self.db.session() as session:
            step = session.get(StepExecutionModel, step_id)
            if step is None:
                raise KeyError(step_id)
            for key, value in fields.items():
                setattr(step, key, value)
            session.flush()
            return step

    def update_task_for_step(self, run_id: str, step_id: str, status: str) -> None:
        with self.db.session() as session:
            task = session.execute(select(TaskModel).where(
                TaskModel.run_id == run_id, TaskModel.payload_json["step_id"].as_string() == step_id,
            )).scalar_one_or_none()
            if task is not None:
                task.status = status

    def create_attempt(self, **fields: Any) -> AttemptModel:
        with self.db.session() as session:
            attempt = AttemptModel(**fields)
            session.add(attempt)
            session.flush()
            return attempt

    def update_attempt(self, attempt_id: str, **fields: Any) -> AttemptModel:
        with self.db.session() as session:
            attempt = session.get(AttemptModel, attempt_id)
            if attempt is None:
                raise KeyError(attempt_id)
            for key, value in fields.items():
                setattr(attempt, key, value)
            session.flush()
            return attempt

    def get_attempts(self, run_id: str) -> list[AttemptModel]:
        with self.db.session() as session:
            return list(session.execute(select(AttemptModel).where(AttemptModel.run_id == run_id).order_by(AttemptModel.started_at)).scalars())

    def find_success_by_idempotency(self, key: str) -> AttemptModel | None:
        with self.db.session() as session:
            return session.execute(select(AttemptModel).where(
                AttemptModel.idempotency_key == key, AttemptModel.status == "succeeded",
            ).order_by(desc(AttemptModel.finished_at)).limit(1)).scalar_one_or_none()

    def create_artifact(self, **fields: Any) -> ArtifactModel:
        with self.db.session() as session:
            artifact = ArtifactModel(**fields)
            session.add(artifact)
            session.flush()
            return artifact

    def get_artifact(self, artifact_id: str) -> ArtifactModel | None:
        with self.db.session() as session:
            return session.get(ArtifactModel, artifact_id)

    def get_artifacts(self, run_id: str) -> list[ArtifactModel]:
        with self.db.session() as session:
            return list(session.execute(select(ArtifactModel).where(ArtifactModel.run_id == run_id).order_by(ArtifactModel.created_at)).scalars())

    def create_evidence(self, **fields: Any) -> EvidenceModel:
        with self.db.session() as session:
            evidence = EvidenceModel(**fields)
            session.add(evidence)
            session.flush()
            return evidence

    def get_evidence(self, run_id: str) -> list[EvidenceModel]:
        with self.db.session() as session:
            return list(session.execute(select(EvidenceModel).where(EvidenceModel.run_id == run_id)).scalars())

    def create_checkpoint(self, **fields: Any) -> CheckpointModel:
        with self.db.session() as session:
            checkpoint = CheckpointModel(**fields)
            session.add(checkpoint)
            session.flush()
            return checkpoint

    def latest_checkpoint(self, run_id: str) -> CheckpointModel | None:
        with self.db.session() as session:
            return session.execute(select(CheckpointModel).where(CheckpointModel.run_id == run_id).order_by(desc(CheckpointModel.sequence_no)).limit(1)).scalar_one_or_none()

    def list_error_inbox(self) -> list[dict[str, Any]]:
        """Return durable work requiring operator attention.

        The inbox intentionally projects three different persisted facts into one
        read model: terminal/uncertain runs, unknown external calls, and pending
        human reviews. It does not mutate or auto-retry any item.
        """
        with self.db.session() as session:
            items: list[dict[str, Any]] = []
            runs = session.execute(select(RunModel).where(
                RunModel.status.in_(["failed", "needs_recovery"]),
            ).order_by(RunModel.updated_at)).scalars()
            for run in runs:
                items.append({
                    "kind": "run", "item_id": run.id, "run_id": run.id,
                    "status": run.status, "error_code": run.error_code,
                    "error_message": run.error_message,
                    "created_at": run.created_at.isoformat() if run.created_at else None,
                    "updated_at": run.updated_at.isoformat() if run.updated_at else None,
                })

            unknown_calls = session.execute(select(ExternalCallModel).where(
                ExternalCallModel.status == "unknown",
            ).order_by(ExternalCallModel.updated_at)).scalars()
            for call in unknown_calls:
                items.append({
                    "kind": "external_call", "item_id": call.id, "run_id": call.run_id,
                    "status": call.status, "error_code": call.error_code,
                    "operation": call.operation, "provider": call.provider,
                    "created_at": call.created_at.isoformat() if call.created_at else None,
                    "updated_at": call.updated_at.isoformat() if call.updated_at else None,
                })

            reviews = session.execute(select(ReviewTaskModel).where(
                ReviewTaskModel.status == "pending",
            ).order_by(ReviewTaskModel.created_at)).scalars()
            for review in reviews:
                items.append({
                    "kind": "review", "item_id": review.id, "run_id": review.run_id,
                    "status": review.status, "scene_id": review.scene_id,
                    "artifact_id": review.artifact_id,
                    "created_at": review.created_at.isoformat() if review.created_at else None,
                })
            return items

    def create_review(self, **fields: Any) -> ReviewTaskModel:
        with self.db.session() as session:
            review = ReviewTaskModel(**fields)
            session.add(review)
            session.flush()
            return review

    def get_reviews(self, run_id: str, *, status: str | None = None) -> list[ReviewTaskModel]:
        with self.db.session() as session:
            stmt = select(ReviewTaskModel).where(ReviewTaskModel.run_id == run_id).order_by(ReviewTaskModel.created_at)
            if status:
                stmt = stmt.where(ReviewTaskModel.status == status)
            return list(session.execute(stmt).scalars())

    def decide_review(self, review_id: str, *, status: str, reviewer: str, comment: str) -> ReviewTaskModel:
        with self.db.session() as session:
            review = session.get(ReviewTaskModel, review_id)
            if review is None:
                raise KeyError(review_id)
            review.status = status
            review.reviewer = reviewer
            review.comment = comment
            review.decided_at = utcnow()
            session.flush()
            return review

    def create_event(self, run_id: str, event_type: str, payload: dict[str, Any], *, step_name: str | None = None) -> RunEventModel:
        with self.db.session() as session:
            event = RunEventModel(
                id=stable_id("event", run_id, event_type, utcnow().isoformat(), content_hash(payload)),
                run_id=run_id, event_type=event_type, step_name=step_name, payload_json=payload,
            )
            session.add(event)
            session.flush()
            return event

    def get_events(self, run_id: str) -> list[RunEventModel]:
        with self.db.session() as session:
            return list(session.execute(select(RunEventModel).where(RunEventModel.run_id == run_id).order_by(RunEventModel.created_at)).scalars())

    def create_external_call(self, **fields: Any) -> ExternalCallModel:
        with self.db.session() as session:
            call = ExternalCallModel(**fields)
            session.add(call)
            session.flush()
            return call

    def update_external_call(self, call_id: str, **fields: Any) -> ExternalCallModel:
        with self.db.session() as session:
            call = session.get(ExternalCallModel, call_id)
            if call is None:
                raise KeyError(call_id)
            for key, value in fields.items():
                setattr(call, key, value)
            call.updated_at = utcnow()
            session.flush()
            return call

    def get_external_calls(self, run_id: str) -> list[ExternalCallModel]:
        with self.db.session() as session:
            return list(session.execute(select(ExternalCallModel).where(ExternalCallModel.run_id == run_id).order_by(ExternalCallModel.created_at)).scalars())

    def create_tool_call(self, **fields: Any) -> ToolCallModel:
        with self.db.session() as session:
            call = ToolCallModel(**fields)
            session.add(call)
            session.flush()
            return call

    def list_workflows(self) -> list[tuple[WorkflowDefinitionModel, WorkflowVersionModel]]:
        with self.db.session() as session:
            rows = session.execute(select(WorkflowDefinitionModel, WorkflowVersionModel).join(
                WorkflowVersionModel, WorkflowVersionModel.workflow_definition_id == WorkflowDefinitionModel.id,
            )).all()
            return [(definition, version) for definition, version in rows]

    def serialize_model(self, model: Any) -> dict[str, Any]:
        data: dict[str, Any] = {}
        for column in model.__table__.columns:
            value = getattr(model, column.name)
            if hasattr(value, "isoformat"):
                value = value.isoformat()
            data[column.name] = value
        return data
