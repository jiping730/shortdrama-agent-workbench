from __future__ import annotations

from pathlib import Path

import pytest

from agent_platform.config import Settings
from agent_platform.db import Database
from agent_platform.providers import FakeModel
from agent_platform.runtime import WorkflowRuntime


@pytest.fixture()
def runtime(tmp_path: Path) -> WorkflowRuntime:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}", artifact_dir=tmp_path / "artifacts"
    )
    return WorkflowRuntime(database=Database(settings), settings=settings, model=FakeModel())


@pytest.fixture()
def script() -> str:
    return """SCENE 1: Studio
角色：Lina；场景：Studio；道具：Ticket。
Lina holds the ticket and whispers: I will try again.

SCENE 2: Street
角色：Lina；场景：Street；道具：Umbrella。
She walks into the rain.
"""
