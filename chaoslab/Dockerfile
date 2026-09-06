FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app/chaoslab
COPY pyproject.toml ./
COPY chaoslab ./chaoslab
RUN pip install --no-cache-dir .

CMD ["uvicorn", "chaoslab.service:app", "--host", "0.0.0.0", "--port", "8080"]
