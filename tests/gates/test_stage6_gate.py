from __future__ import annotations

import re
from pathlib import Path

from agent_platform.config import Settings
from agent_platform.db import Database
from agent_platform.domain import ErrorCode, RunStatus
from agent_platform.providers import FakeModel
from agent_platform.runtime import WorkflowRuntime

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = "SCENE 1: Room\nA enters.\n\nSCENE 2: Hall\nB waits."


def _runtime(tmp_path: Path, mode: str) -> tuple[WorkflowRuntime, FakeModel]:
    model = FakeModel(mode=mode)
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / f'{mode}.db'}",
        artifact_dir=tmp_path / f"{mode}-artifacts",
    )
    return WorkflowRuntime(database=Database(settings), settings=settings, model=model), model


def test_fakemodel_all_modes_are_deterministic_and_structured(tmp_path) -> None:
    expected = {
        "success": RunStatus.WAITING_REVIEW.value,
        "invalid_output": RunStatus.FAILED.value,
        "timeout": RunStatus.NEEDS_RECOVERY.value,
        "model_error": RunStatus.FAILED.value,
        "unknown": RunStatus.NEEDS_RECOVERY.value,
    }
    for mode, expected_status in expected.items():
        runtime, model = _runtime(tmp_path, mode)
        result = runtime.create_run(project_id=f"fake-{mode}", script=SCRIPT)
        assert result.status == expected_status
        assert model.calls[0]["operation"] == "generate_facts"
        if mode == "success":
            assert [call["operation"] for call in model.calls[:2]] == [
                "generate_facts",
                "generate_storyboard",
            ]
        else:
            assert len(model.calls) == 1
        if mode == "invalid_output":
            assert (
                runtime.repository.get_run(result.run_id).error_code
                == ErrorCode.SCHEMA_VALIDATION_FAILED.value
            )
        if mode == "model_error":
            assert (
                runtime.repository.get_run(result.run_id).error_code == ErrorCode.MODEL_ERROR.value
            )
        if mode in {"timeout", "unknown"}:
            assert runtime.repository.get_external_calls(result.run_id)[0].status == "unknown"


def test_input_artifact_foreign_key_order_is_valid(tmp_path) -> None:
    """The PostgreSQL FK requires the Run row before its input Artifact."""
    runtime, _ = _runtime(tmp_path, "success")
    result = runtime.create_run(project_id="foreign-key-order", script=SCRIPT)
    run = runtime.repository.get_run(result.run_id)
    assert run is not None
    assert run.input_artifact_id is not None
    artifact = runtime.repository.get_artifact(run.input_artifact_id)
    assert artifact is not None
    assert artifact.run_id == result.run_id


def test_engineering_files_and_documents_are_present_and_coherent() -> None:
    required_files = [
        "pyproject.toml",
        ".env.example",
        "Dockerfile",
        "docker-compose.yml",
        "alembic.ini",
        ".pre-commit-config.yaml",
        ".github/workflows/ci.yml",
        "README.md",
        "Makefile",
        "docs/architecture.md",
        "docs/README.md",
        "docs/state-machine.md",
        "docs/recovery.md",
        "docs/extension-guide.md",
        "docs/security-scanning.md",
        "docs/stage-gates.md",
        "migrations/versions/0001_initial.py",
        "examples/sample_script.txt",
    ]
    for relative in required_files:
        assert (ROOT / relative).exists(), relative
    readme = (ROOT / "README.md").read_text(encoding="utf-8").lower()
    for token in (
        "架构",
        "数据模型",
        "审核",
        "恢复",
        "启动",
        "测试",
        "环境变量",
        "真实模型",
        "限制",
        "未来",
    ):
        assert token in readme
    ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "setup-python" in ci and "pytest" in ci and "compileall" in ci and "gitleaks" in ci
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY alembic.ini" in dockerfile and "COPY migrations" in dockerfile


def test_repository_has_no_high_confidence_secret_or_reference_path_patterns() -> None:
    patterns = [
        re.compile(r"AKIA[0-9A-Z]{16}"),
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
        re.compile(r"sk-[A-Za-z0-9]{20,}"),
        re.compile(r"D:\\AI\\Chinese\\"),
        re.compile(r"D:\\AI\\agent1"),
    ]
    ignored = {".git", ".pytest_cache", ".pytest-tmp", "data", "exports"}
    suffixes = {".py", ".md", ".yml", ".yaml", ".toml", ".ini", ".env", ".example", ".txt"}
    for path in ROOT.rglob("*"):
        if (
            not path.is_file()
            or any(part in ignored for part in path.parts)
            or path.suffix not in suffixes
        ):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        assert not any(pattern.search(text) for pattern in patterns), path
