"""Evaluation Framework - Measures quality of generated documentation.

Metrics:
1. Hallucination Rate: LLM faithfulness judge (or reviewer-proxy fallback)
2. Ticket Coverage: Priority-weighted, word-boundary key matching (technical docs only)
3. Doc Recommendation Accuracy: Precision/Recall/F1 vs gold set, or validity fallback
4. Content Quality: Structural checks (length, headings, bullets, jargon)

Critical Gates (override overall_score — no averaging can hide these):
- Any fabricated identifier (CVE, ticket key, PR number) → force needs_revision
- Any security-excluded term leaking into customer_release_notes → force needs_revision

Named weight constants replace all inline magic numbers.
"""
import json
import re
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("release_agent")

# ── Named weights (sum to 1.0) ────────────────────────────────────────────────
WEIGHT_HALLUCINATION = 0.35    # contribution of (1 - hallucination_rate)
WEIGHT_TICKET_COVERAGE = 0.30
WEIGHT_DOC_ACCURACY = 0.15
WEIGHT_CONTENT_QUALITY = 0.20

# overall_score below this signals needs_revision; importable by main.py
NEEDS_REVISION_THRESHOLD = 0.5

# Jira priority → weight for weighted ticket coverage
PRIORITY_WEIGHTS: dict[str, float] = {
    "highest": 1.0,
    "high": 0.75,
    "medium": 0.5,
    "low": 0.25,
}
DEFAULT_PRIORITY_WEIGHT = 0.5  # used when priority is absent or unknown

# Gold files live here: backend/mock_data/gold/<release_name>.json
_GOLD_DIR = Path(__file__).parent.parent / "mock_data" / "gold"

# Identifier regexes — mirrors digester.py, kept independent to avoid coupling
_CVE_RE = re.compile(r'CVE-\d{4}-\d+')
_TICKET_RE = re.compile(r'\b[A-Z][A-Z0-9]+-\d+\b')
_PR_REF_RE = re.compile(r'PR\s*#\s*(\d+)')  # "PR #201" or "PR#201"


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class EvaluationResult:
    """Results from evaluating generated documentation."""
    hallucination_rate: float = 0.0
    ticket_coverage: float = 0.0
    doc_recommendation_accuracy: float = 0.0
    content_quality_score: float = 0.0
    overall_score: float = 0.0
    force_needs_revision: bool = False   # True when any critical gate fired
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "hallucination_rate": round(self.hallucination_rate, 3),
            "ticket_coverage": round(self.ticket_coverage, 3),
            "doc_recommendation_accuracy": round(self.doc_recommendation_accuracy, 3),
            "content_quality_score": round(self.content_quality_score, 3),
            "overall_score": round(self.overall_score, 3),
            "force_needs_revision": self.force_needs_revision,
            "details": self.details,
        }


# ── Main entry point ──────────────────────────────────────────────────────────

