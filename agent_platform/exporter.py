from __future__ import annotations

import csv
import html
import io
import json
from pathlib import Path
from typing import Any

from .repository import Repository


def run_payload(repository: Repository, run_id: str) -> dict[str, Any]:
    run = repository.get_run(run_id)
    if run is None:
        raise KeyError(run_id)
    return {
        "run": repository.serialize_model(run),
        "steps": [repository.serialize_model(item) for item in repository.get_steps(run_id)],
        "attempts": [repository.serialize_model(item) for item in repository.get_attempts(run_id)],
        "checkpoints": [
            repository.serialize_model(item) for item in _checkpoints(repository, run_id)
        ],
        "artifacts": [
            repository.serialize_model(item) for item in repository.get_artifacts(run_id)
        ],
        "evidence": [repository.serialize_model(item) for item in repository.get_evidence(run_id)],
        "reviews": [repository.serialize_model(item) for item in repository.get_reviews(run_id)],
        "external_calls": [
            repository.serialize_model(item) for item in repository.get_external_calls(run_id)
        ],
        "events": [repository.serialize_model(item) for item in repository.get_events(run_id)],
    }


def _checkpoints(repository: Repository, run_id: str) -> list[Any]:
    # The repository intentionally exposes only latest checkpoint to the runtime;
    # exports use a small read-only session for the full audit history.
    from sqlalchemy import select

    from .db import CheckpointModel

    with repository.db.session() as session:
        return list(
            session.execute(
                select(CheckpointModel)
                .where(CheckpointModel.run_id == run_id)
                .order_by(CheckpointModel.sequence_no)
            ).scalars()
        )


def write_json(repository: Repository, run_id: str, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(run_payload(repository, run_id), ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return output


def write_csv(repository: Repository, run_id: str, output: Path) -> Path:
    payload = run_payload(repository, run_id)
    output.parent.mkdir(parents=True, exist_ok=True)
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(["kind", "id", "status", "step", "error_code", "created_at"])
    for step in payload["steps"]:
        writer.writerow(
            [
                "step",
                step.get("id"),
                step.get("status"),
                step.get("step_name"),
                step.get("error_code"),
                step.get("started_at"),
            ]
        )
    for review in payload["reviews"]:
        writer.writerow(
            [
                "review",
                review.get("id"),
                review.get("status"),
                review.get("scene_id"),
                "",
                review.get("created_at"),
            ]
        )
    for event in payload["events"]:
        writer.writerow(
            [
                "event",
                event.get("id"),
                event.get("event_type"),
                event.get("step_name"),
                "",
                event.get("created_at"),
            ]
        )
    output.write_text(stream.getvalue(), encoding="utf-8")
    return output


def write_html(repository: Repository, run_id: str, output: Path) -> Path:
    payload = run_payload(repository, run_id)
    output.parent.mkdir(parents=True, exist_ok=True)
    run = payload["run"]
    rows = "".join(
        "<tr>"
        f"<td>{html.escape(str(step.get('step_name')))}</td>"
        f"<td>{html.escape(str(step.get('status')))}</td>"
        f"<td>{html.escape(str(step.get('error_code') or ''))}</td>"
        "</tr>"
        for step in payload["steps"]
    )
    document = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Run {html.escape(run_id)}</title>
<style>
body {{ font: 14px system-ui; margin: 2rem; background: #0d1117; color: #e6edf3; }}
table {{ border-collapse: collapse; width: 100%; }}
td, th {{ border: 1px solid #30363d; padding: 0.5rem; text-align: left; }}
.ok {{ color: #3fb950; }}
</style>
</head>
<body>
<h1>Run {html.escape(run_id)}</h1>
<p>Status: <strong class="ok">{html.escape(str(run.get("status")))}</strong></p>
<p>Workflow version: {html.escape(str(run.get("workflow_version_id")))} ·
Input hash: {html.escape(str(run.get("input_hash")))}</p>
<h2>Step timeline</h2>
<table>
<thead><tr><th>Step</th><th>Status</th><th>Error</th></tr></thead>
<tbody>{rows}</tbody>
</table>
<h2>Audit counts</h2>
<p>Attempts {len(payload["attempts"])} · Artifacts {len(payload["artifacts"])} ·
Evidence {len(payload["evidence"])} · Reviews {len(payload["reviews"])} ·
Events {len(payload["events"])}</p>
</body>
</html>"""
    output.write_text(document, encoding="utf-8")
    return output
