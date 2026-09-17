import asyncio
from threading import Event

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

    def render(source, subtitles, start, duration, output):
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
