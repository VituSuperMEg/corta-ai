"""Edição guiada por IA: um LLM (NVIDIA NIM ou Ollama local) lê a transcrição de cada corte e
devolve um plano JSON de zoom, destaques na tela, emojis e clima. Só roda quando o usuário escolhe."""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request

PROVIDERS = ("off", "nvidia", "ollama")

# clima -> (fonte da legenda, cor primária ASS &HAABBGGRR&)
MOODS = {
    "energetico": ("Poppins ExtraBold", "&H003EFFD8&"),
    "engracado": ("Bebas Neue", "&H0055DDFF&"),
    "serio": ("Barlow Condensed ExtraBold", "&H00FFFFFF&"),
    "calmo": ("Poppins ExtraBold", "&H00FFE0B0&"),
    "misterio": ("Barlow Condensed ExtraBold", "&H008B79FF&"),
}
CALLOUT_COLORS = {"alerta": "&H004040FF&", "dinheiro": "&H0050E080&", "destaque": "&H003EFFD8&",
                  "pergunta": "&H00FFB060&"}

_PROMPT = """Você é um editor de vídeos curtos (Shorts/Reels/TikTok) em português do Brasil.
Receberá a transcrição de um corte de {duration:.0f}s com o tempo (em segundos, relativo ao corte) em que cada trecho começa.
Sua missão: deixar o corte dinâmico e prender atenção. Responda SOMENTE um JSON válido, sem markdown, no formato:
{{
 "mood": "energetico|engracado|serio|calmo|misterio",
 "hook": "frase curta de impacto (até 6 palavras) que resume o gancho do corte",
 "callouts": [{{"t": 12.4, "text": "TEXTO CURTO NA TELA", "style": "alerta|dinheiro|destaque|pergunta"}}],
 "zoom": [3.2, 15.0],
 "emoji": [{{"t": 5.1, "emoji": "🔥"}}]
}}
Regras: no máximo 4 callouts (números, valores, nomes, afirmações fortes; até 28 caracteres, em caixa alta),
no máximo 6 zooms (momentos de ênfase, revelação ou virada), no máximo 6 emojis (1 emoji cada),
tempos sempre entre 0 e {duration:.0f}. Não invente fatos: só use o que está na transcrição.

Transcrição:
{transcript}"""


def transcript_text(words: list[dict], start: float, end: float) -> str:
    lines: list[str] = []
    current: list[str] = []
    line_start = 0.0
    for word in words:
        if word["end"] <= start or word["start"] >= end or not word["text"].strip():
            continue
        if not current:
            line_start = max(0.0, word["start"] - start)
        current.append(word["text"].strip())
        if len(current) >= 8 or word["text"].strip().endswith((".", "!", "?")):
            lines.append(f"[{line_start:.1f}] {' '.join(current)}")
            current = []
    if current:
        lines.append(f"[{line_start:.1f}] {' '.join(current)}")
    return "\n".join(lines)


def _post_json(url: str, payload: dict, headers: dict[str, str], timeout: int = 180) -> dict:
    request = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                     headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"IA respondeu HTTP {error.code}: {error.read().decode()[:200]}") from error
    except (urllib.error.URLError, TimeoutError) as error:
        raise RuntimeError(f"Não foi possível falar com a IA em {url}: {error}") from error


def ask(provider: str, prompt: str) -> str:
    if provider == "nvidia":
        key = os.environ.get("NVIDIA_API_KEY") or os.environ.get("NV_API_KEY")
        if not key:
            raise RuntimeError("Defina NVIDIA_API_KEY no ambiente pra usar a edição guiada pela NVIDIA")
        data = _post_json(
            os.environ.get("NVIDIA_API_URL", "https://integrate.api.nvidia.com/v1/chat/completions"),
            {"model": os.environ.get("NVIDIA_MODEL", "google/gemma-4-31b-it"), "temperature": 0.3,
             "max_tokens": 900, "messages": [{"role": "user", "content": prompt}]},
            {"Authorization": f"Bearer {key}"})
        return data["choices"][0]["message"]["content"]
    if provider == "ollama":
        data = _post_json(
            os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434") + "/api/chat",
            {"model": os.environ.get("OLLAMA_MODEL", "qwen3:8b"), "stream": False, "format": "json",
             "think": False, "options": {"temperature": 0.3},
             "messages": [{"role": "user", "content": prompt}]}, {}, timeout=600)
        return data["message"]["content"]
    raise ValueError(f"Provedor de IA desconhecido: {provider}")


def parse_plan(raw: str, duration: float) -> dict:
    """Extrai e sanitiza o JSON; tudo que não bate com o formato é descartado, nunca aplicado."""
    match = re.search(r"\{.*\}", raw, flags=re.S)
    if not match:
        raise RuntimeError("A IA não devolveu um plano em JSON")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as error:
        raise RuntimeError(f"A IA devolveu JSON inválido: {error}") from error

    def time(value) -> float | None:
        try:
            t = float(value)
        except (TypeError, ValueError):
            return None
        return round(t, 2) if 0 <= t < duration - 0.5 else None

    mood = str(data.get("mood", "")).lower()
    callouts = []
    for item in data.get("callouts") or []:
        t = time(isinstance(item, dict) and item.get("t"))
        text = re.sub(r"[{}\\]", "", str(item.get("text", ""))).strip().upper()[:28] if isinstance(item, dict) else ""
        if t is not None and text:
            style = str(item.get("style", "destaque")).lower()
            callouts.append({"t": t, "text": text, "style": style if style in CALLOUT_COLORS else "destaque"})
    emoji = []
    for item in data.get("emoji") or []:
        t = time(isinstance(item, dict) and item.get("t"))
        symbol = str(item.get("emoji", "")).strip() if isinstance(item, dict) else ""
        if t is not None and 0 < len(symbol) <= 2 and not symbol.isascii():
            emoji.append({"t": t, "emoji": symbol})
    zoom = sorted({t for t in map(time, data.get("zoom") or []) if t is not None})
    return {"mood": mood if mood in MOODS else "energetico",
            "hook": re.sub(r"[{}\\]", "", str(data.get("hook", ""))).strip()[:60],
            "callouts": callouts[:4], "emoji": emoji[:6], "zoom": zoom[:6]}


def plan_clip(provider: str, words: list[dict], start: float, end: float) -> dict:
    prompt = _PROMPT.format(duration=end - start, transcript=transcript_text(words, start, end))
    last_error: Exception | None = None
    for _ in range(2):  # modelos pequenos às vezes quebram o JSON; uma segunda chance resolve
        try:
            return parse_plan(ask(provider, prompt), end - start)
        except RuntimeError as error:
            last_error = error
    raise RuntimeError(f"Edição guiada por IA falhou: {last_error}")
