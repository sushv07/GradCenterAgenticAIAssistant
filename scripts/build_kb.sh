#!/usr/bin/env bash
# scripts/build_kb.sh
# Build, validate, and package the Chroma knowledge base for Render deployment.
#
# This script must be run from the project root or from scripts/:
#   ./scripts/build_kb.sh           # reuse existing store if still fresh (<24h)
#   ./scripts/build_kb.sh --rebuild # force-fetch live CSULB pages and re-embed
#
# Output: chroma_db.tar.gz (~3–4 MB compressed)
#
# After this script completes successfully, upload chroma_db.tar.gz to the
# Render persistent disk. See README.md → "Populate Render Chroma Disk".
#
# Prerequisites:
#   source .venv/bin/activate   (or equivalent)
#   pip install -r requirements.txt

set -euo pipefail
cd "$(dirname "$0")/.."

REBUILD_FLAG="${1:-}"
TARBALL="chroma_db.tar.gz"

echo "========================================"
echo "CSULB Grad Center — KB Build & Package"
echo "========================================"

# ---------------------------------------------------------------------------
# 1. Build (or rebuild) the vector store
# ---------------------------------------------------------------------------
if [[ "$REBUILD_FLAG" == "--rebuild" ]]; then
    echo ""
    echo "[1/4] Force-rebuilding from live CSULB pages..."
    echo "      Fetches and re-embeds all pages. Takes ~2–5 min."
    python -m rag.store --rebuild
else
    echo ""
    echo "[1/4] Building vector store (reusing existing store if still fresh)..."
    python -m rag.store
fi

# ---------------------------------------------------------------------------
# 2. Ingestion evals — must pass before packaging
# ---------------------------------------------------------------------------
echo ""
echo "[2/4] Running ingestion evals (gate: all 21 must pass)..."
if ! python evals/run_ingestion_evals.py --ci; then
    echo ""
    echo "ERROR: Ingestion evals FAILED — aborting. Do not upload this KB."
    exit 1
fi

# ---------------------------------------------------------------------------
# 3. KB health report — informational (does not block packaging)
# ---------------------------------------------------------------------------
echo ""
echo "[3/4] KB health check..."
python -m obs.kb_health_report

# ---------------------------------------------------------------------------
# 4. Package
# ---------------------------------------------------------------------------
echo ""
echo "[4/4] Packaging chroma_db/ → ${TARBALL}..."
tar -czf "${TARBALL}" chroma_db/
SIZE=$(du -sh "${TARBALL}" | cut -f1)

echo ""
echo "========================================"
echo "Done: ${TARBALL} (${SIZE})"
echo "========================================"
echo ""
echo "Next: upload to Render persistent disk."
echo "See README.md -> 'Populate Render Chroma Disk' for upload instructions."
