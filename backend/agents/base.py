"""Base utilities shared across all agents: retry logic, error handling, validation."""
import json
import time
import logging
from typing import Any

from openai import OpenAI, APIError, APITimeoutError, RateLimitError

logger = logging.getLogger("release_agent")


class AgentError(Exception):
    """Raised when an agent fails after retries."""
    def __init__(self, agent_name: str, message: str, attempts: int = 0):
        self.agent_name = agent_name
        self.attempts = attempts
        super().__init__(f"[{agent_name}] {message} (after {attempts} attempts)")


class AgentTimeoutError(AgentError):
    """Raised when an agent times out."""
    pass


def call_llm_with_retry(
    client: OpenAI,
    messages: list[dict[str, str]],
    agent_name: str,
    temperature: float = 0.1,
    max_retries: int = 3,
    timeout: int = 60,
    model: str = "gpt-4o-mini",
) -> dict[str, Any]:
    """Call OpenAI with retry logic, exponential backoff, and structured JSON parsing.
    
    Handles:
    - Rate limiting (429) with exponential backoff
    - Timeout errors with retry
    - API errors with retry
    - Malformed JSON responses with retry
    - Empty responses
    """
    last_error = None

    for attempt in range(1, max_retries + 1):
        try:
            logger.info(
                f"Calling LLM attempt {attempt}/{max_retries}",
                extra={"agent": agent_name},
            )
            start_time = time.time()

            response = client.chat.completions.create(
                model=model,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=temperature,
                timeout=timeout,
            )

            duration_ms = int((time.time() - start_time) * 1000)
            logger.info(
                f"LLM responded in {duration_ms}ms",
                extra={"agent": agent_name, "duration_ms": duration_ms},
            )

            # Validate response
            content = response.choices[0].message.content
            if not content or not content.strip():
                raise AgentError(agent_name, "Empty response from LLM", attempt)

            # Parse JSON
            try:
                result = json.loads(content)
            except json.JSONDecodeError as e:
                logger.warning(
                    f"Invalid JSON from LLM: {e}. Content: {content[:200]}",
                    extra={"agent": agent_name},
                )
                if attempt < max_retries:
                    time.sleep(1)
                    continue
                raise AgentError(agent_name, f"Invalid JSON response: {e}", attempt)

            return result

        except RateLimitError as e:
            last_error = e
            wait_time = min(2 ** attempt, 30)  # Exponential backoff, max 30s
            logger.warning(
                f"Rate limited, waiting {wait_time}s",
                extra={"agent": agent_name},
            )
            time.sleep(wait_time)

        except APITimeoutError as e:
            last_error = e
            logger.warning(
                f"Timeout on attempt {attempt}",
                extra={"agent": agent_name},
            )
            if attempt < max_retries:
                time.sleep(2)

        except APIError as e:
            last_error = e
            logger.error(
                f"API error: {e.status_code} {e.message}",
                extra={"agent": agent_name},
            )
            # Don't retry on 4xx client errors (except 429 handled above)
            if e.status_code and 400 <= e.status_code < 500:
                raise AgentError(agent_name, f"Client error: {e.message}", attempt)
            if attempt < max_retries:
                time.sleep(2)

    raise AgentError(
        agent_name,
        f"Failed after {max_retries} attempts. Last error: {last_error}",
        max_retries,
    )


def truncate_text(text: str, max_chars: int = 2000) -> str:
    """Safely truncate text to fit within context limits."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"... [truncated, {len(text) - max_chars} chars omitted]"


def validate_digest_output(result: dict) -> dict:
    """Ensure digest has all required fields with proper types."""
    defaults = {
        "features": [],
        "bug_fixes": [],
        "breaking_changes": [],
        "affected_systems": [],
        "risk_level": "unknown",
        "summary": "No summary generated.",
    }
    for key, default in defaults.items():
        if key not in result:
            result[key] = default
        elif isinstance(default, list) and not isinstance(result[key], list):
            # Handle case where LLM returns string instead of list
            result[key] = [result[key]] if result[key] else []
    
    # Normalize risk_level
    valid_risks = {"low", "medium", "high"}
    if result["risk_level"] not in valid_risks:
        result["risk_level"] = "medium"
    
    return result


def validate_writer_output(result: dict) -> dict:
    """Ensure writer output has all required fields."""
    defaults = {
        "changelog": "",
        "internal_release_notes": "",
        "customer_release_notes": "",
        "documentation_updates": [],
    }
    for key, default in defaults.items():
        if key not in result:
            result[key] = default

    # Validate documentation_updates structure
    valid_updates = []
    for update in result.get("documentation_updates", []):
        if isinstance(update, dict) and "doc_path" in update:
            valid_updates.append({
                "doc_path": str(update.get("doc_path", "")),
                "section": str(update.get("section", "")),
                "suggested_content": str(update.get("suggested_content", "")),
                "action": str(update.get("action", "review")),
            })
    result["documentation_updates"] = valid_updates
    return result


def validate_review_output(result: dict) -> dict:
    """Ensure reviewer output has all required fields."""
    defaults = {
        "overall_score": 5,
        "hallucination_issues": [],
        "missing_coverage": [],
        "tone_issues": [],
        "suggestions": [],
        "approved": False,
    }
    for key, default in defaults.items():
        if key not in result:
            result[key] = default

    # Ensure score is numeric and bounded
    try:
        result["overall_score"] = max(1, min(10, int(result["overall_score"])))
    except (ValueError, TypeError):
        result["overall_score"] = 5

    # Ensure approved is boolean
    result["approved"] = bool(result.get("approved", False))
    return result
