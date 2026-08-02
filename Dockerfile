# Image applicative : API + scripts d'ingestion.
# La base tourne dans son propre conteneur (voir docker-compose.yml).
FROM python:3.11-slim

# Les modèles sont téléchargés au premier usage dans ce répertoire, monté en volume
# pour éviter de les retélécharger à chaque reconstruction (2,2 Go pour e5-large).
ENV HF_HOME=/modeles \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Les dépendances changent moins souvent que le code : couche séparée pour le cache Docker.
COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install -e . 2>/dev/null || true

COPY src/ ./src/
COPY scripts/ ./scripts/
COPY evaluation/ ./evaluation/
COPY sql/ ./sql/
RUN pip install -e .

EXPOSE 8000

CMD ["uvicorn", "src.api:application", "--host", "0.0.0.0", "--port", "8000"]
