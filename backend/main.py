"""Release Documentation Agent - FastAPI Backend.

Orchestrates a multi-agent pipeline to generate release documentation
from engineering artifacts (commits, PRs, Jira tickets).

Features:
- Multi-agent pipeline with retry and error handling
- RAG-based documentation retrieval
- Automated quality evaluation
- In-memory release store with LRU eviction
- Structured logging
- Health checks with dependency validation
"""
import os
import sys
import uuid
import time
import logging
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from openai import OpenAI
from llm_client import LLMClient
from pydantic import BaseModel, Field

from config import load_config, AppConfig, OpenAIConfig
from logger import setup_logging
from connectors.github import GitHubConnector
from connectors.jira import JiraConnector
from connectors.docs import DocsConnector
from agents.base import AgentError
from agents import digester, planner, writer, reviewer
from rag.indexer import build_index, clear_index
from rag.retriever import retrieve
from evaluation.evaluator import evaluate

load_dotenv()

# --- Configuration ---
app_config, openai_config = load_config()
logger = setup_logging(app_config.log_level)

# --- App Setup ---
app = FastAPI(
    title="Release Documentation Agent",
    description="AI-powered release documentation generation with multi-agent pipeline",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=app_config.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- In-Memory Store with LRU eviction ---
class ReleaseStore:
    """Thread-safe in-memory store with max capacity."""

    def __init__(self, max_size: int = 100):
        self._store: OrderedDict[str, dict] = OrderedDict()
        self._max_size = max_size

    def put(self, release_id: str, data: dict) -> None:
        if release_id in self._store:
            self._store.move_to_end(release_id)
        self._store[release_id] = data
        while len(self._store) > self._max_size:
            evicted_id, _ = self._store.popitem(last=False)
            logger.info(f"Evicted release {evicted_id} (store at capacity)")

    def get(self, release_id: str) -> dict | None:
        if release_id in self._store:
            self._store.move_to_end(release_id)
            return self._store[release_id]
        return None

    def list_all(self) -> list[dict]:
        return list(reversed(self._store.values()))

    def count(self) -> int:
        return len(self._store)


releases_store = ReleaseStore(max_size=app_config.max_releases_in_memory)


# --- Helpers ---
def get_llm_client():
    """Create LLM client (OpenAI or Anthropic based on config)."""
    try:
        return LLMClient()
    except (ValueError, ImportError) as e:
        raise HTTPException(
            status_code=500,
            detail=f"LLM configuration error: {e}. See backend/.env.example for setup.",
        )


def get_openai_client() -> OpenAI:
    """Create raw OpenAI client for embeddings/RAG."""
    errors = openai_config.validate()
    if errors:
        # Try to proceed without - LLMClient may handle it
        raise HTTPException(
            status_code=500,
            detail=f"Configuration error: {'; '.join(errors)}. Add OPENAI_API_KEY to backend/.env",
        )
    return OpenAI(
        api_key=openai_config.api_key,
        timeout=openai_config.timeout_seconds,
        max_retries=0,
    )


# --- Request/Response Models ---
class GenerateRequest(BaseModel):
    release_name: str = Field(
        default="v2.4.0",
        min_length=1,
        max_length=100,
        description="Release version name",
    )
    description: str = Field(
        default="",
        max_length=1000,
        description="Optional release description",
    )
    use_mock_data: bool = Field(
        default=True,
        description="Use mock data (True) or real API connections (False)",
    )


class ApproveRequest(BaseModel):
    changelog: str | None = Field(default=None, max_length=50000)
    internal_release_notes: str | None = Field(default=None, max_length=50000)
    customer_release_notes: str | None = Field(default=None, max_length=50000)


class ErrorResponse(BaseModel):
    detail: str
    error_type: str = "unknown"
    timestamp: str = ""


# --- Endpoints ---

@app.get("/api/health")
def health():
    """Health check with dependency status."""
    status = {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "releases_in_store": releases_store.count(),
        "openai_configured": bool(openai_config.api_key),
    }
    if not openai_config.api_key:
        status["status"] = "degraded"
        status["warning"] = "OPENAI_API_KEY not configured"
    return status


@app.post("/api/releases/generate")
def generate_release(request: GenerateRequest):
    """Run the full agent pipeline to generate release documentation.
    
    Pipeline stages:
    1. Data ingestion (connectors)
    2. RAG index build
    3. Digester agent (raw → structured)
    4. Planner agent (structure → plan)
    5. RAG retrieval (find relevant docs)
    6. Writer agent (plan → content)
    7. Reviewer agent (content → quality check)
    8. Evaluation (metrics computation)
    """
    start_time = time.time()
    release_id = str(uuid.uuid4())[:8]

    logger.info(f"Starting generation: {request.release_name}", extra={"release_id": release_id})

    try:
        client = get_llm_client()
    except HTTPException:
        raise

    try:
        # Stage 1: Ingest data
        github = GitHubConnector(use_mock=request.use_mock_data)
        jira = JiraConnector(use_mock=request.use_mock_data)
        docs_connector = DocsConnector()

        commits = github.get_commits()
        pull_requests = github.get_pull_requests()
        tickets = jira.get_tickets()
        existing_docs = docs_connector.get_all_documents()

        logger.info(
            f"Ingested: {len(commits)} commits, {len(pull_requests)} PRs, "
            f"{len(tickets)} tickets, {len(existing_docs)} docs"
        )

        # Stage 2: Build RAG index (uses OpenAI embeddings or local fallback)
        build_index(existing_docs, client)

        # Stage 3: Digester Agent
        digest_result = digester.digest(
            commits, pull_requests, tickets, client,
            max_retries=openai_config.max_retries,
        )
        logger.info(f"Digest complete: {digest_result.get('risk_level')} risk")

        # Stage 4: Planner Agent
        plan_result = planner.plan(
            digest_result, existing_docs, client,
            max_retries=openai_config.max_retries,
        )
        logger.info(f"Plan complete: {len(plan_result.get('doc_update_plan', []))} doc updates planned")

        # Stage 5: RAG Retrieval
        query = _build_rag_query(digest_result)
        relevant_chunks = retrieve(query, client, top_k=5, documents=existing_docs)
        logger.info(f"Retrieved {len(relevant_chunks)} relevant chunks")

        # Stage 6: Writer Agent
        relevant_docs_for_writer = [
            {"path": c["doc_path"], "section": c["section"], "content": c["content"]}
            for c in relevant_chunks
        ]
        write_result = writer.write(
            digest_result, plan_result, relevant_docs_for_writer, client,
            max_retries=openai_config.max_retries,
        )
        logger.info("Writer complete")

        # Stage 7: Reviewer Agent
        original_artifacts = {"tickets": tickets, "pull_requests": pull_requests}
        review_result = reviewer.review(
            write_result, digest_result, original_artifacts, client,
            max_retries=openai_config.max_retries,
        )
        logger.info(
            f"Review complete: score={review_result.get('overall_score')}, "
            f"approved={review_result.get('approved')}"
        )

        # Stage 8: Evaluation
        eval_result = evaluate(write_result, review_result, tickets, existing_docs)

        # Determine status
        status = "approved" if review_result.get("approved") else "review"
        if eval_result.overall_score < 0.5:
            status = "needs_revision"

        duration_ms = int((time.time() - start_time) * 1000)
        logger.info(
            f"Generation complete in {duration_ms}ms: status={status}",
            extra={"release_id": release_id, "duration_ms": duration_ms},
        )

        # Build release object
        release_data = {
            "id": release_id,
            "name": request.release_name,
            "description": request.description,
            "status": status,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "generation_time_ms": duration_ms,
            "artifacts": write_result,
            "digest": digest_result,
            "plan": plan_result,
            "review": review_result,
            "evaluation": eval_result.to_dict(),
            "source_evidence": {
                "commits": commits,
                "pull_requests": pull_requests,
                "tickets": tickets,
                "relevant_docs": relevant_chunks,
            },
        }
        releases_store.put(release_id, release_data)
        return release_data

    except AgentError as e:
        logger.error(f"Agent pipeline failed: {e}", extra={"release_id": release_id})
        raise HTTPException(
            status_code=502,
            detail=f"AI agent failed: {e.agent_name} - {str(e)}",
        )
    except Exception as e:
        logger.error(f"Unexpected error: {type(e).__name__}: {e}", extra={"release_id": release_id})
        raise HTTPException(
            status_code=500,
            detail=f"Internal error: {type(e).__name__}: {str(e)}",
        )


@app.get("/api/releases")
def list_releases():
    """List all generated releases (most recent first)."""
    return releases_store.list_all()


@app.get("/api/releases/{release_id}")
def get_release(release_id: str):
    """Get a specific release by ID."""
    release = releases_store.get(release_id)
    if release is None:
        raise HTTPException(status_code=404, detail=f"Release '{release_id}' not found")
    return release


@app.post("/api/releases/{release_id}/approve")
def approve_release(release_id: str, request: ApproveRequest):
    """Approve a release, optionally with edits to the artifacts."""
    release = releases_store.get(release_id)
    if release is None:
        raise HTTPException(status_code=404, detail=f"Release '{release_id}' not found")

    if release["status"] == "approved":
        raise HTTPException(status_code=409, detail="Release already approved")

    # Apply edits
    if request.changelog is not None:
        release["artifacts"]["changelog"] = request.changelog
    if request.internal_release_notes is not None:
        release["artifacts"]["internal_release_notes"] = request.internal_release_notes
    if request.customer_release_notes is not None:
        release["artifacts"]["customer_release_notes"] = request.customer_release_notes

    release["status"] = "approved"
    release["approved_at"] = datetime.now(timezone.utc).isoformat()
    release["edited"] = any([
        request.changelog is not None,
        request.internal_release_notes is not None,
        request.customer_release_notes is not None,
    ])

    logger.info(f"Release approved: {release_id}", extra={"release_id": release_id})
    return release


@app.post("/api/releases/{release_id}/reject")
def reject_release(release_id: str):
    """Reject a release and mark for regeneration."""
    release = releases_store.get(release_id)
    if release is None:
        raise HTTPException(status_code=404, detail=f"Release '{release_id}' not found")

    if release["status"] == "approved":
        raise HTTPException(status_code=409, detail="Cannot reject an approved release")

    release["status"] = "rejected"
    release["rejected_at"] = datetime.now(timezone.utc).isoformat()
    logger.info(f"Release rejected: {release_id}", extra={"release_id": release_id})
    return release


@app.get("/api/docs")
def list_docs():
    """List available documentation for RAG."""
    docs_connector = DocsConnector()
    return docs_connector.get_all_documents()


@app.get("/api/docs/search")
def search_docs(q: str = Query(..., min_length=1, max_length=500)):
    """Search documentation using RAG retrieval."""
    client = get_llm_client()
    docs_connector = DocsConnector()
    documents = docs_connector.get_all_documents()
    results = retrieve(q, client, top_k=5, documents=documents)
    return results


@app.delete("/api/releases/{release_id}")
def delete_release(release_id: str):
    """Delete a release from the store."""
    release = releases_store.get(release_id)
    if release is None:
        raise HTTPException(status_code=404, detail=f"Release '{release_id}' not found")
    releases_store._store.pop(release_id, None)
    return {"deleted": release_id}


@app.post("/api/rag/rebuild")
def rebuild_rag_index():
    """Force rebuild of the RAG index."""
    client = get_llm_client()
    docs_connector = DocsConnector()
    documents = docs_connector.get_all_documents()
    clear_index()
    index = build_index(documents, client, force_rebuild=True)
    return {"status": "rebuilt", "chunks": index.get("chunk_count", 0)}


# --- Helper functions ---
def _build_rag_query(digest: dict) -> str:
    """Build a rich query for RAG retrieval from the digest."""
    parts = []
    summary = digest.get("summary", "")
    if summary:
        parts.append(summary)
    systems = digest.get("affected_systems", [])
    if systems:
        parts.append(" ".join(systems))
    features = digest.get("features", [])
    if features:
        parts.append(" ".join(str(f) for f in features[:3]))
    return " ".join(parts) or "release documentation"


if __name__ == "__main__":
    import uvicorn

    # Validate config on startup
    errors = openai_config.validate()
    if errors:
        logger.warning(f"Config warnings: {'; '.join(errors)}")
        logger.warning("Set OPENAI_API_KEY in backend/.env to enable generation")

    logger.info(f"Starting server on {app_config.host}:{app_config.port}")
    uvicorn.run(
        app,
        host=app_config.host,
        port=app_config.port,
        log_level=app_config.log_level.lower(),
    )
