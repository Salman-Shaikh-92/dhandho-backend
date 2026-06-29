"""
Dhandho AI — ai_engine/agents/solution_agent.py

Solution Mapping Agent
----------------------
Reads the local automation_library.json, then uses Groq API (Llama 3.3 70B)
to intelligently match the user's pain point to the best-fit tool and
generate a natural-language recommendation paragraph.
"""

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict

import httpx
from groq import Groq

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_LIBRARY_PATH = Path(__file__).parent.parent / "data" / "automation_library.json"


# ---------------------------------------------------------------------------
# Helper — load the automation library
# ---------------------------------------------------------------------------
def _load_automation_library() -> Dict[str, Any]:
    """
    Reads and returns the parsed automation_library.json.

    Raises:
        FileNotFoundError: If the JSON file is missing.
        json.JSONDecodeError: If the file contains invalid JSON.
    """
    if not _LIBRARY_PATH.exists():
        raise FileNotFoundError(
            f"automation_library.json not found at {_LIBRARY_PATH}"
        )
    with _LIBRARY_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------
_SYSTEM_PROMPT = """You are a Senior Automation Consultant at Dhandho AI.

You will be given:
1. A business pain point.
2. A JSON catalogue of automation tools.

Your task:
- Identify ALL relevant tools from the catalogue that solve the pain points.
- CRITICAL INSTRUCTION: If the user describes MULTIPLE different problems (e.g., cold email AND appointment booking), you MUST recommend at least one specific tool for EACH problem (e.g., include both Instantly.ai AND GoHighLevel in your list).
- Return ONLY strict JSON with these keys:
  {
    "recommended_tools": ["Tool Name 1", "Tool Name 2"],
    "solution_summary": "Explain how these tools work together to solve the specific problems."
  }
- Use exact tool names from the catalogue. Do not include pricing.
- If multiple tools are relevant, recommend no more than 2 tools.
- Do NOT list the entire catalogue or echo all available tool names.
- Do NOT include headers, markdown, or any extra keys.
"""


