"""
Dhandho AI — ai_engine/agents/business_agent.py

Business Analyst Agent
----------------------
Uses the Groq API (Llama 3.3 70B) to extract a structured
`{"industry": "...", "pain_point": "..."}` object from the user's message.

The model is instructed to return STRICT JSON — no markdown fences,
no commentary — so we can safely call json.loads() on the raw response.
"""

import httpx
import json
import logging
import os
from typing import Any, Dict

from groq import Groq

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompt — enforces pure JSON output
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# System prompt — enforces pure JSON output with conversational guardrail
# ---------------------------------------------------------------------------
_SYSTEM_PROMPT = """You are an expert Business Analyst.

Your ONLY task is to analyse the user's message.
1. STRICT RULE: To set `is_business_problem` to true, the user MUST describe a SPECIFIC operational problem, bottleneck, or inefficiency (e.g., "wasting time on emails", "manual data entry", "missing calls").
2. If the user only gives a greeting ("hi"), a general statement ("I started a business"), or a vague request ("I need AI help") WITHOUT a specific problem, you MUST set `is_business_problem` to false.

OUTPUT FORMAT — STRICT JSON:
{
  "is_business_problem": <boolean>,
  "industry": "<concise industry label, or 'Unknown'>",
  "pain_point": "<one clear sentence describing the specific pain, or 'None'>"
}

RULES:
- Return ONLY the raw JSON object. No markdown, no code fences, no explanation.
- Keep `pain_point` under 20 words.
"""


# ---------------------------------------------------------------------------
# Public function
# ---------------------------------------------------------------------------
async def analyse_business_problem(user_message: str) -> Dict[str, Any]:
    """
    Calls the Groq API with Llama 3.3 70B to extract industry + pain_point
    from the user's natural language message.

    Args:
        user_message: The raw text the user typed into the chat widget.

    Returns:
        A dict with keys ``industry`` and ``pain_point``.

    Raises:
        RuntimeError: If the API call fails or the response is not valid JSON.
    """
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GROQ_API_KEY environment variable is not set. "
            "Add it to your .env file."
        )

    logger.info("BusinessAgent: creating Groq client")
    with httpx.Client() as http_client:
        client = Groq(api_key=api_key, http_client=http_client)

        logger.info("BusinessAgent: calling Groq API (llama-3.3-70b-versatile)")

        try:
            completion = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.1,          # Low temperature = deterministic JSON
                max_tokens=256,
                response_format={"type": "json_object"},   # Groq JSON mode
            )

            raw_response: str = completion.choices[0].message.content.strip()
            logger.debug("BusinessAgent raw response: %s", raw_response)

        except Exception as api_exc:
            logger.exception("BusinessAgent: Groq API call failed")
            raise RuntimeError(f"Groq API error: {api_exc}") from api_exc

    # ------------------------------------------------------------------
    # Parse & validate JSON
    # ------------------------------------------------------------------
    try:
        parsed: Dict[str, Any] = json.loads(raw_response)
    except json.JSONDecodeError as parse_exc:
        logger.error(
            "BusinessAgent: failed to parse JSON from Groq response: %s",
            raw_response,
        )
        raise RuntimeError(
            f"Business Agent returned non-JSON output: {parse_exc}"
        ) from parse_exc

    # Guarantee required keys are present
    if "industry" not in parsed or "pain_point" not in parsed:
        raise RuntimeError(
            f"Business Agent JSON missing required keys. Got: {list(parsed.keys())}"
        )

    logger.info(
        "BusinessAgent success — is_business_problem=%s  industry=%s  pain_point=%s",
        parsed.get("is_business_problem"),
        parsed["industry"],
        parsed["pain_point"],
    )
    return {
        "is_business_problem": parsed.get("is_business_problem", True),
        "industry": parsed["industry"],
        "pain_point": parsed["pain_point"],
    }
