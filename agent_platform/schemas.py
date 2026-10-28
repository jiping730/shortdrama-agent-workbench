from __future__ import annotations

from typing import Any, List, Optional

try:
    from typing import Literal
except ImportError:  # Python 3.7 compatibility
    from typing_extensions import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .domain import content_hash, stable_id


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evidence_id: str
    script_id: str
    scene_id: Optional[str] = None
    source_start: int = Field(ge=0)
    source_end: int = Field(ge=0)
    source_text: str = Field(min_length=1)
    content_hash: str

    @field_validator("source_end")
    @classmethod
    def end_after_start(cls, value: int, info: Any) -> int:
        start = info.data.get("source_start")
        if start is not None and value < start:
            raise ValueError("source_end must be >= source_start")
        return value


class ScriptInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    script_id: str = Field(default="script-1", min_length=1)
    title: str = Field(default="Untitled", min_length=1)
    text: str = Field(min_length=1)

    @property
    def input_hash(self) -> str:
        return content_hash({"script_id": self.script_id, "title": self.title, "text": self.text})


class Scene(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scene_id: str
    scene_no: int = Field(ge=1)
    title: str
    source_start: int = Field(ge=0)
    source_end: int = Field(ge=0)
    source_text: str = Field(min_length=1)
    evidence_ids: List[str] = Field(min_length=1)


class Fact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fact_id: str
    kind: Literal["character", "location", "prop", "action", "dialogue"]
    value: str = Field(min_length=1)
    evidence_ids: List[str] = Field(min_length=1)


class Shot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scene_id: str
    shot_id: str
    shot_type: str = Field(min_length=1)
    duration_hint: str = Field(min_length=1)
    location: str = Field(min_length=1)
    characters: List[str]
    action: str = Field(min_length=1)
    camera: str = Field(min_length=1)
    dialogue_or_voiceover: str
    visual_intent: str = Field(min_length=1)
    evidence_ids: List[str] = Field(min_length=1)


class ShotListItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    shot_id: str
    scene_id: str
    order: int = Field(ge=1)
    duration_hint: str = Field(min_length=1)
    location: str = Field(min_length=1)
    characters: List[str]
    action: str = Field(min_length=1)
    evidence_ids: List[str] = Field(min_length=1)


class ShotList(BaseModel):
    model_config = ConfigDict(extra="forbid")
    shotlist_id: str
    script_id: str
    revision: int = Field(ge=1)
    items: List[ShotListItem] = Field(min_length=1)


class Storyboard(BaseModel):
    model_config = ConfigDict(extra="forbid")
    storyboard_id: str
    script_id: str
    revision: int = Field(ge=1)
    shots: List[Shot] = Field(min_length=1)


class RunCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())
    project_id: str = Field(min_length=1)
    workspace_id: str = "default-workspace"
    project_name: Optional[str] = None
    workflow: str = "script-to-storyboard"
    workflow_version: str = "1.0.0"
    script: str = Field(min_length=1)
    script_id: str = "script-1"
    title: str = "Untitled"
    model_mode: Literal["success", "invalid_output", "timeout", "model_error", "unknown"] = "success"
    idempotency_key: Optional[str] = None


class RetryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    step_name: Optional[str] = None
    scene_ids: List[str] = Field(default_factory=list)


class ReviewDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reviewer: str = Field(min_length=1)
    comment: str = ""


class RunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    run_id: str
    status: str
    current_step: Optional[str]
    workflow_version: str
    input_hash: str
    error_code: Optional[str] = None


def stable_scene_id(script_id: str, scene_no: int, source_text: str) -> str:
    return stable_id("scene", script_id, scene_no, content_hash(source_text))
