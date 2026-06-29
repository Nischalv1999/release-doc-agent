# Design Document: Automated Release Documentation Agent

## Overview

This system ingests GitHub commits, pull requests, and Jira tickets for a software release, and automatically produces four documentation artifacts: a changelog, internal release notes, customer-facing release notes, and staleness-detected documentation update suggestions. The pipeline is structured as a sequential multi-agent system, each agent having a narrow, testable responsibility.

---

## Architecture

### Full System Architecture

```
                    ┌─────────────────────────────────────┐
                    │           Browser / UI               │
                    │       Next.js + TypeScript           │
                    │  Generate │ Review │ Edit │ Approve  │
                    └──────────────────┬──────────────────┘
                                       │ HTTP REST
                                       ▼
┌──────────────────────────────────────────────────────────────────────┐
│                      FastAPI Backend  (main.py)                      │
│                                                                      │
│  POST /api/releases/generate    POST /api/releases/:id/approve       │
│  GET  /api/releases/:id         GET  /api/health                     │
│                                                                      │
│                    ┌─────────────────────┐                           │
│                    │  In-Memory LRU Store│                           │
│                    └─────────────────────┘                           │
└──────────────────────────────┬───────────────────────────────────────┘
                               │
          ┌────────────────────┼──────────────────────┐
          ▼                    ▼                       ▼
┌──────────────────┐  ┌────────────────┐  ┌───────────────────────┐
│ GitHub Connector │  │ Jira Connector │  │    Docs Connector     │
│  commits + PRs   │  │    tickets     │  │    markdown files     │
└────────┬─────────┘  └───────┬────────┘  └───────────┬───────────┘
         └───────────────────┬┘                        │
                             │                         ▼
                             │              ┌───────────────────────┐
                             │              │      RAG Indexer      │
                             │              │  • split by headings  │
                             │              │  • 500-word chunks    │
                             │              │    (100-word overlap) │
                             │              │  • embed title +      │
                             │              │    section + content  │
                             │              │  • SHA-256 cache      │
                             │              │    (disk-persisted)   │
                             │              └───────────┬───────────┘
                             │                          │
                             ▼                          │
          ┌────────────────────────────────────────────────────────┐
          │                    Agent Pipeline                       │
          │                                                        │
          │  ┌──────────────────────────────────────────────────┐  │
          │  │  [1] Digester                                    │  │
          │  │      • Pre-extract identifiers (CVE IDs,        │  │
          │  │        ticket keys, PR numbers) in Python        │  │
          │  │      • Injection-guard all freeform user text   │  │
          │  │      • Compute 9 objective risk factors         │  │
          │  │      • LLM call → features / bugs /            │  │
          │  │        breaking_changes / risk_level            │  │
          │  │      • Apply deterministic risk floor           │  │
          │  │      • Enforce full ticket coverage             │  │
          │  │      → structured digest                        │  │
          │  └─────────────────────┬────────────────────────────┘  │
          │                        ▼                               │
          │  ┌──────────────────────────────────────────────────┐  │
          │  │  [2] Planner                                     │  │
          │  │      • LLM call → core_narrative,               │  │
          │  │        audience_outlines, rag_search_queries     │  │
          │  │      • Python: enforce security exclusions       │  │
          │  │        (CVE IDs, security tickets → exclusion   │  │
          │  │         list regardless of LLM output)          │  │
          │  │      → editorial plan + 5 RAG search queries    │  │
          │  └─────────────────────┬────────────────────────────┘  │
          │                        │◄──── RAG index (from above)   │
          │                        ▼                               │
          │  ┌──────────────────────────────────────────────────┐  │
          │  │  [3] RAG Retriever                               │  │
          │  │      • Embed all 5 queries in one batch         │  │
          │  │      • Score chunks by max cosine similarity    │  │
          │  │        across all queries                       │  │
          │  │      • Over-retrieve top 20 candidates          │  │
          │  │      • MMR (λ=0.6) → top 10 diverse chunks     │  │
          │  │      → relevant doc sections                    │  │
          │  └─────────────────────┬────────────────────────────┘  │
          │                        ▼                               │
          │  ┌──────────────────────────────────────────────────┐  │
          │  │  [4] Writer                                      │  │
          │  │      • Plan-driven structure (no fixed template) │  │
          │  │      • Contradiction detection on RAG chunks:   │  │
          │  │        CONFLICT → update / GAP → add / skip     │  │
          │  │      • LLM call → 4 artifacts                   │  │
          │  │      → changelog, internal notes,               │  │
          │  │        customer notes, doc update suggestions   │  │
          │  └─────────────────────┬────────────────────────────┘  │
          │                        ▼                               │
          │  ┌──────────────────────────────────────────────────┐  │
          │  │  [5] Reviewer                                    │  │
          │  │      • LLM call → hallucinations, coverage,     │  │
          │  │        tone issues, score                        │  │
          │  │      • Python: verify no security IDs leaked    │  │
          │  │        into customer notes (independent check)  │  │
          │  │      → approved / needs_revision + issue list   │  │
          │  └─────────────────────┬────────────────────────────┘  │
          │                        ▼                               │
          │  ┌──────────────────────────────────────────────────┐  │
          │  │  [6] Evaluator                                   │  │
          │  │      • Python: fabricated identifier gate        │  │
          │  │      • Python: priority-weighted ticket coverage │  │
          │  │      • Python: doc-update F1 vs gold file       │  │
          │  │      • LLM: faithfulness rate (optional)        │  │
          │  │      • Critical gates override overall score    │  │
          │  │      → overall_score, force_needs_revision      │  │
          │  └─────────────────────┬────────────────────────────┘  │
          └──────────────────────────────────────────────────────--┘
                                   │
                        ┌──────────▼───────────┐
                        │      LLM Client       │
                        │   (llm_client.py)     │
                        │  unified interface    │
                        │  retry + backoff      │
                        └──────────┬────────────┘
                         ┌─────────┴──────────┐
                         ▼                    ▼
               ┌──────────────────┐  ┌──────────────────────┐
               │     OpenAI       │  │      Anthropic        │
               │  GPT-4o / mini   │  │    Claude Sonnet      │
               │  + embeddings    │  │  (OpenAI for embeds)  │
               └──────────────────┘  └──────────────────────┘
```

