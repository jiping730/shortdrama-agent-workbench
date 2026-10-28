from pathlib import Path

from agent_platform.exporter import write_csv, write_html, write_json


def test_demo_flow_exports_all_formats(runtime, script, tmp_path: Path):
    result = runtime.create_run(project_id="e2e-project", script=script)
    for review in runtime.repository.get_reviews(result.run_id):
        runtime.approve_review(review.id, "demo-reviewer")
    assert runtime.repository.get_run(result.run_id).status == "completed"
    assert write_json(runtime.repository, result.run_id, tmp_path / "run.json").exists()
    assert write_csv(runtime.repository, result.run_id, tmp_path / "run.csv").exists()
    assert write_html(runtime.repository, result.run_id, tmp_path / "run.html").exists()
