from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .exporter import run_payload, write_csv, write_html, write_json
from .runtime import WorkflowRuntime


def _emit(value: Any, as_json: bool) -> None:
    if as_json:
        print(json.dumps(value, ensure_ascii=False, indent=2, default=str))
    elif isinstance(value, dict):
        for key, item in value.items():
            print(f"{key}={item}")
    else:
        print(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-platform", description="Agent Workflow Platform control-plane CLI")
    parser.add_argument("--json", action="store_true", help="stable JSON output")
    sub = parser.add_subparsers(dest="group", required=True)

    run = sub.add_parser("run")
    run_sub = run.add_subparsers(dest="action", required=True)
    create = run_sub.add_parser("create")
    create.add_argument("--project-id", required=True)
    create.add_argument("--workspace-id", default="default-workspace")
    create.add_argument("--script")
    create.add_argument("--script-file", type=Path)
    create.add_argument("--script-id", default="script-1")
    create.add_argument("--title", default="Untitled")
    create.add_argument("--model-mode", choices=["success", "invalid_output", "timeout", "model_error", "unknown"], default="success")
    for name in ["show", "pause", "resume", "cancel"]:
        cmd = run_sub.add_parser(name)
        cmd.add_argument("--run-id", required=True)
    retry = run_sub.add_parser("retry")
    retry.add_argument("--run-id", required=True)
    retry.add_argument("--step-name")
    retry.add_argument("--scene-id", action="append", default=[])
    list_cmd = run_sub.add_parser("list")
    list_cmd.add_argument("--project-id")

    review = sub.add_parser("review")
    review_sub = review.add_subparsers(dest="action", required=True)
    review_list = review_sub.add_parser("list")
    review_list.add_argument("--run-id", required=True)
    for name in ["approve", "reject"]:
        cmd = review_sub.add_parser(name)
        cmd.add_argument("--review-id", required=True)
        cmd.add_argument("--reviewer", required=True)
        cmd.add_argument("--comment", default="")

    workflow = sub.add_parser("workflow")
    workflow_sub = workflow.add_subparsers(dest="action", required=True)
    workflow_sub.add_parser("list")
    describe = workflow_sub.add_parser("describe")
    describe.add_argument("--name", default="script-to-storyboard")

    export = sub.add_parser("export")
    export_sub = export.add_subparsers(dest="action", required=True)
    for name in ["json", "csv", "html"]:
        cmd = export_sub.add_parser(name)
        cmd.add_argument("--run-id", required=True)
        cmd.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    runtime = WorkflowRuntime()
    as_json = args.json
    try:
        if args.group == "workflow":
            definition = runtime.workflow_definition
            if args.action == "list":
                _emit({"items": [{"name": definition.name, "version": definition.version}]}, as_json)
            else:
                _emit({"name": definition.name, "version": definition.version, "description": definition.description, "steps": [step.__dict__ for step in definition.steps]}, as_json)
            return 0
        if args.group == "run":
            if args.action == "create":
                script = args.script
                if args.script_file:
                    script = args.script_file.read_text(encoding="utf-8")
                if not script:
                    raise ValueError("one of --script or --script-file is required")
                result = runtime.create_run(project_id=args.project_id, workspace_id=args.workspace_id, script=script, script_id=args.script_id, title=args.title, model_mode=args.model_mode)
                _emit({"run_id": result.run_id, "status": result.status, "paused_for_review": result.paused_for_review}, as_json)
            elif args.action == "show":
                _emit(run_payload(runtime.repository, args.run_id), as_json)
            elif args.action == "list":
                _emit({"items": [runtime.repository.serialize_model(run) for run in runtime.repository.list_runs(project_id=args.project_id)]}, as_json)
            elif args.action == "pause":
                result = runtime.pause(args.run_id); _emit(result.__dict__, as_json)
            elif args.action == "resume":
                result = runtime.resume(args.run_id); _emit(result.__dict__, as_json)
            elif args.action == "cancel":
                result = runtime.cancel(args.run_id); _emit(result.__dict__, as_json)
            elif args.action == "retry":
                result = runtime.retry(args.run_id, step_name=args.step_name, scene_ids=args.scene_id); _emit(result.__dict__, as_json)
            return 0
        if args.group == "review":
            if args.action == "list":
                _emit({"items": [runtime.repository.serialize_model(item) for item in runtime.repository.get_reviews(args.run_id)]}, as_json)
            elif args.action == "approve":
                _emit(runtime.approve_review(args.review_id, args.reviewer, args.comment).__dict__, as_json)
            else:
                _emit(runtime.reject_review(args.review_id, args.reviewer, args.comment).__dict__, as_json)
            return 0
        if args.group == "export":
            if args.action == "json":
                output = write_json(runtime.repository, args.run_id, args.output)
            elif args.action == "csv":
                output = write_csv(runtime.repository, args.run_id, args.output)
            else:
                output = write_html(runtime.repository, args.run_id, args.output)
            _emit({"status": "succeeded", "output": str(output)}, as_json)
            return 0
    except Exception as exc:
        _emit({"status": "failed", "error": {"type": type(exc).__name__, "message": str(exc)}}, True)
        return 1
    return 1


if __name__ == "__main__":
    sys.exit(main())
