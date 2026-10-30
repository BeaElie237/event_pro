# Image Airflow 3 + Java (Spark local) + PySpark + sentence-transformers (CPU)
# Contexte de build : racine du monorepo (voir docker-compose.yml)
FROM apache/airflow:3.0.6-python3.11

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends openjdk-17-jre-headless curl \
    && apt-get clean && rm -rf /var/lib/apt/lists/* \
    # JAVA_HOME indépendant de l'architecture (amd64 / arm64)
    && ln -s "$(dirname "$(dirname "$(readlink -f "$(command -v java)")")")" /opt/java

ENV JAVA_HOME=/opt/java

# Driver JDBC PostgreSQL pour l'écriture Spark -> staging_events
ARG POSTGRES_JDBC_VERSION=42.7.4
RUN mkdir -p /opt/spark-jars \
    && curl -fsSL -o /opt/spark-jars/postgresql.jar \
       "https://repo1.maven.org/maven2/org/postgresql/postgresql/${POSTGRES_JDBC_VERSION}/postgresql-${POSTGRES_JDBC_VERSION}.jar"

USER airflow
ENV HF_HOME=/opt/airflow/models
RUN mkdir -p /opt/airflow/models

# Torch CPU d'abord (évite ~2 Go de dépendances CUDA)
RUN pip install --no-cache-dir torch==2.5.1 --index-url https://download.pytorch.org/whl/cpu

COPY --chown=airflow:root common /opt/eventpro/common
COPY --chown=airflow:root airflow/requirements.txt /opt/eventpro/airflow-requirements.txt
RUN pip install --no-cache-dir \
    "apache-airflow==${AIRFLOW_VERSION}" \
    -r /opt/eventpro/airflow-requirements.txt \
    "/opt/eventpro/common[embeddings]"