### Component Breakdown

| Layer | File(s) | Responsibility |
|---|---|---|
| Connectors | `connectors/github.py`, `connectors/jira.py`, `connectors/docs.py` | Fetch artifacts; swap mock JSON ↔ real API via `use_mock` flag |
| LLM Client | `llm_client.py` | Unified abstraction over OpenAI and Anthropic; always returns raw string |
| Agent base | `agents/base.py` | Retry/backoff, JSON parsing, schema validation, shared error types |
| Digester | `agents/digester.py` | Structured extraction: features, bugs, breaking changes, risk level |
| Planner | `agents/planner.py` | Editorial strategy: narrative, exclusion list, audience angles, RAG queries |
| RAG | `rag/indexer.py`, `rag/retriever.py` | Embedding index with content-hash caching; multi-query MMR retrieval |
| Writer | `agents/writer.py` | Four documentation artifacts driven by the plan |
| Reviewer | `agents/reviewer.py` | LLM quality review + deterministic security exclusion verification |
| Evaluator | `evaluation/evaluator.py` | Metrics: fabricated-identifier detection, weighted coverage, F1 vs gold set |
| API | `main.py` | FastAPI orchestrator; in-memory release store with LRU eviction |
| Frontend | `frontend/src/` | Next.js + TypeScript UI: generate, review, edit, approve |

---

## AI Workflow — End to End

### Stage 1: Data Ingestion

The three connectors (`GitHubConnector`, `JiraConnector`, `DocsConnector`) fetch raw artifacts. A `use_mock_data` flag in the API request toggles between local JSON fixtures and real API calls without changing any agent code. Jira tickets arrive in Atlassian Document Format (ADF); the connector parses ADF to plain text entirely in Python before any LLM ever sees it.

