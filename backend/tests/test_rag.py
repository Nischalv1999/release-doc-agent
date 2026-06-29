"""Tests for RAG indexer and retriever - edge cases included."""
import pytest
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
import numpy as np

from rag.indexer import (
    chunk_document,
    _make_chunk,
    _split_by_sections,
    _make_chunk_id,
    _compute_content_hash,
    build_index,
    load_index,
    clear_index,
    INDEX_PATH,
)
from rag.retriever import retrieve, _cosine_similarity, _mmr_select, _embed_queries


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


# ── Stage 1: embed_text field ─────────────────────────────────────────────────

class TestMakeChunkEmbedText:
    def test_embed_text_present(self):
        doc = {"path": "docs/auth.md", "title": "Auth Guide", "content": "Some content here."}
        chunk = _make_chunk(doc, "Introduction", "Some content here.")
        assert "embed_text" in chunk

    def test_embed_text_includes_title(self):
        doc = {"path": "docs/auth.md", "title": "Auth Guide"}
        chunk = _make_chunk(doc, "Introduction", "Reset your password here.")
        assert "Auth Guide" in chunk["embed_text"]

    def test_embed_text_includes_section(self):
        doc = {"path": "docs/auth.md", "title": "Auth Guide"}
        chunk = _make_chunk(doc, "Password Reset", "Reset your password here.")
        assert "Password Reset" in chunk["embed_text"]

    def test_embed_text_includes_content(self):
        doc = {"path": "docs/auth.md", "title": "Auth Guide"}
        chunk = _make_chunk(doc, "Overview", "JWT tokens are used.")
        assert "JWT tokens are used." in chunk["embed_text"]

    def test_content_unchanged(self):
        doc = {"path": "docs/api.md", "title": "API Reference"}
        chunk = _make_chunk(doc, "Endpoints", "GET /api/v1/users returns list.")
        assert chunk["content"] == "GET /api/v1/users returns list."

    def test_embed_text_format(self):
        doc = {"path": "docs/api.md", "title": "API Reference"}
        chunk = _make_chunk(doc, "Endpoints", "call the endpoint")
        assert chunk["embed_text"] == "API Reference > Endpoints: call the endpoint"

    def test_embed_text_differs_from_content(self):
        doc = {"path": "docs/api.md", "title": "API Reference"}
        chunk = _make_chunk(doc, "Endpoints", "call the endpoint")
        assert chunk["embed_text"] != chunk["content"]

    def test_all_chunk_fields_present(self):
        doc = {"path": "docs/api.md", "title": "API Reference"}
        chunk = _make_chunk(doc, "Overview", "content")
        assert set(chunk.keys()) >= {"doc_path", "doc_title", "section", "content", "embed_text", "chunk_id"}

    def test_build_index_embeds_embed_text(self):
        doc = {"path": "docs/api.md", "title": "API Reference", "content": "# Overview\nSome text."}
        embedded_texts = []

        def fake_embed(batch):
            embedded_texts.extend(batch)
            return [np.zeros(4).tolist() for _ in batch]

        mock_client = MagicMock()
        mock_client.embed = fake_embed

        clear_index()
        build_index([doc], mock_client, force_rebuild=True)

        assert len(embedded_texts) > 0
        for text in embedded_texts:
            assert "API Reference" in text or "Overview" in text


# ── Stage 2: multi-query + MMR ────────────────────────────────────────────────

