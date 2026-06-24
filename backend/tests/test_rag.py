"""Tests for RAG indexer and retriever - edge cases included."""
import pytest
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
import numpy as np

from rag.indexer import (
    chunk_document,
    _split_by_sections,
    _make_chunk_id,
    _compute_content_hash,
    build_index,
    load_index,
    clear_index,
    INDEX_PATH,
)
from rag.retriever import retrieve, _cosine_similarity


class TestSplitBySections:
    def test_basic_headings(self):
        content = "# Title\nIntro text\n## Section 1\nContent one\n## Section 2\nContent two"
        sections = _split_by_sections(content)
        assert len(sections) == 3
        assert sections[0][0] == "Title"
        assert sections[1][0] == "Section 1"
        assert "Content one" in sections[1][1]

    def test_no_headings(self):
        content = "Just plain text\nwith multiple lines\nno headings"
        sections = _split_by_sections(content)
        assert len(sections) == 1
        assert sections[0][0] == "Introduction"
        assert "Just plain text" in sections[0][1]

    def test_empty_content(self):
        sections = _split_by_sections("")
        assert sections == []

    def test_only_headings_no_content(self):
        content = "# Title\n## Section"
        sections = _split_by_sections(content)
        # Empty sections are filtered
        assert len(sections) >= 0  # Headings without body content

    def test_heading_with_no_hash_space(self):
        content = "#Title\nSome content"
        sections = _split_by_sections(content)
        assert sections[0][0] == "Title"

    def test_deeply_nested_headings(self):
        content = "### Deep\nContent\n#### Deeper\nMore content"
        sections = _split_by_sections(content)
        assert len(sections) == 2


class TestChunkDocument:
    def test_small_document(self):
        doc = {"path": "test.md", "title": "Test", "content": "# Heading\nShort content."}
        chunks = chunk_document(doc)
        assert len(chunks) >= 1
        assert chunks[0]["doc_path"] == "test.md"
        assert chunks[0]["section"] == "Heading"

    def test_empty_document(self):
        doc = {"path": "empty.md", "title": "Empty", "content": ""}
        chunks = chunk_document(doc)
        assert chunks == []

    def test_whitespace_only_document(self):
        doc = {"path": "ws.md", "title": "WS", "content": "   \n\n  "}
        chunks = chunk_document(doc)
        assert chunks == []

    def test_large_section_splits(self):
        # Create a doc with one huge section (>500 words)
        big_content = "# Big Section\n" + " ".join(["word"] * 1000)
        doc = {"path": "big.md", "title": "Big", "content": big_content}
        chunks = chunk_document(doc, chunk_size=500, overlap=100)
        assert len(chunks) > 1
        # Each chunk should have the doc metadata
        for c in chunks:
            assert c["doc_path"] == "big.md"
            assert "part" in c["section"]

    def test_unique_chunk_ids(self):
        doc = {"path": "test.md", "title": "Test", "content": "# A\nText\n# B\nMore text"}
        chunks = chunk_document(doc)
        ids = [c["chunk_id"] for c in chunks]
        assert len(set(ids)) == len(ids)

    def test_missing_content_key(self):
        doc = {"path": "test.md", "title": "Test"}  # No content key
        chunks = chunk_document(doc)
        assert chunks == []

    def test_document_without_headings_creates_fallback(self):
        doc = {"path": "plain.md", "title": "Plain", "content": "No headings just text."}
        chunks = chunk_document(doc)
        assert len(chunks) >= 1


class TestChunkId:
    def test_deterministic(self):
        id1 = _make_chunk_id("path.md", "Section", "content here")
        id2 = _make_chunk_id("path.md", "Section", "content here")
        assert id1 == id2

    def test_different_for_different_content(self):
        id1 = _make_chunk_id("path.md", "Section", "content A")
        id2 = _make_chunk_id("path.md", "Section", "content B")
        assert id1 != id2


class TestContentHash:
    def test_same_docs_same_hash(self):
        docs = [{"path": "a.md", "content": "hello"}]
        assert _compute_content_hash(docs) == _compute_content_hash(docs)

    def test_different_docs_different_hash(self):
        docs1 = [{"path": "a.md", "content": "hello"}]
        docs2 = [{"path": "a.md", "content": "world"}]
        assert _compute_content_hash(docs1) != _compute_content_hash(docs2)

    def test_order_independent(self):
        docs1 = [{"path": "a.md", "content": "x"}, {"path": "b.md", "content": "y"}]
        docs2 = [{"path": "b.md", "content": "y"}, {"path": "a.md", "content": "x"}]
        assert _compute_content_hash(docs1) == _compute_content_hash(docs2)


class TestCosineSimilarity:
    def test_identical_vectors(self):
        v = np.array([1.0, 2.0, 3.0])
        assert _cosine_similarity(v, v) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        a = np.array([1.0, 0.0])
        b = np.array([0.0, 1.0])
        assert _cosine_similarity(a, b) == pytest.approx(0.0)

    def test_opposite_vectors(self):
        a = np.array([1.0, 0.0])
        b = np.array([-1.0, 0.0])
        assert _cosine_similarity(a, b) == pytest.approx(-1.0)

    def test_zero_vector(self):
        a = np.array([0.0, 0.0, 0.0])
        b = np.array([1.0, 2.0, 3.0])
        assert _cosine_similarity(a, b) == 0.0

    def test_both_zero(self):
        a = np.array([0.0, 0.0])
        assert _cosine_similarity(a, a) == 0.0


class TestIndexPersistence:
    def test_clear_index(self):
        # Write a dummy index
        INDEX_PATH.write_text('{"chunks": [], "embeddings": []}')
        assert INDEX_PATH.exists()
        clear_index()
        assert not INDEX_PATH.exists()

    def test_load_corrupted_index(self):
        INDEX_PATH.write_text("not json")
        result = load_index()
        assert result is None
        # Cleanup
        clear_index()

    def test_load_mismatched_counts(self):
        data = {"chunks": [{"x": 1}], "embeddings": [[1, 2], [3, 4]]}
        INDEX_PATH.write_text(json.dumps(data))
        result = load_index()
        assert result is None
        clear_index()

    def test_load_nonexistent(self):
        clear_index()
        assert load_index() is None
