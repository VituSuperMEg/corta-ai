import asyncio
from threading import Event

import pytest
from httpx import ASGITransport, AsyncClient

from corta_ai.app import create_app
from corta_ai.jobs import InMemoryJobStore


def test_cloud_queue_rejects_excess_work_while_processing(tmp_path, monkeypatch):
    from corta_ai import pipeline

    started = Event()
    release = Event()

    def process(*args):
        started.set()
        release.wait(timeout=5)

    monkeypatch.setenv("MAX_PENDING_JOBS", "1")
    monkeypatch.setattr(pipeline, "process_job", process)
    app = create_app(workspace=tmp_path)
    payload = {"youtube_url": "https://youtu.be/example", "clip_count": 1, "clip_duration": 30}
    try:
        assert request(app, "GET", "/healthz").json() == {"status": "ok"}
        assert request(app, "POST", "/api/jobs", json=payload).status_code == 202
        assert started.wait(timeout=2)
        assert request(app, "POST", "/api/jobs", json=payload).status_code == 429
    finally:
        release.set()


def make_app(tmp_path):
    store = InMemoryJobStore()
    app = create_app(store=store, workspace=tmp_path, run_jobs=False)
    return app, store


def test_stylish_caption_choice_is_stored_and_defaults_off(tmp_path):
    app, store = make_app(tmp_path)
    payload = {"youtube_url": "https://youtu.be/example", "clip_count": 1, "clip_duration": 30}
    default = request(app, "POST", "/api/jobs", json=payload)
    assert default.json()["stylish_captions"] is False
    enabled = request(app, "POST", "/api/jobs", json={**payload, "stylish_captions": True})
    assert enabled.status_code == 202
    job_id = enabled.json()["id"]
    assert store.get(job_id).stylish_captions is True
    assert request(app, "GET", f"/api/jobs/{job_id}").json()["stylish_captions"] is True


def request(app, method, url, **kwargs):
    async def send():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.request(method, url, **kwargs)

    return asyncio.run(send())


def test_user_can_create_job_with_url_quantity_and_duration(tmp_path):
    app, store = make_app(tmp_path)

    response = request(
        app,
        "POST",
        "/api/jobs",
        json={
            "youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "clip_count": 4,
            "clip_duration": 45,
        },
    )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert store.get(body["id"]).clip_count == 4
    assert store.get(body["id"]).clip_duration == 45


def test_api_rejects_invalid_job_input(tmp_path):
    app, _ = make_app(tmp_path)

    response = request(
        app,
        "POST",
        "/api/jobs",
        json={"youtube_url": "not-a-youtube-url", "clip_count": 0, "clip_duration": 2},
    )

    assert response.status_code == 422

    missing_video_id = request(
        app,
        "POST",
        "/api/jobs",
        json={"youtube_url": "https://youtube.com/", "clip_count": 1, "clip_duration": 30},
    )
    assert missing_video_id.status_code == 422


def test_user_can_read_job_progress_and_error(tmp_path):
    app, store = make_app(tmp_path)
    created = request(
        app,
        "POST",
        "/api/jobs",
        json={
            "youtube_url": "https://youtu.be/dQw4w9WgXcQ",
            "clip_count": 2,
            "clip_duration": 30,
        },
    ).json()
    store.update(created["id"], status="failed", progress=37, error="download falhou")

    response = request(app, "GET", f"/api/jobs/{created['id']}")

    assert response.status_code == 200
    assert response.json()["progress"] == 37
    assert response.json()["error"] == "download falhou"


