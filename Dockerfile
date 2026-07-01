FROM python:3.13-slim

WORKDIR /app

# Build tools required by chromadb (C extensions), sentence-transformers,
# and rapidfuzz.  Removed after install to keep the final image small.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first so this layer is cached as long as
# requirements.txt is unchanged — source code edits don't bust it.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download the embedding model at build time so the container starts
# without requiring network access or a ~90 MB download on first request.
# Model is cached at /root/.cache/huggingface/hub/ inside the image.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

# Copy application source
COPY . .

# Ensure runtime directories exist even when no volumes are mounted.
# chroma_db and logs are expected to be volume-mounted in production.
RUN mkdir -p chroma_db logs evals/reports obs/reports

EXPOSE 8000

# Liveness probe hits /health — the endpoint is deterministic and never
# touches the vector store, so it responds immediately after uvicorn starts.
# start-period gives the process time to bind before checks begin.
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["uvicorn", "api.app:app", "--host", "0.0.0.0", "--port", "8000"]
