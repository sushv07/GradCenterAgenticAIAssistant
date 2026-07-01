# CSULB Graduate Center AI Assistant

An agentic AI assistant for CSULB Graduate Center prospective students.
Covers application steps, deadlines, program recommendations, advisor
contact, eligibility, and FAQ — backed by a local RAG knowledge base
(Chroma + sentence-transformers) and an optional local LLM (Ollama).

---

## Local Development

### Prerequisites

- Python 3.13
- [Ollama](https://ollama.ai) (optional — required only for LLM synthesis features)

### Setup

```bash
# 1. Create and activate a virtual environment
python3.13 -m venv .venv
source .venv/bin/activate        # macOS / Linux
# .venv\Scripts\activate          # Windows

# 2. Install dependencies
pip install -r requirements.txt

# 3. (Optional) Copy and edit environment variables
cp .env.example .env
```

### Build the knowledge base

The Chroma vector store must be built before the app can answer queries.
This step fetches live CSULB pages — requires internet access.

```bash
python rag/store.py
```

The store is written to `chroma_db/`.

### Run the FastAPI service

```bash
uvicorn api.app:app --reload
```

Endpoints:
- `GET  /`        — service identity
- `GET  /health`  — liveness check
- `GET  /ready`   — readiness check (exercises the vector store)
- `POST /query`   — submit a question (body: `{"query": "...", "session_id": "..."}`)

### Run the Streamlit UI

```bash
streamlit run app.py
```

Opens at `http://localhost:8501`.

### Run tests

```bash
pytest tests/
```

### Run evaluations

```bash
python evals/run_recommendation_evals.py
python evals/run_retrieval_evals.py
python evals/run_llm_evals.py
python evals/run_advisor_evals.py
python evals/run_ingestion_evals.py
python evals/weight_validation.py
python evals/run_evals.py --skip-known-failures
```

---

## Docker

### Requirements

- Docker 20.10+ with Compose v2 (`docker compose`)
- A built `chroma_db/` directory on the host (see "Build the knowledge base" above)
- (Optional) Ollama running on the host for LLM features

### Start

```bash
docker compose up --build
```

This builds the image (if not already cached), mounts all data volumes,
loads environment variables from `.env` if present, and starts the FastAPI
service on port 8000.

### Stop

```bash
docker compose down
```

### Where data persists

All application data lives on the host, not inside the container:

| Host path | Purpose |
|---|---|
| `./chroma_db/` | Chroma vector store — **required**. Build once with `python rag/store.py`. |
| `./logs/` | Structured NDJSON observability log (`gradcenter.log`). |
| `./evals/reports/` | Timestamped eval runner output. |
| `./obs/reports/` | KB health, drift reports, and baseline snapshots. |

Stopping or removing the container does not affect any of these directories.
`chroma_db/` is the only required mount — without it `/ready` returns 503
and retrieval queries fail gracefully.

### With LLM features enabled

Ollama runs on the host machine, not inside the container. Set
`OLLAMA_BASE_URL` to reach it from within Docker:

```bash
cp .env.example .env
# Edit .env:
#   LLM_SYNTHESIS_ENABLED=true
#   LLM_EXPLANATION_ENABLED=true
#   OLLAMA_BASE_URL=http://host.docker.internal:11434  # macOS / Windows
#   OLLAMA_BASE_URL=http://172.17.0.1:11434            # Linux
docker compose up --build
```

`docker-compose.yml` loads `.env` automatically when the file exists.
Without `.env`, all LLM features stay off — the assistant runs in its
full deterministic mode with no Ollama dependency.

### Verify

```bash
curl http://localhost:8000/health
curl http://localhost:8000/ready
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"query": "How do I apply?"}'
```

### Ports

| Port | Service |
|------|---------|
| 8000 | FastAPI (uvicorn) |

The Streamlit UI (`app.py`) is not exposed by the Docker image — it is
intended for local development only.

### Environment variables

See `.env.example` for the full list with descriptions. All variables are
optional; the application runs without LLM features when none are set.

### Raw Docker commands (without Compose)

If Compose is unavailable, the equivalent `docker run` command is:

```bash
docker build -t gradcenter-ai .
docker run -p 8000:8000 \
  -v "$(pwd)/chroma_db:/app/chroma_db" \
  -v "$(pwd)/logs:/app/logs" \
  -v "$(pwd)/evals/reports:/app/evals/reports" \
  -v "$(pwd)/obs/reports:/app/obs/reports" \
  --env-file .env \
  gradcenter-ai
```

---

## Architecture

See `ARCHITECTURE_ANALYSIS.md` for a detailed phase-by-phase breakdown
of every design decision, module, and implementation note.
