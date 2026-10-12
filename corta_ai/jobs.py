from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field, fields
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
    stylish_captions: bool = False
    varied_fonts: bool = False
    smooth_zoom: bool = False
    clip_progress: bool = False
    opening_title: bool = False
    sound_effects: bool = False
    hook_start: bool = False
    end_cta: bool = False
    camera_cuts: bool = False
    censor: bool = False
    caption_emoji: bool = False
    background_music: bool = False
    energy_score: bool = False
    suggestions: bool = False
    caption_position: str = "bottom"
    floating_captions: bool = False
    director: str = "off"
    title_text: str = ""
    sfx_hook: bool = False
    sfx_whoosh: bool = False
    sfx_riser: bool = False
    fx_hook: bool = False
    fx_shake: bool = False
    fx_flash: bool = False
    fx_keyword: bool = False
    fx_vignette: bool = False
    ncs_credit: bool = False
    speed_ramp: bool = False
    freeze_climax: bool = False
    music_track: str = ""
    music_volume: int = 35
    metadata: list[dict] = field(default_factory=list)
    ai_plans: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class InMemoryJobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = Lock()

    def create(self, youtube_url: str, clip_count: int, clip_duration: int, stylish_captions: bool = False, varied_fonts: bool = False,
               smooth_zoom: bool = False, clip_progress: bool = False,
               opening_title: bool = False, sound_effects: bool = False, hook_start: bool = False,
               end_cta: bool = False, title_text: str = "", **extra: Any) -> Job:
        job = Job(youtube_url=youtube_url, clip_count=clip_count, clip_duration=clip_duration,
                  stylish_captions=stylish_captions, varied_fonts=varied_fonts,
                  smooth_zoom=smooth_zoom, clip_progress=clip_progress,
                  opening_title=opening_title, sound_effects=sound_effects, hook_start=hook_start,
                  end_cta=end_cta, title_text=title_text, **extra)
        with self._lock:
            self._jobs[job.id] = job
        return deepcopy(job)

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return deepcopy(job) if job else None

    def update(self, job_id: str, **changes: Any) -> Job:
        allowed_fields = {item.name for item in fields(Job)} - {"id"}
        unknown_fields = changes.keys() - allowed_fields
        if unknown_fields:
            raise ValueError(f"Campos de trabalho inválidos: {', '.join(sorted(unknown_fields))}")
        with self._lock:
            job = self._jobs[job_id]
            for name, value in changes.items():
                setattr(job, name, value)
            return deepcopy(job)
