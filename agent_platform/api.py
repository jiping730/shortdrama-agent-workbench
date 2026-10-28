from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

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
    return (
        "<!doctype html>\n"
        "<html><head><meta charset='utf-8'>"
        "<title>Agent Workflow Control Plane</title>\n"
        "<style>\n"
        "body { font-family: system-ui; margin: 0; background: #0d1117; color: #e6edf3; }\n"
        "header { padding: 22px 32px; border-bottom: 1px solid #30363d; }\n"
        "main { padding: 24px 32px; }\n"
        "button { background: #238636; color: white; border: 0; border-radius: 6px; "
        "padding: 8px 12px; cursor: pointer; }\n"
        "table { width: 100%; border-collapse: collapse; margin-top: 18px; }\n"
        "td, th { padding: 10px; border-bottom: 1px solid #30363d; text-align: left; }\n"
        ".muted { color: #8b949e; }\n"
        ".pill { padding: 3px 8px; border-radius: 999px; background: #21262d; }\n"
        "</style></head>\n"
        "<body><header><h1>Agent Workflow Control Plane</h1>\n"
        "<div class='muted'>Runs · steps · attempts · reviews · evidence · recovery</div>"
        "</header>\n"
        "<main><button onclick='loadRuns()'>Refresh runs</button>\n"
        "<div id='app' class='muted'>Loading…</div></main>\n"
        "<script>\n"
        "async function loadRuns() {\n"
        "  const response = await fetch('/api/v1/runs');\n"
        "  const data = await response.json();\n"
        "  let html = '<table><tr><th>Run</th><th>Status</th>' + "
        "'<th>Current step</th><th>Updated</th></tr>';\n"
        "  for (const run of data.items) {\n"
        "    html += `<tr><td><a href='/api/v1/runs/${run.id}' "
        "style='color:#58a6ff'>${run.id}</a></td>` + "
        "`<td><span class='pill'>${run.status}</span></td>` + "
        "`<td>${run.current_step || ''}</td><td>${run.updated_at || ''}</td></tr>`;\n"
        "  }\n"
        "  document.getElementById('app').innerHTML = html + '</table>';\n"
        "}\n"
        "loadRuns();\n"
        "</script></body></html>"
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "agent-workflow-platform"}


@app.get("/api/v1/workflows")
def list_workflows() -> dict[str, Any]:
    definition = runtime.workflow_definition
    return {
        "items": [
            {
                "name": definition.name,
                "version": definition.version,
                "description": definition.description,
                "steps": [step.__dict__ for step in definition.steps],
            }
        ]
    }


@app.get("/api/v1/workflows/{workflow_name}")
def describe_workflow(workflow_name: str) -> dict[str, Any]:
    definition = runtime.workflow_definition
    if workflow_name != definition.name:
        raise HTTPException(404, "workflow not found")
    return {
        "name": definition.name,
        "version": definition.version,
        "description": definition.description,
        "steps": [step.__dict__ for step in definition.steps],
    }


@app.post("/api/v1/runs")
def create_run(request: RunCreateRequest) -> dict[str, Any]:
    if request.workflow != runtime.workflow_definition.name:
        raise HTTPException(400, "workflow is not registered")
    try:
        result = runtime.create_run(
            project_id=request.project_id,
            workspace_id=request.workspace_id,
            project_name=request.project_name,
            script=request.script,
            script_id=request.script_id,
            title=request.title,
            model_mode=request.model_mode,
            idempotency_key=request.idempotency_key,
        )
    except WorkflowStepError as exc:
        raise HTTPException(422, {"code": exc.code.value, "message": str(exc)}) from exc
    return {
        "run_id": result.run_id,
        "status": result.status,
        "paused_for_review": result.paused_for_review,
    }


@app.get("/api/v1/runs")
def list_runs(project_id: str | None = Query(default=None)) -> dict[str, Any]:
    return {
        "items": [_run_summary(run) for run in runtime.repository.list_runs(project_id=project_id)]
    }


@app.get("/api/v1/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    try:
        return run_payload(runtime.repository, run_id)
    except KeyError as exc:
        raise HTTPException(404, "run not found") from exc


def _action(run_id: str, function: Any) -> dict[str, Any]:
    try:
        result = function(run_id)
        return {
            "run_id": result.run_id,
            "status": result.status,
            "paused_for_review": result.paused_for_review,
        }
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
        return {
            "run_id": result.run_id,
            "status": result.status,
            "paused_for_review": result.paused_for_review,
        }
    except KeyError as exc:
        raise HTTPException(404, "run not found") from exc
    except (WorkflowStepError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/api/v1/runs/{run_id}/events")
def run_events(run_id: str) -> dict[str, Any]:
    if runtime.repository.get_run(run_id) is None:
        raise HTTPException(404, "run not found")
    return {
        "items": [
            runtime.repository.serialize_model(event)
            for event in runtime.repository.get_events(run_id)
        ]
    }


@app.get("/api/v1/runs/{run_id}/artifacts")
def run_artifacts(run_id: str) -> dict[str, Any]:
    if runtime.repository.get_run(run_id) is None:
        raise HTTPException(404, "run not found")
    return {
        "items": [
            runtime.repository.serialize_model(item)
            for item in runtime.repository.get_artifacts(run_id)
        ]
    }


@app.get("/api/v1/runs/{run_id}/reviews")
def run_reviews(run_id: str) -> dict[str, Any]:
    if runtime.repository.get_run(run_id) is None:
        raise HTTPException(404, "run not found")
    return {
        "items": [
            runtime.repository.serialize_model(item)
            for item in runtime.repository.get_reviews(run_id)
        ]
    }


@app.get("/api/v1/error-inbox")
def error_inbox() -> dict[str, Any]:
    return {"items": runtime.repository.list_error_inbox()}


@app.post("/api/v1/reviews/{review_id}/approve")
def approve_review(review_id: str, request: ReviewDecisionRequest) -> dict[str, Any]:
    try:
        result = runtime.approve_review(review_id, request.reviewer, request.comment)
        return {
            "run_id": result.run_id,
            "status": result.status,
            "paused_for_review": result.paused_for_review,
        }
    except KeyError as exc:
        raise HTTPException(404, "review not found") from exc
    except (WorkflowStepError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/v1/reviews/{review_id}/reject")
def reject_review(review_id: str, request: ReviewDecisionRequest) -> dict[str, Any]:
    try:
        result = runtime.reject_review(review_id, request.reviewer, request.comment)
        return {
            "run_id": result.run_id,
            "status": result.status,
            "paused_for_review": result.paused_for_review,
        }
    except KeyError as exc:
        raise HTTPException(404, "review not found") from exc
    except (WorkflowStepError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
