FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY config.yaml ./config.yaml

RUN pip install --upgrade pip \
    && pip install .

RUN mkdir -p /app/data /app/logs

CMD ["python", "-m", "crypto_flow_bot_v2"]
