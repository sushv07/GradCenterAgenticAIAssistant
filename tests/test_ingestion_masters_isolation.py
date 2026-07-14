"""
tests/test_ingestion_masters_isolation.py
Architecture invariants for the ingestion package (AST-based).

Ingestion MAY use bs4/stdlib/pydantic/urllib and import domain read-only, but
must never import retrieval/RAG/Chroma/embedding/experiment/inference roots.
The domain must never import ingestion. No " 2" duplicate files are referenced,
and no vector store / model weight is created.

Run: pytest tests/test_ingestion_masters_isolation.py -v
"""
from __future__ import annotations

import ast
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

ROOT = Path(__file__).parent.parent
INGESTION = ROOT / "ingestion"
DOMAIN = ROOT / "domain"
_SKIP_DIRS = {".venv", "venv", "__pycache__", ".git", "node_modules", "chroma_db"}

_FORBIDDEN_FOR_INGESTION = {
    "langchain", "langchain_community", "langchain_core", "langchain_text_splitters",
    "chromadb", "chroma", "sentence_transformers", "torch", "transformers",
    "ollama", "openai", "faiss", "pinecone", "peft", "trl", "bitsandbytes",
    "rag", "retrieval", "experiments", "orchestrator",
}
_DUP2_IMPORT = re.compile(r"(from|import)\s+[\w.]* 2(\.|\s|$)")


def _py_files(root: Path):
    for path in root.rglob("*.py"):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        if " 2." in path.name:
            continue
        yield path


def _imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if not (node.level or 0) and node.module:
                roots.add(node.module.split(".")[0])
    return roots


class TestIngestionImports(unittest.TestCase):
    def test_ingestion_imports_no_forbidden_infra(self):
        offenders = []
        for path in _py_files(INGESTION):
            bad = _imported_roots(path) & _FORBIDDEN_FOR_INGESTION
            if bad:
                offenders.append(f"{path.relative_to(ROOT)}: {sorted(bad)}")
        self.assertEqual(offenders, [], f"ingestion imports forbidden infra: {offenders}")

    def test_ingestion_may_depend_on_domain(self):
        # sanity: the pipeline genuinely consumes the domain (read-only)
        roots = _imported_roots(INGESTION / "masters" / "normalization.py")
        self.assertIn("domain", roots)


class TestDomainDoesNotImportIngestion(unittest.TestCase):
    def test_domain_free_of_ingestion(self):
        offenders = [str(p.relative_to(ROOT)) for p in _py_files(DOMAIN)
                     if "ingestion" in _imported_roots(p)]
        self.assertEqual(offenders, [], f"domain imports ingestion: {offenders}")


class TestNoDuplicateFileReferences(unittest.TestCase):
    def test_no_space2_imports(self):
        offenders = []
        for path in list(_py_files(INGESTION)) + list((ROOT / "tests").glob("test_ingestion_masters_*.py")):
            for line in path.read_text(encoding="utf-8").splitlines():
                if _DUP2_IMPORT.search(line):
                    offenders.append(f"{path.name}: {line.strip()}")
        self.assertEqual(offenders, [], f"' 2' references: {offenders}")


class TestNoHeavyArtifacts(unittest.TestCase):
    def test_no_vector_store_or_weights_in_ingestion(self):
        for pattern in ("*.safetensors", "*.bin", "*.gguf", "*.pt", "chroma.sqlite3"):
            hits = list(INGESTION.rglob(pattern))
            self.assertEqual(hits, [], f"unexpected artifact: {hits}")


if __name__ == "__main__":
    unittest.main()
