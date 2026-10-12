from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

from .highlights import TranscriptSegment, choose_highlights
from .jobs import InMemoryJobStore
from .director import MOODS, plan_clip
from .library import resolve_music
from .timeline import (audio_head_graph, build_timeline, map_times, pick_climax, retime_ass,
                       src_to_out, video_head_graph)
from .effects import (append_director_overlays, append_overlays, censor_word, create_accent_audio, create_beep_audio,
                      create_music_audio, create_sfx_audio, emphasis_times, flash_filter, keyword_index, opening_text,
                      shake_filter, suggest_metadata, word_emoji, zoom_filter)


def _run(command: list[str], error_message: str) -> str:
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        detail = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else error_message
        raise RuntimeError(f"{error_message}: {detail}")
    return result.stdout.strip()


def download_video(url: str, job_dir: Path) -> Path:
    source_dir = job_dir / "source"
    source_dir.mkdir(parents=True, exist_ok=True)
    # YouTube pode exigir login ("Sign in to confirm you're not a bot").
    # CORTA_AI_COOKIES_BROWSER=firefox|chrome  ou  CORTA_AI_COOKIES=/caminho/cookies.txt
    cookie_args: list[str] = []
    if browser := os.environ.get("CORTA_AI_COOKIES_BROWSER"):
        cookie_args = ["--cookies-from-browser", browser]
    elif cookies := os.environ.get("CORTA_AI_COOKIES"):
        cookie_args = ["--cookies", cookies]
    # yt-dlp precisa de runtime JS pro "n challenge"; nvm não fica no PATH do uvicorn.
    if node := (shutil.which("node") or next(iter(sorted(Path.home().glob(".nvm/versions/node/*/bin/node"))), None)):
        cookie_args += ["--js-runtimes", f"node:{node}"]
    output = _run(
        [sys.executable, "-m", "yt_dlp", "--no-playlist", "--restrict-filenames", "--merge-output-format", "mp4",
         "-f", "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/best", "--print", "after_move:filepath",
         *cookie_args, "-o", str(source_dir / "video.%(ext)s"), url],
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
    # medium = bem mais preciso em pt-BR que small; large-v3 via WHISPER_MODEL se sobrar CPU.
    model = WhisperModel(os.environ.get("WHISPER_MODEL", "medium"), device="cpu", compute_type="int8",
                         cpu_threads=int(os.environ.get("CPU_THREADS", max(2, (os.cpu_count() or 4) // 2))))
    raw_segments, _ = model.transcribe(
        str(path), language="pt", vad_filter=True, word_timestamps=True, beam_size=5,
        # Prompt em pt-BR ancora acentuação, pontuação e vocabulário informal do Brasil.
        initial_prompt="Olá, pessoal! Hoje a gente vai conversar sobre isso, tá? Então, vamos lá.",
        hallucination_silence_threshold=2.0,
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


def audio_energy(path: Path) -> list[float]:
    """RMS por segundo do áudio, pra ranquear trechos empolgados."""
    result = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", "8000", "-f", "s16le", "-"],
        capture_output=True, check=False)
    from array import array
    samples = array("h"); samples.frombytes(result.stdout[: len(result.stdout) // 2 * 2])
    return [math.sqrt(sum(x * x for x in samples[i:i + 8000]) / 8000) for i in range(0, len(samples), 8000)]


CAPTION_Y = {"top": 380, "center": 1000, "bottom": 1690}
# "Legendas não fixas": cada frase pula pra um ponto diferente da tela com leve inclinação.
FLOAT_SPOTS = ((540, 1690, -3), (540, 1000, 2), (540, 380, -2), (430, 1320, 4), (650, 700, -4), (540, 1500, 3))


def _float_tag(index: int) -> str:
    x, y, angle = FLOAT_SPOTS[index % len(FLOAT_SPOTS)]
    return f"\\an5\\pos({x},{y})\\frz{angle}"


def _word_text(word: dict, font: str = "Arial") -> str:
    text = _ass_text(word["text"]).upper()
    if word.get("emoji"):
        text += f" {{\\fnNoto Emoji}}{word['emoji']}{{\\fn{font}}}"
    return text


def prepare_words(words: list[dict], *, emoji: bool = False, censor: bool = False) -> list[dict]:
    """Copia as palavras aplicando emoji/censura sem tocar na transcrição original."""
    prepared = []
    for word in words:
        item = dict(word)
        if censor and (masked := censor_word(item["text"])):
            item["text"], item["censored"] = masked, True
        if emoji:
            item["emoji"] = word_emoji(word["text"])
        prepared.append(item)
    return prepared


def _ass_time(seconds: float) -> str:
    value = max(0, round(seconds * 100))
    hours, value = divmod(value, 360000)
    minutes, value = divmod(value, 6000)
    seconds, fraction = divmod(value, 100)
    return f"{hours}:{minutes:02d}:{seconds:02d}.{fraction:02d}"


def _ass_text(value: str) -> str:
    return re.sub(r"[{}]", "", value).replace("\\", "")


def _stylish_events(words: list[dict], clip_start: float, clip_end: float, varied_fonts: bool = False,
                    y: int = 1690, floating: bool = False, theme: tuple[str, str] | None = None,
                    highlight: bool = False) -> list[str]:
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
            font, font_size, weight = (theme[0] if theme else "Arial"), 100 if variant == 2 else 76, 700
        typography = f"\\fn{font}\\b{weight}"
        color = theme[1] if theme else ("&H003EFFD8&", "&H00FFDD55&", "&H008B79FF&")[variant]
        position = _float_tag(group_index) if floating else f"\\an2\\pos(540,{y})"
        keyword = keyword_index(group) if highlight else None
        for index, word in enumerate(group):
            start = max(clip_start, word["start"])
            end = min(clip_end, word["end"])
            if index + 1 < len(group):
                end = min(end, group[index + 1]["start"])
            if round((end - clip_start) * 100) <= round((start - clip_start) * 100):
                continue
            duration_ms = max(1, round((end - start) * 1000))
            settle = min(110, duration_ms)
            text = _word_text(word, font)
            if variant == 2:
                size = min(font_size, int(850 / max(1, len(_ass_text(word["text"]))) / 0.75))
                punch = "\\1c&H0000FFFF&\\bord10" if index == keyword else ""
                body = (f"{{{typography}{position}\\fs{size}\\1c{color}\\bord8{punch}"
                        f"\\fscx115\\fscy115\\t(0,{settle},\\fscx100\\fscy100)}}{text}")
            else:
                # Keep a fixed phrase layout while only the spoken word changes color.
                phrase_parts = []
                for i, item in enumerate(group):
                    overrides = f"\\1c{color if i == index else '&H00FFFFFF&'}"
                    if i == keyword:
                        overrides += "\\1c&H0000FFFF&\\bord9"  # palavra-chave vence o \1c anterior
                    elif keyword is not None and i == keyword + 1:
                        overrides += "\\bord6"  # devolve o contorno ao normal
                    phrase_parts.append(f"{{{overrides}}}{_word_text(item, font)}")
                phrase = " ".join(phrase_parts)
                if variant == 0:
                    animation = f"\\fscx94\\fscy94\\t(0,{settle},\\fscx100\\fscy100)"
                else:
                    animation = f"\\blur1\\shad3\\4c{color}"
                body = f"{{{typography}{position}\\fs{font_size}\\bord6{animation}}}{phrase}"
            lines.append(f"Dialogue: 0,{_ass_time(start - clip_start)},{_ass_time(end - clip_start)},Default,,0,0,0,,{body}")
    return lines


def create_ass(words: list[dict], clip_start: float, clip_end: float, destination: Path,
               stylish_captions: bool = False, varied_fonts: bool = False,
               caption_position: str = "bottom", floating_captions: bool = False,
               theme: tuple[str, str] | None = None, keyword_highlight: bool = False) -> None:
    visible = [word for word in words if word["end"] > clip_start and word["start"] < clip_end]
    y = CAPTION_Y.get(caption_position, CAPTION_Y["bottom"])
    alignment, margin_v = {"top": (8, 300), "center": (5, 0)}.get(caption_position, (2, 230))
    style_font, style_color = theme or ("Arial", "&H00FFFFFF&")
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{style_font},72,{style_color.rstrip("&")},&H0000E8FF,&H00101010,&H70000000,-1,0,0,0,100,100,0,0,1,7,2,{alignment},70,70,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines: list[str] = []
    if stylish_captions:
        lines = _stylish_events(visible, clip_start, clip_end, varied_fonts, y, floating_captions, theme,
                                highlight=keyword_highlight)
        destination.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")
        return
    for offset in range(0, len(visible), 5):
        group = visible[offset:offset + 5]
        start = max(0, group[0]["start"] - clip_start)
        end = min(clip_end - clip_start, group[-1]["end"] - clip_start + 0.12)
        karaoke_parts: list[str] = []
        font = (("Poppins ExtraBold", "Barlow Condensed ExtraBold", "Bebas Neue")[(offset // 5) % 3]
                if varied_fonts else "Arial")
        keyword = keyword_index(group) if keyword_highlight else None
        for index, word in enumerate(group):
            next_start = group[index + 1]["start"] if index + 1 < len(group) else word["end"]
            visible_start = max(word["start"], clip_start)
            highlight_duration = max(word["end"], next_start) - visible_start
            overrides = f"\\kf{max(1, round(highlight_duration * 100))}"
            if index == keyword:
                overrides += "\\1c&H0000FFFF&\\bord9"
            elif keyword is not None and index == keyword + 1:
                overrides += f"\\1c{style_color}\\bord7"  # devolve estilo base após a palavra-chave
            karaoke_parts.append(f"{{{overrides}}}{_word_text(word, font)}")
        karaoke = " ".join(karaoke_parts)
        if varied_fonts:
            font, weight = (("Poppins ExtraBold", 800), ("Barlow Condensed ExtraBold", 800),
                            ("Bebas Neue", 400))[(offset // 5) % 3]
            karaoke = f"{{\\fn{font}\\b{weight}}}" + karaoke
        if floating_captions:
            karaoke = f"{{{_float_tag(offset // 5)}}}" + karaoke
        lines.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Default,,0,0,0,,{karaoke}")
    destination.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")


def camera_cuts(segments: list[TranscriptSegment], words: list[dict], start: float, end: float) -> list[float]:
    """Instantes (relativos ao corte) pra alternar o enquadramento: início de frase ou pausa > 0.7s."""
    points = [s.start for s in segments if start + 1 < s.start < end - 1]
    previous = None
    for word in words:
        if previous and word["start"] - previous["end"] > .7 and start + 1 < word["start"] < end - 1:
            points.append(word["start"])
        previous = word
    cuts: list[float] = []
    for point in sorted(points):
        if not cuts or point - start - cuts[-1] >= 1.5:
            cuts.append(round(point - start, 3))
    return cuts


def render_clip(source: Path, subtitles: Path, start: float, duration: int, output: Path,
                *, smooth_zoom: bool = False, sound_effects: bool = False,
                emphasis: list[float] | None = None, cuts: list[float] | None = None,
                beeps: list[tuple[float, float]] | None = None, music: bool = False,
                zoom: list[float] | None = None, shake: list[float] | None = None,
                flash: list[float] | None = None, hook_fx: bool = False,
                vignette: bool = False, sfx_events: list[tuple[float, str]] | None = None,
                music_file: str = "", music_volume: float = 0.35,
                timeline: dict | None = None) -> None:
    subtitle_filter = str(subtitles).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
    fonts_dir = str(Path(__file__).resolve().parent / "static" / "fonts")
    fonts_filter = fonts_dir.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
    filters: list[str] = []
    if not timeline:
        filters += ["scale=1080:1920:force_original_aspect_ratio=increase", "crop=1080:1920"]
    zoom_times = sorted(set((emphasis if smooth_zoom else []) + (zoom or [])))
    if zoom_times or cuts or hook_fx:
        filters.append(zoom_filter(zoom_times, cuts, hook=hook_fx))
    if shake or hook_fx:
        # Overscan garante margem pro tremor; os offsets 32/58 são o centro do 1144x2036.
        filters.append("scale=1144:2036")
        filters.append(shake_filter(shake or [], hook=hook_fx))
    windows = [(0.55, 0.63), (0.95, 1.03)] if hook_fx else []
    windows += [(time, time + .09) for time in (flash or [])]
    if windows:
        filters.append(flash_filter(windows))
    if vignette:
        filters.append("vignette=angle=PI/5,noise=alls=5:allf=t")
    filters.append(f"ass='{subtitle_filter}':fontsdir='{fonts_filter}'")
    # Entrada suave e saída escurecendo/abaixando a voz nos últimos 1.5s.
    fade_out = max(0, duration - 1.5)
    filters.append(f"fade=t=in:st=0:d=0.5,fade=t=out:st={fade_out}:d=1.5")
    video_filter = ",".join(filters)
    command = ["ffmpeg", "-y", "-ss", f"{start:.3f}", "-i", str(source)]
    normalization = "loudnorm=I=-14:TP=-1.5:LRA=11"
    audio_fade = f"afade=t=in:st=0:d=0.5,afade=t=out:st={fade_out}:d=1.5"
    voice = normalization
    if beeps:  # silencia a voz nos palavrões; o bipe entra como faixa extra
        voice += ",volume=0:enable='" + "+".join(f"between(t,{a:.3f},{b:.3f})" for a, b in beeps) + "'"
    extras: list[Path] = []
    if sound_effects and emphasis:
        extras.append(subtitles.with_suffix(".accents.wav"))
        create_accent_audio(extras[-1], duration, emphasis)
    if beeps:
        extras.append(subtitles.with_suffix(".beeps.wav"))
        create_beep_audio(extras[-1], duration, beeps)
    if sfx_events:
        extras.append(subtitles.with_suffix(".sfx.wav"))
        create_sfx_audio(extras[-1], duration, sfx_events)
    if music:
        if music_file:  # faixa do usuário (ex.: NCS em assets/music) no lugar do sintetizado
            extras.append(Path(music_file))
        else:
            extras.append(subtitles.with_suffix(".music.wav"))
            create_music_audio(extras[-1], duration)
    if extras or timeline:
        graph: list[str] = []
        if timeline:
            graph += video_head_graph(timeline)
            graph += audio_head_graph(timeline)
            video_source, audio_source = "[vcat]", "[acat]"
        else:
            video_source, audio_source = "[0:v:0]", "[0:a:0]"
        graph.append(f"{video_source}{video_filter}[video]")
        graph.append(f"{audio_source}{voice}[voice]")
        mix = ["[voice]"]
        for index, extra in enumerate(extras, start=1):
            command += ["-i", str(extra)]
            label = f"[{index}:a:0]"
            if music and extra == extras[-1]:  # ducking: música abaixa quando a voz entra
                graph[-1] = graph[-1].replace("[voice]", "[voice_src]")
                graph.append("[voice_src]asplit[voice][sidechain]")
                graph.append(f"{label}volume={music_volume:.2f}[music_in];[music_in][sidechain]"
                             "sidechaincompress=threshold=0.03:ratio=8:attack=40:release=500[music]")
                label = "[music]"
            mix.append(label)
        if extras:
            graph.append("".join(mix) + f"amix=inputs={len(mix)}:duration=first:normalize=0,"
                         f"alimiter=limit=0.95:level=false,{audio_fade}[audio]")
        else:
            graph.append(f"[voice]{audio_fade}[audio]")
        command += ["-filter_complex", ";".join(graph), "-map", "[video]", "-map", "[audio]"]
    else:
        command += ["-vf", video_filter, "-af", f"{voice},{audio_fade}",
                    "-map", "0:v:0", "-map", "0:a:0?"]
    command += ["-t", str(duration), "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-pix_fmt", "yuv420p", str(output)]
    _run(command, f"Não foi possível renderizar {output.name}")


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
        energy = audio_energy(source) if job.energy_score else None
        highlights = choose_highlights(segments, job.clip_count, job.clip_duration, duration,
                                       hook_start=job.hook_start, energy=energy)
        words = prepare_words(words, emoji=job.caption_emoji, censor=job.censor)
        outputs: list[str] = []
        metadata: list[dict] = []
        plans: list[dict] = []
        for index, highlight in enumerate(highlights, start=1):
            progress(55 + round((index - 1) / len(highlights) * 40), f"Renderizando corte {index} de {len(highlights)}")
            subtitle_path = job_dir / f"legenda-{index:02d}.ass"
            output_name = f"corte-{index:02d}.mp4"
            plan: dict = {}
            if job.director != "off":
                progress(55 + round((index - 1) / len(highlights) * 40), f"IA analisando corte {index} de {len(highlights)}")
                plan = plan_clip(job.director, words, highlight.start, highlight.end)
                plans.append(plan)
            create_ass(words, highlight.start, highlight.end, subtitle_path,
                       stylish_captions=job.stylish_captions, varied_fonts=job.varied_fonts,
                       caption_position=job.caption_position, floating_captions=job.floating_captions,
                       theme=MOODS[plan["mood"]] if plan else None,
                       keyword_highlight=job.fx_keyword)
            music_path = resolve_music(job.music_track) if job.background_music and job.music_track else None
            credit = music_path.name if job.ncs_credit and music_path else ""
            append_overlays(subtitle_path, highlight.duration, progress_bar=job.clip_progress,
                            title=opening_text(words, highlight.start, highlight.end,
                                               job.title_text or plan.get("hook", ""))
                            if job.opening_title else "", end_cta=job.end_cta, credit=credit)
            if plan:
                append_director_overlays(subtitle_path, plan, highlight.duration)
            emphasis = emphasis_times(words, highlight.start, highlight.end) if job.smooth_zoom or job.sound_effects or job.fx_shake or job.speed_ramp or job.freeze_climax else []
            cut_points = camera_cuts(segments, words, highlight.start, highlight.end) if (
                job.camera_cuts or job.sfx_whoosh or job.fx_flash) else []
            zoom_plan: list[float] = list(plan.get("zoom", []))
            timeline: dict | None = None
            out_duration = job.clip_duration
            if job.speed_ramp or job.freeze_climax:
                climax = pick_climax(highlight.duration, emphasis, energy, highlight.start)
                timeline = build_timeline(highlight.duration, climax=climax,
                                          ramp=job.speed_ramp, freeze=job.freeze_climax)
            if timeline:
                # Rampa/freeze alteram a linha do tempo: legendas e efeitos passam a sair em outro instante.
                retime_ass(subtitle_path, timeline)
                emphasis = map_times(timeline, emphasis)
                cut_points = map_times(timeline, cut_points)
                zoom_plan = map_times(timeline, zoom_plan)
                out_duration = timeline["duration"]
            sfx_events: list[tuple[float, str]] = []
            if job.sfx_hook:
                sfx_events.append((0.0, "impact"))
            if job.sfx_whoosh:
                sfx_events += [(time, "whoosh") for time in cut_points]
            if job.sfx_riser:
                sfx_events.append((max(0.0, out_duration - 1.8), "riser"))
            beeps = [(src_to_out(timeline, w["start"] - highlight.start) if timeline else w["start"] - highlight.start,
                      src_to_out(timeline, w["end"] - highlight.start) if timeline else w["end"] - highlight.start)
                     for w in words
                     if w.get("censored") and highlight.start <= w["start"] < highlight.end]
            render_clip(source, subtitle_path, highlight.start, out_duration, output_dir / output_name,
                        smooth_zoom=job.smooth_zoom, sound_effects=job.sound_effects, emphasis=emphasis,
                        cuts=cut_points if job.camera_cuts else [], beeps=beeps,
                        music=job.background_music, zoom=zoom_plan,
                        shake=emphasis if job.fx_shake else [], flash=cut_points if job.fx_flash else [],
                        hook_fx=job.fx_hook, vignette=job.fx_vignette, sfx_events=sfx_events,
                        music_file=str(music_path) if music_path else "",
                        music_volume=job.music_volume / 100, timeline=timeline)
            outputs.append(output_name)
            if job.suggestions:
                metadata.append(suggest_metadata(words, highlight.start, highlight.end,
                                                 job.title_text if job.opening_title else "", credit=credit))
        store.update(job_id, status="completed", progress=100, message=f"{len(outputs)} cortes prontos",
                     outputs=outputs, metadata=metadata, ai_plans=plans)
    except Exception as error:
        store.update(job_id, status="failed", message="O processamento falhou", error=str(error))