def test_finished_outputs_are_exposed_for_preview_and_download(tmp_path):
    app, store = make_app(tmp_path)
    created = request(
        app,
        "POST",
        "/api/jobs",
        json={
            "youtube_url": "https://youtube.com/shorts/dQw4w9WgXcQ",
            "clip_count": 1,
            "clip_duration": 30,
        },
    ).json()
    output_dir = tmp_path / created["id"] / "outputs"
    output_dir.mkdir(parents=True)
    (output_dir / "corte-01.mp4").write_bytes(b"video")
    store.update(created["id"], status="completed", progress=100, outputs=["corte-01.mp4"])

    response = request(app, "GET", f"/api/jobs/{created['id']}")
    video = request(app, "GET", f"/api/jobs/{created['id']}/outputs/corte-01.mp4")

    assert response.json()["outputs"][0]["name"] == "corte-01.mp4"
    assert response.json()["outputs"][0]["url"].endswith("/corte-01.mp4")
    assert video.status_code == 200
    assert video.content == b"video"

    suffix = request(
        app,
        "GET",
        f"/api/jobs/{created['id']}/outputs/corte-01.mp4",
        headers={"Range": "bytes=-2"},
    )
    assert suffix.status_code == 206
    assert suffix.content == b"eo"
    assert suffix.headers["content-range"] == "bytes 3-4/5"

    invalid_range = request(
        app,
        "GET",
        f"/api/jobs/{created['id']}/outputs/corte-01.mp4",
        headers={"Range": "bytes=99-100"},
    )
    assert invalid_range.status_code == 416


def test_requested_stylish_captions_reach_rendered_subtitles(tmp_path, monkeypatch):
    from corta_ai import pipeline
    from corta_ai.highlights import TranscriptSegment

    app, store = make_app(tmp_path)
    created = request(app, "POST", "/api/jobs", json={
        "youtube_url": "https://youtu.be/example", "clip_count": 1,
        "clip_duration": 15, "stylish_captions": True,
    }).json()
    words = [{"start": i * .5, "end": i * .5 + .4, "text": f"fala{i}"}
             for i in range(9)]
    monkeypatch.setattr(pipeline, "download_video", lambda *args: tmp_path / "source.mp4")
    monkeypatch.setattr(pipeline, "video_duration", lambda *args: 15)
    monkeypatch.setattr(pipeline, "transcribe", lambda *args: (
        [TranscriptSegment(0, 15, "Uma frase para o corte.")], words))
    subtitles_seen = []

    def render(source, subtitles, start, duration, output, **options):
        subtitles_seen.append(subtitles.read_text())
        output.write_bytes(b"video")

    monkeypatch.setattr(pipeline, "render_clip", render)
    pipeline.process_job(created["id"], store, tmp_path)
    assert store.get(created["id"]).status == "completed"
    assert len(subtitles_seen) == 1
    assert r"\fscx94" in subtitles_seen[0]
    assert r"\blur1" in subtitles_seen[0]
    assert r"\fscx115" in subtitles_seen[0]
    assert r"\kf" not in subtitles_seen[0]


def test_caption_options_are_independent_in_api(tmp_path):
    app, store = make_app(tmp_path)
    for effects in (False, True):
        for fonts in (False, True):
            response = request(app, "POST", "/api/jobs", json={
                "youtube_url": "https://youtu.be/example", "clip_count": 1, "clip_duration": 15,
                "stylish_captions": effects, "varied_fonts": fonts,
            })
            assert response.status_code == 202
            job = store.get(response.json()["id"])
            assert job.stylish_captions is effects
            assert job.varied_fonts is fonts


def test_creative_options_round_trip_and_default_off(tmp_path):
    from itertools import product
    app, store = make_app(tmp_path)
    names = ("smooth_zoom", "clip_progress", "opening_title", "sound_effects")
    payload = {"youtube_url": "https://youtu.be/example", "clip_count": 1, "clip_duration": 15}
    default = request(app, "POST", "/api/jobs", json=payload).json()
    assert all(default[name] is False for name in names)
    for values in product((False, True), repeat=4):
        options = dict(zip(names, values))
        response = request(app, "POST", "/api/jobs", json={**payload, **options, "title_text": "Ação!"})
        assert response.status_code == 202
        job = store.get(response.json()["id"])
        for name, value in options.items():
            assert getattr(job, name) is value
        assert job.title_text == "Ação!"
    assert request(app, "POST", "/api/jobs", json={**payload, "title_text": "a" * 61}).status_code == 422


