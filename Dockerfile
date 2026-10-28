FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY agent_platform ./agent_platform
RUN pip install --no-cache-dir ".[postgres]"

ENV DATABASE_URL=sqlite:////app/data/agent_platform.db
ENV ARTIFACT_DIR=/app/data/artifacts
RUN mkdir -p /app/data/artifacts

EXPOSE 8000
CMD ["uvicorn", "agent_platform.api:app", "--host", "0.0.0.0", "--port", "8000"]
