# Architecture

## System Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Frontend (Next.js 14)                              │
│                                                                             │
│  ┌────────────┐  ┌──────────────┐  ┌──────────────┐  ┌─────────────────┐  │
│  │  Generate  │  │   Artifact   │  │    Source    │  │    Review &     │  │
│  │   Panel    │  │    Viewer    │  │   Evidence   │  │    Approval     │  │
│  │            │  │  (Markdown)  │  │    Panel     │  │     Flow        │  │
│  └─────┬──────┘  └──────┬───────┘  └──────┬───────┘  └───────┬─────────┘  │
│        │                 │                 │                   │            │
│  ┌─────┴─────────────────┴─────────────────┴───────────────────┴─────────┐  │
│  │                        State Management (React useState)              │  │
│  └───────────────────────────────┬───────────────────────────────────────┘  │
└──────────────────────────────────┼──────────────────────────────────────────┘
                                   │ HTTP REST (JSON)
                                   │ Port 3000 → Port 8000
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          Backend (FastAPI + Python 3.11)                     │
│                                                                             │
│  ┌─── API Layer ────────────────────────────────────────────────────────┐  │
│  │  POST /api/releases/generate    GET /api/releases                    │  │
│  │  GET  /api/releases/{id}        POST /api/releases/{id}/approve      │  │
│  │  POST /api/releases/{id}/reject GET /api/docs/search?q=...          │  │
│  └──────────────────────────────────┬───────────────────────────────────┘  │
│                                     │                                       │
│  ┌─── Orchestration Layer ──────────┼───────────────────────────────────┐  │
│  │                                  ▼                                    │  │
│  │  ┌──────────────────────────────────────────────────────────────┐   │  │
│  │  │                    Agent Pipeline                             │   │  │
│  │  │                                                              │   │  │
│  │  │  ┌──────────┐    ┌──────────┐    ┌────────┐    ┌─────────┐ │   │  │
│  │  │  │ DIGESTER │ ─→ │ PLANNER  │ ─→ │ WRITER │ ─→ │REVIEWER │ │   │  │
│  │  │  │          │    │          │    │        │    │         │ │   │  │
│  │  │  │ Commits  │    │ Digest + │    │ Plan + │    │ Output +│ │   │  │
│  │  │  │ PRs      │    │ Existing │    │ RAG    │    │ Source  │ │   │  │
│  │  │  │ Tickets  │    │ Docs     │    │ Chunks │    │Evidence │ │   │  │
│  │  │  │    ↓     │    │    ↓     │    │   ↓    │    │    ↓    │ │   │  │
│  │  │  │ Struct.  │    │ Doc Plan │    │Artifacts│    │ Score + │ │   │  │
│  │  │  │ Digest   │    │          │    │        │    │ Issues  │ │   │  │
│  │  │  └──────────┘    └──────────┘    └────────┘    └─────────┘ │   │  │
│  │  └──────────────────────────────────────────────────────────────┘   │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│  ┌─── Data Layer ───────────────────────────────────────────────────────┐  │
│  │                                                                       │  │
│  │  ┌────────────────┐   ┌──────────────────────┐   ┌────────────────┐ │  │
│  │  │  Connectors    │   │    RAG Pipeline       │   │  Evaluation    │ │  │
│  │  │                │   │                      │   │  Framework     │ │  │
│  │  │  ┌──────────┐  │   │  ┌────────────────┐  │   │                │ │  │
│  │  │  │  GitHub  │  │   │  │    Indexer      │  │   │  Hallucination│ │  │
│  │  │  │(commits, │  │   │  │ ┌────────────┐ │  │   │  Rate         │ │  │
│  │  │  │  PRs)    │  │   │  │ │ Section    │ │  │   │                │ │  │
│  │  │  ├──────────┤  │   │  │ │ Splitting  │ │  │   │  Ticket       │ │  │
│  │  │  │   Jira   │  │   │  │ ├────────────┤ │  │   │  Coverage     │ │  │
│  │  │  │(tickets) │  │   │  │ │ Overlap    │ │  │   │                │ │  │
│  │  │  ├──────────┤  │   │  │ │ Chunking   │ │  │   │  Doc Rec.     │ │  │
│  │  │  │   Docs   │  │   │  │ ├────────────┤ │  │   │  Accuracy     │ │  │
│  │  │  │(markdown)│  │   │  │ │ Embedding  │ │  │   │                │ │  │
│  │  │  └──────────┘  │   │  │ └────────────┘ │  │   └────────────────┘ │  │
│  │  └────────────────┘   │  ├────────────────┤  │                       │  │
│  │                       │  │   Retriever    │  │                       │  │
│  │  ┌────────────────┐   │  │ ┌────────────┐ │  │                       │  │
│  │  │  In-Memory     │   │  │ │  Cosine    │ │  │                       │  │
│  │  │  Release Store │   │  │ │ Similarity │ │  │                       │  │
│  │  │  (dict)        │   │  │ │  (NumPy)   │ │  │                       │  │
│  │  └────────────────┘   │  │ └────────────┘ │  │                       │  │
│  │                       │  └────────────────┘  │                       │  │
│  │  ┌────────────────┐   │                      │                       │  │
│  │  │  RAG Index     │   │  ┌────────────────┐  │                       │  │
│  │  │  (JSON file)   │◄──┤  │  Vector Store  │  │                       │  │
│  │  └────────────────┘   │  │  (JSON+NumPy)  │  │                       │  │
│  │                       │  └────────────────┘  │                       │  │
│  └───────────────────────┴──────────────────────┴───────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
                    ┌──────────────────────────────┐
                    │      OpenAI API              │
                    │                              │
                    │  GPT-4o-mini (Completions)   │
                    │  - JSON response mode        │
                    │  - Low temperature (0.1-0.3) │
                    │                              │
                    │  text-embedding-3-small      │
                    │  - 1536 dimensions           │
                    │  - Batch embedding support   │
                    └──────────────────────────────┘
