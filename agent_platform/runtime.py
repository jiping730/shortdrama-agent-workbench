from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from .config import Settings
from .db import Database, RunModel, StepExecutionModel
from .domain import (
    ErrorCode, InvalidTransition, PauseForReview, RunStatus, StepStatus,
    UnknownExternalCall, WorkflowStepError, assert_run_transition,
    assert_step_transition, content_hash, stable_id, utcnow,
)
from .providers import FakeModel, ModelProvider
from .repository import ArtifactStore, Repository
from .schemas import Evidence, Fact, Scene, Shot, Storyboard
from .workflows.base import WorkflowAdapter, assert_workflow_adapter
from .workflows.script_to_storyboard import ScriptToStoryboardAdapter


class SimulatedInterruption(RuntimeError):
    """Used by offline acceptance tests to model a worker process stopping."""


@dataclass
class RuntimeResult:
    run_id: str
    status: str
    paused_for_review: bool = False


class WorkflowRuntime:
    def __init__(
        self, *, database: Database | None = None, settings: Settings | None = None,
        model: ModelProvider | None = None, adapter: WorkflowAdapter | None = None,
    ) -> None:
        self.settings = settings or Settings.from_env()
        self.database = database or Database(self.settings)
        self.database.create_all()
        self.repository = Repository(self.database)
        self.model = model or FakeModel(self.settings.fake_model_mode)
        self.adapter = adapter or ScriptToStoryboardAdapter(self.model)
        assert_workflow_adapter(self.adapter)
        self._definition = self.adapter.register()
        self._step_names = tuple(step.name for step in self._definition.steps)
        self.artifacts = ArtifactStore(self.settings.artifact_dir)
        self.repository.ensure_defaults(
            list(self._step_names), workflow_name=self._definition.name,
            workflow_version=self._definition.version, workflow_description=self._definition.description,
        )

    @property
    def workflow_definition(self):
        return self._definition

    def create_run(
        self, *, project_id: str, script: str, script_id: str = "script-1", title: str = "Untitled",
        workspace_id: str = "default-workspace", project_name: str | None = None,
        model_mode: str | None = None, idempotency_key: str | None = None,
        stop_after_step: str | None = None,
    ) -> RuntimeResult:
        if model_mode and isinstance(self.model, FakeModel):
            self.model.mode = model_mode
        input_hash = content_hash({"script_id": script_id, "title": title, "script": script})
        version = self.repository.ensure_defaults(
            list(self._step_names), workflow_name=self._definition.name,
            workflow_version=self._definition.version, workflow_description=self._definition.description,
        )
        self.repository.ensure_project(project_id, workspace_id, project_name)
        existing = self.repository.find_completed_by_fingerprint(project_id, version.id, input_hash)
        if existing is not None:
            self.repository.create_event(existing.id, "run.idempotent_reuse", {"input_hash": input_hash})
            return RuntimeResult(existing.id, existing.status)

        run_id = stable_id("run", project_id, version.id, input_hash, idempotency_key or "default")
        existing_run = self.repository.get_run(run_id)
        if existing_run is not None:
            return RuntimeResult(existing_run.id, existing_run.status)
        input_artifact = self._create_artifact(
            run_id=run_id, artifact_type="script_input", value={"script_id": script_id, "title": title, "text": script},
            schema_version="script-input.v1", parents=[], metadata={"input_hash": input_hash},
        )
        context = {
            "run_id": run_id, "script_id": script_id, "title": title, "script_text": script,
            "input_hash": input_hash, "revision": 1, "scenes": [], "facts": [], "evidence": [],
            "shots": [], "storyboard": None, "rejected_scene_ids": [], "approved_scene_ids": [],
            "step_artifacts": {},
        }
        self.repository.create_run(
            run_id=run_id, project_id=project_id, workflow_version_id=version.id,
            input_artifact_id=input_artifact.id, input_hash=input_hash,
            correlation_id=stable_id("corr", run_id), context=context, step_names=self._step_names,
        )
        self.repository.create_event(run_id, "run.created", {"workflow": self.workflow_definition.name, "version": version.version})
        context = self._call_adapter_context_hook(run_id, "start", context)
        self.repository.create_event(run_id, "workflow.started", {"workflow": self.workflow_definition.name})
        self._set_run_status(run_id, RunStatus.QUEUED, reason="created")
        return self.execute_run(run_id, stop_after_step=stop_after_step)

    def execute_run(self, run_id: str, *, stop_after_step: str | None = None) -> RuntimeResult:
        run = self._require_run(run_id)
        if run.status in {RunStatus.CANCELLED.value, RunStatus.COMPLETED.value}:
            return RuntimeResult(run_id, run.status)
        if run.status == RunStatus.WAITING_REVIEW.value:
            return RuntimeResult(run_id, run.status, paused_for_review=True)
        if run.status in {RunStatus.CREATED.value, RunStatus.QUEUED.value, RunStatus.PAUSED.value}:
            self._set_run_status(run_id, RunStatus.RUNNING, reason="worker_started")
        elif run.status in {RunStatus.FAILED.value, RunStatus.NEEDS_RECOVERY.value}:
            self._set_run_status(run_id, RunStatus.QUEUED, reason="worker_restart")
            self._set_run_status(run_id, RunStatus.RUNNING, reason="worker_started")
        run = self._require_run(run_id)
        steps = self._ordered_steps(run_id)
        context = dict(run.context_json or {})

        for step in steps:
            if step.status == StepStatus.SUCCEEDED.value or step.status == StepStatus.SKIPPED.value:
                continue
            if self._require_run(run_id).status == RunStatus.PAUSED.value:
                return RuntimeResult(run_id, RunStatus.PAUSED.value)
            if step.status == StepStatus.WAITING_REVIEW.value:
                return RuntimeResult(run_id, RunStatus.WAITING_REVIEW.value, paused_for_review=True)
            if step.status == StepStatus.UNKNOWN.value:
                self._set_run_status(run_id, RunStatus.NEEDS_RECOVERY, reason="unknown_external_call")
                return RuntimeResult(run_id, RunStatus.NEEDS_RECOVERY.value)
            self._execute_step(run_id, step, context)
            run = self._require_run(run_id)
            context = dict(run.context_json or {})
            if stop_after_step == step.step_name:
                raise SimulatedInterruption(f"simulated worker interruption after {step.step_name}")
            if run.status in {RunStatus.WAITING_REVIEW.value, RunStatus.PAUSED.value, RunStatus.NEEDS_RECOVERY.value, RunStatus.FAILED.value}:
                return RuntimeResult(run_id, run.status, paused_for_review=run.status == RunStatus.WAITING_REVIEW.value)

        self._set_run_status(run_id, RunStatus.COMPLETED, reason="all_steps_succeeded")
        self.repository.create_event(run_id, "run.completed", {"run_id": run_id})
        return RuntimeResult(run_id, RunStatus.COMPLETED.value)

    def _execute_step(self, run_id: str, step: StepExecutionModel, context: dict[str, Any]) -> None:
        step_name = step.step_name
        input_snapshot = self._step_input_snapshot(step_name, context)
        input_hash = content_hash(input_snapshot)
        idem_key = stable_id("attempt", run_id, self._require_run(run_id).workflow_version_id, step_name, input_hash)
        previous = self.repository.find_success_by_idempotency(idem_key)
        if previous is not None and previous.output_artifact_id:
            self.repository.update_step(step.id, status=StepStatus.SUCCEEDED.value, input_hash=input_hash, output_artifact_id=previous.output_artifact_id, current_attempt=step.current_attempt)
            self.repository.create_event(run_id, "step.reused", {"step": step_name, "attempt_id": previous.id}, step_name=step_name)
            artifact = self.repository.get_artifact(previous.output_artifact_id)
            if artifact and artifact.content:
                prior_result = json.loads(artifact.content)
                context = self._apply_step_result(step_name, prior_result, context, run_id)
                context.setdefault("step_artifacts", {})[step_name] = artifact.id
                self.repository.update_run(run_id, context_json=context)
            self._advance(run_id, step_name, context, previous.output_artifact_id)
            return

        attempt_no = 1 + sum(1 for item in self.repository.get_attempts(run_id) if item.step_id == step.step_id)
        attempt_id = stable_id("attempt", run_id, step_name, attempt_no, input_hash)
        self._set_step(step.id, StepStatus.RUNNING, started_at=utcnow(), input_hash=input_hash, current_attempt=attempt_no)
        attempt = self.repository.create_attempt(
            id=attempt_id, step_id=step.step_id, run_id=run_id, attempt_no=attempt_no,
            input_snapshot=input_snapshot, output_artifact_id=None, model_version=getattr(self.model, "version", None),
            prompt_version="platform-default-v1", idempotency_key=idem_key, status="running", error_type=None,
        )
        external_call_id: str | None = None
        if step_name in {"extract_facts", "generate_storyboard", "revise_rejected_scenes"}:
            external_call_id = stable_id("external", run_id, step_name, attempt_no)
            self.repository.create_external_call(
                id=external_call_id, run_id=run_id, provider=getattr(self.model, "name", "unknown"), operation=step_name,
                request_json={"step": step_name, "input_hash": input_hash}, response_json=None,
                status="started", error_code=None, idempotency_key=idem_key,
            )
        self.repository.create_event(run_id, "step.started", {"step": step_name, "attempt_id": attempt_id}, step_name=step_name)
        try:
            result = self._normalize(self.adapter.validate(step_name, self.adapter.execute_step(step_name, context)))
            artifact = self._create_artifact(
                run_id=run_id, artifact_type=step_name, value=result, schema_version=f"{step_name}.v1",
                parents=[context.get("step_artifacts", {}).get(self._previous_step(step_name))] if self._previous_step(step_name) else [],
                metadata={"attempt_id": attempt_id, "input_hash": input_hash},
            )
            if external_call_id:
                self.repository.update_external_call(external_call_id, status="succeeded", response_json={"artifact_id": artifact.id})
            self.repository.update_attempt(attempt.id, status="succeeded", output_artifact_id=artifact.id, finished_at=utcnow())
            self._set_step(step.id, StepStatus.SUCCEEDED, output_artifact_id=artifact.id, finished_at=utcnow(), error_code=None)
            context = self._apply_step_result(step_name, result, context, run_id)
            context.setdefault("step_artifacts", {})[step_name] = artifact.id
            self.repository.update_run(run_id, context_json=context, current_step=self._next_step(step_name))
            self.repository.create_event(run_id, "step.succeeded", {"step": step_name, "artifact_id": artifact.id}, step_name=step_name)
            self._checkpoint(run_id, step_name, context, [artifact.id])
            if step_name == "wait_for_human_review":
                self._create_reviews_for_context(run_id, context, artifact.id)
                self._set_step(step.id, StepStatus.WAITING_REVIEW, finished_at=utcnow())
                self._set_run_status(run_id, RunStatus.WAITING_REVIEW, reason="human_review_required")
            elif step_name == "validate_storyboard" and context.get("selective_retry_active"):
                self._create_reviews_for_context(run_id, context, artifact.id)
                wait_step = self.repository.get_step(run_id, "wait_for_human_review")
                if wait_step and wait_step.status == StepStatus.SUCCEEDED.value:
                    self._set_step(wait_step.id, StepStatus.WAITING_REVIEW, finished_at=utcnow())
                self._set_run_status(run_id, RunStatus.WAITING_REVIEW, reason="selective_retry_review")
        except UnknownExternalCall as exc:
            if external_call_id:
                self.repository.update_external_call(external_call_id, status="unknown", error_code=ErrorCode.EXTERNAL_RESULT_UNKNOWN.value)
            self.repository.update_attempt(attempt.id, status="unknown", error_type=ErrorCode.EXTERNAL_RESULT_UNKNOWN.value, error_message=str(exc), finished_at=utcnow())
            self._set_step(step.id, StepStatus.UNKNOWN, error_code=ErrorCode.EXTERNAL_RESULT_UNKNOWN.value, finished_at=utcnow())
            self.repository.create_event(run_id, "external_call.unknown", {"step": step_name, "attempt_id": attempt_id}, step_name=step_name)
            self._set_run_status(run_id, RunStatus.NEEDS_RECOVERY, reason="external_result_unknown")
        except WorkflowStepError as exc:
            if external_call_id:
                self.repository.update_external_call(external_call_id, status="failed", error_code=exc.code.value)
            self.repository.update_attempt(attempt.id, status="failed", error_type=exc.code.value, error_message=str(exc), finished_at=utcnow())
            self._set_step(step.id, StepStatus.FAILED, error_code=exc.code.value, finished_at=utcnow())
            self.repository.create_event(run_id, "step.failed", {"step": step_name, "error_code": exc.code.value, "message": str(exc)}, step_name=step_name)
            self.repository.update_run(run_id, error_code=exc.code.value, error_message=str(exc))
            self._set_run_status(run_id, RunStatus.FAILED, reason=exc.code.value)
        except Exception as exc:  # pragma: no cover - defensive boundary
            if external_call_id:
                self.repository.update_external_call(external_call_id, status="failed", error_code=ErrorCode.UNEXPECTED_ERROR.value)
            self.repository.update_attempt(attempt.id, status="failed", error_type=ErrorCode.UNEXPECTED_ERROR.value, error_message=str(exc), finished_at=utcnow())
            self._set_step(step.id, StepStatus.FAILED, error_code=ErrorCode.UNEXPECTED_ERROR.value, finished_at=utcnow())
            self.repository.create_event(run_id, "step.failed", {"step": step_name, "error_code": ErrorCode.UNEXPECTED_ERROR.value}, step_name=step_name)
            self.repository.update_run(run_id, error_code=ErrorCode.UNEXPECTED_ERROR.value, error_message=str(exc))
            self._set_run_status(run_id, RunStatus.FAILED, reason="unexpected_error")

    def approve_review(self, review_id: str, reviewer: str, comment: str = "") -> RuntimeResult:
        review = self._review(review_id)
        if review.status != "pending":
            raise ValueError("review is already decided")
        review = self.repository.decide_review(review_id, status="approved", reviewer=reviewer, comment=comment)
        self.repository.create_event(review.run_id, "review.approved", {"review_id": review_id, "scene_id": review.scene_id, "reviewer": reviewer})
        pending = self.repository.get_reviews(review.run_id, status="pending")
        if pending:
            return RuntimeResult(review.run_id, RunStatus.WAITING_REVIEW.value, paused_for_review=True)
        run = self._require_run(review.run_id)
        rejected = self.repository.get_reviews(review.run_id, status="rejected")
        if rejected and not dict(run.context_json or {}).get("selective_retry_active"):
            return RuntimeResult(review.run_id, RunStatus.WAITING_REVIEW.value, paused_for_review=True)
        self._finish_review_gate(review.run_id)
        return self.execute_run(review.run_id)

    def reject_review(self, review_id: str, reviewer: str, comment: str = "") -> RuntimeResult:
        review = self._review(review_id)
        if review.status != "pending":
            raise ValueError("review is already decided")
        review = self.repository.decide_review(review_id, status="rejected", reviewer=reviewer, comment=comment)
        self.repository.create_event(review.run_id, "review.rejected", {"review_id": review_id, "scene_id": review.scene_id, "reviewer": reviewer, "comment": comment})
        self.repository.update_run(review.run_id, error_code=ErrorCode.REVIEW_REJECTED.value, error_message=comment or "review rejected")
        return RuntimeResult(review.run_id, RunStatus.WAITING_REVIEW.value, paused_for_review=True)

    def retry(self, run_id: str, *, step_name: str | None = None, scene_ids: list[str] | None = None) -> RuntimeResult:
        run = self._require_run(run_id)
        scene_ids = scene_ids or []
        if scene_ids:
            rejected = [review for review in self.repository.get_reviews(run_id, status="rejected") if review.scene_id in scene_ids]
            if set(review.scene_id for review in rejected) != set(scene_ids):
                raise WorkflowStepError(ErrorCode.REVIEW_REJECTED, "retry scenes must have rejected review tasks")
            context = dict(run.context_json or {})
            context["rejected_scene_ids"] = list(scene_ids)
            context["revision"] = int(context.get("revision", 1)) + 1
            context["selective_retry_active"] = True
            self.repository.update_run(run_id, context_json=context)
            revise_step = self.repository.get_step(run_id, "revise_rejected_scenes")
            if revise_step and revise_step.status == StepStatus.SUCCEEDED.value:
                self.repository.update_step(revise_step.id, status=StepStatus.PENDING.value, output_artifact_id=None, error_code=None)
            wait_step = self.repository.get_step(run_id, "wait_for_human_review")
            if wait_step:
                if wait_step.status == StepStatus.WAITING_REVIEW.value:
                    self._set_step(wait_step.id, StepStatus.SUCCEEDED, output_artifact_id=wait_step.output_artifact_id)
                elif wait_step.status != StepStatus.SUCCEEDED.value:
                    self.repository.update_step(wait_step.id, status=StepStatus.SUCCEEDED.value, output_artifact_id=wait_step.output_artifact_id)
            validate_step = self.repository.get_step(run_id, "validate_storyboard")
            if validate_step and validate_step.status == StepStatus.SUCCEEDED.value:
                self._set_step(validate_step.id, StepStatus.PENDING, output_artifact_id=None)
            self._set_run_status(run_id, RunStatus.QUEUED, reason="selective_scene_retry")
            return self.execute_run(run_id)

        target = step_name or next((s.step_name for s in self.repository.get_steps(run_id) if s.status == StepStatus.FAILED.value), None)
        if not target:
            raise WorkflowStepError(ErrorCode.INVALID_INPUT, "no failed step to retry")
        step = self.repository.get_step(run_id, target)
        if step is None:
            raise WorkflowStepError(ErrorCode.INVALID_INPUT, f"unknown step: {target}")
        self.repository.update_step(step.id, status=StepStatus.PENDING.value, error_code=None, finished_at=None)
        self.repository.update_run(run_id, error_code=None, error_message=None, current_step=target)
        self._set_run_status(run_id, RunStatus.QUEUED, reason="selective_step_retry")
        return self.execute_run(run_id)

    def pause(self, run_id: str) -> RuntimeResult:
        run = self._require_run(run_id)
        if run.status in {RunStatus.COMPLETED.value, RunStatus.CANCELLED.value}:
            return RuntimeResult(run_id, run.status)
        self._set_run_status(run_id, RunStatus.PAUSED, reason="operator_pause")
        return RuntimeResult(run_id, RunStatus.PAUSED.value)

    def resume(self, run_id: str) -> RuntimeResult:
        run = self._require_run(run_id)
        if run.status == RunStatus.WAITING_REVIEW.value:
            if self.repository.get_reviews(run_id, status="pending"):
                return RuntimeResult(run_id, run.status, paused_for_review=True)
            if self.repository.get_reviews(run_id, status="rejected") and not dict(run.context_json or {}).get("selective_retry_active"):
                raise WorkflowStepError(ErrorCode.REVIEW_REJECTED, "rejected scenes require selective retry")
            self._finish_review_gate(run_id)
        context = self._call_adapter_context_hook(run_id, "resume", dict(self._require_run(run_id).context_json or {}))
        self.repository.create_event(run_id, "workflow.resumed", {"workflow": self.workflow_definition.name})
        return self.execute_run(run_id)

    def cancel(self, run_id: str) -> RuntimeResult:
        self._set_run_status(run_id, RunStatus.CANCELLED, reason="operator_cancel")
        return RuntimeResult(run_id, RunStatus.CANCELLED.value)

    def recover(self, run_id: str) -> RuntimeResult:
        run = self._require_run(run_id)
        checkpoint = self.repository.latest_checkpoint(run_id)
        if checkpoint is None:
            raise WorkflowStepError(ErrorCode.PERSISTENCE_ERROR, "no checkpoint available for recovery")
        context = self._call_adapter_context_hook(run_id, "recover", dict(checkpoint.snapshot_json))
        self.repository.update_run(run_id, context_json=context, current_step=checkpoint.step_name, error_code=None, error_message=None)
        for step in self.repository.get_steps(run_id):
            if step.status == StepStatus.RUNNING.value:
                self.repository.update_step(step.id, status=StepStatus.PENDING.value)
        if run.status != RunStatus.NEEDS_RECOVERY.value:
            self._set_run_status(run_id, RunStatus.NEEDS_RECOVERY, reason="recovery_requested")
        self._set_run_status(run_id, RunStatus.QUEUED, reason="checkpoint_loaded")
        self.repository.create_event(run_id, "run.recovered", {"checkpoint_id": checkpoint.id, "sequence_no": checkpoint.sequence_no})
        return self.execute_run(run_id)

    def _create_reviews_for_context(self, run_id: str, context: dict[str, Any], artifact_id: str) -> None:
        existing_pending_or_approved = {(review.scene_id, review.status) for review in self.repository.get_reviews(run_id)}
        for scene_id in [scene["scene_id"] for scene in context.get("scenes", [])]:
            if (scene_id, "approved") in existing_pending_or_approved:
                continue
            if any(review.scene_id == scene_id and review.status == "pending" for review in self.repository.get_reviews(run_id)):
                continue
            self.repository.create_review(
                id=stable_id("review", run_id, scene_id, context.get("revision", 1)), run_id=run_id,
                scene_id=scene_id, artifact_id=artifact_id, status="pending", reviewer=None, comment=None,
            )
            self.repository.create_event(run_id, "review.created", {"scene_id": scene_id, "artifact_id": artifact_id})

    def _finish_review_gate(self, run_id: str) -> None:
        wait_step = self.repository.get_step(run_id, "wait_for_human_review")
        if wait_step and wait_step.status == StepStatus.WAITING_REVIEW.value:
            self._set_step(wait_step.id, StepStatus.SUCCEEDED, finished_at=utcnow())
        self.repository.update_run(run_id, current_step="revise_rejected_scenes")
        self._set_run_status(run_id, RunStatus.QUEUED, reason="review_approved")

    def _apply_step_result(self, step_name: str, result: Any, context: dict[str, Any], run_id: str) -> dict[str, Any]:
        context = dict(context)
        if step_name == "split_script":
            context["scenes"] = result
            evidence: list[dict[str, Any]] = []
            for scene in result:
                source_start, source_end = scene["source_start"], scene["source_end"]
                for evidence_id in scene["evidence_ids"]:
                    entry = Evidence(
                        evidence_id=evidence_id, script_id=context["script_id"], scene_id=scene["scene_id"],
                        source_start=source_start, source_end=source_end, source_text=scene["source_text"],
                        content_hash=content_hash(scene["source_text"]),
                    )
                    self.repository.create_evidence(
                        id=entry.evidence_id, run_id=run_id, script_id=entry.script_id, scene_id=entry.scene_id,
                        source_start=entry.source_start, source_end=entry.source_end, source_text=entry.source_text,
                        content_hash=entry.content_hash,
                    )
                    evidence.append(entry.model_dump(mode="json"))
            context["evidence"] = evidence
        elif step_name == "extract_facts":
            context["facts"] = result
        elif step_name == "generate_storyboard":
            context["shots"] = result
        elif step_name == "validate_storyboard":
            context["storyboard"] = result
        elif step_name == "revise_rejected_scenes":
            old_shots = {shot["scene_id"]: shot for shot in context.get("shots", [])}
            old_shots.update({shot["scene_id"]: shot for shot in result})
            context["shots"] = list(old_shots.values())
        return context

    def _step_input_snapshot(self, step_name: str, context: dict[str, Any]) -> dict[str, Any]:
        keys = {
            "prepare_input": ["script_id", "title", "script_text"],
            "split_script": ["script_id", "script_text"],
            "build_source_index": ["scenes"],
            "extract_facts": ["script_text", "scenes"],
            "validate_facts": ["facts", "evidence"],
            "generate_storyboard": ["script_text", "scenes", "facts", "revision"],
            "validate_storyboard": ["shots", "scenes", "evidence", "revision"],
            "wait_for_human_review": ["storyboard", "revision"],
            "revise_rejected_scenes": ["script_text", "scenes", "facts", "rejected_scene_ids", "revision"],
            "adopt_result": ["storyboard"], "export_artifacts": ["storyboard"],
        }.get(step_name)
        if keys is None:
            # Generic adapters can choose their own context shape. Hashing the
            # complete durable context gives them the same idempotency boundary.
            return dict(context)
        return {key: context.get(key) for key in keys}

    def _advance(self, run_id: str, step_name: str, context: dict[str, Any], artifact_id: str) -> None:
        self.repository.update_run(run_id, current_step=self._next_step(step_name))

    def _checkpoint(self, run_id: str, step_name: str, context: dict[str, Any], artifact_ids: list[str]) -> None:
        previous = self.repository.latest_checkpoint(run_id)
        self.repository.create_checkpoint(
            id=stable_id("checkpoint", run_id, (previous.sequence_no + 1 if previous else 1)), run_id=run_id,
            sequence_no=(previous.sequence_no + 1 if previous else 1), step_name=self._next_step(step_name) or step_name,
            snapshot_json=context, artifact_ids=artifact_ids,
        )

    def _create_artifact(self, *, run_id: str | None, artifact_type: str, value: Any, schema_version: str, parents: list[str | None], metadata: dict[str, Any]) -> Any:
        clean_parents = [parent for parent in parents if parent]
        serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, default=str)
        artifact_id = stable_id("artifact", run_id or "global", artifact_type, content_hash(value), *clean_parents)
        uri = self.artifacts.put(artifact_id, serialized)
        return self.repository.create_artifact(
            id=artifact_id, run_id=run_id, artifact_type=artifact_type, content_hash=content_hash(value),
            schema_version=schema_version, content_uri=uri, content=serialized,
            parent_artifact_ids=clean_parents, metadata_json=metadata,
        )

    def _set_run_status(self, run_id: str, target: RunStatus, *, reason: str) -> None:
        run = self._require_run(run_id)
        current = RunStatus(run.status)
        if current != target:
            try:
                assert_run_transition(current, target)
            except InvalidTransition:
                self.repository.create_event(run_id, "run.illegal_transition", {"from": current.value, "to": target.value, "reason": reason})
                raise
            self.repository.update_run(run_id, status=target.value)
            self.repository.create_event(run_id, "run.status_changed", {"from": current.value, "to": target.value, "reason": reason})

    def _set_step(self, step_id: str, target: StepStatus, **fields: Any) -> None:
        step = self.repository.get_step_by_id(step_id) if hasattr(self.repository, "get_step_by_id") else None
        if step is None:
            with self.database.session() as session:
                step = session.get(StepExecutionModel, step_id)
        if step is None:
            raise KeyError(step_id)
        current = StepStatus(step.status)
        if current != target:
            assert_step_transition(current, target)
        self.repository.update_step(step_id, status=target.value, **fields)
        self.repository.update_task_for_step(step.run_id, step_id, target.value)

    def _require_run(self, run_id: str) -> RunModel:
        run = self.repository.get_run(run_id)
        if run is None:
            raise KeyError(f"run not found: {run_id}")
        return run

    def _review(self, review_id: str):
        with self.database.session() as session:
            from .db import ReviewTaskModel
            review = session.get(ReviewTaskModel, review_id)
            if review is None:
                raise KeyError(f"review not found: {review_id}")
            return review

    def _next_step(self, step_name: str) -> str | None:
        try:
            index = self._step_names.index(step_name)
        except ValueError:
            return None
        return self._step_names[index + 1] if index + 1 < len(self._step_names) else None

    def _ordered_steps(self, run_id: str) -> list[StepExecutionModel]:
        order = {name: index for index, name in enumerate(self._step_names)}
        return sorted(self.repository.get_steps(run_id), key=lambda step: order.get(step.step_name, 999))

    def _previous_step(self, step_name: str) -> str | None:
        try:
            index = self._step_names.index(step_name)
        except ValueError:
            return None
        return self._step_names[index - 1] if index > 0 else None

    @staticmethod
    def _normalize(value: Any) -> Any:
        if isinstance(value, BaseModel):
            return value.model_dump(mode="json")
        if isinstance(value, list):
            return [WorkflowRuntime._normalize(item) for item in value]
        if isinstance(value, dict):
            return {key: WorkflowRuntime._normalize(item) for key, item in value.items()}
        return value

    def _call_adapter_context_hook(
        self, run_id: str, hook_name: str, context: dict[str, Any]
    ) -> dict[str, Any]:
        hook = getattr(self.adapter, hook_name)
        result = hook(dict(context))
        if not isinstance(result, dict):
            raise TypeError(f"workflow adapter {hook_name}() must return a context dict")
        self.repository.update_run(run_id, context_json=result)
        return result
