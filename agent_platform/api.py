from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

from .config import Settings
from .domain import WorkflowStepError
from .exporter import run_payload
from .runtime import WorkflowRuntime
from .schemas import RetryRequest, ReviewDecisionRequest, RunCreateRequest


logger = logging.getLogger(__name__)
runtime = WorkflowRuntime()
app = FastAPI(title="Agent Workflow Platform", version="0.1.0")


def _run_summary(run: Any) -> dict[str, Any]:
    return runtime.repository.serialize_model(run)


@app.get("/", response_class=HTMLResponse)
def dashboard() -> str:
    return """<!doctype html><html><head><meta charset='utf-8'><title>Agent Workflow Control Plane</title>
    <style>body{font-family:system-ui;margin:0;background:#0d1117;color:#e6edf3}header{padding:22px 32px;border-bottom:1px solid #30363d}main{padding:24px 32px}button{background:#238636;color:white;border:0;border-radius:6px;padding:8px 12px;cursor:pointer}table{width:100%;border-collapse:collapse;margin-top:18px}td,th{padding:10px;border-bottom:1px solid #30363d;text-align:left}.muted{color:#8b949e}.pill{padding:3px 8px;border-radius:999px;background:#21262d}</style></head>
    <body><header><h1>Agent Workflow Control Plane</h1><div class='muted'>Runs · steps · attempts · reviews · evidence · recovery</div></header>
    <main><button onclick='loadRuns()'>Refresh runs</button><div id='app' class='muted'>Loading…</div></main>
    <script>async function loadRuns(){const r=await fetch('/api/v1/runs');const data=await r.json();let h='<table><tr><th>Run</th><th>Status</th><th>Current step</th><th>Updated</th></tr>';for(const x of data.items){h+=`<tr><td><a href='/api/v1/runs/${x.id}' style='color:#58a6ff'>${x.id}</a></td><td><span class='pill'>${x.status}</span></td><td>${x.current_step||''}</td><td>${x.updated_at||''}</td></tr>`}document.getElementById('app').innerHTML=h+'</table>'}loadRuns()</script></body></html>"""


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "agent-workflow-platform"}


@app.get("/api/v1/workflows")
def list_workflows() -> dict[str, Any]:
    definition = runtime.workflow_definition
    return {"items": [{"name": definition.name, "version": definition.version, "description": definition.description, "steps": [step.__dict__ for step in definition.steps]}]}


@app.get("/api/v1/workflows/{workflow_name}")
def describe_workflow(workflow_name: str) -> dict[str, Any]:
    definition = runtime.workflow_definition
    if workflow_name != definition.name:
        raise HTTPException(404, "workflow not found")
    return {"name": definition.name, "version": definition.version, "description": definition.description, "steps": [step.__dict__ for step in definition.steps]}


@app.post("/api/v1/runs")
def create_run(request: RunCreateRequest) -> dict[str, Any]:
    if request.workflow != runtime.workflow_definition.name:
        raise HTTPException(400, "workflow is not registered")
    try:
        result = runtime.create_run(
            project_id=request.project_id, workspace_id=request.workspace_id, project_name=request.project_name,
            script=request.script, script_id=request.script_id, title=request.title,
            model_mode=request.model_mode, idempotency_key=request.idempotency_key,
        )
    except WorkflowStepError as exc:
        raise HTTPException(422, {"code": exc.code.value, "message": str(exc)}) from exc
    return {"run_id": result.run_id, "status": result.status, "paused_for_review": result.paused_for_review}


@app.get("/api/v1/runs")
def list_runs(project_id: str | None = Query(default=None)) -> dict[str, Any]:
    return {"items": [_run_summary(run) for run in runtime.repository.list_runs(project_id=project_id)]}


@app.get("/api/v1/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    try:
        return run_payload(runtime.repository, run_id)
    except KeyError as exc:
        raise HTTPException(404, "run not found") from exc


def _action(run_id: str, function: Any) -> dict[str, Any]:
    try:
        result = function(run_id)
        return {"run_id": result.run_id, "status": result.status, "paused_for_review": result.paused_for_review}
    except KeyError as exc:
        raise HTTPException(404, "run not found") from exc
    except (WorkflowStepError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/v1/runs/{run_id}/pause")
def pause_run(run_id: str) -> dict[str, Any]:
    return _action(run_id, runtime.pause)


@app.post("/api/v1/runs/{run_id}/resume")
def resume_run(run_id: str) -> dict[str, Any]:
    return _action(run_id, runtime.resume)


@app.post("/api/v1/runs/{run_id}/cancel")
def cancel_run(run_id: str) -> dict[str, Any]:
    return _action(run_id, runtime.cancel)


@app.post("/api/v1/runs/{run_id}/retry")
def retry_run(run_id: str, request: RetryRequest) -> dict[str, Any]:
    try:
        result = runtime.retry(run_id, step_name=request.step_name, scene_ids=request.scene_ids)
        return {"run_id": result.run_id, "status": result.status, "paused_for_review": result.paused_for_review}
    except KeyError as exc:
        raise HTTPException(404, "run not found") from exc
    except (WorkflowStepError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/api/v1/runs/{run_id}/events")
def run_events(run_id: str) -> dict[str, Any]:
    if runtime.repository.get_run(run_id) is None:
        raise HTTPException(404, "run not found")
    return {"items": [runtime.repository.serialize_model(event) for event in runtime.repository.get_events(run_id)]}


@app.get("/api/v1/runs/{run_id}/artifacts")
def run_artifacts(run_id: str) -> dict[str, Any]:
    if runtime.repository.get_run(run_id) is None:
        raise HTTPException(404, "run not found")
    return {"items": [runtime.repository.serialize_model(item) for item in runtime.repository.get_artifacts(run_id)]}


@app.get("/api/v1/runs/{run_id}/reviews")
def run_reviews(run_id: str) -> dict[str, Any]:
    if runtime.repository.get_run(run_id) is None:
        raise HTTPException(404, "run not found")
    return {"items": [runtime.repository.serialize_model(item) for item in runtime.repository.get_reviews(run_id)]}


@app.get("/api/v1/error-inbox")
def error_inbox() -> dict[str, Any]:
    items = [run for run in runtime.repository.list_runs() if run.status in {"failed", "needs_recovery"}]
    return {"items": [_run_summary(run) for run in items]}


@app.post("/api/v1/reviews/{review_id}/approve")
def approve_review(review_id: str, request: ReviewDecisionRequest) -> dict[str, Any]:
    try:
        result = runtime.approve_review(review_id, request.reviewer, request.comment)
        return {"run_id": result.run_id, "status": result.status, "paused_for_review": result.paused_for_review}
    except KeyError as exc:
        raise HTTPException(404, "review not found") from exc
    except (WorkflowStepError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/v1/reviews/{review_id}/reject")
def reject_review(review_id: str, request: ReviewDecisionRequest) -> dict[str, Any]:
    try:
        result = runtime.reject_review(review_id, request.reviewer, request.comment)
        return {"run_id": result.run_id, "status": result.status, "paused_for_review": result.paused_for_review}
    except KeyError as exc:
        raise HTTPException(404, "review not found") from exc
    except (WorkflowStepError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
