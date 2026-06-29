"""Writer Agent - Generates polished release documentation content.

Receives the digest, plan, RAG docs, AND a condensed view of the original
PRs and tickets so it can cite specific PR numbers and ticket keys accurately.
"""
import json
import logging

from .base import call_llm_with_retry, truncate_text, validate_writer_output, AgentError

logger = logging.getLogger("release_agent")

SYSTEM_PROMPT = """You are a Release Writer Agent. You produce polished, well-structured documentation
based on a release digest, a documentation plan, and the original source evidence.

Output a JSON object with EXACTLY these fields:
- "changelog": markdown-formatted changelog
- "internal_release_notes": markdown-formatted internal notes
- "customer_release_notes": markdown-formatted customer-facing notes
- "documentation_updates": array of {"doc_path": string, "section": string, "suggested_content": string, "action": "add"|"update"}
  Only emit an entry for genuine conflicts ("update") or new coverage gaps ("add"). Never emit "review".

STRUCTURE — DRIVEN BY THE DOCUMENTATION PLAN (not a fixed template):
The user message includes a Documentation Plan. Build each document's structure FROM THAT PLAN:
- changelog: create the sections listed in changelog_plan.sections, in changelog_plan.tone.
  Begin with "# Changelog" and a "## [VERSION] - DATE" header.
- internal_release_notes: create the sections listed in internal_notes_plan.sections, written for
  internal_notes_plan.audience. Include a risk assessment if internal_notes_plan.include_risk is true.
- customer_release_notes: create the sections listed in customer_notes_plan.sections, in
  customer_notes_plan.tone, for customer_notes_plan.audience.
- documentation_updates: produce one entry per item in doc_update_plan, with concrete
  suggested_content for each.
Only create sections warranted by the plan and the data — do not pad with empty sections. If the
plan provides no sections for a document, choose sensible sections from the digest content.

MARKDOWN FORMATTING RULES (apply to changelog, internal_release_notes, customer_release_notes —
this is critical; the output is rendered as markdown):
- Begin each document with a single "# Title" line (e.g. "# Internal Release Notes").
- Render every plan section as a "## Section Name" heading; use "###" for sub-sections.
- Put a blank line BEFORE and AFTER every heading, and a blank line between paragraphs.
- Write all enumerations as markdown bullet lists ("- item") — NEVER as consecutive plain lines.
- Use **bold** for key labels and `inline code` for identifiers, field names, endpoints, and
  version numbers (e.g. `processor`, `/api/v2/search`, `external_subscription_id`).
- Keep prose in short paragraphs or bullets. Do NOT output one sentence per line as a flat wall.

Example shape (use the plan's ACTUAL section names, not these placeholders):
# Internal Release Notes

## <Section from plan>
Short intro sentence for this section.

- **Key point:** supporting detail (PLAT-XXXX, PR #NN)
- **Another point:** supporting detail

## <Next section from plan>
More content...

CITATION RULES:
- Cite ticket keys (e.g. PLAT-2002) and PR numbers (e.g. PR #201) in changelog and internal notes.
- In customer notes, NEVER cite ticket keys or PR numbers — use plain language only.
- If a change has no ticket reference, note it as (no ticket).

AUDIENCE RULES:
- Internal/engineering docs: technical detail is welcome.
- Customer docs: focus on benefits, not implementation. No jargon (avoid "endpoint", "SQL",
  "JWT", "middleware", "migration"). Mention if users must log back in or re-configure anything.

ACCURACY & SAFETY RULES (always apply, regardless of plan):
1. ONLY include facts supported by the digest and source evidence.
2. Do NOT fabricate endpoints, version numbers, or technical details not in the evidence.
3. Anything marked BREAKING must be clearly documented in the changelog and internal notes.
4. Security fixes with CVE IDs must appear in the internal/technical documentation.

EDITORIAL STRATEGY RULES (from the plan):
5. If a core_narrative is provided, open each document with an intro that reflects that theme.
   If core_narrative is null, treat this as a routine release — no forced narrative.
6. The audience_outlines provide ANGLES to cover — make sure each bullet is addressed in the
   appropriate document (customer angles → customer_release_notes; internal angles → internal_release_notes).
7. EXCLUSION LIST (CRITICAL): Items in the exclusion_list MUST NOT appear in the doc types
   listed in their exclude_from field. This is enforced by a separate verification step.
   Specifically: never include CVE IDs, security vulnerability details, or internal
   implementation specifics in customer_release_notes when they appear in the exclusion list."""