def evaluate(
    generated_docs: dict,
    review_result: dict,
    tickets: list[dict],
    existing_docs: list[dict],
    source_artifacts: dict | None = None,
    client=None,
    plan: dict | None = None,
    release_name: str | None = None,
) -> EvaluationResult:
    """Evaluate generated documentation quality across multiple dimensions.

    Original parameters (unchanged — backward compatible):
        generated_docs: Output from Writer agent
        review_result: Output from Reviewer agent
        tickets: Original Jira tickets (ground truth)
        existing_docs: Existing documentation corpus

    New optional parameters (default None — existing callers unaffected):
        source_artifacts: Raw commits/PRs/tickets for identifier fabrication checks
        client: LLM client for faithfulness judge; None → reviewer-proxy fallback
        plan: Documentation plan from Planner (used for security-exclusion gate)
        release_name: Identifies a gold file if one exists for this release

    Returns:
        EvaluationResult with all metrics, gates, and detailed breakdown
    """
    result = EvaluationResult()

    # ── Stage 1: Deterministic fabricated-identifier check ─────────────────
    fabricated: list[dict] = []
    if source_artifacts:
        fabricated = _check_fabricated_identifiers(generated_docs, source_artifacts)

    # ── Stage 2: Hallucination rate ─────────────────────────────────────────
    unsupported_claims: list[dict] = []
    if client and source_artifacts:
        llm_rate, unsupported_claims = _compute_faithfulness_rate(
            generated_docs, source_artifacts, client
        )
        if llm_rate is not None:
            # Fabricated identifiers are always unsupported; blend into rate
            n_extra = len(fabricated)
            if n_extra:
                total_est = max(1, len(unsupported_claims) + n_extra + 5)
                result.hallucination_rate = min(1.0, llm_rate + n_extra / total_est)
            else:
                result.hallucination_rate = llm_rate
        else:
            result.hallucination_rate = _compute_hallucination_rate(review_result)
    else:
        result.hallucination_rate = _compute_hallucination_rate(review_result)

    # ── Stage 3: Priority-weighted ticket coverage (technical docs only) ────
    weighted_score, coverage_per_ticket = _compute_weighted_ticket_coverage(
        generated_docs, tickets
    )
    result.ticket_coverage = weighted_score

    # ── Stage 4: Doc-update F1 vs gold file, or validity fallback ──────────
    doc_accuracy, doc_eval_details = _compute_doc_update_f1(
        generated_docs, existing_docs, release_name
    )
    result.doc_recommendation_accuracy = doc_accuracy

    # Content quality (structural checks — unchanged)
    result.content_quality_score = _compute_content_quality(generated_docs)

    # ── Stage 5: Overall score using named weight constants ─────────────────
    result.overall_score = (
        (1.0 - result.hallucination_rate) * WEIGHT_HALLUCINATION
        + result.ticket_coverage * WEIGHT_TICKET_COVERAGE
        + result.doc_recommendation_accuracy * WEIGHT_DOC_ACCURACY
        + result.content_quality_score * WEIGHT_CONTENT_QUALITY
    )

    # ── Stage 5: Critical gates — override regardless of score ──────────────
    gate_violations = _check_critical_gates(fabricated, generated_docs, plan)
    result.force_needs_revision = bool(gate_violations)

    # Detailed breakdown for transparency
    result.details = _build_details(
        result, generated_docs, review_result, tickets, existing_docs,
        fabricated, unsupported_claims, coverage_per_ticket,
        doc_eval_details, gate_violations,
    )

    logger.info(
        f"Evaluation complete: overall={result.overall_score:.2f}, "
        f"hallucination={result.hallucination_rate:.2f}, "
        f"coverage={result.ticket_coverage:.2f}, "
        f"force_needs_revision={result.force_needs_revision}"
    )
    return result


# ── Stage 1: Fabricated identifier detection ──────────────────────────────────

def _check_fabricated_identifiers(
    generated_docs: dict,
    source_artifacts: dict,
) -> list[dict]:
    """Find CVE IDs, ticket keys, and PR numbers in output absent from source.

    These are guaranteed hallucinations — the LLM invented an identifier that
    does not appear anywhere in the source evidence.
    Returns list of {identifier, type}.
    """
    tickets = source_artifacts.get("tickets", [])
    pull_requests = source_artifacts.get("pull_requests", [])
    commits = source_artifacts.get("commits", [])

    allowed_ticket_keys = {t.get("key", "") for t in tickets if t.get("key")}
    allowed_pr_numbers = {
        str(pr.get("number", pr.get("id", "")))
        for pr in pull_requests
        if pr.get("number") or pr.get("id")
    }
    allowed_cves = set(_CVE_RE.findall(_build_source_text(tickets, pull_requests, commits)))

    all_output = _flatten_text(generated_docs)
    fabricated: list[dict] = []

    for cve in sorted(set(_CVE_RE.findall(all_output)) - allowed_cves):
        fabricated.append({"identifier": cve, "type": "cve"})

    for key in sorted(set(_TICKET_RE.findall(all_output)) - allowed_ticket_keys):
        fabricated.append({"identifier": key, "type": "ticket_key"})

    output_pr_nums = set(_PR_REF_RE.findall(all_output))
    for pr_num in sorted(output_pr_nums - allowed_pr_numbers):
        fabricated.append({"identifier": f"PR #{pr_num}", "type": "pr_number"})

    return fabricated


