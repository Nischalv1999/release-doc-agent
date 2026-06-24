# Setup Instructions (Complete Guide)

## What This Is

An AI-powered system that automatically generates release documentation (changelogs, release notes, doc update suggestions) from engineering artifacts. It uses a multi-agent pipeline (4 AI agents) with RAG retrieval and quality evaluation.

**Tech Stack:** Python + FastAPI (backend), Next.js + React + TypeScript (frontend), OpenAI or Claude (AI)

---

## Prerequisites

You need these installed on your machine:

| Tool | Check if installed | Install if missing |
|------|-------------------|-------------------|
| Python 3.11+ | `python3 --version` | [python.org/downloads](https://www.python.org/downloads/) |
| Node.js 18+ | `node --version` | [nodejs.org](https://nodejs.org/) |
| Git | `git --version` | [git-scm.com](https://git-scm.com/) |

---

## Step 1: Get an API Key (pick ONE)

You need an LLM API key. Choose either OpenAI or Anthropic (Claude):

### Option A: OpenAI (recommended)
1. Go to https://platform.openai.com/api-keys
2. Sign up or log in (this is SEPARATE from a ChatGPT subscription)
3. Click "Create new secret key"
4. Copy the key (starts with `sk-...`)
5. New accounts get **$5 free credits** (this project uses ~$0.02 per run)

### Option B: Anthropic (Claude)
1. Go to https://console.anthropic.com/settings/keys
2. Sign up or log in (this is SEPARATE from a Claude subscription)
3. Click "Create Key"
4. Copy the key (starts with `sk-ant-...`)
5. New accounts get **$5 free credits**

---

## Step 2: Backend Setup

Open a terminal and run these commands one by one:

```bash
# Navigate to the project
cd release-doc-agent/backend

# Create a Python virtual environment
python3 -m venv .venv

# Activate it
# On macOS/Linux:
source .venv/bin/activate
# On Windows:
# .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Configure your API key:

```bash
# Copy the example config
cp .env.example .env
```

Now **edit the `.env` file** with any text editor (VS Code, nano, Notepad, etc.):

**If using OpenAI:**
```
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-paste-your-actual-key-here
```

**If using Claude:**
```
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-paste-your-actual-key-here
```

### Start the backend server:

```bash
python main.py
```

You should see:
```
[...] INFO: Starting server on 0.0.0.0:8000
[...] INFO: Uvicorn running on http://0.0.0.0:8000
```

**Leave this terminal running.** Open a new terminal for the next step.

---

## Step 3: Frontend Setup

In a NEW terminal:

```bash
# Navigate to frontend
cd release-doc-agent/frontend

# Install dependencies
npm install

# If npm install hangs, try:
# npm install --registry=https://registry.npmjs.org

# Start the dev server
npm run dev
```

You should see:
```
▲ Next.js 14.2.13
- Local: http://localhost:3000
```

---

## Step 4: Use the App

1. Open your browser to **http://localhost:3000**
2. You'll see "Release Documentation Agent" with a text field
3. Type a release name (e.g., `v2.4.0`) and click **Generate**
4. Wait 15-30 seconds (the 4 AI agents are working)
5. Results appear in tabs: Changelog, Internal Notes, Customer Notes, Doc Updates, Evidence, Evaluation
6. Click **Edit** to modify any text, then **Approve** to finalize

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `OPENAI_API_KEY not set` | Edit `backend/.env` file, make sure the key is there |
| `ModuleNotFoundError` | Make sure you activated the venv: `source .venv/bin/activate` |
| `npm install` hangs | Try: `npm install --registry=https://registry.npmjs.org` |
| Port 8000 in use | Kill the other process or change PORT in `.env` |
| Port 3000 in use | Next.js will auto-pick 3001; update `CORS_ORIGINS` in backend `.env` |
| `Connection refused` on Generate | Make sure the backend terminal is still running |
| Windows: `source` not found | Use `.venv\Scripts\activate` instead |

---

## Running Tests (optional)

```bash
cd backend
source .venv/bin/activate
pytest tests/ -v
```

Expected output: `110 passed`

---

## Project Structure (for reference)

```
release-doc-agent/
├── backend/
│   ├── .env              ← YOUR API KEY GOES HERE
│   ├── main.py           ← Server entry point
│   ├── agents/           ← 4 AI agents (digester, planner, writer, reviewer)
│   ├── rag/              ← Document retrieval (indexer + retriever)
│   ├── connectors/       ← Data loading (GitHub, Jira, Docs - mock)
│   ├── evaluation/       ← Quality metrics
│   └── tests/            ← 110 tests
├── frontend/
│   └── src/              ← React UI
├── docs/
│   ├── ARCHITECTURE.md   ← System architecture
│   ├── DESIGN.md         ← Design decisions
│   └── *.docx            ← Word document version
└── README.md
```

---

## Cost

- Each "Generate" click costs approximately **$0.01-0.03** (4 LLM calls + embeddings)
- The free $5 credit from OpenAI/Anthropic is enough for **150-500 runs**
- No other costs (everything runs locally)