```

## Sequence Diagram: Release Generation

```
User        Frontend         Backend           Agents            OpenAI        RAG Index
 │              │               │                │                 │              │
 │─ Click ────→│               │                │                 │              │
 │ "Generate"  │               │                │                 │              │
 │              │── POST ──────→│                │                 │              │
 │              │  /generate    │                │                 │              │
 │              │               │── Load ───────→│                 │              │
 │              │               │  mock data     │                 │              │
 │              │               │                │                 │              │
 │              │               │── Build Index ─┼────── Embed ───→│              │
 │              │               │               │                 │──── Store ──→│
 │              │               │               │                 │              │
 │              │               │── Digester ───→│─── Complete ───→│              │
 │              │               │               │←── JSON ────────│              │
 │              │               │←── Digest ────│                 │              │
 │              │               │                │                 │              │
 │              │               │── Planner ────→│─── Complete ───→│              │
 │              │               │               │←── JSON ────────│              │
 │              │               │←── Plan ──────│                 │              │
 │              │               │                │                 │              │
 │              │               │── Retrieve ───┼─────────────────┼──── Query ──→│
 │              │               │               │                 │←── Top-5 ───│
 │              │               │                │                 │              │
 │              │               │── Writer ─────→│─── Complete ───→│              │
 │              │               │               │←── JSON ────────│              │
 │              │               │←── Artifacts ─│                 │              │
 │              │               │                │                 │              │
 │              │               │── Reviewer ───→│─── Complete ───→│              │
 │              │               │               │←── JSON ────────│              │
 │              │               │←── Review ────│                 │              │
 │              │               │                │                 │              │
 │              │               │── Evaluate ──→│ (local compute) │              │
 │              │               │←── Metrics ───│                 │              │
 │              │               │                │                 │              │
 │              │←── Response ──│                │                 │              │
 │              │   (full JSON) │                │                 │              │
 │←── Render ──│               │                │                 │              │
 │   results   │               │                │                 │              │
```

## Component Details

### 1. Data Connectors

Each connector implements a simple interface: fetch data, return structured dicts.

```python
class GitHubConnector:
    get_commits(repo, since, until) → list[Commit]
    get_pull_requests(repo, state) → list[PullRequest]

class JiraConnector:
    get_tickets(ticket_keys) → list[Ticket]

class DocsConnector:
    get_all_documents() → list[Document]
```

**Extensibility**: Adding a new source (Slack, Linear, Confluence) means:
1. Create a new connector file in `connectors/`
2. Return data in the same shape
3. Pass to the Digester agent alongside existing data

### 2. Agent Pipeline

Each agent is a pure function: `(input_data, openai_client) → structured_output`

| Agent | Input | Output | Temperature | Purpose |
|-------|-------|--------|-------------|---------|
| Digester | Commits, PRs, Tickets | `{features, bug_fixes, breaking_changes, affected_systems, risk_level, summary}` | 0.1 | Extract signal from noise |
| Planner | Digest, Existing Docs | `{changelog_plan, internal_notes_plan, customer_notes_plan, doc_update_plan}` | 0.2 | Structure the output |
| Writer | Digest, Plan, RAG Chunks | `{changelog, internal_release_notes, customer_release_notes, documentation_updates}` | 0.3 | Generate polished content |
| Reviewer | Generated Docs, Digest, Original Artifacts | `{overall_score, hallucination_issues, missing_coverage, suggestions, approved}` | 0.1 | Quality gate |

**Why this order matters**:
- Digester first: compresses raw data into a manageable summary (context window efficiency)
- Planner second: uses the summary to decide what to write (separation of planning from execution)
- Writer third: gets both the plan AND relevant context from RAG (informed generation)
- Reviewer last: compares output against source (independent validation)

### 3. RAG Pipeline

```
Documents → [Section Splitter] → [Overlap Chunker] → [Embedder] → [Vector Store]
                                                                         │
