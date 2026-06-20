FROM python:3.12-slim AS runtime

# Python writes logs directly to stdout/stderr so Docker can collect them.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends gosu \
    && rm -rf /var/lib/apt/lists/*

# Create a dedicated unprivileged user before copying application files. The
# fixed UID/GID keeps host-mounted log directories writable after chown 1000:1000.
RUN groupadd --gid 1000 appuser \
    && useradd --uid 1000 --gid appuser --create-home --shell /usr/sbin/nologin appuser \
    && mkdir -p /models/faster-whisper /data/logs \
    && chown -R appuser:appuser /models /data/logs

COPY pyproject.toml README.md /app/
COPY job_logger /app/job_logger
COPY migrations /app/migrations
COPY alembic.ini /app/alembic.ini
COPY docker/entrypoint.sh /app/docker/entrypoint.sh

RUN pip install --upgrade pip \
    && pip install ".[dev]" \
    && chmod +x /app/docker/entrypoint.sh \
    && chown -R appuser:appuser /app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=3).read()"

ENTRYPOINT ["/app/docker/entrypoint.sh"]
