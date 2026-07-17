FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# ffmpeg: frame/audio extraction for the video-file analysis pipeline
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini .

EXPOSE 8000
# Run migrations first (idempotent); create_all remains as dev fallback.
CMD ["sh", "-c", "alembic upgrade head || echo '[warn] alembic failed — relying on AUTO_CREATE_TABLES'; uvicorn app.main:app --host 0.0.0.0 --port 8000"]
