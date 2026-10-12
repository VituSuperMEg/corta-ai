"""Retime de clipes: aceleração (speed ramp) e congelamento no ponto alto.

O FFmpeg renderiza em linha do tempo contínua; quando um trecho é acelerado ou
congelado, o vídeo encurta/alonga e as legendas (geradas em tempo de fonte)
precisam ser remapeadas para o novo instante de saída.
"""
from __future__ import annotations

from pathlib import Path

RAMP_SPEED = 1.5
RAMP_MIN_LEN = 1.0
RAMP_MAX_LEN = 2.5
FREEZE_LENGTH = 0.4
FREEZE_FRAME = 0.04


def pick_climax(duration: float, emphasis: list[float] | None = None,
                energy: list[float] | None = None, src_start: float = 0.0) -> float:
    """Instante do ponto alto (relativo ao corte): pico de energia, senão última ênfase."""
    low, high = 1.2, max(1.5, duration - 2.0)
    if high <= low:
        return max(0.4, duration / 2)
    if energy:
        best_index, best = None, -1.0
        for index in range(int(src_start + low), int(src_start + high) + 1):
            if 0 <= index < len(energy) and energy[index] > best:
                best_index, best = index, energy[index]
        if best_index is not None:
            return min(max(best_index - src_start, low), high)
    candidates = [time for time in (emphasis or []) if low <= time <= high]
    if candidates:
        return candidates[-1]
    return min(max(duration * .55, low), high)


def build_timeline(duration: float, *, climax: float, ramp: bool = False,
                   freeze: bool = False) -> dict | None:
    """Segmenta o clipe em pedaços normais/acelerados + congelamento, com offsets de saída."""
    if not ramp and not freeze:
        return None
    duration = float(duration)
    point = min(max(float(climax), 1.2), max(1.5, duration - 2.0))
    beats: list[dict] = []
    cursor = 0.0
    if freeze:
        beats.append({"kind": "clip", "a": 0.0, "b": point, "speed": 1.0})
        beats.append({"kind": "freeze", "at": point, "length": FREEZE_LENGTH})
        cursor = point
    if ramp:
        ramp_start = point + .6
        ramp_end = min(duration - 1.0, ramp_start + RAMP_MAX_LEN)
        if ramp_end - ramp_start >= RAMP_MIN_LEN:
            if ramp_start > cursor + .05:
                beats.append({"kind": "clip", "a": cursor, "b": ramp_start, "speed": 1.0})
            beats.append({"kind": "clip", "a": ramp_start, "b": ramp_end, "speed": RAMP_SPEED})
            cursor = ramp_end
    if cursor < duration - .05:
        beats.append({"kind": "clip", "a": cursor, "b": duration, "speed": 1.0})
    if not beats:
        beats.append({"kind": "clip", "a": 0.0, "b": duration, "speed": 1.0})
    out = 0.0
    for beat in beats:
        beat["out"] = out
        out += beat["length"] if beat["kind"] == "freeze" else (beat["b"] - beat["a"]) / beat["speed"]
    return {"duration": out, "src_duration": duration, "beats": beats, "climax": point}


def src_to_out(timeline: dict, time: float) -> float:
    """Mapeia um instante da fonte para a nova linha do tempo de saída."""
    beats = timeline["beats"]
    for index, beat in enumerate(beats):
        following = beats[index + 1] if index + 1 < len(beats) else None
        if beat["kind"] == "freeze":
            if time <= beat["at"]:
                return beat["out"]
            continue
        if time < beat["b"] - 1e-9 or following is None:
            return beat["out"] + (time - beat["a"]) / beat["speed"]
    return timeline["duration"]


def map_times(timeline: dict | None, times: list[float]) -> list[float]:
    if not timeline:
        return list(times)
    return [src_to_out(timeline, time) for time in times]


def _ass_time(seconds: float) -> str:
    value = max(0, round(seconds * 100))
    hours, value = divmod(value, 360000)
    minutes, value = divmod(value, 6000)
    seconds, fraction = divmod(value, 100)
    return f"{hours}:{minutes:02d}:{seconds:02d}.{fraction:02d}"


def _parse_ass_time(value: str) -> float:
    hours, minutes, rest = value.split(":")
    seconds, centis = rest.split(".")
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(centis) / 100


def retime_ass(path: Path, timeline: dict) -> None:
    """Reescreve os tempos do ASS gerado em tempo de fonte para o tempo de saída."""
    lines: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("Dialogue:"):
            parts = line.split(",", 8)
            if len(parts) == 9:
                parts[1] = _ass_time(src_to_out(timeline, _parse_ass_time(parts[1])))
                parts[2] = _ass_time(src_to_out(timeline, _parse_ass_time(parts[2])))
                line = ",".join(parts)
        lines.append(line)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def video_head_graph(timeline: dict) -> list[str]:
    """FFmpeg: quebra a fonte em segmentos, aplicando trim/setpts/concat (e o freeze)."""
    beats = timeline["beats"]
    # cada beat (clip ou freeze) consome um output do split
    graph = [f"[0:v:0]split={len(beats)}" + "".join(f"[vs{i}]" for i in range(len(beats)))]
    labels: list[str] = []
    source_index = 0
    for beat in beats:
        if beat["kind"] == "freeze":
            frames = max(2, round(beat["length"] * 30))
            graph.append(
                f"[vs{source_index}]trim=start={beat['at']:.3f}:end={beat['at'] + FREEZE_FRAME:.3f},setpts=PTS-STARTPTS,"
                f"loop=size=1:loop={frames - 1},setpts=N/30/TB,"
                "scale=1166:2074:force_original_aspect_ratio=increase,crop=1080:1920,"
                f"format=yuv420p,setsar=1,fps=30[vfrz]")
            labels.append("[vfrz]")
            source_index += 1
            continue
        speed = beat["speed"]
        setpts = "setpts=PTS-STARTPTS" if speed == 1.0 else f"setpts=(PTS-STARTPTS)/{speed}"
        graph.append(
            f"[vs{source_index}]trim=start={beat['a']:.3f}:end={beat['b']:.3f},{setpts},"
            "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
            f"format=yuv420p,setsar=1,fps=30[v{source_index}]")
        labels.append(f"[v{source_index}]")
        source_index += 1
    graph.append("".join(labels) + f"concat=n={len(labels)}:v=1:a=0[vcat]")
    return graph


def audio_head_graph(timeline: dict) -> list[str]:
    """Mesma segmentação no áudio: voz alinhada à nova linha do tempo (freeze vira silêncio)."""
    beats = timeline["beats"]
    sources = [beat for beat in beats if beat["kind"] == "clip"]
    graph = [f"[0:a:0]asplit={len(sources)}" + "".join(f"[as{i}]" for i in range(len(sources)))]
    labels: list[str] = []
    source_index = 0
    for beat in beats:
        if beat["kind"] == "freeze":
            graph.append(f"anullsrc=r=48000:cl=stereo,atrim=duration={beat['length']:.3f},"
                         "aformat=sample_fmts=fltp:channel_layouts=stereo[afrz]")
            labels.append("[afrz]")
            continue
        speed = beat["speed"]
        tempo = "" if speed == 1.0 else f",atempo={speed}"
        graph.append(
            f"[as{source_index}]atrim=start={beat['a']:.3f}:end={beat['b']:.3f},asetpts=PTS-STARTPTS"
            f"{tempo},aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[a{source_index}]")
        labels.append(f"[a{source_index}]")
        source_index += 1
    graph.append("".join(labels) + f"concat=n={len(labels)}:v=0:a=1[acat]")
    return graph
