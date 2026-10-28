from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

try:
    from typing import Protocol
except ImportError:  # Python 3.7 compatibility for the local offline runner
    from typing_extensions import Protocol

from .domain import ErrorCode, UnknownExternalCall, WorkflowStepError
from .schemas import Fact, Scene, Shot


class ModelProvider(Protocol):
    name: str
    version: str

    def generate_facts(self, *, script_text: str, scenes: list[Scene]) -> list[Fact]: ...

    def generate_storyboard(self, *, script_text: str, scenes: list[Scene], facts: list[Fact]) -> list[Shot]: ...

    def revise_storyboard(self, *, script_text: str, scenes: list[Scene], facts: list[Fact], rejected_scene_ids: list[str]) -> list[Shot]: ...


@dataclass
class FakeModel:
    """Deterministic provider for offline tests and demonstrations.

    The mode is explicit so tests can prove error and unknown-call behavior without
    network access. It intentionally produces no media and has no hidden memory.
    """

    mode: str = "success"
    name: str = "fake"
    version: str = "fake-v1"
    calls: list[dict[str, Any]] = field(default_factory=list)

    def _before_call(self, operation: str, scene_ids: list[str] | None = None) -> None:
        self.calls.append({"operation": operation, "scene_ids": list(scene_ids or [])})
        if self.mode == "invalid_output":
            raise WorkflowStepError(ErrorCode.SCHEMA_VALIDATION_FAILED, "FakeModel returned invalid output")
        if self.mode == "timeout":
            raise WorkflowStepError(ErrorCode.TIMEOUT, "FakeModel timed out", retriable=True)
        if self.mode == "model_error":
            raise WorkflowStepError(ErrorCode.MODEL_ERROR, "FakeModel provider error", retriable=True)
        if self.mode == "unknown":
            raise UnknownExternalCall("FakeModel result cannot be confirmed")

    def generate_facts(self, *, script_text: str, scenes: list[Scene]) -> list[Fact]:
        self._before_call("generate_facts", [scene.scene_id for scene in scenes])
        facts: list[Fact] = []
        for scene in scenes:
            if "角色：" in scene.source_text:
                value = scene.source_text.split("角色：", 1)[1].split("；", 1)[0].strip()
                if value:
                    facts.append(Fact(
                        fact_id=f"fact_{scene.scene_id}_character",
                        kind="character", value=value, evidence_ids=scene.evidence_ids,
                    ))
            if "场景：" in scene.source_text:
                value = scene.source_text.split("场景：", 1)[1].split("；", 1)[0].strip()
                if value:
                    facts.append(Fact(
                        fact_id=f"fact_{scene.scene_id}_location",
                        kind="location", value=value, evidence_ids=scene.evidence_ids,
                    ))
            if "道具：" in scene.source_text:
                value = scene.source_text.split("道具：", 1)[1].split("；", 1)[0].strip()
                if value:
                    facts.append(Fact(
                        fact_id=f"fact_{scene.scene_id}_prop",
                        kind="prop", value=value, evidence_ids=scene.evidence_ids,
                    ))
        return facts

    def generate_storyboard(self, *, script_text: str, scenes: list[Scene], facts: list[Fact]) -> list[Shot]:
        self._before_call("generate_storyboard", [scene.scene_id for scene in scenes])
        return self._shots_for(scenes, facts)

    def revise_storyboard(self, *, script_text: str, scenes: list[Scene], facts: list[Fact], rejected_scene_ids: list[str]) -> list[Shot]:
        self._before_call("revise_storyboard", rejected_scene_ids)
        selected = [scene for scene in scenes if scene.scene_id in set(rejected_scene_ids)]
        return self._shots_for(selected, facts, revised=True)

    @staticmethod
    def _shots_for(scenes: list[Scene], facts: list[Fact], revised: bool = False) -> list[Shot]:
        result: list[Shot] = []
        for scene in scenes:
            characters = [fact.value for fact in facts if fact.kind == "character" and set(fact.evidence_ids) & set(scene.evidence_ids)]
            locations = [fact.value for fact in facts if fact.kind == "location" and set(fact.evidence_ids) & set(scene.evidence_ids)]
            location = locations[0] if locations else scene.title
            dialogue = scene.source_text
            result.append(Shot(
                scene_id=scene.scene_id,
                shot_id=f"shot_{scene.scene_id}_{'r2' if revised else 'r1'}",
                shot_type="medium",
                duration_hint="3-5s",
                location=location,
                characters=characters,
                action="角色在场景中推进当前动作",
                camera="固定中景，必要时轻微推进",
                dialogue_or_voiceover=dialogue,
                visual_intent="清晰表达场景动作与情绪",
                evidence_ids=scene.evidence_ids,
            ))
        return result


