"""Optional clip effects, driven by the user's individual selections."""
from __future__ import annotations

from array import array
import math
from pathlib import Path
import random
import re
import subprocess
import sys
import textwrap
import unicodedata
import wave

from .library import resolve_sfx


def emphasis_times(words: list[dict], start: float, end: float) -> list[float]:
    """Use exclamations, emphasis words and speech after a pause as modest cues."""
    keywords = {"olha", "uau", "incrivel", "surpresa", "cuidado", "agora", "atencao", "nossa"}
    candidates = []
    previous_end = start
    for word in words:
        if word["start"] < start or word["start"] >= end or word["end"] <= word["start"]:
            continue
        normalized = unicodedata.normalize("NFKD", word["text"].lower())
        normalized = re.sub(r"[^a-z]", "", normalized)
        score = 3 * ("!" in word["text"]) + 2 * (normalized in keywords)
        score += word["start"] - previous_end >= .6
        if score:
            candidates.append((score, word["start"] - start))
        previous_end = word["end"]
    selected: list[float] = []
    limit = min(8, max(1, math.ceil((end - start) / 8)))
    for _, time in sorted(candidates, key=lambda item: (-item[0], item[1])):
        if all(abs(time - other) >= 4 for other in selected):
            selected.append(time)
            if len(selected) == limit:
                break
    if not selected:
        step = max(6.0, (end - start) / 3)
        selected = [t for t in (step * i for i in range(1, 4)) if t < end - start - 2]
    return sorted(selected)


def opening_text(words: list[dict], start: float, end: float, custom: str = "") -> str:
    if custom.strip():
        return custom.strip()[:60]
    tokens = [word["text"].strip() for word in words
              if word["end"] > start and word["start"] < end and word["text"].strip()]
    return " ".join(tokens[:7])[:60] or "Confira este momento"


def append_overlays(path: Path, duration: float, *, progress_bar: bool = False,
                    title: str = "", end_cta: bool = False, credit: str = "") -> None:
    # Import here to keep subtitle escaping and timestamps identical to captions.
    from .pipeline import _ass_text, _ass_time

    lines = []
    end = _ass_time(duration)
    if credit:
        # Crédito NCS no topo, para não brigar com legenda nem com a chamada final.
        lines.append(f"Dialogue: 3,{_ass_time(max(0, duration - 2.5))},{end},Default,,0,0,0,,"
                     r"{\an8\pos(540,64)\fnArial\b700\fs32\bord4\shad1\fad(200,0)\1c&H00C8D2E8&}"
                     + _ass_text(f"Música: {credit} · NoCopyrightSounds"))
    if progress_bar:
        drawing = r"\p1}m 0 0 l 1080 0 l 1080 8 l 0 8{\p0}"
        base = r"\an7\pos(0,0)\bord0\shad0"
        lines.append(f"Dialogue: 2,0:00:00.00,{end},Default,,0,0,0,,{{{base}\\1c&H00443A30&{drawing}")
        lines.append(f"Dialogue: 3,0:00:00.00,{end},Default,,0,0,0,,{{{base}"
                     f"\\1c&H003EFFD8&\\fscx0\\t(0,{round(duration * 1000)},\\fscx100){drawing}")
    if title:
        clean = _ass_text(" ".join(title.split())).upper()
        wrapped = r"\N".join(textwrap.wrap(clean, width=24))
        lines.append(f"Dialogue: 4,0:00:00.00,{_ass_time(min(3, duration))},Default,,0,0,0,,"
                     r"{\an8\pos(540,220)\fnArial\b700\fs62\bord5\shad2\fad(180,250)}" + wrapped)
    if end_cta and duration > 6:
        # Chamada nos últimos 4s, antes do fade escurecer tudo.
        lines.append(f"Dialogue: 4,{_ass_time(duration - 4)},{end},Default,,0,0,0,,"
                     r"{\an5\pos(540,1480)\fnArial\b700\fs54\bord5\shad2\fad(250,0)\1c&H0055DDFF&}"
                     r"SEGUE PRA VER MAIS ▶")
    if lines:
        with path.open("a", encoding="utf-8") as file:
            file.write("\n".join(lines) + "\n")


