"""Planner Agent - Decides documentation structure and editorial strategy.

Handles edge cases:
- Empty digest (no features/fixes/breaking_changes)
- No existing documentation
- Very large doc corpora (truncation)

Security exclusions are enforced DETERMINISTICALLY in Python (_enforce_security_exclusions)
after the LLM call — never relying on prompt-following for safety-critical omissions.
"""
import re
import logging

from .base import call_llm_with_retry, truncate_text, AgentError

logger = logging.getLogger("release_agent")

# Compiled regexes for deterministic security token extraction
_CVE_RE = re.compile(r'CVE-\d{4}-\d+')
_TICKET_RE = re.compile(r'\b[A-Z][A-Z0-9]+-\d+\b')

SYSTEM_PROMPT = """You are a Release Documentation Planner and Editorial Strategy Agent.
Given a release digest and existing documentation, you produce a structured documentation plan
AND an editorial strategy that guides the Writer.

Output a JSON object with EXACTLY these fields:

"changelog_plan": {"sections": [...], "tone": "technical"}
"internal_notes_plan": {"audience": "engineering", "sections": [...], "include_risk": true}
"customer_notes_plan": {"audience": "end-users", "sections": [...], "tone": "friendly"}
"doc_update_plan": array of {"doc_path": string, "section": string, "action": "add"|"update"|"review", "reason": string}

"core_narrative": string OR null.
  Infer a unifying editorial theme ONLY from the actual features and breaking_changes in the
  digest. Good examples: "This release modernises the payment stack with Stripe", "Security
  hardening release — authentication overhaul".
  Return null if the release has no coherent theme (e.g. a collection of unrelated fixes).
  NEVER invent a theme not directly supported by the listed items.

"exclusion_list": array of {"item": string, "reason": string, "exclude_from": [doc_type, ...]}.
  Propose items that should be excluded from specific doc types.
  doc_type values: "customer_release_notes", "changelog", "internal_notes".
  Example: internal implementation details (SQL schema names, middleware internals) should be
  excluded from customer_release_notes.
  NOTE: Python will automatically add security/CVE items — do not duplicate them here.

"audience_outlines": {"customer": [...], "internal": [...]}.
  Arrays of short EDITORIAL ANGLES (not prose) for each audience. Tell the Writer what arguments
  to make, not what words to use. Cap at 8 bullets each.
  Customer examples: "Frame Stripe as a 1-click checkout upgrade", "Reassure users card data is safe".
  Internal examples: "Detail JWT breaking change migration steps", "Flag DB migration rollback risk".

"rag_search_queries": array of short search strings (max 5) to run against the documentation
  vector store. Derive them from breaking_changes, affected_systems, and features.
  Examples: "old PayPal subscription payload schema", "JWT auth migration guide",
  "Stripe checkout integration". These help surface relevant prior docs for the Writer.

Rules:
1. If no existing docs match the changes, doc_update_plan should suggest new sections.
2. Consider what level of detail each audience needs.
3. Always include risk assessment in internal notes if risk_level is medium or high.
4. For customer notes, never include internal implementation details.
5. If the release is a bug fix only, keep customer notes brief.
6. core_narrative must be derivable from features or breaking_changes — not invented.
7. audience_outlines bullets are strategy directives, not prose — keep them short and actionable."""


def plan(
    digest: dict,
    existing_docs: list[dict],
    client,
    tickets: list | None = None,
    max_retries: int = 3,
) -> dict:
    """Create a documentation plan and editorial strategy based on the digest and existing docs.

    Args:
        digest: Structured release digest from Digester agent
        existing_docs: List of existing documentation documents
        client: LLM client instance
        tickets: Original Jira tickets (for deterministic security exclusion enforcement)
        max_retries: Number of retry attempts

    Returns:
        Documentation plan and editorial strategy dictionary
    """
    tickets = tickets or []

    # Handle edge case: truly empty digest — no features, no bug_fixes, AND no breaking_changes
    if (
        not digest.get("features")
        and not digest.get("bug_fixes")
        and not digest.get("breaking_changes")
    ):
        logger.warning("Planner received empty digest - generating minimal plan")
        return _minimal_plan()

    user_content = _build_user_prompt(digest, existing_docs)

    result = call_llm_with_retry(
        client=client,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        agent_name="Planner",
        temperature=0.2,
        max_retries=max_retries,
    )

    validated = _validate_plan(result)

    # DETERMINISTIC STEP: enforce security exclusions regardless of LLM output.
    # This is not prompt-following — Python inspects the digest items directly.
    _enforce_security_exclusions(validated, digest, tickets)

    return validated


