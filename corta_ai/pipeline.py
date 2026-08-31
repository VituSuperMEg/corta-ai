from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys

from .highlights import TranscriptSegment, choose_highlights
from .jobs import InMemoryJobStore


def _run(command: list[str], error_message: str) -> str:
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        detail = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else error_message
        raise RuntimeError(f"{error_message}: {detail}")
    return result.stdout.strip()


def download_video(url: str, job_dir: Path) -> Path:
    source_dir = job_dir / "source"
    source_dir.mkdir(parents=True, exist_ok=True)
    output = _run(
        [sys.executable, "-m", "yt_dlp", "--no-playlist", "--restrict-filenames", "--merge-output-format", "mp4",
         "-f", "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/best", "--print", "after_move:filepath",
         "-o", str(source_dir / "video.%(ext)s"), url],
        "Não foi possível baixar o vídeo",
    )
    path = Path(output.splitlines()[-1])
    if not path.is_file():
        raise RuntimeError("O download terminou, mas o arquivo do vídeo não foi encontrado")
    return path


def video_duration(path: Path) -> float:
    output = _run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        "Não foi possível analisar a duração do vídeo",
    )
    return float(json.loads(output)["format"]["duration"])


def transcribe(path: Path) -> tuple[list[TranscriptSegment], list[dict]]:
    try:
        from faster_whisper import WhisperModel
    except ImportError as error:
        raise RuntimeError("O faster-whisper não está instalado. Execute ./iniciar.sh.") from error
    model = WhisperModel("small", device="cpu", compute_type="int8")
    raw_segments, _ = model.transcribe(
        str(path), language="pt", vad_filter=True, word_timestamps=True, beam_size=5
    )
    segments: list[TranscriptSegment] = []
    words: list[dict] = []
    for item in raw_segments:
        segments.append(TranscriptSegment(float(item.start), float(item.end), item.text.strip()))
        for word in item.words or []:
            words.append({"start": float(word.start), "end": float(word.end), "text": word.word.strip()})
    if not segments:
        raise RuntimeError("Não foi possível identificar fala no vídeo")
    return segments, words


def _ass_time(seconds: float) -> str:
    value = max(0, round(seconds * 100))
    hours, value = divmod(value, 360000)
    minutes, value = divmod(value, 6000)
    seconds, fraction = divmod(value, 100)
    return f"{hours}:{minutes:02d}:{seconds:02d}.{fraction:02d}"


def _ass_text(value: str) -> str:
    return re.sub(r"[{}]", "", value).replace("\\", "")


def create_ass(words: list[dict], clip_start: float, clip_end: float, destination: Path) -> None:
    visible = [word for word in words if word["end"] > clip_start and word["start"] < clip_end]
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,72,&H00FFFFFF,&H0000E8FF,&H00101010,&H70000000,-1,0,0,0,100,100,0,0,1,7,2,2,70,70,230,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines: list[str] = []
    for offset in range(0, len(visible), 5):
        group = visible[offset:offset + 5]
        start = max(0, group[0]["start"] - clip_start)
        end = min(clip_end - clip_start, group[-1]["end"] - clip_start + 0.12)
        karaoke_parts: list[str] = []
        for index, word in enumerate(group):
            next_start = group[index + 1]["start"] if index + 1 < len(group) else word["end"]
            highlight_duration = max(word["end"], next_start) - word["start"]
            karaoke_parts.append(
                f"{{\\kf{max(1, round(highlight_duration * 100))}}}{_ass_text(word['text']).upper()}"
            )
        karaoke = " ".join(karaoke_parts)
        lines.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Default,,0,0,0,,{karaoke}")
    destination.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")


def render_clip(source: Path, subtitles: Path, start: float, duration: int, output: Path) -> None:
    subtitle_filter = str(subtitles).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
    video_filter = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920," + f"ass='{subtitle_filter}'"
    _run(
        ["ffmpeg", "-y", "-ss", f"{start:.3f}", "-i", str(source), "-t", str(duration),
         "-vf", video_filter, "-c:v", "libx264", "-preset", "medium", "-crf", "20",
         "-c:a", "aac", "-b:a", "192k", "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
         "-movflags", "+faststart", "-pix_fmt", "yuv420p", str(output)],
        f"Não foi possível renderizar {output.name}",
    )


def process_job(job_id: str, store: InMemoryJobStore, workspace: Path) -> None:
    job = store.get(job_id)
    if not job:
        return

    def progress(value: int, message: str) -> None:
        store.update(job_id, status="processing", progress=value, message=message, error=None)

    job_dir = workspace / job_id
    output_dir = job_dir / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        progress(5, "Baixando o vídeo")
        source = download_video(job.youtube_url, job_dir)
        duration = video_duration(source)
        progress(25, "Transcrevendo o áudio localmente")
        segments, words = transcribe(source)
        progress(55, "Escolhendo os melhores momentos")
        highlights = choose_highlights(segments, job.clip_count, job.clip_duration, duration)
        outputs: list[str] = []
        for index, highlight in enumerate(highlights, start=1):
            progress(55 + round((index - 1) / len(highlights) * 40), f"Renderizando corte {index} de {len(highlights)}")
            subtitle_path = job_dir / f"legenda-{index:02d}.ass"
            output_name = f"corte-{index:02d}.mp4"
            create_ass(words, highlight.start, highlight.end, subtitle_path)
            render_clip(source, subtitle_path, highlight.start, job.clip_duration, output_dir / output_name)
            outputs.append(output_name)
        store.update(job_id, status="completed", progress=100, message=f"{len(outputs)} cortes prontos", outputs=outputs)
    except Exception as error:
        store.update(job_id, status="failed", message="O processamento falhou", error=str(error))