def zoom_filter(times: list[float], cuts: list[float] | None = None, hook: bool = False) -> str:
    # One input frame per output frame at 30 fps; subtitles are applied afterwards.
    pulses = [f"if(between(on/30,{time:.3f},{time + 1.4:.3f}),"
              f"0.08*pow(sin(PI*(on/30-{time:.3f})/1.4),2),0)" for time in times]
    if cuts:  # "duas câmeras": alterna 100%/115% com corte seco a cada frase
        pulses.insert(0, "0.15*mod(" + "+".join(f"gte(on/30,{cut:.3f})" for cut in cuts) + ",2)")
    if hook:  # "Gancho explosivo": punho de 10% que volta ao normal em 1.5 s
        pulses.append("if(between(on/30,0,1.5),0.10*pow(cos(PI*(on/30)/3),2),0)")
    zoom = "1+" + "+".join(pulses) if pulses else "1"
    return f"fps=30,zoompan=z='{zoom}':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d=1:s=1080x1920:fps=30"


def shake_filter(times: list[float], hook: bool = False) -> str:
    """Crop com oscilação amortecida; exige overscan (scale 1144x2036) antes."""
    windows = []
    if hook:
        windows.append("if(lt(t,1.5),1-t/1.5,0)")
    for time in times:
        windows.append(f"if(between(t,{time:.3f},{time + .45:.3f}),1-(t-{time:.3f})/0.45,0)")
    amplitude = "+".join(windows) or "0"
    move = (f"({amplitude})*(14*sin(2*PI*6.5*t)+9*sin(2*PI*3.7*t+1))")
    drift = f"({amplitude})*12*sin(2*PI*5.3*t+0.6)"
    return (f"crop=w=1080:h=1920:x='32+min(24,max(-24,{move}))':"
            f"y='58+min(50,max(-50,{drift}))'")


def flash_filter(windows: list[tuple[float, float]]) -> str:
    """Piscada branca curta em cada janela (brilho salta e volta)."""
    expression = "+".join(f"between(t,{start:.3f},{end:.3f})" for start, end in windows)
    return f"eq=brightness=0.45:enable='{expression}'"


def create_accent_audio(path: Path, duration: float, times: list[float]) -> None:
    """Generate short, quiet percussive accents locally, with no downloaded audio."""
    rate = 24000
    samples = array("h", [0]) * math.ceil(duration * rate)
    for time in times:
        offset = round(time * rate)
        for index in range(min(round(.25 * rate), len(samples) - offset)):
            t = index / rate
            envelope = min(1, t / .004) * math.exp(-16 * t)
            value = .32 * envelope * (math.sin(2 * math.pi * (520 * t - 900 * t * t))
                                      + .5 * math.sin(2 * math.pi * 1040 * t))
            samples[offset + index] = round(value * 32767)
    if sys.byteorder != "little":
        samples.byteswap()
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(rate)
        audio.writeframes(samples.tobytes())


# ---- Biblioteca de SFX: arquivo do usuário em assets/sfx/<tipo>/ ou síntese local ----
SFX_GAINS = {"impact": .9, "whoosh": .6, "riser": .55}


def _synth_sfx(kind: str, rate: int = 24000) -> array:
    """Sons curtos determinísticos: batida grave, vento e subida de tensão."""
    length = {"impact": .7, "whoosh": .55}.get(kind, 1.8)
    total = math.ceil(length * rate)
    samples = array("h", [0]) * total
    noise = random.Random(1234)
    phase = 0.0
    lowpass = 0.0
    for index in range(total):
        t = index / rate
        if kind == "impact":
            envelope = min(1, t / .003) * math.exp(-7 * t)
            value = .85 * envelope * math.sin(2 * math.pi * (150 * t - 85 * t * t))
            value += .3 * envelope * noise.uniform(-1, 1) * math.exp(-40 * t)
        elif kind == "whoosh":
            envelope = math.sin(math.pi * t / length) ** 2
            lowpass += .3 * (noise.uniform(-1, 1) - lowpass)
            value = envelope * (1.4 * lowpass
                                + .3 * math.sin(2 * math.pi * (300 + 700 * t / length) * t))
        else:  # riser
            envelope = (t / length) ** 1.6
            frequency = 180 * (1000 / 180) ** (t / length)
            phase += 2 * math.pi * frequency / rate
            value = envelope * (.5 * math.sin(phase) + .3 * noise.uniform(-1, 1) * (t / length))
        samples[index] = round(32767 * max(-.95, min(.95, value)))
    return samples


