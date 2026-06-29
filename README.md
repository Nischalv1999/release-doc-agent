# Release Documentation Agent

An AI-powered system that automatically generates release documentation from engineering artifacts — git commits, pull requests, and Jira tickets. Produces a changelog, internal release notes, customer-facing release notes, and documentation update suggestions using a multi-agent pipeline.

---

## Prerequisites

| Tool | Minimum version | Check |
|------|----------------|-------|
| Python | 3.11+ | `python3 --version` |
| Node.js | 18+ | `node --version` |
| Git | any | `git --version` |

You also need an API key from one of the following AI providers:

**OpenAI** — [platform.openai.com/api-keys](https://platform.openai.com/api-keys)
- Key starts with `sk-...`
- New accounts receive $5 free credit (~150–500 runs at ~$0.01–0.03 per generation)

**Anthropic (Claude)** — [console.anthropic.com/settings/keys](https://console.anthropic.com/settings/keys)
- Key starts with `sk-ant-...`
- New accounts receive $5 free credit
- Note: embeddings still use OpenAI when using Anthropic. Either provide both keys or the system falls back to a local embedding method.

---

## Backend Setup

```bash
cd release-doc-agent/backend

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate        # macOS / Linux
# .venv\Scripts\activate         # Windows

# Install dependencies
pip install -r requirements.txt

# Create your environment config
cp .env.example .env
```

Edit `.env` and set your provider and API key:

**Using OpenAI:**
```
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-your-key-here
```

**Using Anthropic (Claude):**
```
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-your-key-here
OPENAI_API_KEY=sk-your-openai-key-here   # optional, for better embeddings
```

Start the backend server:

```bash
python main.py
```

Expected output:
```
INFO: Starting server on 0.0.0.0:8000
INFO: Uvicorn running on http://0.0.0.0:8000
```

API is live at **http://localhost:8000** — interactive docs at **http://localhost:8000/docs**.

Leave this terminal running and open a new one for the frontend.

---

## Frontend Setup

```bash
cd release-doc-agent/frontend

npm install
npm run dev
```

Expected output:
```
▲ Next.js 14.x
- Local: http://localhost:3000
```

---

## Using the App

1. Open **http://localhost:3000**
2. Enter a release name (e.g. `v2.5.0`) and click **Generate**
3. The pipeline runs in ~15–30 seconds (4 AI agent calls)
4. Review the output across tabs: **Changelog**, **Internal Notes**, **Customer Notes**, **Doc Updates**, **Source Evidence**, **Evaluation**
5. Click **Edit** to modify any section, then **Approve** to finalise

The system uses mock GitHub and Jira data by default so it runs without any live API credentials. The mock data simulates a realistic release with commits, pull requests, tickets, and existing documentation.

---

## Running Tests

```bash
cd backend
source .venv/bin/activate
pytest tests/ -v
```

Expected: `404 passed`

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Health check and config status |
| POST | `/api/releases/generate` | Run full agent pipeline |
| GET | `/api/releases` | List all stored releases |
| GET | `/api/releases/{id}` | Get a specific release |
| POST | `/api/releases/{id}/approve` | Approve with optional edits |
| POST | `/api/releases/{id}/reject` | Reject a release |
| GET | `/api/docs` | List indexed documentation |
| GET | `/api/docs/search?q=...` | Search docs via RAG |

---

## Project Structure

```
release-doc-agent/
├── backend/
│   ├── .env                    ← your API keys go here
│   ├── main.py                 ← FastAPI server + pipeline orchestration
│   ├── llm_client.py           ← unified OpenAI / Anthropic abstraction
│   ├── agents/
│   │   ├── digester.py         ← summarises raw artifacts into structured digest
│   │   ├── planner.py          ← editorial strategy + RAG search queries
│   │   ├── writer.py           ← generates the four documentation artifacts
│   │   └── reviewer.py         ← quality check + security exclusion verification
│   ├── rag/
│   │   ├── indexer.py          ← chunks, embeds, and caches documentation
│   │   └── retriever.py        ← multi-query retrieval with MMR diversity
│   ├── connectors/
│   │   ├── github.py           ← commits and pull requests (mock or real)
│   │   ├── jira.py             ← tickets (mock or real)
│   │   └── docs.py             ← existing documentation loader
│   ├── evaluation/
│   │   └── evaluator.py        ← quality metrics and critical gates
│   ├── mock_data/              ← sample data for demo (no API needed)
│   │   ├── commits.json
│   │   ├── pull_requests.json
│   │   ├── jira_tickets.json
│   │   ├── docs/               ← sample documentation corpus
│   │   └── gold/               ← reference outputs for evaluation
│   └── tests/                  ← 404 unit tests
├── frontend/
│   └── src/
│       ├── app/page.tsx        ← main page
│       └── components/         ← GeneratePanel, ReleaseCard
├── DESIGN.md                   ← architecture decisions, RAG pipeline, trade-offs
└── README.md
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `OPENAI_API_KEY not set` | Edit `backend/.env` and confirm the key is present |
| `ModuleNotFoundError` | Run `source .venv/bin/activate` before starting the server |
| `Connection refused` on Generate | The backend terminal must still be running |
| Port 8000 already in use | Kill the other process or set `PORT=8001` in `.env` |
| Port 3000 already in use | Next.js auto-selects 3001; update `CORS_ORIGINS` in `.env` accordingly |
| `npm install` hangs | Try `npm install --registry=https://registry.npmjs.org` |
| Windows: `source` not found | Use `.venv\Scripts\activate` instead |
