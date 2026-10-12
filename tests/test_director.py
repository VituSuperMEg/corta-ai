from itertools import product

from corta_ai import director
from corta_ai.director import parse_plan, transcript_text
from corta_ai.effects import append_director_overlays
from corta_ai.pipeline import create_ass


def test_plan_is_sanitized_and_bounded():
    raw = '```json\n{"mood":"ENGRACADO","hook":"Olha {isso}","zoom":[1,"x",-2,40,5,5],' \
          '"callouts":[{"t":2,"text":"r$ 10 mil {\\\\pos}","style":"dinheiro"},{"t":99,"text":"fora"},{"t":3,"text":"","style":"?"}],' \
          '"emoji":[{"t":1,"emoji":"🔥"},{"t":2,"emoji":"abc"},{"t":3,"emoji":"💰💰💰"}]}\n```'
    plan = parse_plan(raw, 30)
    assert plan == {"mood": "engracado", "hook": "Olha isso", "zoom": [1.0, 5.0],
                    "callouts": [{"t": 2.0, "text": "R$ 10 MIL POS", "style": "dinheiro"}],
                    "emoji": [{"t": 1.0, "emoji": "🔥"}]}
    assert parse_plan("{}", 10) == {"mood": "energetico", "hook": "", "callouts": [], "emoji": [], "zoom": []}


def test_transcript_is_clip_relative():
    words = [dict(start=9, end=9.5, text="fora"), dict(start=10.2, end=11, text="Oi!"), dict(start=12, end=13, text="tudo")]
    assert transcript_text(words, 10, 20) == "[0.2] Oi!\n[2.0] tudo"


def test_director_overlays_only_when_plan_present(tmp_path):
    path = tmp_path / "a.ass"
    create_ass([], 0, 10, path)
    append_director_overlays(path, {"callouts": [], "emoji": []}, 10)
    assert "Dialogue: 5," not in path.read_text()
    append_director_overlays(path, {"callouts": [{"t": 1, "text": "R$ 10 MIL", "style": "dinheiro"}],
                                    "emoji": [{"t": 9.5, "emoji": "🔥"}]}, 10)
    content = path.read_text()
    assert "Dialogue: 5,0:00:01.00,0:00:02.80" in content and "R$ 10 MIL" in content and "Bebas Neue" in content
    assert "Dialogue: 5,0:00:09.50,0:00:10.00" in content and "Noto Emoji" in content and "🔥" in content


def test_floating_captions_and_theme_are_independent(tmp_path):
    words = [{"start": i * .5, "end": i * .5 + .4, "text": "ação"} for i in range(15)]
    for stylish, floating in product((False, True), repeat=2):
        path = tmp_path / f"{stylish}-{floating}.ass"
        create_ass(words, 0, 8, path, stylish_captions=stylish, floating_captions=floating)
        content = path.read_text()
        assert (r"\frz" in content) == floating
        assert ("Style: Default,Arial,72,&H00FFFFFF," in content)
        if floating:
            assert r"\pos(540,1690)" in content and r"\pos(540,1000)" in content
    create_ass(words, 0, 8, tmp_path / "theme.ass", theme=("Bebas Neue", "&H0055DDFF&"))
    assert "Style: Default,Bebas Neue,72,&H0055DDFF," in (tmp_path / "theme.ass").read_text()


def test_director_retries_then_fails_clearly(monkeypatch):
    calls = []
    monkeypatch.setattr(director, "ask", lambda provider, prompt: calls.append(provider) or "sem json")
    try:
        director.plan_clip("ollama", [], 0, 10)
    except RuntimeError as error:
        assert "Edição guiada por IA falhou" in str(error)
    assert calls == ["ollama", "ollama"]
