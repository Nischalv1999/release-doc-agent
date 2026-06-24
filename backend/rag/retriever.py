"""RAG Retriever - Finds relevant documentation chunks for a query."""
import numpy as np
from openai import OpenAI

from .indexer import load_index, build_index, _get_embeddings


def retrieve(query: str, client: OpenAI, top_k: int = 5, documents: list | None = None) -> list[dict]:
    """Retrieve the most relevant document chunks for a query."""
    index = load_index()
    if index is None:
        if documents is None:
            return []
        index = build_index(documents, client)
    
    # Embed the query
    query_embedding = _get_embeddings([query], client)[0]
    
    # Compute cosine similarity against all chunks
    similarities = []
    for emb in index["embeddings"]:
        emb_array = np.array(emb) if not isinstance(emb, np.ndarray) else emb
        sim = _cosine_similarity(query_embedding, emb_array)
        similarities.append(sim)
    
    # Get top-k results
    top_indices = np.argsort(similarities)[-top_k:][::-1]
    
    results = []
    for idx in top_indices:
        chunk = index["chunks"][idx].copy()
        chunk["relevance_score"] = float(similarities[idx])
        results.append(chunk)
    
    return results


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity between two vectors."""
    dot = np.dot(a, b)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(dot / (norm_a * norm_b))
