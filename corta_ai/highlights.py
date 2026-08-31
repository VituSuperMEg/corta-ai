from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class TranscriptSegment:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class Highlight:
    start: float
    end: float
    score: float

    @property
    def duration(self) -> float:
        return round(self.end - self.start, 6)


def _window_score(segments: list[TranscriptSegment], start: float, end: float) -> float:
    text = " ".join(segment.text for segment in segments if segment.end > start and segment.start < end)
    words = re.findall(r"\w+", text, flags=re.UNICODE)
    if not words:
        return 0
    questions = text.count("?") * 7
    emphasis = text.count("!") * 5
    completeness = 4 if text.rstrip().endswith((".", "?", "!")) else 0
    return len(words) + questions + emphasis + completeness


def choose_highlights(
    segments: list[TranscriptSegment],
    clip_count: int,
    clip_duration: int,
    video_duration: float,
) -> list[Highlight]:
    required_duration = clip_count * clip_duration
    if video_duration + 0.001 < required_duration:
        raise ValueError(
            f"O vídeo não comporta {clip_count} cortes de {clip_duration}s sem repetição."
        )

    step = max(5, min(clip_duration / 3, 15))
    starts = {min(index * step, video_duration - clip_duration) for index in range(int(video_duration // step) + 1)}
    candidates = [
        Highlight(start=start, end=start + clip_duration, score=_window_score(segments, start, start + clip_duration))
        for start in starts
        if start >= 0 and start + clip_duration <= video_duration + 0.001
    ]
    candidates.sort(key=lambda item: (-item.score, item.start))

    selected: list[Highlight] = []
    for candidate in candidates:
        if all(candidate.end <= item.start or item.end <= candidate.start for item in selected):
            selected.append(candidate)
            if len(selected) == clip_count:
                return sorted(selected, key=lambda item: item.start)

    # A score-based grid can leave gaps that fit poorly. This deterministic
    # fallback guarantees the requested quantity whenever capacity permits.
    return [
        Highlight(
            start=index * clip_duration,
            end=(index + 1) * clip_duration,
            score=_window_score(segments, index * clip_duration, (index + 1) * clip_duration),
        )
        for index in range(clip_count)
    ]

