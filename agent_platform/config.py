from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database_url: str = "sqlite:///./agent_platform.db"
    artifact_dir: Path = Path("./data/artifacts")
    default_model: str = "fake-v1"
    fake_model_mode: str = "success"
    log_level: str = "INFO"
    anthropic_api_key: str | None = None
    anthropic_model: str | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=os.getenv("DATABASE_URL", cls.database_url),
            artifact_dir=Path(os.getenv("ARTIFACT_DIR", str(cls.artifact_dir))),
            default_model=os.getenv("DEFAULT_MODEL", cls.default_model),
            fake_model_mode=os.getenv("FAKE_MODEL_MODE", cls.fake_model_mode),
            log_level=os.getenv("LOG_LEVEL", cls.log_level),
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY") or None,
            anthropic_model=os.getenv("ANTHROPIC_MODEL") or None,
        )
