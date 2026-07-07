# Build context: lambda/
FROM python:3.12-slim
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
COPY s3_to_redshift/pyproject.toml s3_to_redshift/uv.lock ./
RUN uv sync --frozen --no-dev
ENV PATH="/app/.venv/bin:$PATH"
COPY shared/ ./
COPY s3_to_redshift/main.py ./
CMD ["python", "-c", "import main"]
