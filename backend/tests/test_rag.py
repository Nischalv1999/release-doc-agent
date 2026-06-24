"""Tests for RAG indexer (unit tests that don't require OpenAI)."""
from rag.indexer import chunk_document, _split_by_sections


def test_split_by_sections():
    content = "# Title\nIntro text\n## Section 1\nContent one\n## Section 2\nContent two"
    sections = _split_by_sections(content)
    assert len(sections) == 3
    assert sections[0][0] == "Title"
    assert sections[1][0] == "Section 1"
    assert "Content one" in sections[1][1]


def test_chunk_document_small():
    doc = {"path": "test.md", "title": "Test", "content": "# Heading\nShort content here."}
    chunks = chunk_document(doc)
    assert len(chunks) >= 1
    assert chunks[0]["doc_path"] == "test.md"
    assert chunks[0]["section"] == "Heading"


def test_chunk_document_produces_ids():
    doc = {"path": "test.md", "title": "Test", "content": "# A\nText\n# B\nMore text"}
    chunks = chunk_document(doc)
    ids = [c["chunk_id"] for c in chunks]
    assert len(set(ids)) == len(ids)  # All unique