def _build_source_text(tickets: list, pull_requests: list, commits: list) -> str:
    """Flatten source artifact text for identifier extraction."""
    parts: list[str] = []
    for t in tickets:
        parts.append(t.get("key", ""))
        fields = t.get("fields", t)
        parts.append(str(fields.get("summary", "")))
        desc = fields.get("description", "")
        if isinstance(desc, str):
            parts.append(desc)
    for pr in pull_requests:
        parts.append(str(pr.get("number", pr.get("id", ""))))
        parts.append(pr.get("body", "") or "")
        parts.append(pr.get("title", "") or "")
    for c in commits:
        commit_obj = c.get("commit", {})
        parts.append(commit_obj.get("message", c.get("message", "")) or "")
        for f in c.get("files", []):
            parts.append(f.get("patch", "") or "")
    return " ".join(parts)


# ── Stage 2: LLM faithfulness judge ──────────────────────────────────────────

def _compute_faithfulness_rate(
    generated_docs: dict,
    source_artifacts: dict,
    client,
) -> tuple[float | None, list[dict]]:
    """LLM judge: identify unsupported claims in generated docs.

    Returns (rate, unsupported_claims) where rate = unsupported/total.
    Returns (None, []) on failure — caller falls back to reviewer proxy.
    """
    from agents.base import call_llm_with_retry, truncate_text

    tickets = source_artifacts.get("tickets", [])
    pull_requests = source_artifacts.get("pull_requests", [])
    commits = source_artifacts.get("commits", [])

    source_lines: list[str] = []
    for t in tickets:
        key = t.get("key", "")
        fields = t.get("fields", t)
        summary = fields.get("summary", "")
        source_lines.append(f"Ticket {key}: {summary}")
    for pr in pull_requests:
        source_lines.append(f"PR #{pr.get('number', '?')}: {pr.get('title', '')}")
    for c in commits[:10]:
        msg = (c.get("commit", {}) or {}).get("message", c.get("message", ""))
        first_line = (msg or "").split("\n")[0]
        if first_line:
            source_lines.append(f"Commit: {first_line}")
    source_summary = "\n".join(source_lines[:40])

    doc_sample = "\n".join([
        truncate_text(generated_docs.get("changelog", ""), 1500),
        truncate_text(generated_docs.get("internal_release_notes", ""), 1500),
        truncate_text(generated_docs.get("customer_release_notes", ""), 800),
    ]).strip()

    if not doc_sample:
        return 0.0, []

    prompt = (
        "You are a faithfulness judge for release documentation.\n\n"
        f"SOURCE ARTIFACTS (ground truth):\n{source_summary}\n\n"
        f"GENERATED DOCUMENTATION:\n{doc_sample}\n\n"
        "Task: Identify claims in the documentation NOT supported by the sources.\n"
        "A claim is any factual assertion: a feature exists, an endpoint name, a specific behavior.\n"
        "A claim IS supported if the source artifacts provide evidence for it, even indirectly.\n\n"
        "Count ALL specific factual claims in the generated docs (features, fixes, behaviors).\n"
        "List only the UNSUPPORTED ones.\n\n"
        'Return JSON: {"total_claims": <integer>, "unsupported_claims": '
        '[{"claim": "<short claim>", "reason": "<why not in sources>"}]}'
    )

    try:
        result = call_llm_with_retry(
            client=client,
            messages=[{"role": "user", "content": prompt}],
            agent_name="FaithfulnessJudge",
            temperature=0.0,
            max_retries=2,
        )
        total = max(1, int(result.get("total_claims", 1)))
        unsupported = result.get("unsupported_claims", [])
        if not isinstance(unsupported, list):
            unsupported = []
        return min(1.0, len(unsupported) / total), unsupported
    except Exception as e:
        logger.error(f"Faithfulness judge failed: {e}")
        return None, []


# ── Stage 3: Priority-weighted ticket coverage ────────────────────────────────

