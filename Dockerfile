# Two images from one Dockerfile:
#   docker build --target app    -t stc-app .     # full web app (SQLite or Postgres), local or any container host
#   docker build --target worker -t stc-worker .  # heavy jobs: OpenSanctions sync, SDV + Faker, batch screening
FROM python:3.12-slim AS base
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
COPY pyproject.toml README.md ./
COPY src ./src

FROM base AS app
RUN pip install ".[mcp]" && useradd -m app && mkdir -p /data && chown app /data
USER app
ENV STC_DB_PATH=/data/stc.sqlite3 STC_CUSTOMERS=/data/customers/customers.csv
EXPOSE 8000
HEALTHCHECK CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/health')"
CMD ["stc", "serve", "--host", "0.0.0.0", "--port", "8000"]

FROM base AS worker
# CPU-only PyTorch keeps the SDV image ~1 GB smaller than the default CUDA build.
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu && pip install ".[synth]" \
    && useradd -m app && mkdir -p /app/data && chown -R app /app/data
USER app
ENV STC_WATCHLIST=opensanctions
ENTRYPOINT ["stc", "worker"]
CMD ["refresh"]
