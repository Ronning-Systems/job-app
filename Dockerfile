FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for psycopg2 and pdfplumber
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY backend/ ./backend/
COPY agents/ ./agents/
COPY static/ ./static/

EXPOSE 8080

ENV PYTHONPATH=/app/backend
ENV AUTH0_DOMAIN=""
ENV AUTH0_AUDIENCE="https://jobsync/api"
ENV CORS_ORIGIN="http://localhost:8000"
ENV MODEL_GENERATION=""
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8080"]