def _compute_weighted_ticket_coverage(
    generated_docs: dict,
    tickets: list[dict],
) -> tuple[float, dict]:
    """Priority-weighted ticket coverage using word-boundary matching.

    Coverage is checked only in changelog and internal_release_notes.
    Customer notes intentionally omit ticket keys — they are excluded from
    keyed scoring rather than counted as missing.

    Returns (weighted_score, per_ticket_details).
    """
    if not tickets:
        return 1.0, {}

    technical_text = (
        (generated_docs.get("changelog") or "") + " " +
        (generated_docs.get("internal_release_notes") or "")
    )

    total_weight = 0.0
    covered_weight = 0.0
    per_ticket: dict[str, dict] = {}

    for t in tickets:
        key = t.get("key", "")
        if not key:
            continue

        fields = t.get("fields", t)
        priority_name = ""
        p = fields.get("priority")
        if isinstance(p, dict):
            priority_name = p.get("name", "").lower()
        elif isinstance(p, str):
            priority_name = p.lower()

        weight = PRIORITY_WEIGHTS.get(priority_name, DEFAULT_PRIORITY_WEIGHT)
        total_weight += weight

        # Word-boundary match prevents PLAT-202 matching inside PLAT-2020
        pattern = re.compile(r'\b' + re.escape(key) + r'\b', re.IGNORECASE)
        covered = bool(pattern.search(technical_text))

        per_ticket[key] = {
            "covered": covered,
            "priority": priority_name or "unknown",
            "weight": weight,
        }
        if covered:
            covered_weight += weight

    score = covered_weight / total_weight if total_weight > 0 else 1.0
    return score, per_ticket


# ── Stage 4: Doc-update F1 vs gold set ───────────────────────────────────────

def _compute_doc_update_f1(
    generated_docs: dict,
    existing_docs: list[dict],
    release_name: str | None = None,
) -> tuple[float, dict]:
    """Precision/Recall/F1 of doc_path coverage vs gold file when available.

    Gold file: mock_data/gold/<release_name>.json
    Falls back to _compute_doc_accuracy (validity check) when no gold file.

    Returns (score, detail_dict).
    """
    doc_updates = generated_docs.get("documentation_updates", [])

    gold = None
    if release_name:
        gold_path = _GOLD_DIR / f"{release_name}.json"
        if gold_path.exists():
            try:
                gold = json.loads(gold_path.read_text())
            except Exception as e:
                logger.warning(f"Could not load gold file {gold_path}: {e}")

    if gold:
        gold_paths = {e["doc_path"] for e in gold.get("expected_doc_updates", [])}
        system_paths = {
            u["doc_path"]
            for u in doc_updates
            if isinstance(u, dict) and u.get("doc_path")
        }
        if not gold_paths and not system_paths:
            return 1.0, {"mode": "gold_f1", "precision": 1.0, "recall": 1.0, "f1": 1.0}
        tp = len(gold_paths & system_paths)
        precision = tp / len(system_paths) if system_paths else 0.0
        recall = tp / len(gold_paths) if gold_paths else 1.0
        f1 = (
            2 * precision * recall / (precision + recall)
            if (precision + recall) > 0
            else 0.0
        )
        return f1, {
            "mode": "gold_f1",
            "gold_paths": sorted(gold_paths),
            "system_paths": sorted(system_paths),
            "precision": round(precision, 3),
            "recall": round(recall, 3),
            "f1": round(f1, 3),
        }

    # Fallback: existing validity check
    score = _compute_doc_accuracy(generated_docs, existing_docs)
    return score, {"mode": "validity", "validity_score": round(score, 3)}


# ── Stage 5: Critical gates ───────────────────────────────────────────────────

