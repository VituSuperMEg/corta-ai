FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=7860 \
    WORKSPACE_DIR=/app/workspace \
    HF_HOME=/app/cache \
    CPU_THREADS=2 \
    MAX_PENDING_JOBS=5

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg fonts-liberation ca-certificates libgomp1 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN useradd --create-home --uid 1000 app && mkdir -p /app/workspace /app/cache && chown -R app:app /app
COPY --chown=app:app corta_ai ./corta_ai
USER app
EXPOSE 7860
CMD ["sh", "-c", "exec uvicorn corta_ai.app:app --host 0.0.0.0 --port ${PORT:-7860} --workers 1"]
