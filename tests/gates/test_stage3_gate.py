from __future__ import annotations

import pytest

from agent_platform.config import Settings
from agent_platform.db import Database
from agent_platform.domain import ErrorCode, InvalidTransition, RunStatus, StepStatus, WorkflowStepError
from agent_platform.providers import FakeModel
from agent_platform.runtime import SimulatedInterruption, WorkflowRuntime


def _runtime(tmp_path, name: str, model: FakeModel) -> WorkflowRuntime:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / f'{name}.db'}",
        artifact_dir=tmp_path / f"{name}-artifacts",
    )
    return WorkflowRuntime(database=Database(settings), settings=settings, model=model)


def test_process_restart_recovers_from_checkpoint_without_reexecuting_successful_steps(tmp_path, script):
    first_model = FakeModel()
    first = _runtime(tmp_path, "restart", first_model)
    with pytest.raises(SimulatedInterruption):
        first.create_run(project_id="restart-project", script=script, stop_after_step="split_script")

    run_id = first.repository.list_runs(project_id="restart-project")[0].id
    attempts_before = first.repository.get_attempts(run_id)
    step_names = {step.step_id: step.step_name for step in first.repository.get_steps(run_id)}
    successful_before = {
        step_names[attempt.step_id]: attempt.id
        for attempt in attempts_before if attempt.status == "succeeded"
    }

    second_model = FakeModel()
    second = _runtime(tmp_path, "restart", second_model)
    recovered = second.recover(run_id)

    assert recovered.status == RunStatus.WAITING_REVIEW.value
    attempts_after = second.repository.get_attempts(run_id)
    step_names_after = {step.step_id: step.step_name for step in second.repository.get_steps(run_id)}
    successful_after = {
        step_names_after[attempt.step_id]: attempt.id
        for attempt in attempts_after if attempt.status == "succeeded"
    }
    assert successful_after["prepare_input"] == successful_before["prepare_input"]
    assert successful_after["split_script"] == successful_before["split_script"]
    assert [call["operation"] for call in second_model.calls] == [
        "generate_facts", "generate_storyboard",
    ]
    assert second.repository.latest_checkpoint(run_id).sequence_no >= 8
    assert any(event.event_type == "run.recovered" for event in second.repository.get_events(run_id))


def test_successful_step_attempts_are_not_duplicated_when_execution_resumes(tmp_path, script):
    model = FakeModel()
    runtime = _runtime(tmp_path, "resume-idempotency", model)
    with pytest.raises(SimulatedInterruption):
        runtime.create_run(project_id="resume-project", script=script, stop_after_step="split_script")
    run_id = runtime.repository.list_runs(project_id="resume-project")[0].id
    attempts_before = len(runtime.repository.get_attempts(run_id))
    steps_before = {
        step.step_name: step.output_artifact_id
        for step in runtime.repository.get_steps(run_id)
        if step.status == StepStatus.SUCCEEDED.value
    }

    result = runtime.execute_run(run_id)

    assert result.status == RunStatus.WAITING_REVIEW.value
    attempts_after = runtime.repository.get_attempts(run_id)
    assert len(attempts_after) > attempts_before
    steps_after = {step.step_name: step.output_artifact_id for step in runtime.repository.get_steps(run_id)}
    assert steps_after["prepare_input"] == steps_before["prepare_input"]
    assert steps_after["split_script"] == steps_before["split_script"]
    assert len([call for call in model.calls if call["operation"] == "generate_facts"]) == 1
    assert len([call for call in model.calls if call["operation"] == "generate_storyboard"]) == 1