Query ────────────────────────────── [Embedder] → [Cosine Sim] → [Top-K] → Results
```

**Chunking Strategy**:
- First pass: split by markdown headings (preserves semantic boundaries)
- Second pass: if a section > 500 words, split with 100-word overlap
- Each chunk retains metadata: `doc_path`, `doc_title`, `section`, `chunk_id`

**Retrieval**:
- Query = digest summary + affected system names (captures both high-level intent and specific terms)
- Cosine similarity over all chunk embeddings
- Top-5 returned with relevance scores
- Scores exposed in UI for transparency/debugging

**Storage**: JSON file (`rag_index.json`) containing:
```json
{
  "chunks": [{"doc_path": "...", "section": "...", "content": "...", "chunk_id": "..."}],
  "embeddings": [[0.012, -0.034, ...], ...]  // 1536-dim vectors
}
```

### 4. Evaluation Framework

Three automated metrics computed without additional LLM calls:

```
┌────────────────────────────────────────────────────────────────────┐
│                      Evaluation Pipeline                           │
│                                                                    │
│  ┌─────────────────┐                                              │
│  │ Hallucination   │  Source: Reviewer agent's hallucination_issues│
│  │ Rate            │  Formula: min(1.0, issue_count × 0.1)        │
│  │                 │  Weight: 40%                                  │
│  └─────────────────┘                                              │
│                                                                    │
│  ┌─────────────────┐                                              │
│  │ Ticket          │  Source: String match of ticket keys in text  │
│  │ Coverage        │  Formula: mentioned_keys / total_keys         │
│  │                 │  Weight: 35%                                  │
│  └─────────────────┘                                              │
│                                                                    │
│  ┌─────────────────┐                                              │
│  │ Doc Recommend.  │  Source: Check doc_path exists in corpus      │
│  │ Accuracy        │  Formula: valid_recs / total_recs             │
│  │                 │  Weight: 25%                                  │
│  └─────────────────┘                                              │
│                                                                    │
│  Overall = (1-hallucination)×0.4 + coverage×0.35 + accuracy×0.25  │
└────────────────────────────────────────────────────────────────────┘
```

### 5. Frontend Architecture

```
app/
├── layout.tsx          ← Shell (header, global styles)
├── page.tsx            ← Main page (state management, API calls)
└── globals.css         ← Tailwind imports

components/
├── GeneratePanel.tsx   ← Input form + trigger button
└── ReleaseCard.tsx     ← Tabbed view of all release data
    ├── MarkdownPanel   ← View/edit mode for text artifacts
    ├── DocUpdatesPanel ← Renders suggested doc changes
    ├── EvidencePanel   ← Shows source commits/PRs/tickets/RAG
    └── EvaluationPanel ← Metric cards + reviewer assessment
```

**State Flow**:
```
GeneratePanel → (API call) → releases[] state → ReleaseCard → (edit/approve) → API → update state
```

No global state library needed; `useState` at page level is sufficient for this scope.

### 6. API Contract

**POST /api/releases/generate**
```
Request:  { release_name: string, description?: string, use_mock_data: boolean }
Response: {
  id: string,
  name: string,
  status: "review" | "needs_revision",
  created_at: ISO8601,
  artifacts: { changelog, internal_release_notes, customer_release_notes, documentation_updates[] },
  digest: { features[], bug_fixes[], breaking_changes[], affected_systems[], risk_level, summary },
  plan: { changelog_plan, internal_notes_plan, customer_notes_plan, doc_update_plan[] },
  review: { overall_score, hallucination_issues[], missing_coverage[], suggestions[], approved },
  evaluation: { hallucination_rate, ticket_coverage, doc_recommendation_accuracy, overall_score },
  source_evidence: { commits[], pull_requests[], tickets[], relevant_docs[] }
}
```

**POST /api/releases/{id}/approve**
```
Request:  { changelog?: string, internal_release_notes?: string, customer_release_notes?: string }
Response: (same as above, with status: "approved", approved_at: ISO8601)
```

## Error Handling

| Layer | Error Type | Handling |
|-------|-----------|----------|
| API | Missing OPENAI_API_KEY | HTTP 500 with clear message |
| API | Release not found | HTTP 404 |
| Connectors | Real API not configured | `NotImplementedError` with guidance |
| Agents | OpenAI API failure | Exception propagates to API layer → 500 |
| RAG | No index exists | Auto-builds on first retrieval |
| Frontend | Network failure | Error banner with message |

## Scaling Considerations (Production Path)

| Current | Production | When to Switch |
|---------|-----------|----------------|
| In-memory dict | PostgreSQL + SQLAlchemy | Multi-user or persistence needed |
| JSON vector store | pgvector or Pinecone | >10K documents |
| Sync API call | Background task + WebSocket | >30s generation time |
| Single process | Celery workers | Multiple concurrent generations |
| No auth | OAuth2 / API keys | Multi-user deployment |
| Mock connectors | Real GitHub/Jira OAuth | Production integration |

## Security Considerations

- **API key isolation**: OpenAI key in `.env`, never committed (`.gitignore`)
- **No PII in mock data**: Fake names, no real credentials
- **CORS restricted**: Only `localhost:3000` allowed
- **No file uploads**: Documentation loaded from server filesystem only
- **Input validation**: Pydantic models validate all request bodies
