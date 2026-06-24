"""RAG Retriever - Finds relevant documentation chunks for a query.

Handles:
- Empty queries
- No index available (auto-builds)
- Zero-vector edge case
- Score thresholding (filter low-relevance results)
"""
import logging

import numpy as np
from openai import OpenAI

from .indexer import load_index, build_index

logger = logging.getLogger("release_agent")

# Minimum relevance score to include in results
MIN_RELEVANCE_THRESHOLD = 0.1


def retrieve(
    query: str,
    client: OpenAI,
    top_k: int = 5,
    documents: list | None = None,
    min_score: float = MIN_RELEVANCE_THRESHOLD,
) -> list[dict]:
    """Retrieve the most relevant document chunks for a query.
    
    Args:
        query: Natural language search query
        client: OpenAI client for embedding
        top_k: Maximum number of results to return
        documents: Documents to index if no index exists
        min_score: Minimum relevance score threshold
        
    Returns:
        List of chunk dicts with relevance_score, sorted by relevance
    """
    if not query or not query.strip():
        logger.warning("Empty retrieval query")
        return []

    # Load or build index
    index = load_index()
    if index is None:
        if documents is None or not documents:
            logger.warning("No RAG index and no documents to build from")
            return []
        index = build_index(documents, client)

    if not index.get("chunks") or not index.get("embeddings"):
        logger.warning("RAG index is empty")
        return []

    # Embed the query
    try:
        response = client.embeddings.create(
            model="text-embedding-3-small",
            input=[query.strip()],
        )
        query_embedding = np.array(response.data[0].embedding)
    except Exception as e:
        logger.error(f"Failed to embed query: {e}")
        return []

    # Compute cosine similarity against all chunks
    similarities = []
    for emb in index["embeddings"]:
        emb_array = np.array(emb) if not isinstance(emb, np.ndarray) else emb
        sim = _cosine_similarity(query_embedding, emb_array)
        similarities.append(sim)

    if not similarities:
        return []

    # Get top-k results above threshold
    sorted_indices = np.argsort(similarities)[::-1]

    results = []
    for idx in sorted_indices:
        if len(results) >= top_k:
            break
        score = float(similarities[idx])
        if score < min_score:
            break  # Remaining are even lower
        chunk = index["chunks"][idx].copy()
        chunk["relevance_score"] = score
        results.append(chunk)

    logger.info(f"RAG retrieved {len(results)} chunks (query: {query[:50]}...)")
    return results


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity between two vectors. Handles zero vectors."""
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))
