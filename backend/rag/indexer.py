"""RAG Indexer - Chunks and embeds documentation for retrieval."""
import json
import hashlib
from pathlib import Path
from typing import Any

import numpy as np
from openai import OpenAI

INDEX_PATH = Path(__file__).parent.parent / "rag_index.json"


def chunk_document(doc: dict[str, str], chunk_size: int = 500, overlap: int = 100) -> list[dict]:
    """Split a document into overlapping chunks for embedding."""
    content = doc["content"]
    chunks = []
    
    # Split by sections (headings) first for semantic coherence
    sections = _split_by_sections(content)
    
    for section_title, section_content in sections:
        # If section is small enough, keep as one chunk
        if len(section_content) <= chunk_size:
            chunks.append({
                "doc_path": doc["path"],
                "doc_title": doc["title"],
                "section": section_title,
                "content": section_content,
                "chunk_id": _make_chunk_id(doc["path"], section_title, section_content),
            })
        else:
            # Split large sections into overlapping chunks
            words = section_content.split()
            for i in range(0, len(words), chunk_size - overlap):
                chunk_text = " ".join(words[i:i + chunk_size])
                chunks.append({
                    "doc_path": doc["path"],
                    "doc_title": doc["title"],
                    "section": section_title,
                    "content": chunk_text,
                    "chunk_id": _make_chunk_id(doc["path"], section_title, chunk_text[:50]),
                })
    return chunks


def build_index(documents: list[dict], client: OpenAI) -> dict[str, Any]:
    """Build a vector index from documents."""
    all_chunks = []
    for doc in documents:
        all_chunks.extend(chunk_document(doc))
    
    # Get embeddings for all chunks
    texts = [c["content"] for c in all_chunks]
    embeddings = _get_embeddings(texts, client)
    
    index = {
        "chunks": all_chunks,
        "embeddings": [e.tolist() for e in embeddings],
    }
    
    # Persist to disk
    INDEX_PATH.write_text(json.dumps(index))
    return index


def load_index() -> dict[str, Any] | None:
    """Load existing index from disk."""
    if INDEX_PATH.exists():
        data = json.loads(INDEX_PATH.read_text())
        data["embeddings"] = [np.array(e) for e in data["embeddings"]]
        return data
    return None


def _get_embeddings(texts: list[str], client: OpenAI) -> list[np.ndarray]:
    """Get embeddings from OpenAI API in batches."""
    all_embeddings = []
    batch_size = 100
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        response = client.embeddings.create(
            model="text-embedding-3-small",
            input=batch,
        )
        for item in response.data:
            all_embeddings.append(np.array(item.embedding))
    return all_embeddings


def _split_by_sections(content: str) -> list[tuple[str, str]]:
    """Split markdown content by headings."""
    lines = content.split("\n")
    sections = []
    current_title = "Introduction"
    current_lines = []
    
    for line in lines:
        if line.startswith("#"):
            if current_lines:
                sections.append((current_title, "\n".join(current_lines).strip()))
            current_title = line.lstrip("#").strip()
            current_lines = []
        else:
            current_lines.append(line)
    
    if current_lines:
        sections.append((current_title, "\n".join(current_lines).strip()))
    
    return sections


def _make_chunk_id(path: str, section: str, content: str) -> str:
    return hashlib.md5(f"{path}:{section}:{content[:50]}".encode()).hexdigest()[:12]