### Stage 2: RAG Index Build

Before any agent runs, existing documentation is chunked by markdown heading, and each chunk is embedded using `text-embedding-3-small`. The embed text is `"{doc_title} > {section}: {content}"` — title and section are prepended to give the embedding model the context that the raw content alone would lack. A content-hash (including a format version token) is compared against the on-disk index; the index is only rebuilt when documents actually change.

### Stage 3: Digester Agent

This is the most hardened agent. It:

1. **Pre-extracts all identifiers** in Python (CVE IDs via `_CVE_RE`, ticket keys via `_TICKET_RE`, PR numbers) before the LLM call. The LLM is explicitly instructed to select only from these lists — it cannot invent identifiers.
2. **Wraps all freeform text** (commit messages, PR bodies, ticket descriptions, code patches) in `<<<UNTRUSTED_ARTIFACT_BEGIN>>>` / `<<<UNTRUSTED_ARTIFACT_END>>>` delimiters with an explicit system-prompt instruction to ignore any directives found inside. This prevents prompt injection.
3. **Parses ADF in Python**. The LLM never receives raw Jira ADF.
4. **Computes nine objective risk factors** (CVE count, breaking-change presence, SQL migrations, line churn, systems touched, etc.) in Python before the LLM call. These facts are surfaced in the prompt so the LLM reasons holistically from evidence.
5. **Applies a deterministic risk floor** post-LLM: if a CVE is present, risk ≥ high; if a breaking change or SQL migration is present, risk ≥ medium. The LLM may escalate above the floor but cannot drop below it.
6. **Enforces ticket coverage** in Python: every input ticket key must appear somewhere in features, bug_fixes, or breaking_changes. Missing keys are added as `[unverified]` placeholders — the LLM cannot silently omit a ticket.
7. **Detects patch truncation** per file: if the GitHub API elided part of a diff (signalled by an elision marker line or a visible-line-count materially below stated additions+deletions stats), `verified: false` is set on that code insight.

Output is a structured dict: `features`, `bug_fixes`, `breaking_changes`, `affected_systems`, `risk_level`, `risk_rationale`, `code_insights`, `summary`.

### Stage 4: Planner Agent

The Planner is an editorial strategy agent, not a boilerplate generator. It produces:

- **`core_narrative`**: A unifying theme inferred from actual features and breaking changes, or null. The LLM is explicitly instructed not to invent a theme if the changes don't support one.
- **`audience_outlines`**: Short editorial angles (not prose) for customer and internal audiences, capped at 8 bullets each.
- **`exclusion_list`**: Items to suppress from specific doc types. The LLM may propose items; Python **always** adds security-sensitive items deterministically regardless of what the LLM does.
- **`rag_search_queries`**: Up to 5 targeted search strings derived from breaking changes, features, and affected systems.

Security exclusions are enforced deterministically: `_enforce_security_exclusions()` scans each digest item for CVE IDs (regex) and references to security-labelled Jira tickets, and adds them to the exclusion list in Python. LLM prompt-following is not trusted for security-critical omissions.

### Stage 5: RAG Retrieval

The Planner's `rag_search_queries` list is passed directly to `retrieve()`, which:

1. Embeds all queries in a single batch.
2. Scores each chunk by its **maximum similarity across all queries** (so a chunk relevant to any query is surfaced).
3. Over-retrieves to the top 20 candidates above the relevance threshold.
4. Applies **Maximal Marginal Relevance (MMR)** (`λ = 0.6`) to select the final set: each selection maximises `0.6 × relevance − 0.4 × max_similarity_to_already_selected`. This avoids returning five near-duplicate chunks from the same document section.

Falls back to a single digest-summary query when no Planner queries are available.

### Stage 6: Writer Agent

The Writer receives the digest, the plan, and the RAG chunks. Its SYSTEM_PROMPT drives structure from the plan's section lists rather than a fixed template. The user prompt provides:

