FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"
WORKDIR /app

RUN pip install --no-cache-dir uv==0.13.8
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY agent ./agent
COPY api ./api
COPY auth ./auth
COPY checkpoint ./checkpoint
COPY config ./config
COPY knowledge ./knowledge
COPY milvus ./milvus
COPY models ./models
COPY prompts ./prompts
COPY scripts ./scripts
COPY session ./session
COPY utils ./utils

EXPOSE 8002
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8002"]
