import asyncio

from httpx import ASGITransport, AsyncClient

from corta_ai.app import create_app
from corta_ai.jobs import InMemoryJobStore


def make_app(tmp_path):
    store = InMemoryJobStore()
    app = create_app(store=store, workspace=tmp_path, run_jobs=False)
    return app, store


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
