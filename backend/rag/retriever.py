"""RAG Retriever - Finds relevant documentation chunks for a query.

Handles:
- Empty queries
- No index available (auto-builds)
- Zero-vector edge case
- Score thresholding (filter low-relevance results)
- Multi-query retrieval with MMR diversity
"""
import logging

import numpy as np

from .indexer import load_index, build_index

logger = logging.getLogger("release_agent")

# Minimum relevance score to include in results
MIN_RELEVANCE_THRESHOLD = 0.1

# MMR balance: higher = more relevance, lower = more diversity
_MMR_LAMBDA = 0.6

# Over-retrieve this many candidates before MMR (capped at chunk count)
_CANDIDATE_K = 20


def retrieve(
    query: str | list[str],
    client,
    top_k: int = 5,
    documents: list | None = None,
    min_score: float = MIN_RELEVANCE_THRESHOLD,
) -> list[dict]:
    """Retrieve the most relevant document chunks for a query.

    Accepts a single query string or a list of query strings. When a list
    is given, each query is embedded separately and chunks are scored by
    their maximum similarity across all queries. Over-retrieval + MMR then
    produces a diverse final set.

    Args:
        query: Natural language search query, or list of queries
        client: LLMClient or OpenAI client
        top_k: Maximum number of results to return (capped at 10)
        documents: Documents to index if no index exists
        min_score: Minimum relevance score threshold

    Returns:
        List of chunk dicts with relevance_score, sorted by relevance
    """
    top_k = min(top_k, 10)

    queries = [query] if isinstance(query, str) else list(query)
    queries = [q for q in queries if q and q.strip()]
    if not queries:
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

    embeddings = index["embeddings"]

    # Embed all queries
    query_embeddings = _embed_queries(queries, client)
    if not query_embeddings:
        return []

    # Score each chunk by max similarity across all query embeddings
    n_chunks = len(embeddings)
    max_scores = np.full(n_chunks, -1.0)
    for q_emb in query_embeddings:
        for i, chunk_emb in enumerate(embeddings):
            emb_arr = chunk_emb if isinstance(chunk_emb, np.ndarray) else np.array(chunk_emb)
            sim = _cosine_similarity(q_emb, emb_arr)
            if sim > max_scores[i]:
                max_scores[i] = sim

    # Gather candidates above threshold (over-retrieve before MMR)
    candidate_k = min(_CANDIDATE_K, n_chunks)
    sorted_indices = np.argsort(max_scores)[::-1]
    candidate_indices = []
    for idx in sorted_indices[:candidate_k]:
        if max_scores[idx] >= min_score:
            candidate_indices.append(int(idx))

    if not candidate_indices:
        logger.info(f"RAG: no chunks above threshold {min_score}")
        return []

    # Apply MMR to select diverse final set
    selected_indices = _mmr_select(
        candidate_indices, max_scores, embeddings, top_k, _MMR_LAMBDA
    )

    results = []
    for idx in selected_indices:
        chunk = index["chunks"][idx].copy()
        chunk["relevance_score"] = float(max_scores[idx])
        results.append(chunk)

    logger.info(
        f"RAG retrieved {len(results)} chunks "
        f"({len(queries)} quer{'y' if len(queries)==1 else 'ies'}, "
        f"{len(candidate_indices)} candidates, MMR applied)"
    )
    return results


def _embed_queries(queries: list[str], client) -> list[np.ndarray]:
    """Embed a list of query strings. Returns empty list on failure."""
    try:
        texts = [q.strip() for q in queries]
        if hasattr(client, "embed") and callable(client.embed):
            vectors = client.embed(texts)
            return [np.array(v) for v in vectors]
        else:
            response = client.embeddings.create(
                model="text-embedding-3-small",
                input=texts,
            )
            return [np.array(item.embedding) for item in response.data]
    except Exception as e:
        logger.error(f"Failed to embed queries: {e}")
        return []


def _mmr_select(
    candidate_indices: list[int],
    scores: np.ndarray,
    embeddings: list,
    top_k: int,
    mmr_lambda: float,
) -> list[int]:
    """Select up to top_k diverse chunks using Maximal Marginal Relevance.

    MMR balances relevance (cosine sim to query) and diversity (dissimilarity
    to already-selected chunks). mmr_lambda=1.0 is pure relevance; 0.0 is
    pure diversity.
    """
    selected: list[int] = []
    selected_embs: list[np.ndarray] = []
    remaining = list(candidate_indices)

    for _ in range(min(top_k, len(remaining))):
        best_idx = None
        best_mmr = float("-inf")

        for idx in remaining:
            relevance = float(scores[idx])
            if selected_embs:
                emb = embeddings[idx] if isinstance(embeddings[idx], np.ndarray) else np.array(embeddings[idx])
                redundancy = max(_cosine_similarity(emb, s) for s in selected_embs)
            else:
                redundancy = 0.0
            mmr_val = mmr_lambda * relevance - (1 - mmr_lambda) * redundancy
            if mmr_val > best_mmr:
                best_mmr = mmr_val
                best_idx = idx

        if best_idx is None:
            break
        selected.append(best_idx)
        emb = embeddings[best_idx] if isinstance(embeddings[best_idx], np.ndarray) else np.array(embeddings[best_idx])
        selected_embs.append(emb)
        remaining.remove(best_idx)

    return selected


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity between two vectors. Handles zero vectors."""
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))
