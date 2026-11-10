# Imagen de la API y del trabajador (misma imagen, distinto comando).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# OCR de materiales (workflows/knowledge.py busca el binario `tesseract`), como en la imagen del VPS.
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-spa \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY services/api/pyproject.toml services/api/README.md ./
COPY services/api/src ./src
COPY services/api/migrations ./migrations
COPY services/api/alembic.ini ./alembic.ini
COPY infra/api-requirements.txt ./requirements.txt
# uv.lock del VPS no incluye defusedxml ni reportlab: se instalan con las mismas versiones
# que usó el despliegue (deployments/vps-20261030-r33/api.Dockerfile.deployed).
RUN pip install -r requirements.txt \
    && pip install defusedxml==0.7.1 reportlab==4.5.1 \
    && pip install --no-deps .
# Contrato de voz empaquetado; elevenlabs_setup.py lo busca en /opt/uno-voice.
COPY infra/elevenlabs /opt/uno-voice

# Usuario sin privilegios
RUN useradd --system --uid 10001 uno
USER uno

EXPOSE 8000
CMD ["uvicorn", "uno.main:app_factory", "--factory", "--host", "0.0.0.0", "--port", "8000"]