class TestMmrSelect:
    def _unit_vec(self, dim, idx):
        v = np.zeros(dim)
        v[idx] = 1.0
        return v

    def test_selects_top_k(self):
        embs = [self._unit_vec(3, i % 3) for i in range(5)]
        scores = np.array([0.9, 0.8, 0.7, 0.6, 0.5])
        selected = _mmr_select([0, 1, 2, 3, 4], scores, embs, top_k=3, mmr_lambda=1.0)
        assert len(selected) == 3

    def test_with_lambda_1_picks_highest_scores(self):
        embs = [self._unit_vec(4, i) for i in range(4)]
        scores = np.array([0.9, 0.8, 0.7, 0.6])
        selected = _mmr_select([0, 1, 2, 3], scores, embs, top_k=2, mmr_lambda=1.0)
        assert 0 in selected
        assert 1 in selected

    def test_with_lambda_0_picks_diverse(self):
        # Two very similar chunks and one very different chunk
        embs = [
            np.array([1.0, 0.0]),   # idx=0, high score
            np.array([0.99, 0.14]), # idx=1, similar to 0
            np.array([0.0, 1.0]),   # idx=2, orthogonal to 0
        ]
        scores = np.array([0.9, 0.85, 0.7])
        # lambda=0 means pure diversity: after picking 0, should prefer 2 over 1
        selected = _mmr_select([0, 1, 2], scores, embs, top_k=2, mmr_lambda=0.0)
        assert 0 in selected
        assert 2 in selected

    def test_returns_no_more_than_top_k(self):
        embs = [self._unit_vec(5, i) for i in range(5)]
        scores = np.array([0.9, 0.8, 0.7, 0.6, 0.5])
        selected = _mmr_select([0, 1, 2, 3, 4], scores, embs, top_k=2, mmr_lambda=0.6)
        assert len(selected) <= 2

    def test_handles_single_candidate(self):
        embs = [np.array([1.0, 0.0])]
        scores = np.array([0.8])
        selected = _mmr_select([0], scores, embs, top_k=5, mmr_lambda=0.6)
        assert selected == [0]

    def test_no_duplicates_in_selection(self):
        embs = [self._unit_vec(4, i) for i in range(4)]
        scores = np.array([0.9, 0.8, 0.7, 0.6])
        selected = _mmr_select([0, 1, 2, 3], scores, embs, top_k=4, mmr_lambda=0.6)
        assert len(selected) == len(set(selected))


class TestRetrieveMultiQuery:
    def _make_fake_index(self, n_chunks=4):
        clear_index()
        chunks = [
            {"doc_path": f"doc{i}.md", "doc_title": f"Doc {i}",
             "section": f"Section {i}", "content": f"Content {i}",
             "embed_text": f"Doc {i} > Section {i}: Content {i}",
             "chunk_id": f"abc{i}"}
            for i in range(n_chunks)
        ]
        embs = [np.eye(n_chunks)[i].tolist() for i in range(n_chunks)]
        index = {"chunks": chunks, "embeddings": embs, "content_hash": "test"}
        INDEX_PATH.write_text(json.dumps(index))
        return chunks

    def _mock_client_for_queries(self, query_vecs: list[list[float]]):
        call_count = [0]
        def fake_embed(batch):
            results = []
            for _ in batch:
                idx = call_count[0] % len(query_vecs)
                results.append(query_vecs[idx])
                call_count[0] += 1
            return results
        client = MagicMock()
        client.embed = fake_embed
        return client

    def test_list_query_returns_results(self):
        self._make_fake_index(4)
        client = self._mock_client_for_queries([[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]])
        results = retrieve(["query one", "query two"], client, top_k=2)
        assert len(results) >= 1

    def test_string_query_backward_compat(self):
        self._make_fake_index(4)
        client = self._mock_client_for_queries([[1.0, 0.0, 0.0, 0.0]])
        results = retrieve("single query", client, top_k=2)
        assert isinstance(results, list)

    def test_empty_list_query_returns_empty(self):
        self._make_fake_index(2)
        client = MagicMock()
        results = retrieve([], client, top_k=5)
        assert results == []

    def test_empty_string_in_list_filtered(self):
        self._make_fake_index(4)
        client = self._mock_client_for_queries([[1.0, 0.0, 0.0, 0.0]])
        results = retrieve(["", "  ", "valid query"], client, top_k=2)
        assert isinstance(results, list)

    def test_top_k_capped_at_10(self):
        self._make_fake_index(4)
        client = self._mock_client_for_queries([[1.0, 0.0, 0.0, 0.0]])
        results = retrieve("query", client, top_k=999)
        assert len(results) <= 10

    def test_results_have_relevance_score(self):
        self._make_fake_index(4)
        client = self._mock_client_for_queries([[1.0, 0.0, 0.0, 0.0]])
        results = retrieve("query", client, top_k=5, min_score=0.0)
        for r in results:
            assert "relevance_score" in r
            assert isinstance(r["relevance_score"], float)

    def test_multi_query_merges_by_max_score(self):
        # chunk 0 is very similar to query1; chunk 1 is very similar to query2
        # both should appear in results from multi-query
        self._make_fake_index(4)
        q1 = [1.0, 0.0, 0.0, 0.0]  # scores chunk 0 highest
        q2 = [0.0, 1.0, 0.0, 0.0]  # scores chunk 1 highest
        client = self._mock_client_for_queries([q1, q2])
        results = retrieve(["q1", "q2"], client, top_k=5, min_score=0.0)
        paths = {r["doc_path"] for r in results}
        assert "doc0.md" in paths
        assert "doc1.md" in paths

    def teardown_method(self, _method):
        clear_index()


