"""
experiments/rag_vs_finetuning/embeddings/embedder.py
Experiment-only embedding service (Phase P6).

Wraps the project's confirmed model (all-MiniLM-L6-v2) via sentence-transformers
directly — no LangChain, no LLM, no production-RAG import. A deterministic
FakeEmbedder is provided for offline unit tests so the default suite never
downloads a model. Validation fails on empty content, wrong dimension, and
NaN/inf vectors. Input ordering is preserved.

Reproducibility: within one locked environment (same model files, library
versions, device, normalization) vector values are stable; bit-for-bit equality
is NOT claimed across different hardware/library backends.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from typing import Protocol


class EmbeddingError(Exception):
    pass


@dataclass
class EmbedderInfo:
    model_id: str
    dimension: int
    normalize: bool
    library: str
    library_version: str
    device: str
    model_revision: str = "unknown"


class Embedder(Protocol):
    info: EmbedderInfo
    def embed(self, texts: list[str]) -> list[list[float]]: ...


def _validate(vectors: list[list[float]], *, dimension: int) -> None:
    for v in vectors:
        if len(v) != dimension:
            raise EmbeddingError(f"vector dimension {len(v)} != expected {dimension}")
        for x in v:
            if math.isnan(x) or math.isinf(x):
                raise EmbeddingError("vector contains NaN or infinite value")


def _check_inputs(texts: list[str]) -> None:
    for i, t in enumerate(texts):
        if not isinstance(t, str) or not t.strip():
            raise EmbeddingError(f"empty content at index {i}")


class SentenceTransformerEmbedder:
    """Real embedder using the project's model. Loads sentence-transformers
    lazily so importing this module never requires the model library."""

    def __init__(self, *, model_id: str = "all-MiniLM-L6-v2", device: str = "cpu",
                 normalize: bool = True, batch_size: int = 32):
        import sentence_transformers as st  # lazy
        self._model = st.SentenceTransformer(model_id, device=device)
        self._normalize = normalize
        self._batch_size = batch_size
        dim = int(self._model.get_sentence_embedding_dimension())
        self.info = EmbedderInfo(
            model_id=model_id, dimension=dim, normalize=normalize,
            library="sentence-transformers", library_version=st.__version__,
            device=device)

    def embed(self, texts: list[str]) -> list[list[float]]:
        _check_inputs(texts)
        arr = self._model.encode(
            list(texts), batch_size=self._batch_size,
            normalize_embeddings=self._normalize, convert_to_numpy=True,
            show_progress_bar=False)
        vectors = [[float(x) for x in row] for row in arr]
        _validate(vectors, dimension=self.info.dimension)
        return vectors


class FakeEmbedder:
    """Deterministic hash-based embedder for offline tests (no model download)."""

    def __init__(self, *, dimension: int = 384, normalize: bool = True):
        self.info = EmbedderInfo(
            model_id="fake-deterministic", dimension=dimension, normalize=normalize,
            library="fake", library_version="0", device="cpu")

    def embed(self, texts: list[str]) -> list[list[float]]:
        _check_inputs(texts)
        dim = self.info.dimension
        vectors: list[list[float]] = []
        for t in texts:
            seed = hashlib.sha256(t.encode("utf-8")).digest()
            raw = [(seed[i % len(seed)] - 128) / 128.0 for i in range(dim)]
            if self.info.normalize:
                norm = math.sqrt(sum(x * x for x in raw)) or 1.0
                raw = [x / norm for x in raw]
            vectors.append(raw)
        _validate(vectors, dimension=dim)
        return vectors


def embed_chunks(embedder, chunks) -> list[list[float]]:
    """Embed chunk contents in order, preserving input ordering."""
    return embedder.embed([c.content for c in chunks])