- **Explicit contradiction-detection instructions** for the RAG chunks: for each chunk, the LLM must decide CONFLICT (emit `action='update'`), COVERAGE GAP (emit `action='add'`), or RELATED-BUT-UNAFFECTED (omit entirely). `action='review'` is explicitly prohibited.
- **Exclusion list** with mandatory suppression rules (CVE IDs and security tickets excluded from customer notes).
- **Audience angle bullets** from the Planner.

### Stage 7: Reviewer Agent

An LLM reviews the generated docs against the source artifacts for hallucinations, missing coverage, tone issues, and completeness. After the LLM review, a **deterministic Python step** (`_verify_exclusions`) checks whether any CVE ID or security ticket key (extracted by regex) appears literally in `customer_release_notes`. If found, `approved` is forced to `False` and the issue is added to `hallucination_issues` regardless of what the LLM returned.

### Stage 8: Evaluation

The evaluator runs four metrics and two critical gates:

**Metrics:**
- **Hallucination rate**: LLM faithfulness judge (one call: identify unsupported claims / total claims) when a client is provided; reviewer-proxy (issues × 0.1) as fallback.
- **Ticket coverage**: Priority-weighted (Highest=1.0, High=0.75, Medium=0.5, Low=0.25), word-boundary matching against changelog + internal notes only. Customer notes are excluded from keyed scoring because they intentionally omit ticket keys.
- **Doc-update accuracy**: Precision/Recall/F1 against a gold file (`mock_data/gold/<release_name>.json`) when available; falls back to a validity check (path exists in corpus).
- **Content quality**: Structural checks — headings, bullets, word count, jargon in customer notes.

**Critical gates** (override the averaged score — no weighted combination can hide these):
- Any CVE ID, ticket key, or PR number in the output that does not appear in the source artifacts → fabricated identifier → force `needs_revision`.
- Any security-excluded token leaking into `customer_release_notes` → force `needs_revision`.

Weights are named constants (`WEIGHT_HALLUCINATION = 0.35`, etc.) so they can be reasoned about and changed without searching for magic numbers.

---

## RAG Pipeline

The RAG (Retrieval-Augmented Generation) pipeline is responsible for finding the right existing documentation sections to give the Writer context about what already exists and what may be outdated. It runs in two phases: indexing (build once, cache on disk) and retrieval (run per release).

### Chunking Strategy

Documents are split into chunks using a two-level strategy:

**Level 1 — Heading-based splitting.** The document is scanned line by line. Every markdown heading (`#`, `##`, `###`) starts a new chunk. The text between two headings becomes one chunk, with the heading itself as the section title. This preserves semantic coherence — a section about "JWT Payload Structure" stays together rather than being arbitrarily split mid-paragraph. Content before the first heading is collected under an implicit "Introduction" section.

**Level 2 — Word-count splitting with overlap.** If a section exceeds 500 words, it is split further into sub-chunks of 500 words each with a 100-word overlap between consecutive chunks. The overlap ensures that a sentence spanning a chunk boundary is present in both chunks, so no context is lost at the seam. Each sub-chunk is labelled with a `(part N)` suffix so its position in the section is traceable. A fallback handles documents with no headings at all — the entire document becomes one chunk, capped at 2000 characters.

Each chunk carries full metadata: `doc_path`, `doc_title`, `section`, `content`, `embed_text`, and a deterministic `chunk_id` (MD5 of path + section + first 100 characters of content).

### Embed Text Format

The text that gets embedded is not just the chunk's body content. It is formatted as:

```
"{doc_title} > {section_title}: {content}"
```

For example: `"Authentication Guide > JWT Payload Structure: Tokens use HS256 signing and expire after 30 minutes."`

This matters because embedding only the body text produces a vector with no signal about where the content lives. Prepending the document title and section heading means the embedding captures topical context — a query for "how does authentication work" can now match this chunk through the heading words, even if those words don't appear in the body. The `content` field is stored separately (unchanged) for display in the Writer's prompt.

This embed format is versioned via a `_EMBED_FORMAT_VERSION` constant (`"v2-title-section-content"`). The version is included in the content hash used for cache invalidation, so changing the format automatically invalidates any existing cached index.