def test_new_effects_reach_pipeline_without_enabling_caption_options(tmp_path, monkeypatch):
    from corta_ai import pipeline
    from corta_ai.highlights import TranscriptSegment
    app, store = make_app(tmp_path)
    response = request(app, "POST", "/api/jobs", json={
        "youtube_url": "https://youtu.be/example", "clip_count": 1, "clip_duration": 15,
        "smooth_zoom": True, "clip_progress": True, "opening_title": True,
        "sound_effects": True, "title_text": "Teste de abertura",
    })
    words = [dict(start=1, end=1.5, text="Incrível!")]
    monkeypatch.setattr(pipeline, "download_video", lambda *args: tmp_path / "source.mp4")
    monkeypatch.setattr(pipeline, "video_duration", lambda *args: 15)
    monkeypatch.setattr(pipeline, "transcribe", lambda *args: (
        [TranscriptSegment(0, 15, "Incrível!")], words))
    rendered = []
    def render(source, subtitles, start, duration, output, **options):
        rendered.append((subtitles.read_text(), options))
        output.write_bytes(b"video")
    monkeypatch.setattr(pipeline, "render_clip", render)
    pipeline.process_job(response.json()["id"], store, tmp_path)
    assert store.get(response.json()["id"]).status == "completed"
    content, options = rendered[0]
    assert "TESTE DE ABERTURA" in content
    assert "Dialogue: 2," in content
    assert r"\kf" in content
    assert "Poppins" not in content
    assert options == {"smooth_zoom": True, "sound_effects": True, "emphasis": [1],
                       "cuts": [], "beeps": [], "music": False, "zoom": [],
                       "shake": [], "flash": [], "hook_fx": False, "vignette": False,
                       "sfx_events": [], "music_file": "", "music_volume": 0.35,
                       "timeline": None}


def test_editing_options_reach_render_and_metadata(tmp_path, monkeypatch):
    from corta_ai import pipeline
    from corta_ai.highlights import TranscriptSegment
    app, store = make_app(tmp_path)
    response = request(app, "POST", "/api/jobs", json={
        "youtube_url": "https://youtu.be/example", "clip_count": 1, "clip_duration": 15,
        "camera_cuts": True, "censor": True, "caption_emoji": True, "background_music": True,
        "energy_score": True, "suggestions": True, "caption_position": "top",
    })
    assert response.status_code == 202
    words = [dict(start=1, end=1.5, text="Que"), dict(start=1.5, end=2, text="porra!"),
             dict(start=4, end=5, text="Dinheiro"), dict(start=5, end=6, text="fácil?")]
    monkeypatch.setattr(pipeline, "download_video", lambda *args: tmp_path / "source.mp4")
    monkeypatch.setattr(pipeline, "video_duration", lambda *args: 15)
    monkeypatch.setattr(pipeline, "audio_energy", lambda *args: [1.0] * 15)
    monkeypatch.setattr(pipeline, "transcribe", lambda *args: (
        [TranscriptSegment(0, 3, "Que porra!"), TranscriptSegment(4, 6, "Dinheiro fácil?")], words))
    rendered = []
    def render(source, subtitles, start, duration, output, **options):
        rendered.append((subtitles.read_text(), options))
        output.write_bytes(b"video")
    monkeypatch.setattr(pipeline, "render_clip", render)
    pipeline.process_job(response.json()["id"], store, tmp_path)
    job = store.get(response.json()["id"])
    assert job.status == "completed"
    content, options = rendered[0]
    assert "P****!" in content and "porra" not in content.lower()
    assert "🔥" in content and "💰" in content and "🤔" in content and "Noto Emoji" in content
    assert ",8,70,70,300,1" in content  # legenda no topo
    assert options["music"] is True and options["beeps"] == [(1.5, 2)] and options["cuts"] == [4.0]
    assert job.metadata[0]["title"] == "Dinheiro fácil?"
    assert "#shorts" in job.metadata[0]["hashtags"]
    assert request(app, "GET", f"/api/jobs/{job.id}").json()["metadata"] == job.metadata
    assert request(app, "POST", "/api/jobs", json={"youtube_url": "https://youtu.be/example", "clip_count": 1,
                                                     "clip_duration": 15, "caption_position": "left"}).status_code == 422


