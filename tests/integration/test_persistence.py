from agent_platform.db import Database


def test_all_required_domain_tables_are_created(runtime):
    counts = runtime.database.table_counts()
    for name in [
        "workspaces", "projects", "workflow_definitions", "workflow_versions", "runs", "tasks",
        "step_executions", "attempts", "checkpoints", "artifacts", "evidence", "review_tasks",
        "tool_calls", "external_calls", "run_events",
    ]:
        assert name in counts


def test_artifact_lineage_is_persisted(runtime, script):
    result = runtime.create_run(project_id="project-lineage", script=script)
    artifacts = runtime.repository.get_artifacts(result.run_id)
    types = {artifact.artifact_type for artifact in artifacts}
    assert {"script_input", "split_script", "generate_storyboard", "validate_storyboard"}.issubset(types)
    assert any(artifact.parent_artifact_ids for artifact in artifacts if artifact.artifact_type == "validate_storyboard")
