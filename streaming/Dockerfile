# Webhook (producteur) + consumer Kafka EventPro — contexte de build : racine du monorepo
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/models

WORKDIR /srv

RUN pip install torch==2.5.1 --index-url https://download.pytorch.org/whl/cpu

COPY common /opt/eventpro/common
COPY streaming/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt "/opt/eventpro/common[embeddings]"

COPY streaming/app ./app

RUN useradd --uid 10001 --create-home appuser && mkdir -p /models && chown appuser /models
USER appuser

CMD ["python", "-m", "app.consumer"]
