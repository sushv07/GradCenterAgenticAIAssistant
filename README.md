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

## Cloud Deployment (Render)

The project includes a `render.yaml` Blueprint for one-click deployment
to [Render](https://render.com).

> **Warnings before you deploy**
> - LLM features (`LLM_SYNTHESIS_ENABLED`, `LLM_EXPLANATION_ENABLED`) are
>   **off by default**. The assistant runs fully without Ollama.
> - Ollama is **not included** in the Render deployment. If you want LLM
>   features in production, you need a separately hosted Ollama instance and
>   must update `OLLAMA_BASE_URL` in the Render dashboard.
> - The Chroma vector store (`chroma_db/`) is **not committed to git** and is
>   not baked into the Docker image. On first deploy it is built automatically
>   from live CSULB pages (~30–60 s). Configure the persistent disk below so
>   the store survives restarts.

### Requirements

- Render account
- **Starter plan or higher** (free tier has no persistent disk — the vector
  store would rebuild on every cold start, which is ~30–60 s after every
  ~15 minutes of inactivity)

### Deploy with the Blueprint (recommended)

1. Push this repository to GitHub.
2. In the Render dashboard: **New → Blueprint** → select your repo.
3. Render reads `render.yaml` and creates the `gradcenter-ai` web service
   with a 1 GB persistent disk at `/app/chroma_db`.
4. The first deploy builds the Docker image (includes the embedding model).
   When the first request arrives, the app fetches CSULB pages and builds
   the Chroma store onto the disk (~30–60 s, one time only).
5. All subsequent requests (and restarts) load the store from disk in < 1 s.

### Deploy manually (dashboard)

If you prefer not to use the Blueprint:

1. **New → Web Service** → connect your GitHub repo.
2. Environment: **Docker**.
3. Dockerfile path: `./Dockerfile`.
4. Plan: **Starter** (required for the persistent disk).
5. Health check path: `/health`.
6. Add environment variables (all optional — defaults shown):

   | Key | Default value |
   |---|---|
   | `LLM_SYNTHESIS_ENABLED` | `false` |
   | `LLM_EXPLANATION_ENABLED` | `false` |
   | `OLLAMA_BASE_URL` | `http://localhost:11434` |
   | `LLM_SYNTHESIS_MODEL` | `qwen2.5:7b-instruct` |
   | `LLM_SYNTHESIS_TIMEOUT_S` | `30` |

7. **Disks** tab → **Add Disk**:
   - Name: `chroma-db`
   - Mount path: `/app/chroma_db`
   - Size: 1 GB

### Persistent data on Render

| What | Where it lives | Notes |
|---|---|---|
| Chroma vector store | Render persistent disk → `/app/chroma_db/` | **Required**. Built on first request, reused across restarts. |
| Logs | Container filesystem (ephemeral) | Lost on restart. Render streams logs in the dashboard. |
| Eval reports | Container filesystem (ephemeral) | Run evals locally, not in production. |

### Memory constraints

The Render Starter plan has 512 MB RAM. The readiness endpoint (`/ready`) is
optimized for this constraint:

- `/ready` performs a **passive disk check** only — it verifies `chroma.sqlite3`
  is present on disk without loading the embedding model or instantiating Chroma.
- The embedding model (`all-MiniLM-L6-v2`, ~200 MB in-process) loads lazily on
  the **first `/query` request**.
- On first deploy the persistent disk is empty, so `/ready` returns HTTP 503
  (`"vector_store": {"ok": false, "detail": "chroma.sqlite3 not present"}`) until
  the first `/query` triggers the store build (~30–60 s, one time).

### Deployment verification

Replace `<render-url>` with your service URL (e.g.
`gradcenter-ai.onrender.com`):

```bash
# Liveness — always returns 200 if the process is running
curl https://<render-url>/health

# Readiness — passive disk check; 503 until first /query populates the store
curl https://<render-url>/ready

# Swagger UI — interactive API docs
open https://<render-url>/docs

# First query — triggers vector store build if not already populated (~30–60 s)
curl -X POST https://<render-url>/query \
  -H "Content-Type: application/json" \
  -d '{"query": "How do I apply to a doctoral program at CSULB?"}'

# Readiness after first query — should now return 200
curl https://<render-url>/ready
```

Expected responses:

| Endpoint | Expected |
|---|---|
| `/health` | `{"status": "ok", "service": "csulb-grad-center-assistant", ...}` |
| `/ready` (before first query) | `{"status": "degraded", ...}` HTTP 503 — store not yet built |
| `/ready` (after first query) | `{"status": "ok", ...}` HTTP 200 |
| `/docs` | Swagger UI with `/`, `/health`, `/ready`, `/query` |
| `/query` | JSON with routing and retrieval results |

### Populate Render Chroma Disk

Render Starter (512 MB RAM) cannot safely build the vector store inside the
container — the initial ingest + embed cycle may exceed the memory limit.
Build the knowledge base locally and upload the prebuilt artifact instead.

#### Step 1 — Build and validate locally

```bash
# Reuse existing local store if still fresh (<24h), or:
./scripts/build_kb.sh

# Force a full rebuild from live CSULB pages (~2–5 min):
./scripts/build_kb.sh --rebuild
```

The script runs three checks before packaging:
1. Builds (or reuses) the Chroma vector store
2. Runs all 21 ingestion eval cases — aborts if any fail
3. Prints a KB health report

On success it produces `chroma_db.tar.gz` (~3–4 MB).

#### Step 2 — Upload to Render disk

Render Shell is available from the Render dashboard (your service → **Shell**
tab). The persistent disk is already mounted at `/app/chroma_db/` inside the
container.

**Option A — download from a URL (recommended)**

Host `chroma_db.tar.gz` anywhere reachable over HTTPS (e.g. a GitHub Release
asset, a private S3 bucket). In the Render Shell:

```bash
curl -L https://<url>/chroma_db.tar.gz | tar -xz -C /app/
touch /app/chroma_db/.last_built
ls -lh /app/chroma_db/
```

`touch .last_built` resets the 24-hour freshness TTL so the next cold start
loads from disk instead of triggering a rebuild.

**Option B — scp (if your Render plan supports it)**

```bash
# From your local machine — copy the tarball to the container
scp chroma_db.tar.gz <render-ssh-string>:/app/

# In the Render Shell — extract and reset TTL
tar -xzf /app/chroma_db.tar.gz -C /app/
touch /app/chroma_db/.last_built
ls -lh /app/chroma_db/
```

Find `<render-ssh-string>` in the Render dashboard under your service →
**Shell → SSH**.

#### Step 3 — Verify

After extraction, verify from anywhere:

```bash
# Should return {"status": "ok", "checks": {..., "vector_store": {"ok": true}}}
curl https://<render-url>/ready

# First RAG query — loads embedding model (~200-400 MB) + reads from disk
curl -X POST https://<render-url>/query \
  -H "Content-Type: application/json" \
  -d '{"query": "What GPA do I need for graduate admission?"}'
```

#### TTL and re-upload

The `.last_built` freshness window is 24 hours. After a cold start > 24h after
the last `touch`, the app tries to rebuild from live pages — which may OOM.

To reset the TTL without re-uploading the full artifact, run in the Render Shell:

```bash
touch /app/chroma_db/.last_built
```

To fully refresh the knowledge base (e.g. after CSULB pages change):

```bash
./scripts/build_kb.sh --rebuild   # locally
# re-upload chroma_db.tar.gz to Render disk
```

---

## Architecture

See `ARCHITECTURE_ANALYSIS.md` for a detailed phase-by-phase breakdown
of every design decision, module, and implementation note.
