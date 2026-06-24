# Design Document

## Architecture Decisions

### 1. Multi-Agent Pipeline over Monolithic Prompt
**Decision**: Four specialized agents (Digester, Planner, Writer, Reviewer) instead of one large prompt.

**Rationale**:
- Each agent has a focused responsibility with clear input/output contracts
- Easier to debug (inspect intermediate outputs between agents)
- Individual agents can be improved without affecting others
- Reviewer agent acts as a quality gate, catching hallucinations

**Tradeoff**: More API calls (4 LLM calls per generation), adding ~10-15 seconds latency and higher cost. Acceptable for a documentation workflow that runs per-release (not real-time).

### 2. OpenAI API over Local Models
**Decision**: Use OpenAI GPT-4o-mini for generation, text-embedding-3-small for embeddings.

**Rationale**:
- No GPU required; works on any machine with internet
- GPT-4o-mini provides excellent structured output (JSON mode) at low cost
- text-embedding-3-small is fast, cheap, and produces quality embeddings
- Easy to swap for other providers (Anthropic, local Ollama) by changing the client

**Tradeoff**: Requires internet + API key. Data is sent to OpenAI. For sensitive codebases, swap to a self-hosted model.

### 3. NumPy Vector Store over ChromaDB/Pinecone
**Decision**: Simple JSON file + NumPy cosine similarity for RAG.

**Rationale**:
- Zero infrastructure dependencies (no database server)
- Documentation corpora are small (typically <1000 chunks)
- Full index rebuilds are fast (<5 seconds for typical doc sets)
- Eliminates heavy dependencies (ChromaDB pulls onnxruntime, torch, etc.)

**Tradeoff**: Won't scale to millions of documents. At that point, use pgvector or Pinecone.

### 4. Mock Data by Default
**Decision**: Ship with rich mock data; real API integration is opt-in.

**Rationale**:
- Evaluators can run the full pipeline immediately without API keys for GitHub/Jira
- Mock data demonstrates the expected input shape
- Real connectors are trivial to implement (the interface is simple)

### 5. Next.js + Tailwind Frontend
**Decision**: Lightweight React UI with server-side rendering capability.

**Rationale**:
- Familiar stack; fast to build
- Tailwind avoids CSS-in-JS runtime overhead
- App Router provides good file-based routing
- No component library lock-in

## AI Workflow Detail

```
Input Artifacts                Agent Pipeline                    Output
─────────────────             ────────────────                  ──────
Commits (7)     ─┐
                 ├─→ [Digester] ─→ Structured Digest
PRs (2)         ─┘                        │
                                          ▼
Existing Docs ────→ [Planner] ─→ Documentation Plan
                                          │
                                          ▼
RAG Retrieval ────→ [Writer]  ─→ Generated Artifacts ─→ changelog
                                          │              internal_notes
                                          │              customer_notes
                                          │              doc_updates
                                          ▼
Source Evidence ──→ [Reviewer] ─→ Quality Assessment ─→ score
                                                        hallucinations
                                                        coverage gaps
```

### Prompt Design Principles
1. **System prompts** define the agent's role, output format, and constraints
2. **JSON mode** ensures structured output (no regex parsing)
3. **Low temperature** (0.1-0.3) for factual accuracy over creativity
4. **Anti-hallucination instruction**: "Only include facts supported by source evidence"
5. **Explicit output schemas** in system prompts guide the model

### Retrieval Strategy
- Documents are split by markdown headings (semantic boundaries)
- Large sections get overlapping chunks (500 words, 100 overlap)
- Query is formed from digest summary + affected systems
- Top-5 chunks are passed to the Writer for context
- Relevance scores are surfaced in the UI for transparency

## Evaluation Approach

Three metrics measured automatically:

| Metric | How Measured | Target |
|--------|-------------|--------|
| Hallucination Rate | Reviewer agent flags unsupported claims; count / normalized | < 10% |
| Ticket Coverage | Check if each ticket key appears in generated text | > 90% |
| Doc Recommendation Accuracy | Verify suggested doc paths exist in corpus | > 80% |

Overall score = weighted combination: `(1-hallucination)*0.4 + coverage*0.35 + accuracy*0.25`

## Future Improvements

1. **Streaming**: Stream agent outputs to UI for faster perceived performance
2. **Caching**: Cache digests for unchanged artifact sets (content-hash key)
3. **Real Connectors**: GitHub API, Jira API, Confluence API with OAuth
4. **Multi-Source**: Slack thread ingestion, Linear tickets, Zendesk tickets
5. **Versioning**: Store release history in SQLite/Postgres for audit trail
6. **CI Integration**: GitHub Action that auto-generates docs on release tag
7. **Feedback Loop**: Track human edits to fine-tune prompts over time
8. **Local LLM**: Support Ollama/llama.cpp for air-gapped environments
