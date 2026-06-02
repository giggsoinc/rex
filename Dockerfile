FROM python:3.11-slim AS base

WORKDIR /app

# System deps for unstructured and magic
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmagic1 \
    poppler-utils \
    tesseract-ocr \
    libreoffice-core \
    && rm -rf /var/lib/apt/lists/*

# Python deps
COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[dev]" 2>/dev/null || pip install --no-cache-dir .

# App code
COPY src/ src/
COPY .env.local .env.local

EXPOSE 8501

CMD ["streamlit", "run", "src/rex/ui/app.py", "--server.port=8501", "--server.address=0.0.0.0"]
