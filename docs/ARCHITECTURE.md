# Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Frontend (Next.js)                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────────────────┐ │
│  │ Generate │  │ Artifact │  │ Evidence │  │  Review & Approve  │ │
│  │  Panel   │  │  Viewer  │  │  Panel   │  │      Panel         │ │
│  └──────────┘  └──────────┘  └──────────┘  └────────────────────┘ │
└────────────────────────────────┬────────────────────────────────────┘
                                 │ HTTP (REST)
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      Backend (FastAPI)                              │
│                                                                     │
│  ┌─────────────────── Agent Pipeline ───────────────────────────┐  │
│  │                                                               │  │
│  │  ┌──────────┐   ┌─────────┐   ┌────────┐   ┌────────────┐  │  │
│  │  │ Digester │ → │ Planner │ → │ Writer │ → │  Reviewer  │  │  │
│  │  │  Agent   │   │  Agent  │   │ Agent  │   │   Agent    │  │  │
│  │  └──────────┘   └─────────┘   └────────┘   └────────────┘  │  │
│  │       ↑                            ↑                         │  │
│  └───────┼────────────────────────────┼─────────────────────────┘  │
│          │                            │                             │
│  ┌───────┴──────────┐    ┌───────────┴──────────────┐             │
│  │  Data Connectors │    │     RAG Pipeline         │             │
│  │  ┌─────────────┐ │    │  ┌─────────┐ ┌────────┐ │             │
│  │  │   GitHub    │ │    │  │ Indexer │ │Retriever│ │             │
│  │  │   Jira      │ │    │  │(Chunks) │ │(Search)│ │             │
│  │  │   Docs      │ │    │  └─────────┘ └────────┘ │             │
│  │  └─────────────┘ │    └──────────────────────────┘             │
│  └──────────────────┘                                              │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │              Evaluation Framework                             │  │
│  │  Hallucination Rate │ Ticket Coverage │ Doc Accuracy          │  │
│  └──────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
                    ┌────────────────────────┐
                    │   OpenAI API (GPT-4o)  │
                    │   - Chat Completions   │
                    │   - Embeddings         │
                    └────────────────────────┘
```

## Data Flow

1. **Ingestion**: Connectors pull commits, PRs, tickets, and existing docs
2. **RAG Index**: Documentation is chunked, embedded, and indexed for retrieval
3. **Digester Agent**: Analyzes raw artifacts → structured release summary
4. **Planner Agent**: Takes digest + existing docs → documentation plan
5. **RAG Retrieval**: Finds relevant doc sections for the release context
6. **Writer Agent**: Generates all artifacts using plan + retrieved context
7. **Reviewer Agent**: Validates output against source evidence
8. **Evaluation**: Quantifies quality metrics (hallucination, coverage, accuracy)
9. **UI**: Presents results for human review, editing, and approval

## Component Boundaries

- **Connectors** are isolated behind interfaces; swap mock for real APIs without touching agents
- **Agents** are stateless functions; each takes input + OpenAI client, returns structured JSON
- **RAG** is decoupled from agents; the retriever can be used independently
- **Evaluation** is independent of generation; can be run on any generated output
