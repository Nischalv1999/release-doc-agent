"""RAG Indexer - Chunks and embeds documentation for retrieval.

Handles:
- Empty documents
- Documents with no headings
- Embedding API failures (retry)
- Index persistence and cache invalidation
- Unicode content safely
"""
import json
import hashlib
import logging
import time
from pathlib import Path
from typing import Any

import numpy as np


logger = logging.getLogger("release_agent")

INDEX_PATH = Path(__file__).parent.parent / "rag_index.json"


def chunk_document(
    doc: dict[str, str],
    chunk_size: int = 500,
    overlap: int = 100,
) -> list[dict]:
    """Split a document into overlapping chunks for embedding.
    
    Strategy:
    1. Split by markdown headings for semantic coherence
    2. If a section exceeds chunk_size words, split with overlap
    3. Each chunk retains full metadata for retrieval transparency
    
    Args:
        doc: Document with path, title, content keys
        chunk_size: Maximum words per chunk
        overlap: Overlap words between consecutive chunks
        
    Returns:
        List of chunk dictionaries
    """
    content = doc.get("content", "")
    if not content.strip():
        logger.warning(f"Empty document: {doc.get('path', 'unknown')}")
        return []

    sections = _split_by_sections(content)
    chunks = []

    for section_title, section_content in sections:
        if not section_content.strip():
            continue

        word_count = len(section_content.split())

        if word_count <= chunk_size:
            chunks.append(_make_chunk(doc, section_title, section_content))
        else:
            # Split large sections with overlap
            words = section_content.split()
            step = max(1, chunk_size - overlap)
            for i in range(0, len(words), step):
                chunk_words = words[i:i + chunk_size]
                if not chunk_words:
                    break
                chunk_text = " ".join(chunk_words)
                chunk_idx = i // step
                chunks.append(_make_chunk(
                    doc, f"{section_title} (part {chunk_idx + 1})", chunk_text
                ))

    if not chunks:
        # Fallback: treat entire document as one chunk
        chunks.append(_make_chunk(doc, "Full Document", content[:2000]))

    return chunks


def build_index(
    documents: list[dict],
    client,
    force_rebuild: bool = False,
) -> dict[str, Any]:
    """Build a vector index from documents.
    
    Features:
    - Content-hash based cache invalidation
    - Batch embedding with retry
    - Graceful handling of empty corpora
    
    Args:
        documents: List of document dicts with path, title, content
        client: LLMClient or OpenAI client for embedding
        force_rebuild: Skip cache and rebuild from scratch
        
    Returns:
        Index dictionary with chunks and embeddings
    """
    if not documents:
        logger.warning("No documents to index")
        return {"chunks": [], "embeddings": [], "content_hash": ""}

    # Check cache validity
    content_hash = _compute_content_hash(documents)
    if not force_rebuild:
        existing = load_index()
        if existing and existing.get("content_hash") == content_hash:
            logger.info("RAG index cache hit - skipping rebuild")
            return existing

    logger.info(f"Building RAG index from {len(documents)} documents")
    all_chunks = []
    for doc in documents:
        doc_chunks = chunk_document(doc)
        all_chunks.extend(doc_chunks)

    if not all_chunks:
        logger.warning("No chunks produced from documents")
        return {"chunks": [], "embeddings": [], "content_hash": content_hash}

    logger.info(f"Produced {len(all_chunks)} chunks, embedding...")

    # Embed title+heading+content for better recall; "content" stays unchanged for display
    texts = [c["embed_text"] for c in all_chunks]
    embeddings = _get_embeddings_with_retry(texts, client)

    if len(embeddings) != len(all_chunks):
        logger.error(
            f"Embedding count mismatch: {len(embeddings)} embeddings for {len(all_chunks)} chunks"
        )
        # Truncate to match
        min_len = min(len(embeddings), len(all_chunks))
        all_chunks = all_chunks[:min_len]
        embeddings = embeddings[:min_len]

    index = {
        "chunks": all_chunks,
        "embeddings": [e.tolist() for e in embeddings],
        "content_hash": content_hash,
        "built_at": time.time(),
        "chunk_count": len(all_chunks),
    }

    # Persist to disk
    try:
        INDEX_PATH.write_text(json.dumps(index))
        logger.info(f"RAG index saved: {len(all_chunks)} chunks")
    except IOError as e:
        logger.error(f"Failed to persist RAG index: {e}")

    return index


