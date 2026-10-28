from __future__ import annotations

import json

import pytest

from agent_platform.domain import ErrorCode, RunStatus, WorkflowStepError
from agent_platform.providers import FakeModel
from agent_platform.schemas import Shot
from agent_platform.workflows.script_to_storyboard import SCRIPT_STEPS, ScriptToStoryboardAdapter


def test_workflow_declares_the_required_business_steps_in_order() -> None:
    adapter = ScriptToStoryboardAdapter(FakeModel())
    assert [step.name for step in adapter.register().steps] == list(SCRIPT_STEPS)
    assert adapter.register().steps[7].human_gate is True


def test_scene_split_is_deterministic_and_preserves_source_evidence() -> None:
    text = "SCENE 1: Room\nA enters.\n\nSCENE 2: Hall\nB waits.\n"
    adapter = ScriptToStoryboardAdapter(FakeModel())
    first = adapter.execute_step(
        "split_script", {"run_id": "run-a", "script_id": "script-a", "script_text": text}
    )
    repeat = adapter.execute_step(
        "split_script", {"run_id": "run-a", "script_id": "script-a", "script_text": text}
    )
    other_run = adapter.execute_step(
        "split_script", {"run_id": "run-b", "script_id": "script-a", "script_text": text}
    )

    assert first == repeat
    assert [scene["scene_id"] for scene in first] == [scene["scene_id"] for scene in other_run]
    assert [scene["evidence_ids"] for scene in first] != [
        scene["evidence_ids"] for scene in other_run
    ]
    for scene in first:
        assert scene["source_text"] == text[scene["source_start"] : scene["source_end"]]
        assert scene["source_start"] < scene["source_end"]
        assert len(scene["evidence_ids"]) == 1


def test_schema_validation_and_evidence_coverage_are_hard_boundaries() -> None:
    adapter = ScriptToStoryboardAdapter(FakeModel())
    with pytest.raises(WorkflowStepError) as schema_error:
        adapter.validate("generate_storyboard", [{"scene_id": "scene-1"}])
    assert schema_error.value.code == ErrorCode.SCHEMA_VALIDATION_FAILED

    with pytest.raises(WorkflowStepError) as evidence_error:
        adapter.execute_step(
            "validate_facts",
            {
                "facts": [
                    {
                        "fact_id": "fact-1",
                        "kind": "action",
                        "value": "enters",
                        "evidence_ids": ["missing"],
                    }
                ],
                "evidence": [],
            },
        )
    assert evidence_error.value.code == ErrorCode.EVIDENCE_MISSING


def test_offline_workflow_persists_evidence_and_completes_after_review(runtime, script) -> None:
    result = runtime.create_run(project_id="storyboard-gate", script=script)
    assert result.status == RunStatus.WAITING_REVIEW.value
    run = runtime.repository.get_run(result.run_id)
    context = run.context_json
    evidence_ids = {item["evidence_id"] for item in context["evidence"]}
    assert (
        len(evidence_ids)
        == len(context["evidence"])
        == len(runtime.repository.get_evidence(result.run_id))
    )
    assert all(
        fact_evidence in evidence_ids
        for fact in context["facts"]
        for fact_evidence in fact["evidence_ids"]
    )
    assert all(scene["evidence_ids"] for scene in context["scenes"])
    assert all(
        shot_evidence in evidence_ids
        for shot in context["shots"]
        for shot_evidence in shot["evidence_ids"]
    )
    required_shot_fields = {
        "scene_id",
        "shot_id",
        "shot_type",
        "duration_hint",
        "location",
        "characters",
        "action",
        "camera",
        "dialogue_or_voiceover",
        "visual_intent",
        "evidence_ids",
    }
    assert all(required_shot_fields <= set(shot) for shot in context["shots"])
    assert {
        artifact.artifact_type for artifact in runtime.repository.get_artifacts(result.run_id)
    } >= {
        "script_input",
        "split_script",
        "build_source_index",
        "extract_facts",
        "validate_facts",
        "generate_storyboard",
        "validate_storyboard",
        "wait_for_human_review",
    }

    for review in runtime.repository.get_reviews(result.run_id):
        final = runtime.approve_review(review.id, "gate-reviewer", "approved")
    assert final.status == RunStatus.COMPLETED.value
    run = runtime.repository.get_run(result.run_id)
    assert run.context_json["storyboard"]["revision"] == 1
    artifacts = runtime.repository.get_artifacts(result.run_id)
    exported = next(item for item in artifacts if item.artifact_type == "export_artifacts")
    assert json.loads(exported.content)["formats"] == ["json", "csv", "html"]


def test_storyboard_model_contract_accepts_all_required_fields() -> None:
    shot = Shot(
        scene_id="scene-1",
        shot_id="shot-1",
        shot_type="wide",
        duration_hint="3s",
        location="Room",
        characters=["A"],
        action="enters",
        camera="locked",
        dialogue_or_voiceover="hello",
        visual_intent="establish space",
        evidence_ids=["e-1"],
    )
    assert shot.evidence_ids == ["e-1"]
