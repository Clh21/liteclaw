FROM python:3.11-slim AS builder

WORKDIR /build
COPY . .
RUN python -m pip install --upgrade pip \
    && python -m pip wheel --wheel-dir /wheels ".[postgres]"

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LITECLAW_HOST=0.0.0.0 \
    LITECLAW_PORT=8000 \
    LITECLAW_DB_PATH=/data/liteclaw.db \
    LITECLAW_WORKSPACE_ROOT=/workspace

WORKDIR /app
COPY --from=builder /wheels /wheels
RUN python -m pip install --no-cache-dir /wheels/*.whl \
    && python -m playwright install --with-deps chromium \
    && useradd --create-home --uid 10001 liteclaw \
    && mkdir -p /data /workspace \
    && chown -R liteclaw:liteclaw /data /workspace /app

COPY --chown=liteclaw:liteclaw . /app

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"

USER liteclaw
EXPOSE 8000
CMD ["python", "-m", "liteclaw"]