def _build_user_prompt(digest: dict, existing_docs: list[dict]) -> str:
    parts = ["Based on this release digest, plan the documentation artifacts and editorial strategy:\n"]

    parts.append("## Release Digest")
    parts.append(f"Summary: {digest.get('summary', 'N/A')}")
    parts.append(f"Risk Level: {digest.get('risk_level', 'unknown')}")
    risk_rationale = digest.get("risk_rationale", [])
    if risk_rationale:
        parts.append(f"Risk Rationale: {'; '.join(str(r) for r in risk_rationale[:3])}")
    parts.append(f"Affected Systems: {', '.join(digest.get('affected_systems', []))}")

    features = digest.get("features", [])
    if features:
        parts.append("Features:")
        for f in features[:20]:
            parts.append(f"  - {truncate_text(str(f), 200)}")

    bug_fixes = digest.get("bug_fixes", [])
    if bug_fixes:
        parts.append("Bug Fixes:")
        for b in bug_fixes[:20]:
            parts.append(f"  - {truncate_text(str(b), 200)}")

    breaking = digest.get("breaking_changes", [])
    if breaking:
        parts.append("BREAKING CHANGES (must get their own section in all docs):")
        for bc in breaking:
            parts.append(f"  - {truncate_text(str(bc), 200)}")

    code_insights = digest.get("code_insights", [])
    if code_insights:
        parts.append("Code-Level Insights (from diff analysis):")
        for ci in code_insights[:10]:
            if isinstance(ci, dict):
                verified_tag = "" if ci.get("verified", True) else " [unverified]"
                line = f"[{ci.get('change_type', '?')}] {ci.get('filename', '?')}{verified_tag}: {ci.get('observation', '')}"
            else:
                line = str(ci)
            parts.append(f"  - {truncate_text(line, 200)}")

    if existing_docs:
        parts.append("\n## Existing Documentation")
        for d in existing_docs[:20]:
            path = d.get("path", "unknown")
            content_preview = truncate_text(d.get("content", ""), 150)
            parts.append(f"- {path}: {content_preview}")
    else:
        parts.append("\n## Existing Documentation\nNo existing documentation found.")

    parts.append(
        "\nCreate a structured plan and editorial strategy. "
        "For core_narrative, derive it ONLY from the features and breaking_changes listed above — "
        "return null if there is no coherent theme. "
        "For rag_search_queries, derive them from breaking_changes, affected_systems, and features."
    )
    return "\n".join(parts)


def _minimal_plan() -> dict:
    """Return a minimal plan when there is nothing substantial to document."""
    return {
        "changelog_plan": {"sections": ["maintenance"], "tone": "technical"},
        "internal_notes_plan": {
            "audience": "engineering",
            "sections": ["summary"],
            "include_risk": False,
        },
        "customer_notes_plan": {
            "audience": "end-users",
            "sections": ["summary"],
            "tone": "friendly",
        },
        "doc_update_plan": [],
        "core_narrative": None,
        "exclusion_list": [],
        "audience_outlines": {"customer": [], "internal": []},
        "rag_search_queries": [],
    }


def _validate_plan(result: dict) -> dict:
    """Ensure plan has required structure with correct types and bounds."""
    # ── Existing fields ────────────────────────────────────────────────────────
    if "changelog_plan" not in result:
        result["changelog_plan"] = {"sections": ["changes"], "tone": "technical"}
    if "internal_notes_plan" not in result:
        result["internal_notes_plan"] = {
            "audience": "engineering",
            "sections": ["summary", "changes"],
            "include_risk": True,
        }
    if "customer_notes_plan" not in result:
        result["customer_notes_plan"] = {
            "audience": "end-users",
            "sections": ["summary"],
            "tone": "friendly",
        }
    if "doc_update_plan" not in result:
        result["doc_update_plan"] = []

    valid_actions = {"add", "update", "review"}
    validated_updates = []
    for entry in result.get("doc_update_plan", []):
        if isinstance(entry, dict) and "doc_path" in entry:
            action = entry.get("action", "review")
            if action not in valid_actions:
                action = "review"
            validated_updates.append({
                "doc_path": str(entry["doc_path"]),
                "section": str(entry.get("section", "")),
                "action": action,
                "reason": str(entry.get("reason", "")),
            })
    result["doc_update_plan"] = validated_updates

    # ── New fields ─────────────────────────────────────────────────────────────

    # core_narrative: non-empty string or null only
    cn = result.get("core_narrative")
    if cn is None:
        pass
    elif not isinstance(cn, str):
        cn = str(cn) if cn else None
    elif not cn.strip():
        cn = None
    result["core_narrative"] = cn

    # exclusion_list: list of {item, reason, exclude_from}
    raw_excl = result.get("exclusion_list", [])
    if not isinstance(raw_excl, list):
        raw_excl = []
    valid_doc_types = {"customer_release_notes", "changelog", "internal_notes"}
    exclusion_list = []
    for entry in raw_excl:
        if not isinstance(entry, dict):
            continue
        item = str(entry.get("item", "")).strip()
        reason = str(entry.get("reason", "")).strip()
        exclude_from = entry.get("exclude_from", [])
        if not isinstance(exclude_from, list):
            exclude_from = [str(exclude_from)] if exclude_from else []
        exclude_from = [d for d in exclude_from if d in valid_doc_types]
        if item and exclude_from:
            exclusion_list.append({
                "item": item,
                "reason": reason,
                "exclude_from": exclude_from,
            })
    result["exclusion_list"] = exclusion_list

    # audience_outlines: {customer: [...], internal: [...]}, cap at 8 each
    ao = result.get("audience_outlines")
    if not isinstance(ao, dict):
        ao = {}
    customer_bullets = ao.get("customer", [])
    internal_bullets = ao.get("internal", [])
    if not isinstance(customer_bullets, list):
        customer_bullets = []
    if not isinstance(internal_bullets, list):
        internal_bullets = []
    result["audience_outlines"] = {
        "customer": [str(b) for b in customer_bullets[:8]],
        "internal": [str(b) for b in internal_bullets[:8]],
    }

    # rag_search_queries: list of strings, cap at 5
    rq = result.get("rag_search_queries", [])
    if not isinstance(rq, list):
        rq = []
    result["rag_search_queries"] = [str(q) for q in rq if q][:5]

    return result


