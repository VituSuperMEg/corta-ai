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


# Aberturas que seguram o espectador nos primeiros segundos de um short.
_HOOK = re.compile(r"\b(voc[eê] sabia|ningu[eé]m (te )?(fala|conta)|o segredo|o (maior )?erro|nunca|jamais|"
                   r"a verdade|cuidado|aten[cç][aã]o|o que acontece|por que|como (eu|voc[eê])|\d+)\b", re.IGNORECASE)


def _window_score(segments: list[TranscriptSegment], start: float, end: float,
                  hook_start: bool = False) -> float:
    inside = [segment for segment in segments if segment.end > start and segment.start < end]
    text = " ".join(segment.text for segment in inside)
    words = re.findall(r"\w+", text, flags=re.UNICODE)
    if not words:
        return 0
    questions = text.count("?") * 7
    emphasis = text.count("!") * 5
    completeness = 4 if text.rstrip().endswith((".", "?", "!")) else 0
    score = len(words) + questions + emphasis + completeness
    if hook_start:
        opening = " ".join(segment.text for segment in inside if segment.start < start + 3)
        score += 12 * bool(_HOOK.search(opening)) + 8 * bool(re.search(r"\?", opening))
        score += 3 * len(words) / max(1, end - start)  # ritmo: fala rápida = energia
        score -= 6 * (inside[0].start < start - 0.5)  # janela que começa no meio da frase
    return score


def choose_highlights(
    segments: list[TranscriptSegment],
    clip_count: int,
    clip_duration: int,
    video_duration: float,
    hook_start: bool = False,
    energy: list[float] | None = None,
) -> list[Highlight]:
    required_duration = clip_count * clip_duration
    if video_duration + 0.001 < required_duration:
        raise ValueError(
            f"O vídeo não comporta {clip_count} cortes de {clip_duration}s sem repetição."
        )

    step = max(5, min(clip_duration / 3, 15))
    starts = {min(index * step, video_duration - clip_duration) for index in range(int(video_duration // step) + 1)}
    if hook_start:  # também começa exatamente onde cada frase começa
        starts |= {min(round(segment.start, 3), video_duration - clip_duration) for segment in segments}
    mean_energy = (sum(energy) / len(energy)) if energy else 0

    def energy_bonus(start: float) -> float:
        if not energy or not mean_energy:
            return 0
        window = energy[int(start):int(start + clip_duration)] or [0]
        return 10 * (sum(window) / len(window)) / mean_energy  # 10 = média; mais alto = empolgado

    candidates = [
        Highlight(start=start, end=start + clip_duration,
                  score=_window_score(segments, start, start + clip_duration, hook_start) + energy_bonus(start))
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

