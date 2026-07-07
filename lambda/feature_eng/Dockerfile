# Build context: lambda/
FROM python:3.12-slim
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
COPY feature_eng/pyproject.toml feature_eng/uv.lock ./
RUN uv sync --frozen --no-dev
ENV PATH="/app/.venv/bin:$PATH"
COPY feature_eng/main.py ./
CMD ["python", "-c", "import main"]