def test_director_plan_reaches_subtitles_zoom_and_result(tmp_path, monkeypatch):
    from corta_ai import pipeline
    from corta_ai.highlights import TranscriptSegment
    app, store = make_app(tmp_path)
    payload = {"youtube_url": "https://youtu.be/example", "clip_count": 1, "clip_duration": 15}
    assert request(app, "POST", "/api/jobs", json=payload).json()["director"] == "off"
    assert request(app, "POST", "/api/jobs", json={**payload, "director": "gpt"}).status_code == 422
    response = request(app, "POST", "/api/jobs", json={**payload, "director": "ollama", "opening_title": True,
                                                       "floating_captions": True})
    assert response.json()["director"] == "ollama" and response.json()["floating_captions"] is True
    words = [dict(start=1, end=1.5, text="Ganhei"), dict(start=1.5, end=2, text="dez"), dict(start=2, end=3, text="mil!")]
    monkeypatch.setattr(pipeline, "download_video", lambda *args: tmp_path / "source.mp4")
    monkeypatch.setattr(pipeline, "video_duration", lambda *args: 15)
    monkeypatch.setattr(pipeline, "transcribe", lambda *args: ([TranscriptSegment(0, 3, "Ganhei dez mil!")], words))
    asked = []
    monkeypatch.setattr(pipeline, "plan_clip", lambda provider, *args: asked.append(provider) or {
        "mood": "engracado", "hook": "Dez mil na conta", "zoom": [2.0],
        "callouts": [{"t": 1.5, "text": "R$ 10 MIL", "style": "dinheiro"}], "emoji": [{"t": 2.5, "emoji": "💰"}]})
    rendered = []
    def render(source, subtitles, start, duration, output, **options):
        rendered.append((subtitles.read_text(), options))
        output.write_bytes(b"video")
    monkeypatch.setattr(pipeline, "render_clip", render)
    pipeline.process_job(response.json()["id"], store, tmp_path)
    job = store.get(response.json()["id"])
    assert job.status == "completed" and asked == ["ollama"]
    content, options = rendered[0]
    assert "Style: Default,Bebas Neue,72,&H0055DDFF," in content
    assert "DEZ MIL NA CONTA" in content and "R$ 10 MIL" in content and "💰" in content and r"\frz" in content
    assert options["zoom"] == [2.0] and options["smooth_zoom"] is False
    assert request(app, "GET", f"/api/jobs/{job.id}").json()["ai_plans"][0]["mood"] == "engracado"


def test_attention_and_sfx_options_reach_render_independently(tmp_path, monkeypatch):
    from corta_ai import pipeline
    from corta_ai.highlights import TranscriptSegment
    app, store = make_app(tmp_path)
    response = request(app, "POST", "/api/jobs", json={
        "youtube_url": "https://youtu.be/example", "clip_count": 1, "clip_duration": 15,
        "sfx_hook": True, "sfx_whoosh": True, "sfx_riser": True, "fx_hook": True,
        "fx_shake": True, "fx_flash": True, "fx_keyword": True, "fx_vignette": True,
        "ncs_credit": True,
    })
    assert response.status_code == 202
    words = [dict(start=1, end=1.5, text="Dinheiro"), dict(start=4, end=5, text="fácil")]
    monkeypatch.setattr(pipeline, "download_video", lambda *args: tmp_path / "source.mp4")
    monkeypatch.setattr(pipeline, "video_duration", lambda *args: 15)
    monkeypatch.setattr(pipeline, "transcribe", lambda *args: (
        [TranscriptSegment(0, 3, "Dinheiro"), TranscriptSegment(4, 6, "fácil")], words))
    rendered = []
    def render(source, subtitles, start, duration, output, **options):
        rendered.append((subtitles.read_text(), options))
        output.write_bytes(b"video")
    monkeypatch.setattr(pipeline, "render_clip", render)
    pipeline.process_job(response.json()["id"], store, tmp_path)
    job = store.get(response.json()["id"])
    assert job.status == "completed"
    content, options = rendered[0]
    assert options["hook_fx"] is True and options["vignette"] is True
    assert options["shake"] and options["flash"] == [4.0] and options["cuts"] == []
    assert options["sfx_events"] == [(0.0, "impact"), (4.0, "whoosh"), (13.2, "riser")]
    assert options["music_file"] == "" and options["music_volume"] == 0.35
    assert "&H0000FFFF&" in content  # palavra-chave destacada sem ligar legenda estilosa
    assert "NoCopyrightSounds" not in content  # crédito só com faixa real da pasta