### Index Caching and Cache Invalidation

Building embeddings for every document on every request would be slow and expensive. The index is persisted to disk as `rag_index.json` after the first build. On subsequent requests, `_compute_content_hash` computes a SHA-256 fingerprint over all document paths and contents (sorted by path for determinism), plus the embed format version. If the fingerprint matches the stored index, the build is skipped entirely. If any document changed — or the embed format was updated — the index is rebuilt from scratch.

Embeddings are requested in batches of 50 to avoid hitting API payload limits. Each batch retries up to 3 times with exponential backoff on rate-limit errors. If all retries fail, zero vectors are inserted as placeholders so the rest of the batch is not lost.

### Multi-Query Retrieval

Instead of searching with a single query string, the Planner produces up to 5 targeted search queries derived from the release's features, breaking changes, and affected systems. All queries are embedded in a single batch. Each document chunk is then scored by its **maximum cosine similarity across all query embeddings** — a chunk only needs to be relevant to any one query to be surfaced, not to all of them. This is critical for releases that span multiple systems: a release touching both billing and authentication will have queries for both, and chunks from each domain will score highly against their respective queries.

### Over-retrieval and Threshold Filtering

After scoring, the top 20 candidates are selected (the `_CANDIDATE_K` constant) rather than the final top-k. Candidates with a cosine similarity below `MIN_RELEVANCE_THRESHOLD = 0.1` are discarded regardless of rank — this filters out chunks that are technically the closest match in the corpus but are still not meaningfully related to the release. The over-retrieved candidate pool then goes into MMR selection.

### MMR Diversity Selection

Maximal Marginal Relevance (MMR) selects the final set of chunks from the 20 candidates. The algorithm is greedy: at each step it picks the chunk that maximises:

```
MMR score = 0.6 × relevance − 0.4 × max_similarity_to_any_already_selected_chunk
```

The `λ = 0.6` balance means relevance is weighted 60% and diversity 40%. A chunk that is highly relevant but says essentially the same thing as a chunk already selected will lose to a moderately relevant chunk that covers a different topic. The result is a final set of up to 10 chunks (hard cap) that covers the release's topics broadly rather than repeating the highest-scoring section five times.

### Retrieval Flow Summary

```
Planner produces rag_search_queries (up to 5 strings)
         │
         ▼
Embed all queries in one batch → list of query vectors
         │
         ▼
Score every index chunk: max cosine sim across all query vectors
         │
         ▼
Filter: discard chunks below MIN_RELEVANCE_THRESHOLD (0.1)
         │
         ▼
Over-retrieve: take top 20 candidates
         │
         ▼
MMR selection (λ=0.6): greedily pick up to 10 diverse chunks
         │
         ▼
Return chunks with relevance_score attached → passed to Writer
```

---

## Architectural Decisions and Rationale

### Decision 1: Multiple focused agents instead of one large prompt

The simplest approach would be to send everything — commits, tickets, PRs, existing docs — to a single LLM call and ask it to produce all four documents at once. The problem is that when something goes wrong (wrong risk level, missing ticket, bad tone), there is no way to know which part of the reasoning failed. Splitting the work into separate agents means each one has a clear, narrow job: the Digester only reads and summarises, the Planner only decides structure, the Writer only produces prose. Each agent can be tested in isolation with a mock LLM client, retried independently without re-running the whole pipeline, and debugged by inspecting exactly what it received and what it returned.

Beyond agent separation, the system pairs LLM calls with deterministic Python checks. An LLM is probabilistic — it follows instructions most of the time, not all of the time. For properties that must hold on every single release without exception, such as "every input ticket must appear in the output" or "a CVE always produces at least high risk", the system enforces these in Python code that runs after the LLM, treating LLM output as untrusted input to be validated. The LLM handles judgment calls; Python enforces the non-negotiables.

### Decision 2: Pre-extract identifiers before the LLM call

