from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from agent_platform.cli import main as cli_main
from agent_platform.config import Settings
from agent_platform.db import Database
from agent_platform.providers import FakeModel
from agent_platform.runtime import WorkflowRuntime


SCRIPT = """SCENE 1: Room
角色：A；场景：Room；道具：key。
A enters and waits.

SCENE 2: Hall
角色：B；场景：Hall；道具：lamp。
B opens the door.
"""


def _runtime(tmp_path: Path, name: str) -> WorkflowRuntime:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / f'{name}.db'}",
        artifact_dir=tmp_path / f"{name}-artifacts",
    )
    return WorkflowRuntime(database=Database(settings), settings=settings, model=FakeModel())


def test_rest_api_and_management_dashboard_cover_run_review_recovery_surface(tmp_path, monkeypatch) -> None:
    import agent_platform.api as api

    monkeypatch.setattr(api, "runtime", _runtime(tmp_path, "api"))
    client = TestClient(api.app)

    assert client.get("/health").json()["status"] == "ok"
    workflows = client.get("/api/v1/workflows")
    assert workflows.status_code == 200
    assert workflows.json()["items"][0]["name"] == "script-to-storyboard"
    assert client.get("/api/v1/workflows/script-to-storyboard").status_code == 200
    required_paths = {
        "/api/v1/runs", "/api/v1/runs/{run_id}", "/api/v1/runs/{run_id}/pause",
        "/api/v1/runs/{run_id}/resume", "/api/v1/runs/{run_id}/cancel",
        "/api/v1/runs/{run_id}/retry", "/api/v1/runs/{run_id}/events",
        "/api/v1/runs/{run_id}/artifacts", "/api/v1/runs/{run_id}/reviews",
        "/api/v1/reviews/{review_id}/approve", "/api/v1/reviews/{review_id}/reject",
    }
    assert required_paths <= set(client.get("/openapi.json").json()["paths"])

    created = client.post("/api/v1/runs", json={"project_id": "api-gate", "script": SCRIPT})
    assert created.status_code == 200
    run_id = created.json()["run_id"]
    assert created.json()["status"] == "waiting_review"
    assert client.get("/api/v1/runs", params={"project_id": "api-gate"}).json()["items"]
    detail = client.get(f"/api/v1/runs/{run_id}")
    assert detail.status_code == 200
    assert detail.json()["run"]["id"] == run_id
    assert client.get(f"/api/v1/runs/{run_id}/events").status_code == 200
    assert client.get(f"/api/v1/runs/{run_id}/artifacts").status_code == 200
    reviews = client.get(f"/api/v1/runs/{run_id}/reviews").json()["items"]
    assert len(reviews) == 2
    assert any(item["kind"] == "review" for item in client.get("/api/v1/error-inbox").json()["items"])

    assert client.post(f"/api/v1/reviews/{reviews[0]['id']}/reject", json={"reviewer": "api", "comment": "revise"}).status_code == 200
    assert client.post(f"/api/v1/reviews/{reviews[1]['id']}/approve", json={"reviewer": "api"}).status_code == 200
    retry = client.post(f"/api/v1/runs/{run_id}/retry", json={"scene_ids": [reviews[0]["scene_id"]]})
    assert retry.status_code == 200
    revised_reviews = client.get(f"/api/v1/runs/{run_id}/reviews").json()["items"]
    pending = [item for item in revised_reviews if item["status"] == "pending"]
    assert len(pending) == 1
    assert client.post(f"/api/v1/reviews/{pending[0]['id']}/approve", json={"reviewer": "api"}).status_code == 200
    assert client.get(f"/api/v1/runs/{run_id}").json()["run"]["status"] == "completed"

    dashboard = client.get("/")
    assert dashboard.status_code == 200
    assert "Agent Workflow Control Plane" in dashboard.text
    assert "Runs" in dashboard.text and "chat" not in dashboard.text.lower()


def test_cli_commands_and_exports_are_machine_consumable(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'cli.db'}")
    monkeypatch.setenv("ARTIFACT_DIR", str(tmp_path / "cli-artifacts"))

    assert cli_main(["--json", "workflow", "list"]) == 0
    workflow_list = json.loads(capsys.readouterr().out)
    assert workflow_list["items"][0]["name"] == "script-to-storyboard"
    assert cli_main(["--json", "workflow", "describe", "--name", "script-to-storyboard"]) == 0
    assert json.loads(capsys.readouterr().out)["steps"]

    assert cli_main(["--json", "run", "create", "--project-id", "cli-gate", "--script", SCRIPT]) == 0
    run = json.loads(capsys.readouterr().out)
    run_id = run["run_id"]
    assert run["status"] == "waiting_review"
    assert cli_main(["--json", "run", "list", "--project-id", "cli-gate"]) == 0
    assert json.loads(capsys.readouterr().out)["items"]
    assert cli_main(["--json", "run", "show", "--run-id", run_id]) == 0
    assert json.loads(capsys.readouterr().out)["run"]["id"] == run_id
    assert cli_main(["--json", "review", "list", "--run-id", run_id]) == 0
    reviews = json.loads(capsys.readouterr().out)["items"]
    assert len(reviews) == 2

    for review in reviews:
        assert cli_main([
            "--json", "review", "approve", "--review-id", review["id"], "--reviewer", "cli",
        ]) == 0
        result = json.loads(capsys.readouterr().out)
    assert result["status"] == "completed"

    assert cli_main(["--json", "run", "create", "--project-id", "cli-operator", "--script", SCRIPT]) == 0
    operator_run = json.loads(capsys.readouterr().out)["run_id"]
    assert cli_main(["--json", "run", "pause", "--run-id", operator_run]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "paused"
    assert cli_main(["--json", "run", "resume", "--run-id", operator_run]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "waiting_review"
    assert cli_main(["--json", "run", "cancel", "--run-id", operator_run]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "cancelled"

    assert cli_main([
        "--json", "run", "create", "--project-id", "cli-retry", "--script", SCRIPT,
        "--model-mode", "invalid_output",
    ]) == 0
    retry_run = json.loads(capsys.readouterr().out)["run_id"]
    assert cli_main(["--json", "run", "retry", "--run-id", retry_run, "--step-name", "extract_facts"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "waiting_review"

    output_dir = tmp_path / "exports"
    for format_name, suffix in [("json", ".json"), ("csv", ".csv"), ("html", ".html")]:
        output = output_dir / f"run{suffix}"
        assert cli_main([
            "--json", "export", format_name, "--run-id", run_id, "--output", str(output),
        ]) == 0
        response = json.loads(capsys.readouterr().out)
        assert response["status"] == "succeeded"
        assert output.exists() and output.stat().st_size > 0
    assert json.loads((output_dir / "run.json").read_text(encoding="utf-8"))["run"]["status"] == "completed"
    assert "Step timeline" in (output_dir / "run.html").read_text(encoding="utf-8")