# ---------------------------------------------------------------------------
# Public function
# ---------------------------------------------------------------------------
async def map_solution(
    pain_point: str,
    industry: str,
) -> Dict[str, Any]:
    """
    Uses Groq (Llama 3) to select the best automation tool for the
    given pain point and generate a recommendation summary.

    Args:
        pain_point: Short description of the business problem (from Business Agent).
        industry:   The industry label (from Business Agent).

    Returns:
        A dict with keys:
          - ``recommended_tool``  (str)  — tool_name from the library
          - ``solution_summary``  (str)  — generated recommendation paragraph
          - ``tool_details``      (dict) — raw tool object from the library
    """
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GROQ_API_KEY environment variable is not set. "
            "Add it to your .env file."
        )

    # ------------------------------------------------------------------
    # Load tool catalogue
    # ------------------------------------------------------------------
    try:
        library = _load_automation_library()
    except (FileNotFoundError, json.JSONDecodeError) as lib_exc:
        raise RuntimeError(f"Failed to load automation library: {lib_exc}") from lib_exc

    tools = library.get("automation_tools", [])
    if not tools:
        raise RuntimeError("automation_library.json contains no tools.")

    # ------------------------------------------------------------------
    # Build the user prompt
    # ------------------------------------------------------------------
    user_prompt = (
        f"BUSINESS CONTEXT\n"
        f"Industry:   {industry}\n"
        f"Pain Point: {pain_point}\n\n"
        f"AVAILABLE TOOLS (JSON catalogue):\n"
        f"{json.dumps(tools, indent=2)}\n\n"
        f"Please provide a strict JSON response with keys `recommended_tools` and "
        f"`solution_summary`. The `solution_summary` should explain what each "
        f"recommended tool does and how it saves time and money."
        f" Use exact tool names from the catalogue in `recommended_tools`."
    )

    # ------------------------------------------------------------------
    # Call Groq API (Swapped from Gemini)
    # ------------------------------------------------------------------
    logger.info("SolutionAgent: calling Groq API (llama-3.3-70b-versatile)")

    with httpx.Client() as http_client:
        client = Groq(api_key=api_key, http_client=http_client)

        try:
            completion = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,          
                max_tokens=512,
                response_format={"type": "json_object"}, 
            )

            recommendation_text: str = completion.choices[0].message.content.strip()
            logger.debug("SolutionAgent raw response: %s", recommendation_text)

        except Exception as api_exc:
            logger.exception("SolutionAgent: Groq API call failed")
            raise RuntimeError(f"Groq API error: {api_exc}") from api_exc

    # ------------------------------------------------------------------
    # Parse model output, clean code fences, and extract JSON if present.
    # ------------------------------------------------------------------
    parsed_json = _extract_json_response(recommendation_text)
    response_summary = recommendation_text
    if parsed_json:
        response_summary = parsed_json.get("solution_summary", response_summary)

    cleaned_text = _strip_code_fences(response_summary)
    if isinstance(cleaned_text, str):
        response_summary = cleaned_text.strip()

    matched_tools = []
    if parsed_json:
        names = parsed_json.get("recommended_tools")
        if isinstance(names, list):
            matched_tools = _match_tools_from_names(names, tools)

    if not matched_tools:
        matched_tools = _match_tools_from_response(recommendation_text, tools)

    if len(matched_tools) > max(2, len(tools) // 2):
        logger.warning(
            "SolutionAgent: matched too many tools from Groq response (%d); using heuristic fallback.",
            len(matched_tools),
        )
        matched_tools = []

    if not matched_tools:
        fallback_tool = _heuristic_fallback(pain_point, tools)
        matched_tools = [fallback_tool]
        logger.warning(
            "SolutionAgent: could not detect specific tool match; fell back to heuristic match → %s",
            fallback_tool["tool_name"],
        )

    categories = []
    seen_categories = set()
    for tool in matched_tools:
        category = tool.get("automation_category") or tool["tool_name"]
        if category not in seen_categories:
            categories.append(category)
            seen_categories.add(category)

    if not categories:
        categories = [matched_tools[0].get("automation_category") or matched_tools[0]["tool_name"]]

    recommended_tool_category = categories[0]
    tool_recommendations = _build_tool_recommendations(matched_tools)
    response_summary = _build_category_summary(categories, pain_point, industry)

    logger.info(
        "SolutionAgent success — recommended_categories=%s",
        categories,
    )

    return {
        "recommended_tool": recommended_tool_category,
        "recommended_tools": categories,
        "solution_summary": response_summary,
        "tool_details": matched_tools[0],
        "tool_recommendations": tool_recommendations,
    }


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------
def _match_tools_from_response(
    text: str,
    tools: list,
) -> list[Dict[str, Any]]:
    """Extracts one or more matching tools from the model output."""
    if not text:
        return []

    parsed_json = _extract_json_response(text)
    if parsed_json:
        names = parsed_json.get("recommended_tools")
        if isinstance(names, list):
            return _match_tools_from_names(names, tools)

    return _match_tools_from_text_list(text, tools)


def _build_tool_recommendations(
    tools: list[Dict[str, Any]],
) -> list[Dict[str, Any]]:
    """Builds a structured recommendation list with cost and time-saving details."""
    recommendations: list[Dict[str, Any]] = []
    for tool in tools:
        recommendations.append(
            {
                "tool_name": tool["tool_name"],
                "automation_category": tool.get("automation_category"),
                "cost": float(tool.get("estimated_monthly_cost", 0)),
                "monthly_savings": float(tool.get("estimated_monthly_savings", 0)),
                "description": tool.get("description", ""),
                "time_saving": (
                    "Automates manual follow-up and lead nurturing so staff can focus on closing deals."
                ),
            }
        )
    return recommendations


def _build_category_summary(
    categories: list[str],
    pain_point: str,
    industry: str,
) -> str:
    if not categories:
        return (
            f"For a {industry} business facing '{pain_point}', focus on automation to reduce manual work, "
            "improve accuracy, and scale operations."
        )

    if len(categories) == 1:
        return (
            f"For a {industry} business facing '{pain_point}', the recommended automation category is {categories[0]}. "
            "This automation focus helps reduce manual work, improve operational reliability, and save time and cost."
        )

    return (
        f"For a {industry} business facing '{pain_point}', the recommended automation categories are "
        f"{', '.join(categories)}. These areas work together to reduce manual effort and improve overall efficiency."
    )


def _match_tools_from_json_response(
    text: str,
    tools: list,
) -> list[Dict[str, Any]]:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return []

    if not isinstance(parsed, dict):
        return []

    names = parsed.get("recommended_tools")
    if not isinstance(names, list):
        return []

    return _match_tools_from_names(names, tools)


def _match_tools_from_names(
    names: list,
    tools: list,
) -> list[Dict[str, Any]]:
    normalized_names = [str(name).strip().lower() for name in names if isinstance(name, str)]
    matched_tools = []
    seen = set()

    for name in normalized_names:
        for tool in tools:
            if tool["tool_name"].lower() == name:
                if tool["tool_name"] not in seen:
                    matched_tools.append(tool)
                    seen.add(tool["tool_name"])
                break
            for alias in tool.get("aliases", []):
                if alias.lower() == name:
                    if tool["tool_name"] not in seen:
                        matched_tools.append(tool)
                        seen.add(tool["tool_name"])
                    break

    return matched_tools


def _match_tools_from_text_list(
    text: str,
    tools: list,
) -> list[Dict[str, Any]]:
    text_lower = _strip_code_fences(text).lower()
    matched_tools = []
    seen = set()

    for tool in tools:
        for name in [tool["tool_name"]] + tool.get("aliases", []):
            if name.lower() in text_lower and tool["tool_name"] not in seen:
                matched_tools.append(tool)
                seen.add(tool["tool_name"])
                break

    return matched_tools


def _heuristic_fallback(
    pain_point: str,
    tools: list,
) -> Dict[str, Any]:
    """Fallback to the best matching tool using keyword matching in the pain point."""
    if not isinstance(pain_point, str) or not pain_point.strip():
        return tools[0]

    pain_lower = pain_point.lower()
    best_match = None
    best_score = 0

    for tool in tools:
        score = 0
        for keyword in tool.get("solves_problem", []):
            if keyword.lower() in pain_lower:
                score += 2
        for keyword in tool.get("best_for_industries", []):
            if keyword.lower() in pain_lower:
                score += 1

        if score > best_score:
            best_score = score
            best_match = tool

    return best_match or tools[0]


def _extract_json_response(text: str) -> Dict[str, Any]:
    text = _strip_code_fences(text).strip()
    if not text:
        return {}

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    # Try to extract a JSON object from anywhere in the model output.
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        fragment = text[start:end + 1]
        try:
            parsed = json.loads(fragment)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

    return {}


def _build_tool_summary(
    tool: Dict[str, Any],
    pain_point: str,
    industry: str,
) -> str:
    return (
        f"For a business in {industry} facing '{pain_point}', the best automation "
        f"fit is {tool['tool_name']}. {tool.get('description', '').strip()} "
        f"This tool can help automate the core problem and save time and money."
    )


def _strip_code_fences(text: str) -> str:
    """Remove markdown code fences and return plain text."""
    if not isinstance(text, str):
        return ""

    # Remove optional leading language specifier and any surrounding fences.
    text = re.sub(r"^\s*```(?:json|yaml|js|python|typescript)?\s*\n", "", text, flags=re.IGNORECASE | re.MULTILINE)
    text = re.sub(r"```", "", text)
    text = re.sub(r"^\s*(?:json|yaml|js|python|typescript)\s*\n", "", text, flags=re.IGNORECASE)
    text = re.sub(r"http://googleusercontent.com/immersive_entry_chip/0", "", text)
    return text.strip()