LLMs are strong pattern recognisers and will confidently produce ticket keys like `PLAT-9999` or CVE IDs like `CVE-2024-00001` that look completely real but were never in the source data. There is no reliable way to catch fabricated identifiers after the fact without the original source of truth. The solution is to collect all valid ticket keys, PR numbers, and CVE IDs from the raw artifacts in Python before any LLM call, pass that allowlist to the LLM explicitly, and instruct it to reference only from that list — never invent its own. Any identifier appearing in the output that was not in the source is flagged by the evaluator's `_check_fabricated_identifiers` check and forces the release to `needs_revision`.

### Decision 3: Risk level is an LLM holistic judgment with a deterministic safety floor

Jira priority reflects how urgently the team wants something done, not how dangerous it is to ship. A ticket labelled "Low" priority could be a cryptographic change that breaks existing integrations. A fixed rule-book mapping priority fields to risk levels will always have cases where the mapping is wrong, because Jira priority is not the same thing as deployment risk.

At the same time, pure LLM judgment has its own gap: one rule should always hold regardless of any contextual reasoning — if a release patches a known CVE, the risk is at least high. That is a fact, not a judgment call. The system lets the LLM assess overall risk freely using all available context, then enforces a Python floor post-LLM: the LLM's risk level can only be raised, never lowered below what the deterministic check calculates.

### Decision 4: Embed title and section alongside content in the RAG index

Embedding only the body content of a documentation chunk — for example, "Tokens use HS256 signing" — produces a vector that matches other cryptographic sentences but gives the retrieval system no signal about which document or section it came from. Embedding `"Authentication Guide > JWT Payload Structure: Tokens use HS256 signing"` instead makes the chunk findable via queries about authentication, JWT, or token payload, even if those exact words do not appear in the body text. The document title and section heading are free metadata that dramatically improve retrieval recall at no added cost — leaving them out discards context that the embedding model could directly use.

### Decision 5: MMR-based retrieval for diverse document coverage

With five RAG queries over a doc corpus, naive top-k retrieval tends to return five variations of the same highest-ranked paragraph. If the release touches both the billing system and the authentication system, the Writer ends up with five billing chunks and nothing about authentication. MMR (Maximal Marginal Relevance) solves this by penalising a chunk if it is semantically similar to one already selected. Each new selection must maximise `0.6 × relevance − 0.4 × redundancy`. The result is a diverse set of chunks that covers the full breadth of the release rather than a single topic repeated five times.



---

## Trade-offs

### Multiple LLM calls per release vs one combined call

Each release triggers 4–5 separate LLM calls — one per agent, plus an optional faithfulness judge. This costs more and takes longer (typically 10–30 seconds end to end) than a single combined call would. The benefit is that each call is small, focused, and independently debuggable. If the Writer produces a bad document, you can inspect exactly what the Planner handed it. If the Digester misclassifies risk, you can see the nine objective risk factors it was given. A single monolithic call would be cheaper but would make it nearly impossible to isolate and improve individual failure modes.

### In-memory release storage vs a real database

Generated releases are stored in a simple in-memory LRU store — fast, zero external dependencies, and no schema migrations. The downside is that everything is lost on server restart. For a project at this scope, the simplicity was the right call. The API contract (create, fetch, approve) maps directly onto a database table, so adding persistent storage later changes only the storage layer, not the agent pipeline or the API the frontend depends on.

### Mock data vs live GitHub and Jira APIs

The connectors default to local JSON fixtures instead of live API calls. This made it practical to build and test the entire agent pipeline without needing live credentials, worrying about rate limits, or depending on a real repository with the right data shape. The mock data is realistic — it includes proper ADF-formatted Jira descriptions, PR diffs with additions and deletions, labels, and priorities — so agents behave identically to how they would against real data. Switching to live APIs is a one-flag change; the connectors are already structured to accept real credentials.

### RAG index invalidated by content hash, not by time or external signal

