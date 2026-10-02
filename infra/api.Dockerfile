# Imagen de la API y del trabajador (misma imagen, distinto comando).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY services/api/pyproject.toml services/api/README.md ./
COPY services/api/src ./src
COPY services/api/migrations ./migrations
COPY services/api/alembic.ini ./alembic.ini
COPY infra/api-requirements.txt ./requirements.txt
RUN pip install -r requirements.txt && pip install --no-deps .

# Usuario sin privilegios
RUN useradd --system --uid 10001 uno
USER uno

EXPOSE 8000
CMD ["uvicorn", "uno.main:app_factory", "--factory", "--host", "0.0.0.0", "--port", "8000"]