def load_index() -> dict[str, Any] | None:
    """Load existing index from disk. Returns None if not found or corrupted."""
    if not INDEX_PATH.exists():
        return None
    try:
        data = json.loads(INDEX_PATH.read_text())
        # Validate structure
        if "chunks" not in data or "embeddings" not in data:
            logger.warning("Corrupted RAG index - missing fields")
            return None
        if len(data["chunks"]) != len(data["embeddings"]):
            logger.warning("Corrupted RAG index - count mismatch")
            return None
        # Convert embeddings back to numpy
        data["embeddings"] = [np.array(e) for e in data["embeddings"]]
        return data
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"Failed to load RAG index: {e}")
        return None


def clear_index() -> None:
    """Delete the persisted index (useful for testing)."""
    if INDEX_PATH.exists():
        INDEX_PATH.unlink()


def _get_embeddings_with_retry(
    texts: list[str],
    client,
    batch_size: int = 50,
    max_retries: int = 3,
) -> list[np.ndarray]:
    """Get embeddings using LLMClient or raw OpenAI client with retry."""
    all_embeddings: list[np.ndarray] = []

    # Ensure no empty strings
    texts = [t if t.strip() else "empty" for t in texts]

    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]

        for attempt in range(1, max_retries + 1):
            try:
                # Support both LLMClient and raw OpenAI client
                if hasattr(client, 'embed') and callable(client.embed):
                    vectors = client.embed(batch)
                    for v in vectors:
                        all_embeddings.append(np.array(v))
                else:
                    response = client.embeddings.create(
                        model="text-embedding-3-small",
                        input=batch,
                    )
                    for item in response.data:
                        all_embeddings.append(np.array(item.embedding))
                break
            except Exception as e:
                if "rate" in str(e).lower() or "429" in str(e):
                    wait = 2 ** attempt
                    logger.warning(f"Rate limited on embeddings, waiting {wait}s")
                    time.sleep(wait)
                else:
                    logger.error(f"Embedding error: {e}")
                    if attempt == max_retries:
                        for _ in batch:
                            all_embeddings.append(np.zeros(1536))
                    time.sleep(1)

    return all_embeddings


def _split_by_sections(content: str) -> list[tuple[str, str]]:
    """Split markdown content by headings. Handles edge cases."""
    lines = content.split("\n")
    sections: list[tuple[str, str]] = []
    current_title = "Introduction"
    current_lines: list[str] = []

    for line in lines:
        if line.startswith("#"):
            if current_lines:
                text = "\n".join(current_lines).strip()
                if text:
                    sections.append((current_title, text))
            current_title = line.lstrip("#").strip() or "Untitled Section"
            current_lines = []
        else:
            current_lines.append(line)

    # Don't forget the last section
    if current_lines:
        text = "\n".join(current_lines).strip()
        if text:
            sections.append((current_title, text))

    # If no sections found (no headings), treat whole doc as one section
    if not sections and content.strip():
        sections.append(("Full Document", content.strip()))

    return sections


def _make_chunk(doc: dict, section_title: str, content: str) -> dict:
    """Create a chunk dictionary with metadata."""
    doc_title = doc.get("title", "Unknown")
    return {
        "doc_path": doc.get("path", "unknown"),
        "doc_title": doc_title,
        "section": section_title,
        "content": content,
        "embed_text": f"{doc_title} > {section_title}: {content}",
        "chunk_id": _make_chunk_id(doc.get("path", ""), section_title, content),
    }


def _make_chunk_id(path: str, section: str, content: str) -> str:
    """Generate a deterministic chunk ID."""
    raw = f"{path}:{section}:{content[:100]}"
    return hashlib.md5(raw.encode("utf-8", errors="replace")).hexdigest()[:12]


_EMBED_FORMAT_VERSION = b"v2-title-section-content"


def _compute_content_hash(documents: list[dict]) -> str:
    """Compute a hash of all document content for cache invalidation."""
    hasher = hashlib.sha256()
    hasher.update(_EMBED_FORMAT_VERSION)
    for doc in sorted(documents, key=lambda d: d.get("path", "")):
        hasher.update(doc.get("path", "").encode())
        hasher.update(doc.get("content", "").encode("utf-8", errors="replace"))
    return hasher.hexdigest()[:16]
