from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from ..domain import ErrorCode, WorkflowStepError, content_hash, stable_id
from ..schemas import Scene, ShotList, ShotListItem
from .base import StepSpec, WorkflowDefinition
from .script_to_storyboard import ScriptToStoryboardAdapter


SHOTLIST_STEPS = (
    "prepare_input", "split_script", "generate_shotlist", "validate_shotlist", "export_artifacts",
)


class ScriptToShotlistAdapter:
    """A second, deterministic workflow proving the adapter extension boundary."""

    definition = WorkflowDefinition(
        name="script-to-shotlist", version="1.0.0",
        description="Evidence-backed production shot list derived from script scenes",
        steps=tuple(StepSpec(name, name.replace("_", " ").title()) for name in SHOTLIST_STEPS),
    )

    def register(self) -> WorkflowDefinition:
        return self.definition

    def start(self, context: dict[str, Any]) -> dict[str, Any]:
        return dict(context)

    def resume(self, context: dict[str, Any]) -> dict[str, Any]:
        return dict(context)

    def recover(self, context: dict[str, Any]) -> dict[str, Any]:
        return dict(context)

    def validate(self, step_name: str, value: Any) -> Any:
        try:
            if step_name == "split_script":
                return [Scene.model_validate(item) for item in value]
            if step_name == "generate_shotlist":
                return [ShotListItem.model_validate(item) for item in value]
            if step_name == "validate_shotlist":
                return ShotList.model_validate(value)
            return value
        except (ValidationError, TypeError, ValueError) as exc:
            raise WorkflowStepError(ErrorCode.SCHEMA_VALIDATION_FAILED, str(exc)) from exc

    def execute_step(self, step_name: str, context: dict[str, Any]) -> Any:
        if step_name == "prepare_input":
            text = str(context.get("script_text", "")).strip()
            if not text:
                raise WorkflowStepError(ErrorCode.INVALID_INPUT, "script text cannot be empty")
            return {"script_id": context["script_id"], "input_hash": content_hash(text), "length": len(text)}
        if step_name == "split_script":
            # Reuse the established deterministic scene/evidence algorithm rather
            # than creating a second, divergent script parser.
            return ScriptToStoryboardAdapter._split_script(
                context["script_id"], context["script_text"], context.get("run_id"),
            )
        if step_name == "generate_shotlist":
            result: list[dict[str, Any]] = []
            for scene in [Scene.model_validate(item) for item in context.get("scenes", [])]:
                result.append(ShotListItem(
                    shot_id=stable_id("shotlist-shot", context["run_id"], scene.scene_id),
                    scene_id=scene.scene_id, order=scene.scene_no, duration_hint="3-5s",
                    location=scene.title, characters=[], action=scene.source_text,
                    evidence_ids=scene.evidence_ids,
                ).model_dump(mode="json"))
            return result
        if step_name == "validate_shotlist":
            scenes = [Scene.model_validate(item) for item in context.get("scenes", [])]
            items = [ShotListItem.model_validate(item) for item in context.get("shotlist_items", [])]
            scene_ids = {scene.scene_id for scene in scenes}
            if {item.scene_id for item in items} != scene_ids:
                raise WorkflowStepError(ErrorCode.SCHEMA_VALIDATION_FAILED, "shot list must cover every scene")
            evidence_ids = {item["evidence_id"] for item in context.get("evidence", [])}
            if any(eid not in evidence_ids for item in items for eid in item.evidence_ids):
                raise WorkflowStepError(ErrorCode.EVIDENCE_MISSING, "shot list references missing evidence")
            return ShotList(
                shotlist_id=stable_id("shotlist", context["run_id"]), script_id=context["script_id"],
                revision=1, items=items,
            ).model_dump(mode="json")
        if step_name == "export_artifacts":
            shotlist = context.get("shotlist")
            if not shotlist:
                raise WorkflowStepError(ErrorCode.INVALID_INPUT, "no validated shot list to export")
            return {"exported": True, "formats": ["json", "csv"], "shotlist_id": shotlist["shotlist_id"]}
        raise WorkflowStepError(ErrorCode.INVALID_INPUT, f"unknown step: {step_name}")

    def apply_step_result(
        self, step_name: str, result: Any, context: dict[str, Any], *, run_id: str,
    ) -> dict[str, Any]:
        updated = dict(context)
        if step_name == "generate_shotlist":
            updated["shotlist_items"] = result
        elif step_name == "validate_shotlist":
            updated["shotlist"] = result
        return updated
