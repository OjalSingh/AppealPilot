FROM python:3.12-slim
WORKDIR /app
COPY backend/pyproject.toml ./
COPY backend/appealpilot ./appealpilot
RUN pip install --no-cache-dir ".[postgres]"
COPY samples /samples
ENV PYTHONUNBUFFERED=1 APPEALPILOT_SAMPLES=/samples
EXPOSE 8000
# Cloud Run sets $PORT; default to 8000 locally.
CMD ["sh", "-c", "uvicorn appealpilot.api:app --host 0.0.0.0 --port ${PORT:-8000}"]