def _check_critical_gates(
    fabricated: list[dict],
    generated_docs: dict,
    plan: dict | None,
) -> list[str]:
    """Return violation descriptions that force needs_revision regardless of score.

    Gate 1: Any fabricated identifier (CVE ID, ticket key, PR number).
    Gate 2: Any security-excluded identifying token in customer_release_notes.
    """
    violations: list[str] = []

    if fabricated:
        ids_str = ", ".join(f["identifier"] for f in fabricated[:5])
        extra = f" (+{len(fabricated) - 5} more)" if len(fabricated) > 5 else ""
        violations.append(f"Fabricated identifiers: {ids_str}{extra}")

    if plan:
        try:
            from agents.planner import extract_security_tokens
        except ImportError:
            extract_security_tokens = None  # type: ignore[assignment]

        if extract_security_tokens:
            customer_notes = generated_docs.get("customer_release_notes", "") or ""
            for entry in plan.get("exclusion_list", []):
                if "customer_release_notes" not in entry.get("exclude_from", []):
                    continue
                for token in extract_security_tokens(entry.get("item", "")):
                    if token in customer_notes:
                        violations.append(
                            f"Security exclusion leak: '{token}' in customer_release_notes"
                        )
                        break

    return violations


# ── Legacy functions (kept for backward compatibility) ────────────────────────

def _compute_hallucination_rate(review_result: dict) -> float:
    """Compute hallucination rate from reviewer findings (proxy — no LLM required).

    Each reported issue adds 10%, capped at 100%.
    Used as fallback when no client is provided to evaluate().
    """
    if not review_result:
        return 0.5  # Unknown quality — assume medium risk
    hallucination_issues = review_result.get("hallucination_issues", [])
    if not isinstance(hallucination_issues, list):
        return 0.0
    return min(1.0, len(hallucination_issues) * 0.1)


def _compute_ticket_coverage(generated_docs: dict, tickets: list[dict]) -> float:
    """Check if all ticket keys appear in the generated text.

    Uses word-boundary matching (upgraded from substring) so PLAT-202 does not
    false-match inside PLAT-2020. Searches all generated text including doc_updates.
    """
    if not tickets:
        return 1.0

    ticket_keys = {t.get("key", "") for t in tickets if t.get("key")}
    if not ticket_keys:
        return 1.0

    all_text = _flatten_text(generated_docs)
    mentioned_keys = set()
    for key in ticket_keys:
        pattern = re.compile(r'\b' + re.escape(key) + r'\b', re.IGNORECASE)
        if pattern.search(all_text):
            mentioned_keys.add(key)

    return len(mentioned_keys) / len(ticket_keys)


def _compute_doc_accuracy(generated_docs: dict, existing_docs: list[dict]) -> float:
    """Verify that doc update suggestions reference real documents."""
    doc_updates = generated_docs.get("documentation_updates", [])
    if not doc_updates:
        return 0.5  # No suggestions made — neutral (not penalized)

    existing_paths: set[str] = set()
    for d in existing_docs:
        path = d.get("path", "")
        if path:
            existing_paths.add(path)
            existing_paths.add(path.rsplit(".", 1)[0] if "." in path else path)

    valid_count = 0
    for update in doc_updates:
        if not isinstance(update, dict):
            continue
        doc_path = update.get("doc_path", "")
        action = update.get("action", "")
        if action == "add":
            valid_count += 1
        elif doc_path in existing_paths:
            valid_count += 1
        elif _fuzzy_path_match(doc_path, existing_paths):
            valid_count += 1

    return valid_count / len(doc_updates)


def _compute_content_quality(generated_docs: dict) -> float:
    """Structural quality checks on generated content."""
    scores: list[float] = []

    changelog = generated_docs.get("changelog", "")
    if changelog:
        has_headings = "#" in changelog
        has_bullets = "-" in changelog or "*" in changelog
        has_substance = len(changelog.split()) > 20
        scores.append((int(has_headings) + int(has_bullets) + int(has_substance)) / 3)
    else:
        scores.append(0.0)

    internal = generated_docs.get("internal_release_notes", "")
    if internal:
        has_substance = len(internal.split()) > 30
        has_structure = "\n" in internal
        scores.append((int(has_substance) + int(has_structure)) / 2)
    else:
        scores.append(0.0)

    customer = generated_docs.get("customer_release_notes", "")
    if customer:
        word_count = len(customer.split())
        appropriate_length = 20 <= word_count <= 500
        no_jargon = not any(
            term in customer.lower()
            for term in ["endpoint", "api call", "middleware", "stack trace", "deployment"]
        )
        scores.append((int(appropriate_length) + int(no_jargon)) / 2)
    else:
        scores.append(0.0)

    doc_updates = generated_docs.get("documentation_updates", [])
    if doc_updates:
        has_content = sum(
            1 for u in doc_updates
            if isinstance(u, dict) and len(u.get("suggested_content", "")) > 10
        )
        scores.append(has_content / len(doc_updates))
    else:
        scores.append(0.5)  # Neutral

    return sum(scores) / len(scores) if scores else 0.0


