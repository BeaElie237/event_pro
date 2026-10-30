# API FastAPI EventPro — contexte de build : racine du monorepo
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/models

WORKDIR /app

# Torch CPU d'abord (évite les dépendances CUDA)
RUN pip install torch==2.5.1 --index-url https://download.pytorch.org/whl/cpu

COPY common /opt/eventpro/common
COPY backend/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt "/opt/eventpro/common[embeddings]"

COPY backend/app ./app

# /models appartient à l'utilisateur applicatif : le volume nommé hérite de ces droits
RUN useradd --uid 10001 --create-home appuser && mkdir -p /models && chown appuser /models
USER appuser

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
