FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY bookworm ./bookworm
COPY migrations ./migrations
COPY alembic.ini ./
RUN useradd --uid 10001 --create-home bookworm
USER bookworm
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uvicorn", "bookworm.main:app", "--host", "0.0.0.0", "--port", "8000"]