class AnthropicModelAdapter:
    """Optional boundary for the official Anthropic SDK.

    The dependency is deliberately optional and the adapter never becomes the
    platform's default. Production deployments should configure prompts and model
    policy outside this repository.
    """

    name = "anthropic"
    version = "external"

    def __init__(self, api_key: str, model: str, *, client: Any | None = None, max_tokens: int = 4096) -> None:
        self.api_key = api_key
        self.model = model
        self.max_tokens = max_tokens
        self._import_error: Exception | None = None
        if client is not None:
            self._client = client
        else:
            try:
                from anthropic import Anthropic
            except ImportError as exc:  # optional dependency
                self._client = None
                self._import_error = exc
            else:
                self._client = Anthropic(api_key=api_key)

    def _call(self, operation: str, payload: dict[str, Any]) -> list[Any] | dict[str, Any]:
        if self._client is None:
            raise WorkflowStepError(ErrorCode.MODEL_ERROR, "optional anthropic package is not installed")
        try:
            response = self._client.messages.create(
                model=self.model, max_tokens=self.max_tokens,
                system="Return only valid JSON matching the requested workflow contract.",
                messages=[{"role": "user", "content": f"operation={operation}\npayload={payload}"}],
            )
            blocks = getattr(response, "content", [])
            text = getattr(blocks[0], "text", "") if blocks else ""
            result = json.loads(text)
            if not isinstance(result, (list, dict)):
                raise WorkflowStepError(ErrorCode.SCHEMA_VALIDATION_FAILED, "Anthropic response must be a JSON list or object")
            return result
        except WorkflowStepError:
            raise
        except json.JSONDecodeError as exc:
            raise WorkflowStepError(ErrorCode.SCHEMA_VALIDATION_FAILED, "Anthropic response was not valid JSON") from exc
        except Exception as exc:
            raise WorkflowStepError(ErrorCode.MODEL_ERROR, f"Anthropic call failed: {exc}", retriable=True) from exc

    @staticmethod
    def _items(result: list[Any] | dict[str, Any], key: str) -> list[Any]:
        items = result if isinstance(result, list) else result.get(key, [])
        if not isinstance(items, list):
            raise WorkflowStepError(ErrorCode.SCHEMA_VALIDATION_FAILED, f"Anthropic field {key} must be a list")
        return items

    def generate_facts(self, *, script_text: str, scenes: list[Scene]) -> list[Fact]:
        result = self._call("generate_facts", {"script_text": script_text, "scenes": [scene.model_dump(mode="json") for scene in scenes]})
        try:
            return [Fact.model_validate(item) for item in self._items(result, "facts")]
        except ValidationError as exc:
            raise WorkflowStepError(ErrorCode.SCHEMA_VALIDATION_FAILED, str(exc)) from exc

    def generate_storyboard(self, *, script_text: str, scenes: list[Scene], facts: list[Fact]) -> list[Shot]:
        result = self._call("generate_storyboard", {"script_text": script_text, "scenes": [scene.model_dump(mode="json") for scene in scenes], "facts": [fact.model_dump(mode="json") for fact in facts]})
        try:
            return [Shot.model_validate(item) for item in self._items(result, "shots")]
        except ValidationError as exc:
            raise WorkflowStepError(ErrorCode.SCHEMA_VALIDATION_FAILED, str(exc)) from exc

    def revise_storyboard(self, *, script_text: str, scenes: list[Scene], facts: list[Fact], rejected_scene_ids: list[str]) -> list[Shot]:
        result = self._call("revise_storyboard", {"script_text": script_text, "scenes": [scene.model_dump(mode="json") for scene in scenes], "facts": [fact.model_dump(mode="json") for fact in facts], "rejected_scene_ids": rejected_scene_ids})
        try:
            return [Shot.model_validate(item) for item in self._items(result, "shots")]
        except ValidationError as exc:
            raise WorkflowStepError(ErrorCode.SCHEMA_VALIDATION_FAILED, str(exc)) from exc


def build_model_provider(settings: Any, *, client: Any | None = None) -> ModelProvider:
    """Select a provider only from explicit configuration.

    FakeModel remains the default, so local tests never contact a model service.
    Anthropic uses the official SDK through AnthropicModelAdapter; no OpenAI
    compatibility layer is involved.
    """

    if settings.model_provider == "fake":
        return FakeModel(mode=settings.fake_model_mode, version=settings.default_model)
    if settings.model_provider == "anthropic":
        if not settings.anthropic_api_key or not settings.anthropic_model:
            raise ValueError("ANTHROPIC_API_KEY and ANTHROPIC_MODEL are required for MODEL_PROVIDER=anthropic")
        return AnthropicModelAdapter(settings.anthropic_api_key, settings.anthropic_model, client=client)
    raise ValueError(f"unsupported model provider: {settings.model_provider}")