The embedding index is only rebuilt when the document content or embed format version changes, detected via a content hash. This is efficient for the common case where docs are stable across many release generations. The risk is that a document edited between two generations could be served stale if the hash was computed before the edit arrived. In production this would be replaced by a webhook from the documentation CMS that explicitly invalidates the cache on any doc change — the hash approach is the correct lightweight choice for a system without that infrastructure.

### Customer-facing notes excluded from ticket key coverage scoring

The evaluator checks whether each Jira ticket key appears in the changelog and internal notes, weighted by priority. It deliberately skips customer-facing notes because those notes intentionally omit internal ticket identifiers — they mean nothing to a customer and would look unprofessional. The trade-off is that the evaluator has no keyed check for whether a ticket's user impact is represented in customer notes. The LLM faithfulness judge is the right signal there, since it checks whether the prose captures the intent of each change without requiring the ticket key to appear literally.

### Security exclusion verification by exact token match, not semantic similarity

The reviewer's `_verify_exclusions` step scans customer notes for literal CVE IDs and security-flagged ticket keys. If `CVE-2024-12345` appears in the customer notes verbatim, it is caught with certainty. The gap is that a paraphrase — "a vulnerability in the authentication layer was patched" — would not be caught by this check even if it reveals something the team did not want disclosed. Catching semantic leaks would require an additional LLM call and would risk false positives on legitimate security-awareness language. The exact-match check is the right automated gate for the clearest violations; the LLM reviewer's general quality pass is the backstop for subtler cases.

---

## Future Improvements

### 1. Webhook-triggered generation with real GitHub and Jira integrations

Right now, a user manually submits a release request through the UI. A more natural workflow would have the system trigger automatically: when an engineer merges a pull request into the release branch, GitHub sends a webhook to this backend, which kicks off the full pipeline without any manual step. When a Jira version is marked as released, the system could pull all tickets in that version automatically. The connectors are already structured to accept real credentials — completing the OAuth flows and adding webhook handlers would make the system fit into an engineering team's existing release process without requiring anyone to remember to run it.

### 2. Iterative revision loop between Reviewer and Writer

If the Reviewer flags problems — a hallucinated claim, a missing ticket, wrong tone in customer notes — the release is currently marked `needs_revision` and a human has to step in. A better design would have the Reviewer send its specific feedback back to the Writer automatically, and the Writer would regenerate only the sections with problems. This loop would run two or three times before escalating to a human. Most quality issues in practice are small and deterministic — a ticket key appearing in customer notes, a missing breaking-change warning — and an automated revision pass would resolve them without human involvement, so reviewers only see genuinely ambiguous cases.

### 3. Streaming output for real-time pipeline visibility

The pipeline takes 10–30 seconds because several LLM calls run sequentially. The user currently sees a loading spinner for the entire duration and receives everything at once. With server-sent events or WebSocket streaming, the frontend could display each agent's output as it completes — the digest appears after a few seconds, the editorial plan appears while the Writer is running, and the four documents fill in progressively. The total latency stays the same, but users get early signal about whether the generation is on track and can start reviewing the digest while the Writer is still working.

### 4. Learning from human edits to improve future generations

Every time a reviewer edits an AI-generated release note before approving it, that edit is a signal about where the system fell short. If reviewers consistently rewrite customer-facing sections to be less technical, or always add a migration warning the system missed, those patterns should feed back into the system. The practical implementation is collecting approved releases alongside their human-edited final versions and using them as few-shot examples in the Writer's prompt — the next generation sees concrete examples of what good output looks like for this specific team. Over time the system gets calibrated to each organisation's style and standards without any manual prompt engineering.

### 5. Parallel agent execution to reduce end-to-end latency

The pipeline runs each agent sequentially even when steps have no dependency on each other. The RAG index build and the Digester both start from the same raw source data and are fully independent — they could run simultaneously. The Planner can start the moment the Digester finishes, while RAG retrieval uses a preliminary query derived from the digest summary to warm up in parallel. Restructuring the pipeline as a dependency graph — where each agent starts as soon as its inputs are ready — would cut total wall-clock time by 30–40% without changing what any individual agent does. This matters more as the system grows to handle additional data sources or more agents in the pipeline.
