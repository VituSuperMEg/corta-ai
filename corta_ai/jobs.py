from __future__ import annotations

from dataclasses import asdict, dataclass, field
from threading import Lock
from typing import Any
from uuid import uuid4


@dataclass
class Job:
    youtube_url: str
    clip_count: int
    clip_duration: int
    id: str = field(default_factory=lambda: uuid4().hex)
    status: str = "queued"
    progress: int = 0
    message: str = "Na fila"
    error: str | None = None
    outputs: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class InMemoryJobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = Lock()

    def create(self, youtube_url: str, clip_count: int, clip_duration: int) -> Job:
        job = Job(youtube_url=youtube_url, clip_count=clip_count, clip_duration=clip_duration)
        with self._lock:
            self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def update(self, job_id: str, **changes: Any) -> Job:
        with self._lock:
            job = self._jobs[job_id]
            for name, value in changes.items():
                setattr(job, name, value)
            return job


