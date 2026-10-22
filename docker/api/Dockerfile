# API del comedor (FastAPI). Contexto de build: la raíz del repositorio.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY comedorback/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY comedorback/alembic.ini ./
COPY comedorback/alembic ./alembic
COPY comedorback/app ./app
COPY --chmod=755 docker/api/entrypoint.sh /entrypoint.sh

RUN useradd --system --uid 1000 comedor
USER comedor

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=40s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/salud',timeout=2).status==200 else 1)"
ENTRYPOINT ["/entrypoint.sh"]