def test_selective_scene_retry_preserves_attempts_and_only_revises_rejected_scene(runtime, script):
    result = runtime.create_run(project_id="selective-gate", script=script)
    reviews = runtime.repository.get_reviews(result.run_id)
    rejected_scene = reviews[0].scene_id
    approved_scene = reviews[1].scene_id
    runtime.reject_review(reviews[0].id, "reviewer", "revise action")
    runtime.approve_review(reviews[1].id, "reviewer")
    attempts_before = runtime.repository.get_attempts(result.run_id)
    generated_attempts_before = len(attempts_before)

    retried = runtime.retry(result.run_id, scene_ids=[rejected_scene])

    assert retried.status == RunStatus.WAITING_REVIEW.value
    attempts_after = runtime.repository.get_attempts(result.run_id)
    assert len(attempts_after) > len(attempts_before)
    revisions = [call for call in runtime.model.calls if call["operation"] == "revise_storyboard"]
    assert revisions[-1]["scene_ids"] == [rejected_scene]
    assert approved_scene not in revisions[-1]["scene_ids"]
    assert len([call for call in runtime.model.calls if call["operation"] == "generate_storyboard"]) == 1
    assert len(runtime.repository.get_attempts(result.run_id)) > generated_attempts_before
    revised_artifacts = [artifact for artifact in runtime.repository.get_artifacts(result.run_id) if artifact.artifact_type == "revise_rejected_scenes"]
    assert revised_artifacts and revised_artifacts[-1].parent_artifact_ids


def test_timeout_becomes_unknown_and_is_not_automatically_retried(tmp_path, script):
    model = FakeModel(mode="timeout")
    runtime = _runtime(tmp_path, "timeout", model)
    result = runtime.create_run(project_id="timeout-project", script=script)

    assert result.status == RunStatus.NEEDS_RECOVERY.value
    assert len(model.calls) == 1
    assert runtime.repository.get_external_calls(result.run_id)[0].status == "unknown"
    unknown_step = runtime.repository.get_step(result.run_id, "extract_facts")
    assert unknown_step.status == StepStatus.UNKNOWN.value
    assert runtime.repository.get_attempts(result.run_id)[-1].status == "unknown"
    assert runtime.resume(result.run_id).status == RunStatus.NEEDS_RECOVERY.value
    assert len(model.calls) == 1
    with pytest.raises(WorkflowStepError) as error:
        runtime.retry(result.run_id, step_name="extract_facts")
    assert error.value.code == ErrorCode.EXTERNAL_RESULT_UNKNOWN
    assert len(model.calls) == 1


def test_error_inbox_contains_failed_unknown_and_human_review_items(tmp_path, script):
    model = FakeModel()
    runtime = _runtime(tmp_path, "inbox", model)
    failed = runtime.create_run(project_id="failed-project", script=script, model_mode="invalid_output")
    review_run = runtime.create_run(project_id="review-project", script=script, model_mode="success")
    unknown = runtime.create_run(project_id="unknown-project", script=script, model_mode="unknown")

    items = runtime.repository.list_error_inbox()
    kinds_by_run = {(item["kind"], item["run_id"]) for item in items}
    assert ("run", failed.run_id) in kinds_by_run
    assert ("run", unknown.run_id) in kinds_by_run
    assert any(item["kind"] == "external_call" and item["run_id"] == unknown.run_id for item in items)
    assert any(item["kind"] == "review" and item["run_id"] == review_run.run_id for item in items)


def test_pause_resume_and_cancel_are_safe_at_boundaries(runtime, script):
    result = runtime.create_run(project_id="operator-project", script=script)
    paused = runtime.pause(result.run_id)
    assert paused.status == RunStatus.PAUSED.value
    assert runtime.resume(result.run_id).status == RunStatus.WAITING_REVIEW.value
    assert runtime.cancel(result.run_id).status == RunStatus.CANCELLED.value
    assert runtime.cancel(result.run_id).status == RunStatus.CANCELLED.value


def test_illegal_step_transition_is_audited(runtime, script):
    result = runtime.create_run(project_id="transition-project", script=script)
    step = runtime.repository.get_step(result.run_id, "prepare_input")
    with pytest.raises(InvalidTransition):
        runtime._set_step(step.id, StepStatus.RUNNING)
    assert any(
        event.event_type == "step.illegal_transition"
        and event.step_name == "prepare_input"
        for event in runtime.repository.get_events(result.run_id)
    )
