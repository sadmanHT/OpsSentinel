FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl git procps \
    && git config --system --add safe.directory /workspace \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 opssentinel

WORKDIR /app/backend

COPY pyproject.toml alembic.ini requirements.lock ./
COPY app ./app
COPY migrations ./migrations

RUN pip install --no-cache-dir -r requirements.lock \
    && pip install --no-cache-dir --no-deps . \
    && chown -R opssentinel:opssentinel /app/backend

USER opssentinel

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
