from __future__ import annotations

from pathlib import Path
from threading import Thread
from urllib.parse import parse_qs, urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from .jobs import InMemoryJobStore, Job


class CreateJobRequest(BaseModel):
    youtube_url: str
    clip_count: int = Field(ge=1, le=20)
    clip_duration: int = Field(ge=15, le=180)

    @field_validator("youtube_url")
    @classmethod
    def validate_youtube_url(cls, value: str) -> str:
        parsed = urlparse(value)
        host = (parsed.hostname or "").lower()
        allowed = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}
        if parsed.scheme not in {"http", "https"} or host not in allowed:
            raise ValueError("Informe uma URL válida do YouTube")
        if host == "youtu.be":
            video_id = parsed.path.strip("/").split("/", 1)[0]
        elif parsed.path == "/watch":
            video_id = parse_qs(parsed.query).get("v", [""])[0]
        elif parsed.path.startswith(("/shorts/", "/embed/", "/live/")):
            video_id = parsed.path.strip("/").split("/", 1)[1].split("/", 1)[0]
        else:
            video_id = ""
        if not video_id:
            raise ValueError("A URL precisa apontar para um vídeo do YouTube")
        return value


def _serialize(job: Job) -> dict:
    data = job.as_dict()
    data["outputs"] = [
        {
            "name": filename,
            "url": f"/api/jobs/{job.id}/outputs/{filename}",
            "download_url": f"/api/jobs/{job.id}/outputs/{filename}?download=1",
        }
        for filename in job.outputs
    ]
    return data


def _video_response(path: Path, request: Request, download: bool) -> StreamingResponse:
    size = path.stat().st_size
    start, end = 0, max(0, size - 1)
    status_code = 200
    range_header = request.headers.get("range")
    if range_header and range_header.startswith("bytes="):
        try:
            value = range_header.removeprefix("bytes=")
            if "," in value or "-" not in value or size == 0:
                raise ValueError
            first, last = value.split("-", 1)
            if not first:
                suffix_length = int(last)
                if suffix_length <= 0:
                    raise ValueError
                start = max(0, size - suffix_length)
            else:
                start = int(first)
                end = min(int(last) if last else end, end)
                if start >= size or end < start:
                    raise ValueError
        except ValueError as error:
            raise HTTPException(
                status_code=416,
                detail="Intervalo de vídeo inválido",
                headers={"Content-Range": f"bytes */{size}"},
            ) from error
        status_code = 206

    async def chunks():
        with path.open("rb") as video:
            video.seek(start)
            remaining = end - start + 1
            while remaining > 0:
                chunk = video.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    disposition = "attachment" if download else "inline"
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(end - start + 1),
        "Content-Disposition": f'{disposition}; filename="{path.name}"',
    }
    if status_code == 206:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    return StreamingResponse(chunks(), status_code=status_code, media_type="video/mp4", headers=headers)


def create_app(
    store: InMemoryJobStore | None = None,
    workspace: Path | None = None,
    run_jobs: bool = True,
) -> FastAPI:
    app = FastAPI(title="Corta Aí", version="0.1.0")
    app.state.store = store or InMemoryJobStore()
    app.state.workspace = Path(workspace or "workspace").resolve()
    app.state.workspace.mkdir(parents=True, exist_ok=True)

    @app.post("/api/jobs", status_code=202)
    async def create_job(request: CreateJobRequest):
        job = app.state.store.create(
            youtube_url=request.youtube_url,
            clip_count=request.clip_count,
            clip_duration=request.clip_duration,
        )
        if run_jobs:
            from .pipeline import process_job

            Thread(
                target=process_job,
                args=(job.id, app.state.store, app.state.workspace),
                daemon=True,
            ).start()
        return _serialize(job)

    @app.get("/api/jobs/{job_id}")
    async def get_job(job_id: str):
        job = app.state.store.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Processamento não encontrado")
        return _serialize(job)

    @app.get("/api/jobs/{job_id}/outputs/{filename}")
    async def get_output(job_id: str, filename: str, request: Request, download: bool = False):
        job = app.state.store.get(job_id)
        if not job or filename not in job.outputs or Path(filename).name != filename:
            raise HTTPException(status_code=404, detail="Arquivo não encontrado")
        path = app.state.workspace / job_id / "outputs" / filename
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Arquivo não encontrado")
        return _video_response(path, request, download)

    static_dir = Path(__file__).parent / "static"
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
    return app


app = create_app()