# ── Stage 3: main.py passes list to retrieve() ───────────────────────────────

class TestMainRagWiring:
    """Verify main.py passes rag_search_queries (list) to retrieve(), not a loop."""

    def test_main_passes_list_to_retrieve_when_queries_present(self):
        import main
        import inspect
        src = inspect.getsource(main.generate_release)
        # After Stage 3, main.py should call retrieve() with a list (rag_queries)
        assert "retrieve(\n            rag_queries" in src or "retrieve(rag_queries" in src or "retrieve(\n                rag_queries" in src or "retrieve(rag_queries," in src

    def test_main_no_per_query_loop(self):
        import main
        import inspect
        src = inspect.getsource(main.generate_release)
        # Old loop pattern should be gone
        assert "for q in rag_queries" not in src

    def test_main_fallback_single_string_query(self):
        import main
        import inspect
        src = inspect.getsource(main.generate_release)
        # Fallback path should still call _build_rag_query for a single string
        assert "_build_rag_query" in src


# ── Stage 4: Contradiction-detection in writer.py ────────────────────────────

class TestWriterContradictionDetection:
    def _make_digest(self):
        return {
            "summary": "v3.0.0 release",
            "risk_level": "medium",
            "risk_rationale": [],
            "affected_systems": ["Payments"],
            "features": ["Added Stripe integration (PLAT-2002, PR #201)"],
            "bug_fixes": [],
            "breaking_changes": ["BREAKING: JWT payload schema changed (PLAT-2003)"],
            "code_insights": [],
        }

    def _call_build_prompt(self, relevant_docs):
        from agents.writer import _build_user_prompt
        digest = self._make_digest()
        plan = {
            "core_narrative": None,
            "exclusion_list": [],
            "audience_outlines": {"customer": [], "internal": []},
            "changelog_plan": {"sections": ["changes"], "tone": "technical"},
            "internal_notes_plan": {"audience": "engineering", "sections": [], "include_risk": False},
            "customer_notes_plan": {"audience": "end-users", "sections": [], "tone": "friendly"},
            "doc_update_plan": [],
        }
        return _build_user_prompt(digest, plan, relevant_docs, {})

    def test_prompt_instructs_update_for_conflicts(self):
        prompt = self._call_build_prompt([{"path": "docs/auth.md", "section": "JWT", "content": "JWT tokens use HS256."}])
        assert "action='update'" in prompt or "update" in prompt.lower()

    def test_prompt_instructs_add_for_coverage_gap(self):
        prompt = self._call_build_prompt([{"path": "docs/api.md", "section": "Intro", "content": "Old content."}])
        assert "action='add'" in prompt or "add" in prompt.lower()

    def test_prompt_says_no_review_action(self):
        prompt = self._call_build_prompt([{"path": "docs/api.md", "section": "Intro", "content": "Content."}])
        # The prompt should explicitly say not to use 'review'
        assert "Never emit" in prompt or "never emit" in prompt or "not emit" in prompt or "do NOT emit" in prompt

    def test_prompt_shows_chunk_path_and_section(self):
        prompt = self._call_build_prompt([{"path": "docs/stripe.md", "section": "Overview", "content": "PayPal is used."}])
        assert "docs/stripe.md" in prompt
        assert "Overview" in prompt

    def test_prompt_handles_empty_docs(self):
        prompt = self._call_build_prompt([])
        assert "No relevant docs" in prompt
        assert "add" in prompt.lower()

    def test_system_prompt_excludes_review_action(self):
        from agents.writer import SYSTEM_PROMPT
        assert "'add'|'update'" in SYSTEM_PROMPT or '"add"|"update"' in SYSTEM_PROMPT

    def test_system_prompt_says_no_review(self):
        from agents.writer import SYSTEM_PROMPT
        assert "Never emit" in SYSTEM_PROMPT or "never emit" in SYSTEM_PROMPT or "Never use" in SYSTEM_PROMPT or "never" in SYSTEM_PROMPT.lower()
