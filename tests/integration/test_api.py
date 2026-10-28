from fastapi.testclient import TestClient


def test_versioned_api_exposes_runs_and_reviews(monkeypatch, tmp_path):
    import agent_platform.api as api
    from agent_platform.config import Settings
    from agent_platform.db import Database
    from agent_platform.providers import FakeModel
    from agent_platform.runtime import WorkflowRuntime

    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'api.db'}", artifact_dir=tmp_path / "artifacts"
    )
    api.runtime = WorkflowRuntime(database=Database(settings), settings=settings, model=FakeModel())
    client = TestClient(api.app)
    created = client.post(
        "/api/v1/runs",
        json={
            "project_id": "api-project",
            "script": "SCENE 1: room\n角色：A；场景：room；道具：key.",
        },
    )
    assert created.status_code == 200
    run_id = created.json()["run_id"]
    detail = client.get(f"/api/v1/runs/{run_id}")
    assert detail.status_code == 200
    assert detail.json()["run"]["status"] == "waiting_review"
    assert len(client.get(f"/api/v1/runs/{run_id}/reviews").json()["items"]) == 1
    assert client.get(f"/api/v1/runs/{run_id}/events").status_code == 200