def _enforce_security_exclusions(plan: dict, digest: dict, tickets: list) -> None:
    """Deterministically add security-sensitive items to exclusion_list.

    Operates entirely in Python on pre-extracted data — no LLM involvement.
    Adds any digest item that references a CVE ID, or whose source ticket has a
    security label or vulnerability-type issue, to exclusion_list with
    exclude_from including 'customer_release_notes'.

    Called after _validate_plan so exclusion_list already exists as a list.
    """
    # Build a set of security-sensitive ticket keys from the original tickets
    security_ticket_keys: set[str] = set()
    for t in tickets:
        key = t.get("key", "")
        if not key:
            continue
        fields = t.get("fields", t)

        # Check issue type (vulnerability, security)
        issuetype_name = ""
        issuetype = fields.get("issuetype")
        if isinstance(issuetype, dict):
            issuetype_name = issuetype.get("name", "").lower()
        elif isinstance(issuetype, str):
            issuetype_name = issuetype.lower()
        if "vulnerability" in issuetype_name or "security" in issuetype_name:
            security_ticket_keys.add(key)

        # Check Jira labels
        for lbl in fields.get("labels", []):
            lbl_str = lbl.lower() if isinstance(lbl, str) else str(lbl).lower()
            if "security" in lbl_str or "vulnerability" in lbl_str or "vuln" in lbl_str:
                security_ticket_keys.add(key)

    # Track items already in exclusion_list (avoid duplicates)
    already_excluded = {
        e["item"]
        for e in plan.get("exclusion_list", [])
        if "customer_release_notes" in e.get("exclude_from", [])
    }

    new_entries = []
    for field in ("features", "bug_fixes", "breaking_changes"):
        for item in digest.get(field, []):
            item_str = str(item)
            if item_str in already_excluded:
                continue

            # Signal 1: CVE reference in the item text
            cves = _CVE_RE.findall(item_str)
            if cves:
                new_entries.append({
                    "item": item_str,
                    "reason": f"CVE reference detected ({', '.join(cves)}) — excluded from customer release notes",
                    "exclude_from": ["customer_release_notes"],
                })
                already_excluded.add(item_str)
                continue

            # Signal 2: references a security-sensitive ticket key
            item_ticket_keys = set(_TICKET_RE.findall(item_str))
            if item_ticket_keys & security_ticket_keys:
                matched = sorted(item_ticket_keys & security_ticket_keys)
                new_entries.append({
                    "item": item_str,
                    "reason": f"Security-sensitive ticket ({', '.join(matched)}) — excluded from customer release notes",
                    "exclude_from": ["customer_release_notes"],
                })
                already_excluded.add(item_str)

    plan["exclusion_list"].extend(new_entries)


def extract_security_tokens(item_text: str) -> list[str]:
    """Extract CVE IDs and Jira ticket keys from an exclusion item for leak verification.

    Used by the reviewer to check that excluded terms don't appear in customer notes.
    Public so it can be imported by reviewer.py without circular dependencies.
    """
    cves = _CVE_RE.findall(item_text)
    tickets = _TICKET_RE.findall(item_text)
    return cves + tickets