def _load_sfx(path: Path, rate: int = 24000) -> array | None:
    """Lê WAV 24 kHz mono direto; outros formatos passam pelo FFmpeg."""
    try:
        with wave.open(str(path)) as audio:
            if audio.getsampwidth() == 2 and audio.getframerate() == rate and audio.getnchannels() == 1:
                return array("h", audio.readframes(audio.getnframes()))
    except (wave.Error, EOFError):
        pass
    result = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(rate),
                             "-f", "s16le", "-"], capture_output=True, check=False)
    if result.returncode != 0 or not result.stdout:
        return None
    payload = result.stdout[: len(result.stdout) // 2 * 2]
    samples = array("h")
    samples.frombytes(payload)
    return samples


def create_sfx_audio(path: Path, duration: float, events: list[tuple[float, str]]) -> None:
    """Uma única trilha de SFX com eventos posicionados no tempo do corte."""
    rate = 24000
    total = math.ceil(duration * rate)
    samples = array("h", [0]) * total
    cache: dict[str, array] = {}
    for time, kind in events:
        base = cache.get(kind)
        if base is None:
            asset = resolve_sfx(kind)
            base = (_load_sfx(asset) if asset else None) or _synth_sfx(kind)
            cache[kind] = base
        gain = SFX_GAINS.get(kind, .7)
        offset = round(max(0.0, time) * rate)
        for index, value in enumerate(base):
            position = offset + index
            if position >= total:
                break
            samples[position] = round(max(-32767, min(32767, samples[position] + value * gain)))
    _write_wave(path, samples, rate)


# ---- Emojis por contexto (fonte Noto Emoji mono, colorida via \1c) ----
EMOJI_KEYWORDS = {
    "dinheiro": "💰", "grana": "💰", "real": "💰", "reais": "💰", "lucro": "💰", "caro": "💸",
    "cuidado": "⚠️", "perigo": "⚠️", "erro": "❌", "errado": "❌", "nunca": "🚫",
    "incrivel": "🔥", "demais": "🔥", "top": "🔥", "melhor": "🏆", "ganhou": "🏆",
    "amor": "❤️", "coracao": "❤️", "medo": "😱", "susto": "😱", "rir": "😂", "engracado": "😂",
    "tempo": "⏰", "rapido": "⚡", "segredo": "🤫", "ideia": "💡", "dica": "💡",
    "comida": "🍔", "musica": "🎵", "jogo": "🎮", "carro": "🚗", "casa": "🏠", "trabalho": "💼",
}


def _plain(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return re.sub(r"[^a-z]", "", text)


def word_emoji(word: str) -> str:
    """Emoji para uma palavra: por pontuação final ou por palavra-chave."""
    stripped = word.strip()
    if stripped.endswith("?"):
        return "🤔"
    if stripped.endswith("!"):
        return "🔥"
    return EMOJI_KEYWORDS.get(_plain(stripped), "")


def keyword_index(group: list[dict]) -> int | None:
    """Índice da palavra de destaque: termo de emoji primeiro, senão a mais longa."""
    plain = [_plain(word["text"]) for word in group]
    for index, key in enumerate(plain):
        if key in EMOJI_KEYWORDS:
            return index
    longest: int | None = None
    for index, key in enumerate(plain):
        if len(key) >= 6 and (longest is None or len(key) > len(plain[longest])):
            longest = index
    return longest


# ---- Censura leve pt-BR ----
_CENSOR = re.compile(r"^(porra|caralho|merda|puta|puto|foda|fuder|fodase|buceta|cu|viado|cacete|desgraca|bosta|arrombado|pau|piroca)s?$")


def censor_word(word: str) -> str | None:
    """Retorna a palavra mascarada se for palavrão, senão None."""
    core = re.sub(r"[^\w]", "", word, flags=re.UNICODE)
    if core and _CENSOR.match(_plain(core)):
        return word.replace(core, core[0] + "*" * (len(core) - 1))
    return None


def _write_wave(path: Path, samples: "array", rate: int) -> None:
    if sys.byteorder != "little":
        samples.byteswap()
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(rate)
        audio.writeframes(samples.tobytes())


def create_beep_audio(path: Path, duration: float, intervals: list[tuple[float, float]]) -> None:
    """Bipe de 1 kHz cobrindo cada intervalo censurado."""
    rate = 24000
    samples = array("h", [0]) * math.ceil(duration * rate)
    for start, end in intervals:
        for index in range(max(0, round(start * rate)), min(len(samples), round(end * rate))):
            samples[index] = round(.35 * 32767 * math.sin(2 * math.pi * 1000 * index / rate))
    _write_wave(path, samples, rate)


def create_music_audio(path: Path, duration: float) -> None:
    """Pad lo-fi gerado localmente: Am-F-C-G a 72 bpm com kick suave. Sem download."""
    rate = 24000
    beat = 60 / 72
    chords = ([220.0, 261.63, 329.63], [174.61, 220.0, 261.63], [130.81, 164.81, 196.0], [196.0, 246.94, 293.66])
    samples = array("h", [0]) * math.ceil(duration * rate)
    chord_len = 4 * beat
    for index in range(len(samples)):
        t = index / rate
        chord = chords[int(t // chord_len) % 4]
        phase = (t % chord_len) / chord_len
        envelope = min(1, phase * 6) * (1 - .35 * phase)
        pad = sum(math.sin(2 * math.pi * f * t) + .3 * math.sin(2 * math.pi * 2 * f * t) for f in chord) / len(chord)
        kick_t = t % beat
        kick = math.exp(-28 * kick_t) * math.sin(2 * math.pi * (60 + 80 * math.exp(-40 * kick_t)) * kick_t)
        samples[index] = round(32767 * min(.95, max(-.95, .16 * envelope * pad + .22 * kick)))
    _write_wave(path, samples, rate)


# ---- Título, descrição e hashtags ----
_STOP = set("""a o os as um uma de do da dos das em no na nos nas por para pra com sem que e ou mas se não nao sim
eu tu ele ela nós nos vocês voce você eles elas meu minha seu sua isso isto aqui ali lá la então entao muito
mais menos bem mal tá ta tão tao já ja só so como quando onde porque por que assim tipo gente coisa coisas
foi ser ter está esta estão estao vai vou era são sao tem têm tinha fazer fez faz pode ainda também tambem
agora hoje depois antes sempre nunca cada todo toda todos todas outro outra esse essa este esta aquele aquela
ele ela dele dela né ne aí ai ok tá bom boa ali lá""".split())


def suggest_metadata(words: list[dict], start: float, end: float, title: str = "", credit: str = "") -> dict:
    text = " ".join(w["text"].strip() for w in words if w["end"] > start and w["start"] < end and w["text"].strip())
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    hook = next((s for s in sentences if "?" in s or re.search(r"\d", s)), sentences[0] if sentences else "")
    title = (title.strip() or hook or text)[:60].rstrip(" ,.;:")
    description = ""
    for sentence in sentences:
        if len(description) + len(sentence) > 170:
            break
        description = f"{description} {sentence}".strip()
    counts: dict[str, int] = {}
    for token in re.findall(r"\w+", text, flags=re.UNICODE):
        key = _plain(token)
        if len(key) >= 5 and token.lower() not in _STOP and not token.isdigit():
            counts[key] = counts.get(key, 0) + 1
    tags = [f"#{k}" for k, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:4]]
    description = (description or text[:170]).strip()
    if credit:
        description = f"{description}\n\nMúsica: {credit} · NoCopyrightSounds"
    return {"title": title, "description": description,
            "hashtags": " ".join(tags + ["#shorts", "#cortes", "#viral"])}


# ---- Edição guiada por IA: sobreposições do plano ----
def append_director_overlays(path: Path, plan: dict, duration: float) -> None:
    """Callouts e emojis do plano da IA como eventos ASS por cima das legendas."""
    from .director import CALLOUT_COLORS
    from .pipeline import _ass_text, _ass_time

    lines = []
    for item in plan.get("callouts", []):
        start, end = item["t"], min(duration, item["t"] + 1.8)
        text = _ass_text(item["text"])
        size = min(96, int(900 / max(6, len(text)) / 0.55))
        lines.append(f"Dialogue: 5,{_ass_time(start)},{_ass_time(end)},Default,,0,0,0,,"
                     f"{{\\an5\\pos(540,640)\\fnBebas Neue\\b400\\fs{size}\\bord7\\shad4\\1c{CALLOUT_COLORS[item['style']]}"
                     f"\\fscx60\\fscy60\\t(0,140,\\fscx108\\fscy108)\\t(140,260,\\fscx100\\fscy100)\\fad(60,220)}}{text}")
    for index, item in enumerate(plan.get("emoji", [])):
        start, end = item["t"], min(duration, item["t"] + 1.2)
        x = (220, 860)[index % 2]
        lines.append(f"Dialogue: 5,{_ass_time(start)},{_ass_time(end)},Default,,0,0,0,,"
                     f"{{\\an5\\pos({x},520)\\fnNoto Emoji\\fs150\\bord0\\shad0\\1c&H00FFFFFF&\\frz-12"
                     f"\\fscx0\\fscy0\\t(0,160,\\fscx120\\fscy120)\\t(160,300,\\fscx100\\fscy100\\frz8)\\fad(0,250)}}"
                     f"{item['emoji']}")
    if lines:
        with path.open("a", encoding="utf-8") as file:
            file.write("\n".join(lines) + "\n")
