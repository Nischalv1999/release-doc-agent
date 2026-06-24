# Release Documentation Agent

An AI-powered system that automatically generates release documentation from engineering artifacts (git commits, pull requests, Jira tickets). Uses a multi-agent pipeline with RAG retrieval and built-in quality evaluation.

## Features

- **Multi-Agent Pipeline**: Digester → Planner → Writer → Reviewer
- **RAG Documentation Retrieval**: Identifies impacted docs and suggests updates
- **Evaluation Framework**: Measures hallucination rate, ticket coverage, doc accuracy
- **Review & Approval UI**: Edit generated content before approving
- **Source Evidence**: Full traceability from output back to source artifacts

## Quick Start

### Prerequisites

- Python 3.11+ (check: `python3 --version`)
- Node.js 18+ (check: `node --version`)
- An OpenAI API key ([get one here](https://platform.openai.com/api-keys))

### 1. Backend Setup

```bash
cd backend

# Create virtual environment and install dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Configure your OpenAI API key
cp .env.example .env
# Edit .env and add your OPENAI_API_KEY

# Run the server
python main.py
```

Backend starts at http://localhost:8000. API docs at http://localhost:8000/docs.

### 2. Frontend Setup

```bash
cd frontend

# Install dependencies
npm install

# Start dev server
npm run dev
```

Frontend starts at http://localhost:3000.

### 3. Generate Documentation

1. Open http://localhost:3000
2. Enter a release name (e.g., "v2.4.0")
3. Click "Generate" — the agent pipeline runs (~15-30 seconds)
4. Review the generated changelog, internal notes, customer notes
5. Check the Evaluation tab for quality metrics
6. Edit if needed, then click "Approve"

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full diagram.

```
Commits + PRs + Tickets
        │
        ▼
  [Digester Agent] → Structured summary
        │
        ▼
  [Planner Agent]  → Documentation plan
        │
        ▼
  [Writer Agent]   → Generated artifacts (with RAG context)
        │
        ▼
  [Reviewer Agent] → Quality assessment
        │
        ▼
  [Evaluator]      → Metrics (hallucination, coverage, accuracy)
        │
        ▼
  [UI]             → Human review, edit, approve
```

## Project Structure

```
release-doc-agent/
├── backend/
│   ├── main.py                 # FastAPI app + API endpoints
│   ├── agents/
│   │   ├── digester.py         # Analyzes raw artifacts
│   │   ├── planner.py          # Plans documentation structure
│   │   ├── writer.py           # Generates release docs
│   │   └── reviewer.py         # Reviews for quality/accuracy
│   ├── rag/
│   │   ├── indexer.py          # Chunks + embeds documents
│   │   └── retriever.py       # Cosine similarity search
│   ├── connectors/
│   │   ├── github.py           # GitHub data (mock/real)
│   │   ├── jira.py             # Jira data (mock/real)
│   │   └── docs.py             # Documentation loader
│   ├── evaluation/
│   │   └── evaluator.py        # Quality metrics framework
│   ├── mock_data/              # Sample data for demo
│   │   ├── commits.json
│   │   ├── pull_requests.json
│   │   ├── jira_tickets.json
│   │   └── docs/               # Sample documentation
│   └── tests/                  # Unit tests
├── frontend/
│   └── src/
│       ├── app/page.tsx        # Main page
│       └── components/         # UI components
├── docs/
│   ├── ARCHITECTURE.md         # System architecture diagram
│   └── DESIGN.md               # Design decisions + tradeoffs
└── README.md
```

## Running Tests

```bash
cd backend
source .venv/bin/activate
pip install pytest pytest-asyncio
pytest tests/ -v
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Health check |
| POST | `/api/releases/generate` | Run full agent pipeline |
| GET | `/api/releases` | List all releases |
| GET | `/api/releases/{id}` | Get release details |
| POST | `/api/releases/{id}/approve` | Approve (with optional edits) |
| POST | `/api/releases/{id}/reject` | Reject release |
| GET | `/api/docs` | List indexed documentation |
| GET | `/api/docs/search?q=...` | Search docs via RAG |

## Design Decisions

See [docs/DESIGN.md](docs/DESIGN.md) for full details. Key choices:

1. **Multi-agent over monolithic**: Better debugging, focused prompts, quality gate
2. **OpenAI over local models**: Zero GPU requirement, excellent JSON mode
3. **NumPy over vector DB**: No infrastructure for small doc corpora
4. **Mock data default**: Runs immediately without external API setup

## Limitations

- Requires OpenAI API key (costs ~$0.01-0.05 per generation with gpt-4o-mini)
- In-memory storage (releases lost on server restart)
- Mock data only for GitHub/Jira (real API connectors are stubbed)
- Single-user (no auth on the API)

## Future Work

- Streaming agent output to UI
- Real GitHub/Jira/Confluence connectors
- Persistent storage (SQLite)
- CI/CD integration (GitHub Action on release tags)
- Support for local LLMs (Ollama)
