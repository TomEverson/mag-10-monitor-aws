# Build context: lambda/
FROM python:3.12-slim
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
COPY signal_archive/pyproject.toml signal_archive/uv.lock ./
RUN uv sync --frozen --no-dev
ENV PATH="/app/.venv/bin:$PATH"
COPY shared/ ./
COPY signal_archive/main.py ./
CMD ["python", "-c", "import main"]