def write(
    digest: dict,
    plan: dict,
    relevant_docs: list[dict],
    client,
    source_artifacts: dict | None = None,
    max_retries: int = 3,
) -> dict:
    """Generate all release documentation artifacts.

    Args:
        digest: Structured release digest from Digester agent
        plan: Documentation plan from Planner agent
        relevant_docs: RAG-retrieved document chunks
        client: LLM client instance
        source_artifacts: Optional condensed view of original PRs and tickets
        max_retries: Number of retry attempts
    """
    if not digest.get("summary") and not digest.get("features") and not digest.get("bug_fixes"):
        logger.warning("Writer received empty digest - returning minimal output")
        return {
            "changelog": "# Changelog\n\nNo significant changes in this release.",
            "internal_release_notes": "No significant changes.",
            "customer_release_notes": "No customer-facing changes in this release.",
            "documentation_updates": [],
        }

    user_content = _build_user_prompt(digest, plan, relevant_docs, source_artifacts or {})

    result = call_llm_with_retry(
        client=client,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        agent_name="Writer",
        temperature=0.3,
        max_retries=max_retries,
    )

    return validate_writer_output(result)


def _build_user_prompt(
    digest: dict,
    plan: dict,
    relevant_docs: list[dict],
    source_artifacts: dict,
) -> str:
    parts = []

    # --- Release Digest ---
    parts.append("## Release Digest\n")
    parts.append(f"**Summary:** {digest.get('summary', 'N/A')}")
    parts.append(f"**Risk Level:** {digest.get('risk_level', 'unknown')}")
    rationale = digest.get("risk_rationale", [])
    if rationale:
        parts.append(f"**Risk Rationale:** {'; '.join(str(r) for r in rationale)}")

    affected = digest.get("affected_systems", [])
    if affected:
        parts.append(f"**Affected Systems:** {', '.join(str(s) for s in affected)}")

    features = digest.get("features", [])
    if features:
        parts.append("\n**Features:**")
        for f in features[:20]:
            parts.append(f"  - {truncate_text(str(f), 250)}")

    bug_fixes = digest.get("bug_fixes", [])
    if bug_fixes:
        parts.append("\n**Bug Fixes:**")
        for b in bug_fixes[:20]:
            parts.append(f"  - {truncate_text(str(b), 250)}")

    breaking = digest.get("breaking_changes", [])
    if breaking:
        parts.append("\n**BREAKING CHANGES (must be documented):**")
        for bc in breaking:
            parts.append(f"  - {truncate_text(str(bc), 250)}")

    code_insights = digest.get("code_insights", [])
    if code_insights:
        parts.append("\n**Code-Level Insights (from diff analysis):**")
        for ci in code_insights[:10]:
            if isinstance(ci, dict):
                verified_tag = "" if ci.get("verified", True) else " [unverified]"
                line = f"[{ci.get('change_type', '?')}] {ci.get('filename', '?')}{verified_tag}: {ci.get('observation', '')}"
            else:
                line = str(ci)
            parts.append(f"  - {truncate_text(line, 200)}")

    # --- Source Evidence: PRs and Tickets (condensed) ---
    prs = source_artifacts.get("pull_requests", [])
    if prs:
        parts.append("\n## Pull Requests Included in This Release\n")
        parts.append("IMPORTANT: Use the exact PR number when citing each change.\n")
        for pr in prs:
            number = pr.get("number", pr.get("id", "?"))
            title = pr.get("title", "?")
            labels = pr.get("labels", [])
            label_names = [
                lbl.get("name", str(lbl)) if isinstance(lbl, dict) else str(lbl)
                for lbl in labels
            ]
            additions = pr.get("additions", 0)
            deletions = pr.get("deletions", 0)
            body = pr.get("body", "")
            parts.append(f"**PR #{number}:** {title}")
            if label_names:
                parts.append(f"  Labels: {', '.join(label_names)}")
            parts.append(f"  Changes: +{additions} -{deletions}")
            jira_refs = pr.get("jira_tickets", [])
            if jira_refs:
                parts.append(f"  Jira refs: {', '.join(jira_refs)}")
            if body:
                parts.append(f"  Description (excerpt):\n{truncate_text(body, 500)}")

    tickets = source_artifacts.get("tickets", [])
    if tickets:
        parts.append("\n## Jira Tickets in This Release\n")
        for t in tickets:
            key = t.get("key", "?")
            fields = t.get("fields", t)
            summary = fields.get("summary", t.get("summary", "?"))
            issuetype = (fields.get("issuetype") or {}).get("name", fields.get("type", "?"))
            priority = (fields.get("priority") or {}).get("name", fields.get("priority", "?"))

            # Extract description text from ADF or plain string
            desc_field = fields.get("description", t.get("description", ""))
            desc_text = ""
            if isinstance(desc_field, dict) and desc_field.get("type") == "doc":
                desc_text = _extract_adf_text(desc_field)
            elif isinstance(desc_field, str):
                desc_text = desc_field

            parts.append(f"**[{key}]** ({issuetype}, {priority}) {summary}")
            if desc_text:
                parts.append(f"  Details: {truncate_text(desc_text, 400)}")

    # --- Editorial Strategy (from Planner) ---
    core_narrative = plan.get("core_narrative")
    if core_narrative:
        parts.append(f"\n## Editorial Theme\n"
                     f"Frame all three documents around this theme: **{core_narrative}**\n"
                     f"Open each document with an intro that reflects this narrative.")
    else:
        parts.append("\n## Editorial Theme\nNo unifying theme identified — treat as a routine release.\n")

    audience_outlines = plan.get("audience_outlines", {})
    customer_angles = audience_outlines.get("customer", [])
    internal_angles = audience_outlines.get("internal", [])
    if customer_angles:
        parts.append("## Customer Document Angles (cover all of these in customer_release_notes)")
        for bullet in customer_angles:
            parts.append(f"  - {bullet}")
    if internal_angles:
        parts.append("## Internal Document Angles (cover all of these in internal_release_notes)")
        for bullet in internal_angles:
            parts.append(f"  - {bullet}")

    exclusion_list = plan.get("exclusion_list", [])
    if exclusion_list:
        parts.append("\n## EXCLUSION LIST (mandatory — do NOT include these in the specified doc types)")
        for entry in exclusion_list:
            doc_types = ", ".join(entry.get("exclude_from", []))
            parts.append(f"  EXCLUDE from [{doc_types}]: {truncate_text(entry.get('item', ''), 150)}")
            parts.append(f"    Reason: {entry.get('reason', '')}")

    # --- Documentation Plan ---
    parts.append("\n## Documentation Plan (follow this structure)\n")
    plan_keys = ["changelog_plan", "internal_notes_plan", "customer_notes_plan", "doc_update_plan"]
    plan_subset = {k: plan[k] for k in plan_keys if k in plan}
    plan_text = json.dumps(plan_subset, indent=2)
    parts.append(truncate_text(plan_text, 1500))

    # --- RAG Context with contradiction-detection instructions ---
    if relevant_docs:
        parts.append("\n## Existing Documentation — Contradiction Analysis\n")
        parts.append(
            "For EACH chunk below, decide ONE of:\n"
            "  (a) CONFLICT: This chunk says something the release changes make outdated or wrong.\n"
            "      → Emit documentation_updates entry: action='update', doc_path=the path,\n"
            "        section=the section, suggested_content naming what is outdated and the correction.\n"
            "  (b) COVERAGE GAP: The release introduces something with NO doc coverage in ANY chunk.\n"
            "      → Emit documentation_updates entry: action='add', suggested_content describing\n"
            "        what new section is needed and what it should say.\n"
            "  (c) RELATED BUT UNAFFECTED: The chunk is topically related but not actually changed.\n"
            "      → Do NOT emit any documentation_updates entry. Skip it entirely.\n"
            "Only emit an entry when there is a genuine conflict or new coverage gap. "
            "Never emit action='review' — only 'update' or 'add'.\n"
        )
        for d in relevant_docs[:5]:
            path = d.get("path", d.get("doc_path", "unknown"))
            section = d.get("section", "")
            content = truncate_text(d.get("content", ""), 350)
            parts.append(f"### {path} > {section}\n{content}")
    else:
        parts.append(
            "\n## Existing Documentation\n"
            "No relevant docs found via RAG. "
            "If the release introduces new capabilities, emit 'add' entries in documentation_updates."
        )

    parts.append(
        "\nNow write all four documentation artifacts, structuring each one according to the "
        "Documentation Plan above. Cite every PR number and ticket key in changelog and internal "
        "notes (never in customer notes). Use proper markdown with headings and bullet points. "
        "Ensure any breaking changes are clearly documented."
    )

    return "\n".join(parts)


def _extract_adf_text(node: dict, depth: int = 0) -> str:
    """Recursively extract plain text from Atlassian Document Format nodes."""
    if depth > 8 or not isinstance(node, dict):
        return str(node) if not isinstance(node, dict) else ""
    if node.get("type") == "text":
        return node.get("text", "")
    parts = []
    for child in node.get("content", []):
        t = _extract_adf_text(child, depth + 1)
        if t:
            parts.append(t)
    sep = "\n" if node.get("type") in ("paragraph", "heading", "listItem", "bulletList", "orderedList") else " "
    return sep.join(parts)