# ── Utilities ─────────────────────────────────────────────────────────────────

def _fuzzy_path_match(path: str, existing_paths: set[str]) -> bool:
    """Check if a path roughly matches any existing doc path."""
    if not path:
        return False
    path_lower = path.lower().replace("-", "").replace("_", "").replace(" ", "")
    for existing in existing_paths:
        existing_lower = existing.lower().replace("-", "").replace("_", "").replace(" ", "")
        if path_lower in existing_lower or existing_lower in path_lower:
            return True
    return False


def _flatten_text(docs: dict) -> str:
    """Flatten all generated documentation into a single string for analysis."""
    parts = [
        docs.get("changelog", "") or "",
        docs.get("internal_release_notes", "") or "",
        docs.get("customer_release_notes", "") or "",
    ]
    for update in docs.get("documentation_updates", []):
        if isinstance(update, dict):
            parts.append(update.get("suggested_content", "") or "")
            parts.append(update.get("doc_path", "") or "")
    return " ".join(p for p in parts if p)


def _build_details(
    result: EvaluationResult,
    generated_docs: dict,
    review_result: dict,
    tickets: list[dict],
    existing_docs: list[dict],
    fabricated: list[dict] | None = None,
    unsupported_claims: list[dict] | None = None,
    coverage_per_ticket: dict | None = None,
    doc_eval_details: dict | None = None,
    gate_violations: list[str] | None = None,
) -> dict:
    """Build detailed evaluation breakdown (backward-compat fields plus new ones)."""
    # Legacy fields preserved for existing consumers
    ticket_keys = {t.get("key", "") for t in tickets if t.get("key")}
    all_text = _flatten_text(generated_docs)
    mentioned = {
        k for k in ticket_keys
        if re.search(r'\b' + re.escape(k) + r'\b', all_text, re.IGNORECASE)
    }

    return {
        # ── Backward-compatible fields ──────────────────────────────────────
        "tickets_total": len(ticket_keys),
        "tickets_covered": len(mentioned),
        "tickets_missing": sorted(ticket_keys - mentioned),
        "hallucination_count": len(review_result.get("hallucination_issues", [])),
        "hallucination_details": review_result.get("hallucination_issues", []),
        "doc_updates_count": len(generated_docs.get("documentation_updates", [])),
        "reviewer_score": review_result.get("overall_score", 0),
        "reviewer_approved": review_result.get("approved", False),
        "content_lengths": {
            "changelog_words": len((generated_docs.get("changelog") or "").split()),
            "internal_notes_words": len((generated_docs.get("internal_release_notes") or "").split()),
            "customer_notes_words": len((generated_docs.get("customer_release_notes") or "").split()),
        },
        # ── New fields ──────────────────────────────────────────────────────
        "fabricated_identifiers": fabricated or [],
        "unsupported_claims": unsupported_claims or [],
        "coverage_per_ticket": coverage_per_ticket or {},
        "doc_eval": doc_eval_details or {},
        "critical_gates": gate_violations or [],
        "weights": {
            "hallucination": WEIGHT_HALLUCINATION,
            "ticket_coverage": WEIGHT_TICKET_COVERAGE,
            "doc_accuracy": WEIGHT_DOC_ACCURACY,
            "content_quality": WEIGHT_CONTENT_QUALITY,
            "needs_revision_threshold": NEEDS_REVISION_THRESHOLD,
        },
    }
