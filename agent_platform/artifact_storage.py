from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class ArtifactStorageError(RuntimeError):
    """Raised when an artifact cannot be written to the configured backend."""


class ArtifactStore(Protocol):
    """Small storage contract used by the runtime's content-addressed artifacts."""

    def put(self, artifact_id: str, content: str) -> str: ...


class LocalArtifactStore:
    """Content-addressed local repository for offline and single-node deployments."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, artifact_id: str, content: str) -> str:
        path = self.root / f"{artifact_id}.json"
        path.write_text(content, encoding="utf-8")
        return str(path)


class S3ArtifactStore:
    """S3-compatible object store adapter with an optional boto3 dependency."""

    def __init__(
        self, *, bucket: str, prefix: str = "artifacts", client: Any | None = None,
        endpoint_url: str | None = None,
    ) -> None:
        if not bucket.strip():
            raise ValueError("S3 bucket is required")
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        if client is None:
            try:
                import boto3
            except ImportError as exc:
                raise ArtifactStorageError(
                    "boto3 is required for S3ArtifactStore when no client is injected"
                ) from exc
            client = boto3.client("s3", endpoint_url=endpoint_url)
        self.client = client

    def _key(self, artifact_id: str) -> str:
        return f"{self.prefix}/{artifact_id}.json" if self.prefix else f"{artifact_id}.json"

    def put(self, artifact_id: str, content: str) -> str:
        key = self._key(artifact_id)
        try:
            self.client.put_object(
                Bucket=self.bucket, Key=key, Body=content.encode("utf-8"),
                ContentType="application/json; charset=utf-8",
            )
        except Exception as exc:  # pragma: no cover - provider-specific failure
            raise ArtifactStorageError(f"failed to store artifact in s3: {exc}") from exc
        return f"s3://{self.bucket}/{key}"


def build_artifact_store(settings: Any) -> ArtifactStore:
    """Build storage from explicit settings without making cloud SDKs mandatory."""

    if settings.artifact_backend == "local":
        return LocalArtifactStore(settings.artifact_dir)
    if settings.artifact_backend == "s3":
        if not settings.s3_bucket:
            raise ValueError("S3_ARTIFACT_BUCKET is required when ARTIFACT_BACKEND=s3")
        return S3ArtifactStore(
            bucket=settings.s3_bucket, prefix=settings.s3_prefix,
            endpoint_url=settings.s3_endpoint_url,
        )
    raise ValueError(f"unsupported artifact backend: {settings.artifact_backend}")
