"""
tests/test_experiment_isolation.py
Architecture-boundary guards for the experiment package (Phase P5, AST-based).

- projection imports only stdlib / pydantic / domain / experiments.projection —
  never ingestion, LangChain, Chroma, embeddings, vector stores, or production RAG;
- freeze may import ingestion + domain (it materializes via the pipeline) but not
  infra/RAG/embeddings;
- production code never imports experiments;
- no " 2" duplicate files referenced; no vector store / model weights created.

Run: pytest tests/test_experiment_isolation.py -v
"""
from __future__ import annotations

import ast
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

ROOT = Path(__file__).parent.parent
EXP = ROOT / "experiments"
PROJECTION = EXP / "rag_vs_finetuning" / "projection"
FREEZE = EXP / "rag_vs_finetuning" / "freeze"
_SKIP = {".venv", "venv", "__pycache__", ".git", "node_modules", "chroma_db"}

_INFRA = {
    "langchain", "langchain_community", "langchain_core", "langchain_text_splitters",
    "chromadb", "chroma", "sentence_transformers", "torch", "transformers",
    "ollama", "openai", "faiss", "pinecone", "rag", "retrieval", "orchestrator",
    "routing", "api", "backend",
}
_DUP2 = re.compile(r"(from|import)\s+[\w.]* 2(\.|\s|$)")


def _py(root: Path):
    for p in root.rglob("*.py"):
        if any(part in _SKIP for part in p.parts) or " 2." in p.name:
            continue
        yield p


def _roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                out.add(a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and not (node.level or 0) and node.module:
            out.add(node.module.split(".")[0])
    return out


class TestProjectionIsEngineIndependent(unittest.TestCase):
    def test_projection_imports_allowlisted_only(self):
        allowed = {"experiments", "domain", "pydantic", "typing", "typing_extensions"}
        stdlib = set(getattr(sys, "stdlib_module_names", set()))
        offenders = []
        for p in _py(PROJECTION):
            for r in _roots(p):
                if r in allowed or r in stdlib:
                    continue
                offenders.append(f"{p.relative_to(ROOT)}: {r}")
        self.assertEqual(offenders, [], f"projection has unexpected imports: {offenders}")

    def test_projection_does_not_import_ingestion(self):
        offenders = [str(p.relative_to(ROOT)) for p in _py(PROJECTION) if "ingestion" in _roots(p)]
        self.assertEqual(offenders, [], f"projection imports ingestion: {offenders}")


class TestFreezeBoundaries(unittest.TestCase):
    def test_freeze_has_no_infra_imports(self):
        offenders = []
        for p in _py(FREEZE):
            bad = _roots(p) & _INFRA
            if bad:
                offenders.append(f"{p.relative_to(ROOT)}: {sorted(bad)}")
        self.assertEqual(offenders, [], f"freeze imports infra: {offenders}")


class TestProductionDoesNotImportExperiments(unittest.TestCase):
    def test_no_production_module_imports_experiments(self):
        offenders = []
        for p in _py(ROOT):
            rel = p.relative_to(ROOT)
            if rel.parts and rel.parts[0] in ("tests", "experiments"):
                continue
            if "experiments" in _roots(p):
                offenders.append(str(rel))
        self.assertEqual(offenders, [], f"production imports experiments: {offenders}")


class TestP6Boundaries(unittest.TestCase):
    def test_chunk_model_does_not_import_chroma_or_langchain(self):
        offenders = []
        for p in _py(EXP / "rag_vs_finetuning" / "chunking"):
            bad = _roots(p) & {"chromadb", "chroma", "langchain", "langchain_community"}
            if bad:
                offenders.append(f"{p.relative_to(ROOT)}: {sorted(bad)}")
        self.assertEqual(offenders, [], f"chunking imports chroma/langchain: {offenders}")

    def test_chroma_import_confined_to_index_package(self):
        offenders = []
        for p in _py(EXP):
            if "chromadb" in _roots(p) and p.parent.name != "index":
                offenders.append(str(p.relative_to(ROOT)))
        self.assertEqual(offenders, [], f"chromadb imported outside index/: {offenders}")

    def test_domain_and_ingestion_do_not_import_chroma_or_experiment_index(self):
        offenders = []
        for pkg in (ROOT / "domain", ROOT / "ingestion"):
            for p in _py(pkg):
                bad = _roots(p) & {"chromadb", "experiments", "sentence_transformers"}
                if bad:
                    offenders.append(f"{p.relative_to(ROOT)}: {sorted(bad)}")
        self.assertEqual(offenders, [], f"domain/ingestion import experiment infra: {offenders}")


class TestNoDuplicateRefsOrArtifacts(unittest.TestCase):
    def test_no_space2_imports(self):
        offenders = []
        for p in _py(EXP):
            for line in p.read_text(encoding="utf-8").splitlines():
                if _DUP2.search(line):
                    offenders.append(f"{p.name}: {line.strip()}")
        self.assertEqual(offenders, [], offenders)

    def test_no_committed_vector_store_or_weights(self):
        # artifacts/checkpoints/models are git-ignored generated locations; a
        # Chroma DB there is expected in P6. Only COMMITTABLE paths must be clean.
        ignored = {"artifacts", "checkpoints", "models"}
        for pattern in ("chroma.sqlite3", "*.safetensors", "*.bin", "*.gguf", "*.pt"):
            hits = [p for p in EXP.rglob(pattern)
                    if not any(x in _SKIP or x in ignored for x in p.parts)]
            self.assertEqual(hits, [], f"unexpected committed artifact: {hits}")


if __name__ == "__main__":
    unittest.main()
