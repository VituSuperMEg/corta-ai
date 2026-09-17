from __future__ import annotations

import json
import os
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
    model = WhisperModel(os.environ.get("WHISPER_MODEL", "small"), device="cpu", compute_type="int8",
                         cpu_threads=int(os.environ.get("CPU_THREADS", "2")))
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


def _stylish_events(words: list[dict], clip_start: float, clip_end: float, varied_fonts: bool = False) -> list[str]:
    """Alternate short phrases and punch words using the transcription's timings."""
    groups: list[list[dict]] = []
    for word in words:
        if word["end"] <= word["start"] or not word["text"].strip():
            continue
        if (not groups or len(groups[-1]) >= 3
                or sum(len(item["text"]) + 1 for item in groups[-1]) + len(word["text"]) > 24
                or word["start"] - groups[-1][-1]["end"] > 0.35
                or groups[-1][-1]["text"].endswith((".", "!", "?", ";"))):
            groups.append([])
        groups[-1].append(word)

    lines: list[str] = []
    for group_index, group in enumerate(groups):
        variant = group_index % 3
        font, font_size, weight = (
            ("Poppins ExtraBold", 70, 800),
            ("Barlow Condensed ExtraBold", 84, 800),
            ("Bebas Neue", 112, 400),
        )[variant]
        if not varied_fonts:
            font, font_size, weight = "Arial", 100 if variant == 2 else 76, 700
        typography = f"\\fn{font}\\b{weight}"
        color = ("&H003EFFD8&", "&H00FFDD55&", "&H008B79FF&")[variant]
        for index, word in enumerate(group):
            start = max(clip_start, word["start"])
            end = min(clip_end, word["end"])
            if index + 1 < len(group):
                end = min(end, group[index + 1]["start"])
            if round((end - clip_start) * 100) <= round((start - clip_start) * 100):
                continue
            duration_ms = max(1, round((end - start) * 1000))
            settle = min(110, duration_ms)
            text = _ass_text(word["text"]).upper()
            if variant == 2:
                size = min(font_size, int(850 / max(1, len(text)) / 0.75))
                body = (f"{{{typography}\\an2\\pos(540,1690)\\fs{size}\\1c{color}\\bord8"
                        f"\\fscx115\\fscy115\\t(0,{settle},\\fscx100\\fscy100)}}{text}")
            else:
                # Keep a fixed phrase layout while only the spoken word changes color.
                phrase = " ".join(
                    f"{{\\1c{color if i == index else '&H00FFFFFF&'}}}{_ass_text(item['text']).upper()}"
                    for i, item in enumerate(group)
                )
                if variant == 0:
                    animation = f"\\fscx94\\fscy94\\t(0,{settle},\\fscx100\\fscy100)"
                else:
                    animation = f"\\blur1\\shad3\\4c{color}"
                body = f"{{{typography}\\an2\\pos(540,1690)\\fs{font_size}\\bord6{animation}}}{phrase}"
            lines.append(f"Dialogue: 0,{_ass_time(start - clip_start)},{_ass_time(end - clip_start)},Default,,0,0,0,,{body}")
    return lines


def create_ass(words: list[dict], clip_start: float, clip_end: float, destination: Path,
               stylish_captions: bool = False, varied_fonts: bool = False) -> None:
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
    if stylish_captions:
        lines = _stylish_events(visible, clip_start, clip_end, varied_fonts)
        destination.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")
        return
    for offset in range(0, len(visible), 5):
        group = visible[offset:offset + 5]
        start = max(0, group[0]["start"] - clip_start)
        end = min(clip_end - clip_start, group[-1]["end"] - clip_start + 0.12)
        karaoke_parts: list[str] = []
        for index, word in enumerate(group):
            next_start = group[index + 1]["start"] if index + 1 < len(group) else word["end"]
            visible_start = max(word["start"], clip_start)
            highlight_duration = max(word["end"], next_start) - visible_start
            karaoke_parts.append(
                f"{{\\kf{max(1, round(highlight_duration * 100))}}}{_ass_text(word['text']).upper()}"
            )
        karaoke = " ".join(karaoke_parts)
        if varied_fonts:
            font, weight = (("Poppins ExtraBold", 800), ("Barlow Condensed ExtraBold", 800),
                            ("Bebas Neue", 400))[(offset // 5) % 3]
            karaoke = f"{{\\fn{font}\\b{weight}}}" + karaoke
        lines.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Default,,0,0,0,,{karaoke}")
    destination.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")


def render_clip(source: Path, subtitles: Path, start: float, duration: int, output: Path) -> None:
    subtitle_filter = str(subtitles).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
    fonts_dir = str(Path(__file__).resolve().parent / "static" / "fonts")
    fonts_filter = fonts_dir.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
    video_filter = ("scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
                    + f"ass='{subtitle_filter}':fontsdir='{fonts_filter}'")
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
            create_ass(words, highlight.start, highlight.end, subtitle_path,
                       stylish_captions=job.stylish_captions, varied_fonts=job.varied_fonts)
            render_clip(source, subtitle_path, highlight.start, job.clip_duration, output_dir / output_name)
            outputs.append(output_name)
        store.update(job_id, status="completed", progress=100, message=f"{len(outputs)} cortes prontos", outputs=outputs)
    except Exception as error:
        store.update(job_id, status="failed", message="O processamento falhou", error=str(error))
