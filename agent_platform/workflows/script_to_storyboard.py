from __future__ import annotations

import re
from typing import Any

from pydantic import ValidationError

from ..domain import ErrorCode, WorkflowStepError, content_hash, stable_id
from ..providers import ModelProvider
from ..schemas import Fact, Scene, Shot, Storyboard, stable_scene_id
from .base import StepSpec, WorkflowDefinition

SCRIPT_STEPS = (
    "prepare_input",
    "split_script",
    "build_source_index",
    "extract_facts",
    "validate_facts",
    "generate_storyboard",
    "validate_storyboard",
    "wait_for_human_review",
    "revise_rejected_scenes",
    "adopt_result",
    "export_artifacts",
)


class ScriptToStoryboardAdapter:
    """Adapter around the existing business idea, with durable runtime context outside it.

    The adapter owns deterministic script semantics and provider calls. It does not
    own transactions, checkpoints, review decisions, or process lifecycle.
    """

    definition = WorkflowDefinition(
        name="script-to-storyboard",
        version="1.0.0",
        description="Evidence-backed script decomposition and reviewable storyboard",
        steps=tuple(
            StepSpec(name, name.replace("_", " ").title(), name == "wait_for_human_review")
            for name in SCRIPT_STEPS
        ),
    )

    def __init__(self, model: ModelProvider) -> None:
        self.model = model

    def register(self) -> WorkflowDefinition:
        return self.definition

    def start(self, context: dict[str, Any]) -> dict[str, Any]:
        """Initialize business context; durable run state stays in WorkflowRuntime."""
        return dict(context)

    def resume(self, context: dict[str, Any]) -> dict[str, Any]:
        """Resume business context after the runtime has loaded a persisted run."""
        return dict(context)

    def recover(self, context: dict[str, Any]) -> dict[str, Any]:
        """Normalize a checkpoint context without owning checkpoint persistence."""
        return dict(context)

    def validate(self, step_name: str, value: Any) -> Any:
        try:
            if step_name == "split_script":
                return [Scene.model_validate(item) for item in value]
            if step_name == "extract_facts":
                return [Fact.model_validate(item) for item in value]
            if step_name == "validate_facts":
                if not isinstance(value, dict) or value.get("valid") is not True:
                    raise ValueError("validate_facts must return a validation report")
                return value
            if step_name in {"generate_storyboard", "revise_rejected_scenes"}:
                return [Shot.model_validate(item) for item in value]
            if step_name == "validate_storyboard":
                return Storyboard.model_validate(value)
            return value
        except ValidationError as exc:
            raise WorkflowStepError(ErrorCode.SCHEMA_VALIDATION_FAILED, str(exc)) from exc

    def execute_step(self, step_name: str, context: dict[str, Any]) -> Any:
        if step_name == "prepare_input":
            text = str(context.get("script_text", "")).strip()
            if not text:
                raise WorkflowStepError(ErrorCode.INVALID_INPUT, "script text cannot be empty")
            return {
                "script_id": context["script_id"],
                "title": context["title"],
                "input_hash": content_hash(text),
                "length": len(text),
            }
        if step_name == "split_script":
            return self._split_script(
                context["script_id"], context["script_text"], context.get("run_id")
            )
        if step_name == "build_source_index":
            scenes = [Scene.model_validate(item) for item in context["scenes"]]
            return {
                "script_id": context["script_id"],
                "ranges": [
                    {"scene_id": s.scene_id, "start": s.source_start, "end": s.source_end}
                    for s in scenes
                ],
            }
        if step_name == "extract_facts":
            scenes = [Scene.model_validate(item) for item in context["scenes"]]
            return [
                fact.model_dump(mode="json")
                for fact in self.model.generate_facts(
                    script_text=context["script_text"], scenes=scenes
                )
            ]
        if step_name == "validate_facts":
            facts = [Fact.model_validate(item) for item in context.get("facts", [])]
            evidence_ids = {item["evidence_id"] for item in context.get("evidence", [])}
            if any(
                evidence_id not in evidence_ids
                for fact in facts
                for evidence_id in fact.evidence_ids
            ):
                raise WorkflowStepError(
                    ErrorCode.EVIDENCE_MISSING, "fact references missing evidence"
                )
            return {"valid": True, "fact_count": len(facts), "evidence_coverage": len(facts) > 0}
        if step_name == "generate_storyboard":
            scenes = [Scene.model_validate(item) for item in context["scenes"]]
            facts = [Fact.model_validate(item) for item in context.get("facts", [])]
            return [
                shot.model_dump(mode="json")
                for shot in self.model.generate_storyboard(
                    script_text=context["script_text"], scenes=scenes, facts=facts
                )
            ]
        if step_name == "validate_storyboard":
            scenes = [Scene.model_validate(item) for item in context["scenes"]]
            storyboard = Storyboard(
                storyboard_id=stable_id(
                    "storyboard", context["run_id"], context.get("revision", 1)
                ),
                script_id=context["script_id"],
                revision=int(context.get("revision", 1)),
                shots=[Shot.model_validate(item) for item in context.get("shots", [])],
            )
            scene_ids = {scene.scene_id for scene in scenes}
            evidence_ids = {item["evidence_id"] for item in context.get("evidence", [])}
            if {shot.scene_id for shot in storyboard.shots} != scene_ids:
                raise WorkflowStepError(
                    ErrorCode.SCHEMA_VALIDATION_FAILED, "storyboard must cover every scene"
                )
            if any(
                eid not in evidence_ids for shot in storyboard.shots for eid in shot.evidence_ids
            ):
                raise WorkflowStepError(
                    ErrorCode.EVIDENCE_MISSING, "shot references missing evidence"
                )
            return storyboard.model_dump(mode="json")
        if step_name == "wait_for_human_review":
            return {
                "review_required": True,
                "scene_ids": [scene["scene_id"] for scene in context["scenes"]],
            }
        if step_name == "revise_rejected_scenes":
            rejected = list(context.get("rejected_scene_ids", []))
            if not rejected:
                return []
            scenes = [Scene.model_validate(item) for item in context["scenes"]]
            facts = [Fact.model_validate(item) for item in context.get("facts", [])]
            return [
                shot.model_dump(mode="json")
                for shot in self.model.revise_storyboard(
                    script_text=context["script_text"],
                    scenes=scenes,
                    facts=facts,
                    rejected_scene_ids=rejected,
                )
            ]
        if step_name == "adopt_result":
            storyboard = context.get("storyboard")
            if not storyboard:
                raise WorkflowStepError(ErrorCode.INVALID_INPUT, "no validated storyboard to adopt")
            return {
                "adopted": True,
                "storyboard_id": storyboard["storyboard_id"],
                "shot_count": len(storyboard["shots"]),
            }
        if step_name == "export_artifacts":
            storyboard = context.get("storyboard")
            return {
                "exported": True,
                "formats": ["json", "csv", "html"],
                "storyboard_id": storyboard["storyboard_id"],
            }
        raise WorkflowStepError(ErrorCode.INVALID_INPUT, f"unknown step: {step_name}")

    @staticmethod
    def _split_script(script_id: str, text: str, run_id: str | None = None) -> list[dict[str, Any]]:
        # Deterministic headings are preferred; fallback is one scene, never an LLM guess.
        matches = list(
            re.finditer(
                r"(?m)^(?:\s*(?:场景|SCENE)\s*[-#：:]?\s*(\d+)?[^\n]*|\s*(?:INT\.|EXT\.)[^\n]*)$",
                text,
                re.IGNORECASE,
            )
        )
        ranges: list[tuple[int, int]] = []
        if matches:
            for index, match in enumerate(matches):
                start = match.start()
                end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
                ranges.append((start, end))
        else:
            ranges.append((0, len(text)))
        scenes: list[dict[str, Any]] = []
        for index, (start, end) in enumerate(ranges, 1):
            source_text = text[start:end].strip()
            leading = len(text[start:end]) - len(text[start:end].lstrip())
            actual_start = start + leading
            actual_end = actual_start + len(source_text)
            scene_id = stable_scene_id(script_id, index, source_text)
            evidence_id = stable_id(
                "evidence",
                run_id or script_id,
                script_id,
                scene_id,
                actual_start,
                actual_end,
                content_hash(source_text),
            )
            title = (
                source_text.splitlines()[0][:120] if source_text.splitlines() else f"Scene {index}"
            )
            scenes.append(
                Scene(
                    scene_id=scene_id,
                    scene_no=index,
                    title=title,
                    source_start=actual_start,
                    source_end=actual_end,
                    source_text=source_text,
                    evidence_ids=[evidence_id],
                ).model_dump(mode="json")
            )
        return scenes
