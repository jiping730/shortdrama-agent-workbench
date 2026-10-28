from agent_platform.domain import ErrorCode, RunStatus
from agent_platform.providers import FakeModel
from agent_platform.runtime import SimulatedInterruption, WorkflowRuntime


def test_offline_run_reaches_review_and_selective_retry_only_calls_rejected_scene(runtime, script):
    result = runtime.create_run(project_id="project-1", script=script)
    assert result.status == RunStatus.WAITING_REVIEW.value
    reviews = runtime.repository.get_reviews(result.run_id)
    assert len(reviews) == 2

    runtime.reject_review(reviews[0].id, "reviewer", "action is unclear")
    runtime.approve_review(reviews[1].id, "reviewer")
    runtime.retry(result.run_id, scene_ids=[reviews[0].scene_id])
    replacement = [
        review
        for review in runtime.repository.get_reviews(result.run_id)
        if review.status == "pending"
    ]
    assert len(replacement) == 1
    assert replacement[0].scene_id == reviews[0].scene_id

    runtime.approve_review(replacement[0].id, "reviewer")
    assert runtime.repository.get_run(result.run_id).status == RunStatus.COMPLETED.value
    calls = runtime.model.calls
    revisions = [call for call in calls if call["operation"] == "revise_storyboard"]
    assert len(revisions) == 1
    assert revisions[0]["scene_ids"] == [reviews[0].scene_id]


def test_repeated_completed_input_reuses_run_without_new_success_attempts(runtime, script):
    first = runtime.create_run(project_id="project-2", script=script)
    for review in runtime.repository.get_reviews(first.run_id):
        runtime.approve_review(review.id, "reviewer")
    attempts_before = len(runtime.repository.get_attempts(first.run_id))
    second = runtime.create_run(project_id="project-2", script=script)
    assert second.run_id == first.run_id
    assert len(runtime.repository.get_attempts(first.run_id)) == attempts_before


def test_unknown_external_result_is_persisted_and_not_blindly_retried(tmp_path, script):
    from agent_platform.config import Settings
    from agent_platform.db import Database

    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'unknown.db'}", artifact_dir=tmp_path / "artifacts"
    )
    model = FakeModel(mode="unknown")
    runtime = WorkflowRuntime(database=Database(settings), settings=settings, model=model)
    result = runtime.create_run(project_id="project-3", script=script)
    assert result.status == RunStatus.NEEDS_RECOVERY.value
    assert runtime.repository.get_external_calls(result.run_id)[0].status == "unknown"
    assert len(model.calls) == 1
    resumed = runtime.resume(result.run_id)
    assert resumed.status == RunStatus.NEEDS_RECOVERY.value
    assert len(model.calls) == 1


def test_checkpoint_recovery_after_process_interruption(tmp_path, script):
    from agent_platform.config import Settings
    from agent_platform.db import Database

    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'recovery.db'}", artifact_dir=tmp_path / "artifacts"
    )
    runtime = WorkflowRuntime(database=Database(settings), settings=settings, model=FakeModel())
    try:
        runtime.create_run(project_id="project-4", script=script, stop_after_step="split_script")
    except SimulatedInterruption:
        pass
    run_id = runtime.repository.list_runs(project_id="project-4")[0].id
    recovered = WorkflowRuntime(database=Database(settings), settings=settings, model=FakeModel())
    recovered_result = recovered.recover(run_id)
    assert recovered_result.status == RunStatus.WAITING_REVIEW.value
    assert recovered.repository.latest_checkpoint(run_id).sequence_no >= 4


def test_invalid_model_output_fails_with_structured_error(tmp_path, script):
    from agent_platform.config import Settings
    from agent_platform.db import Database

    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'invalid.db'}", artifact_dir=tmp_path / "artifacts"
    )
    runtime = WorkflowRuntime(
        database=Database(settings), settings=settings, model=FakeModel(mode="invalid_output")
    )
    result = runtime.create_run(project_id="project-5", script=script)
    run = runtime.repository.get_run(result.run_id)
    assert result.status == RunStatus.FAILED.value
    assert run.error_code == ErrorCode.SCHEMA_VALIDATION_FAILED.value
