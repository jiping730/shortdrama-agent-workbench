from __future__ import annotations

from collections import Counter
from time import monotonic
from typing import Iterator
from contextlib import contextmanager


class RuntimeMetrics:
    """Dependency-free metrics facade; OpenTelemetry can subscribe later."""

    def __init__(self) -> None:
        self.counters: Counter[str] = Counter()
        self.durations_ms: dict[str, list[float]] = {}

    @contextmanager
    def step(self, step_name: str) -> Iterator[None]:
        started = monotonic()
        self.counters["steps.started"] += 1
        try:
            yield
        except Exception:
            self.counters["steps.failed"] += 1
            raise
        else:
            self.counters["steps.succeeded"] += 1
        finally:
            self.durations_ms.setdefault(step_name, []).append((monotonic() - started) * 1000)

    def snapshot(self) -> dict[str, object]:
        return {
            "counters": dict(self.counters),
            "durations_ms": {name: {"count": len(values), "total": sum(values), "max": max(values)} for name, values in self.durations_ms.items()},
        }
