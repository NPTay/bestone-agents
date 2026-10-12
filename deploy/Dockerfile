FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# The app resolves agents/ and knowledge/ relative to the repo root (PROJECT_ROOT),
# so the source lives in /app and the package is installed in editable mode.
WORKDIR /app
COPY pyproject.toml alembic.ini ./
COPY app ./app
COPY migrations ./migrations
COPY agents ./agents
COPY knowledge ./knowledge
COPY deploy/entrypoint.sh ./deploy/entrypoint.sh
RUN pip install -e . \
    && useradd --system --uid 1000 --home-dir /app bestone \
    && chmod +x /app/deploy/entrypoint.sh \
    && chown -R bestone:bestone /app

USER bestone
EXPOSE 8000
ENTRYPOINT ["/app/deploy/entrypoint.sh"]
