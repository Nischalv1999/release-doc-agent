"""Release Documentation Agent - FastAPI Backend.

Orchestrates a multi-agent pipeline to generate release documentation
from engineering artifacts (commits, PRs, Jira tickets).
"""
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from openai import OpenAI
from pydantic import BaseModel

from connectors.github import GitHubConnector
from connectors.jira import JiraConnector
from connectors.docs import DocsConnector
from agents import digester, planner, writer, reviewer
from rag.indexer import build_index
from rag.retriever import retrieve
from evaluation.evaluator import evaluate

load_dotenv()

app = FastAPI(
    title="Release Documentation Agent",
    description="AI-powered release documentation generation",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory store for releases (would be a DB in production)
releases_store: dict[str, dict] = {}


def get_openai_client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="OPENAI_API_KEY not set. Add it to backend/.env",
        )
    return OpenAI(api_key=api_key)


# --- Request/Response Models ---

class GenerateRequest(BaseModel):
    release_name: str = "v2.4.0"
    description: str = ""
    use_mock_data: bool = True


class ApproveRequest(BaseModel):
    changelog: str | None = None
    internal_release_notes: str | None = None
    customer_release_notes: str | None = None


# --- Endpoints ---

@app.get("/api/health")
def health():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


@app.post("/api/releases/generate")
def generate_release(request: GenerateRequest):
    """Run the full agent pipeline to generate release documentation."""
    client = get_openai_client()

    # 1. Ingest data
    github = GitHubConnector(use_mock=request.use_mock_data)
    jira = JiraConnector(use_mock=request.use_mock_data)
    docs_connector = DocsConnector()

    commits = github.get_commits()
    pull_requests = github.get_pull_requests()
    tickets = jira.get_tickets()
    existing_docs = docs_connector.get_all_documents()

    # 2. Build RAG index from existing docs
    build_index(existing_docs, client)

    # 3. Digester Agent - analyze artifacts
    digest_result = digester.digest(commits, pull_requests, tickets, client)

    # 4. Planner Agent - plan documentation
    plan_result = planner.plan(digest_result, existing_docs, client)

    # 5. RAG Retrieval - find relevant existing docs
    query = f"{digest_result.get('summary', '')} {' '.join(digest_result.get('affected_systems', []))}"
    relevant_chunks = retrieve(query, client, top_k=5, documents=existing_docs)

    # 6. Writer Agent - generate documentation
    relevant_docs_for_writer = [
        {"path": c["doc_path"], "section": c["section"], "content": c["content"]}
        for c in relevant_chunks
    ]
    write_result = writer.write(digest_result, plan_result, relevant_docs_for_writer, client)

    # 7. Reviewer Agent - review quality
    original_artifacts = {"tickets": tickets, "pull_requests": pull_requests}
    review_result = reviewer.review(write_result, digest_result, original_artifacts, client)

    # 8. Evaluation - measure quality metrics
    eval_result = evaluate(write_result, review_result, tickets, existing_docs)

    # Store the release
    release_id = str(uuid.uuid4())[:8]
    release_data = {
        "id": release_id,
        "name": request.release_name,
        "description": request.description,
        "status": "review" if review_result.get("approved") else "needs_revision",
        "created_at": datetime.now(timezone.utc).isoformat(),
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
    releases_store[release_id] = release_data

    return release_data


@app.get("/api/releases")
def list_releases():
    """List all generated releases."""
    return list(releases_store.values())


@app.get("/api/releases/{release_id}")
def get_release(release_id: str):
    """Get a specific release by ID."""
    if release_id not in releases_store:
        raise HTTPException(status_code=404, detail="Release not found")
    return releases_store[release_id]


@app.post("/api/releases/{release_id}/approve")
def approve_release(release_id: str, request: ApproveRequest):
    """Approve a release (optionally with edits)."""
    if release_id not in releases_store:
        raise HTTPException(status_code=404, detail="Release not found")

    release = releases_store[release_id]

    # Apply any edits
    if request.changelog is not None:
        release["artifacts"]["changelog"] = request.changelog
    if request.internal_release_notes is not None:
        release["artifacts"]["internal_release_notes"] = request.internal_release_notes
    if request.customer_release_notes is not None:
        release["artifacts"]["customer_release_notes"] = request.customer_release_notes

    release["status"] = "approved"
    release["approved_at"] = datetime.now(timezone.utc).isoformat()
    return release


@app.post("/api/releases/{release_id}/reject")
def reject_release(release_id: str):
    """Reject a release and mark for regeneration."""
    if release_id not in releases_store:
        raise HTTPException(status_code=404, detail="Release not found")
    releases_store[release_id]["status"] = "rejected"
    return releases_store[release_id]


@app.get("/api/docs")
def list_docs():
    """List available documentation for RAG."""
    docs_connector = DocsConnector()
    return docs_connector.get_all_documents()


@app.get("/api/docs/search")
def search_docs(q: str):
    """Search documentation using RAG."""
    client = get_openai_client()
    docs_connector = DocsConnector()
    documents = docs_connector.get_all_documents()
    results = retrieve(q, client, top_k=5, documents=documents)
    return results


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