def test_speed_ramp_and_freeze_retime_timeline(tmp_path, monkeypatch):
    from corta_ai import pipeline
    from corta_ai.highlights import TranscriptSegment
    app, store = make_app(tmp_path)
    response = request(app, "POST", "/api/jobs", json={
        "youtube_url": "https://youtu.be/example", "clip_count": 1, "clip_duration": 15,
        "speed_ramp": True, "freeze_climax": True, "sound_effects": True, "sfx_riser": True,
    })
    assert response.status_code == 202
    words = [dict(start=1, end=1.5, text="Dinheiro"), dict(start=8, end=9, text="fácil")]
    monkeypatch.setattr(pipeline, "download_video", lambda *args: tmp_path / "source.mp4")
    monkeypatch.setattr(pipeline, "video_duration", lambda *args: 15)
    monkeypatch.setattr(pipeline, "transcribe", lambda *args: (
        [TranscriptSegment(0, 3, "Dinheiro"), TranscriptSegment(8, 10, "fácil")], words))
    rendered = []
    def render(source, subtitles, start, duration, output, **options):
        rendered.append((subtitles.read_text(), options, duration))
        output.write_bytes(b"video")
    monkeypatch.setattr(pipeline, "render_clip", render)
    pipeline.process_job(response.json()["id"], store, tmp_path)
    assert store.get(response.json()["id"]).status == "completed"
    content, options, duration = rendered[0]
    timeline = options["timeline"]
    assert timeline and timeline["duration"] < duration + 1.5  # rampa encurta o clipe
    assert duration < 15  # -t usa a duração da nova timeline
    # legendas reescritas em tempo de saída: fim de diálogo avança pelo freeze+rampa
    dialogue = [line for line in content.splitlines() if line.startswith("Dialogue:")]
    assert dialogue and "0:00:01.00" in dialogue[0]  # início antes do clima alto: intocado
    # fim era 9.12 na fonte; com freeze 0.4s + trecho lento + rampa 1.5x vira 9.35
    assert "0:00:09.35" in dialogue[0]
    # riser mapeado para o fim real da saída, não para o tempo da fonte
    assert options["sfx_events"][-1][1] == "riser"
    assert options["sfx_events"][-1][0] == pytest.approx(duration - 1.8, abs=0.05)


def test_music_track_is_validated_and_listed(tmp_path, monkeypatch):
    assets = tmp_path / "assets"
    (assets / "music").mkdir(parents=True)
    (assets / "music" / "meu-tema.mp3").write_bytes(b"x")
    monkeypatch.setenv("CORTA_AI_ASSETS_DIR", str(assets))
    app, store = make_app(tmp_path)
    payload = {"youtube_url": "https://youtu.be/example", "clip_count": 1, "clip_duration": 15}
    default = request(app, "POST", "/api/jobs", json=payload).json()
    assert default["music_track"] == "" and default["music_volume"] == 35
    assert default["ncs_credit"] is False and default["fx_vignette"] is False
    chosen = request(app, "POST", "/api/jobs", json={**payload, "music_track": "meu-tema.mp3",
                                                     "music_volume": 50, "ncs_credit": True})
    assert chosen.status_code == 202
    assert store.get(chosen.json()["id"]).music_track == "meu-tema.mp3"
    for bad in ("fora.mp3", "../fora.mp3", "pasta/fora.mp3"):
        assert request(app, "POST", "/api/jobs", json={**payload, "music_track": bad}).status_code == 422
    assert request(app, "POST", "/api/jobs", json={**payload, "music_volume": 101}).status_code == 422
    listing = request(app, "GET", "/api/music").json()["tracks"]
    assert [item["value"] for item in listing] == ["", "meu-tema.mp3"]
    assert listing[0]["label"] == "Lo-fi sintetizada"


def test_attention_options_round_trip_and_default_off(tmp_path):
    from itertools import product
    app, store = make_app(tmp_path)
    names = ("sfx_hook", "sfx_whoosh", "sfx_riser", "fx_hook", "fx_shake",
             "fx_flash", "fx_keyword", "fx_vignette", "ncs_credit",
             "speed_ramp", "freeze_climax")
    payload = {"youtube_url": "https://youtu.be/example", "clip_count": 1, "clip_duration": 15}
    default = request(app, "POST", "/api/jobs", json=payload).json()
    assert all(default[name] is False for name in names)
    for values in product((False, True), repeat=len(names)):
        options = dict(zip(names, values))
        response = request(app, "POST", "/api/jobs", json={**payload, **options})
        assert response.status_code == 202
        job = store.get(response.json()["id"])
        for name, value in options.items():
            assert getattr(job, name) is value
