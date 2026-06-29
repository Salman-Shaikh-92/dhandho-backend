"""
Dhandho AI — ai_engine/orchestrator.py

Central Pipeline Orchestrator
------------------------------
Flow:
  User Message + Full Conversation History
      │
      ▼
  [CLASSIFIER]  — Groq JSON mode, fast & strict
      │  → {needs_pipeline: true/false}
      │
      ├── needs_pipeline = false ──► [CHAT AGENT] — normal Groq chat completion
      │                              Real dynamic response using full history
      │                              Returns {status: "conversational", reply: "..."}
      │
      └── needs_pipeline = true  ──► [1] Business Analyst Agent
                                     [2] Solution Agent
                                     [3] ROI Agent
                                     Returns {status: "success", ...full report...}
"""

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

import httpx
from groq import Groq

from ai_engine.agents.business_agent import analyse_business_problem
from ai_engine.agents.roi_agent import calculate_roi
from ai_engine.agents.solution_agent import map_solution

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# CLASSIFIER system prompt — ONLY returns {needs_pipeline: bool}
# Fast, cheap, reliable. Does NOT generate the reply itself.
# ---------------------------------------------------------------------------
_CLASSIFIER_PROMPT = """You are a routing classifier for an AI business automation consultant.

Your ONLY job: decide if the user's message needs the full business analysis pipeline.

Set needs_pipeline = true ONLY if the user clearly describes:
- A specific operational problem or bottleneck (e.g., "spending 3 hours on invoices")
- A specific workflow they want automated
- A specific pain point with measurable impact

Set needs_pipeline = false for:
- Greetings (hi, hello, hey, good morning, etc.)
- Follow-up questions about a previous answer
- Asking for clarification or more info about a recommendation
- General questions about automation, AI, or Dhandho
- Small talk or casual conversation
- Vague statements without a clear problem ("I run a business", "I need help")
- Asking what the AI can do

Return ONLY this JSON, nothing else:
{"needs_pipeline": <true or false>}"""


# ---------------------------------------------------------------------------
# CHAT AGENT system prompt — generates the actual dynamic reply
# Used when needs_pipeline = false. Full human-like conversation.
# ---------------------------------------------------------------------------
_CHAT_AGENT_PROMPT = """You are Dhandho AI — a smart, warm, and expert AI business automation consultant.

You have a deep understanding of business operations, automation tools, and ROI.
You help entrepreneurs save time and money through AI and automation.

Your personality:
- Conversational, warm, and encouraging — like a trusted advisor
- You remember everything said earlier in the conversation
- You give varied, contextual answers — NEVER repeat the same response
- You ask insightful follow-up questions to understand the business better
- You use the conversation history to personalize each reply

Guidelines:
- For greetings: respond warmly, introduce yourself briefly, and ask ONE engaging question
- For follow-ups on recommendations: expand on the details intelligently using history
- For questions about capabilities: explain what you can do with enthusiasm
- For vague inputs: ask a specific, smart follow-up question (not generic)
- NEVER give the same reply twice in a conversation
- NEVER use the exact same phrasing as a previous response
- Keep replies concise (2-4 sentences max) unless the user asks for detail
- Do NOT start every message with "Hello!" — vary your openings

You have access to the full conversation history. Use it."""


def _get_groq_client(api_key: str) -> Groq:
    """Create and return a Groq client."""
    return Groq(api_key=api_key, http_client=httpx.Client())


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
async def process_chat_message(
    user_message: str,
    conversation_history: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """
    Main entry point. Routes message to either:
    - Dynamic conversational reply (with full history context)
    - Full business analysis pipeline (Business → Solution → ROI)

    Args:
        user_message: The latest message from the user.
        conversation_history: Prior messages as:
            [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]
            In chronological order (oldest first).
    """
    logger.info("Orchestrator: received message (len=%d)", len(user_message))

    history = conversation_history or []
    api_key = os.getenv("GROQ_API_KEY")

    # ======================================================================
    # STEP 1 — CLASSIFY: Does this need the pipeline?
    # Fast JSON-mode call, no reply generation here
    # ======================================================================
    needs_pipeline = await _classify_message(user_message, history, api_key)
    logger.info("Orchestrator: classifier → needs_pipeline=%s", needs_pipeline)

    # ======================================================================
    # STEP 2A — CONVERSATIONAL: Generate dynamic reply using full history
    # ======================================================================
    if not needs_pipeline:
        reply = await _generate_chat_reply(user_message, history, api_key)
        return {
            "status": "conversational",
            "reply": reply,
        }

    # ======================================================================
    # STEP 2B — PIPELINE: Full business analysis
    # ======================================================================

    # Stage 1 — Business Analyst Agent
    logger.info("Orchestrator: Stage 1 — Business Analysis")
    try:
        business_analysis: Dict[str, Any] = await analyse_business_problem(user_message)
    except Exception as exc:
        logger.exception("Orchestrator: Stage 1 failed")
        # Don't crash — fall back to conversational
        return {
            "status": "conversational",
            "reply": await _generate_chat_reply(user_message, history, api_key),
        }

    # If Stage 1 says it's NOT a business problem despite classifier saying yes,
    # generate a contextual conversational reply asking for more info
    if not business_analysis.get("is_business_problem", True):
        logger.info("Orchestrator: Stage 1 overrides classifier — not a business problem")
        return {
            "status": "conversational",
            "reply": await _generate_chat_reply(user_message, history, api_key),
        }

    industry: str = business_analysis.get("industry", "Unknown")
    pain_point: str = business_analysis.get("pain_point", "Unknown")
    logger.info("Orchestrator: Stage 1 done — industry=%s pain_point=%s", industry, pain_point)

    # Stage 2 — Solution Mapping Agent
    logger.info("Orchestrator: Stage 2 — Solution Mapping")
    try:
        solution_result: Dict[str, Any] = await map_solution(
            pain_point=pain_point,
            industry=industry,
        )
    except Exception as exc:
        logger.exception("Orchestrator: Stage 2 failed")
        return {
            "status": "error",
            "error": f"Solution Mapping Agent failed: {exc}",
            "stage": "solution_mapping",
        }

    recommended_tool: str = solution_result["recommended_tool"]
    recommended_tools: list = solution_result.get("recommended_tools", [recommended_tool])
    tool_recommendations: list = solution_result.get("tool_recommendations", [])
    solution_summary: str = solution_result["solution_summary"]
    tool_details: Dict[str, Any] = solution_result["tool_details"]
    logger.info("Orchestrator: Stage 2 done — tools=%s", recommended_tools)

    # Stage 3 — ROI Calculation
    logger.info("Orchestrator: Stage 3 — ROI Calculation")
    try:
        if tool_recommendations:
            monthly_cost = sum(float(item.get("cost", 0)) for item in tool_recommendations)
            monthly_savings = sum(float(item.get("monthly_savings", 0)) for item in tool_recommendations)
        else:
            monthly_cost = float(tool_details.get("estimated_monthly_cost", 0))
            monthly_savings = float(tool_details.get("estimated_monthly_savings", 0))

        roi_metrics: Dict[str, Any] = calculate_roi(
            monthly_cost=monthly_cost,
            monthly_savings=monthly_savings,
        )
    except (ValueError, TypeError) as exc:
        logger.exception("Orchestrator: Stage 3 failed")
        return {
            "status": "error",
            "error": f"ROI Calculation Agent failed: {exc}",
            "stage": "roi_calculation",
        }

    logger.info(
        "Orchestrator: Pipeline complete — ROI=%.1f%% net=$%.0f/mo",
        roi_metrics.get("roi_percentage") or 0,
        roi_metrics.get("monthly_net_profit", 0),
    )

    return {
        "status": "success",
        "business_analysis": {"industry": industry, "pain_point": pain_point},
        "recommended_tool": recommended_tool,
        "recommended_tools": recommended_tools,
        "solution_summary": solution_summary,
        "tool_recommendations": tool_recommendations,
        "roi_metrics": roi_metrics,
    }


# ---------------------------------------------------------------------------
# CLASSIFIER — Step 1 (strict JSON, fast)
# ---------------------------------------------------------------------------
async def _classify_message(
    user_message: str,
    history: List[Dict[str, str]],
    api_key: Optional[str],
) -> bool:
    """
    Returns True if the message needs the full business pipeline.
    Returns False if it should be handled conversationally.
    """
    if not api_key:
        return _heuristic_classify(user_message)

    # Build context: include last 6 messages so classifier understands follow-ups
    messages = [{"role": "system", "content": _CLASSIFIER_PROMPT}]
    for h in history[-6:]:
        role = h.get("role", "user")
        content = h.get("content", "")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content[:500]})  # truncate for speed
    messages.append({"role": "user", "content": user_message})

    try:
        with httpx.Client() as http_client:
            client = Groq(api_key=api_key, http_client=http_client)
            completion = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=messages,
                temperature=0.0,   # Deterministic classification
                max_tokens=20,     # Only need {"needs_pipeline": true/false}
                response_format={"type": "json_object"},
            )
        raw = completion.choices[0].message.content.strip()
        parsed = json.loads(raw)
        return bool(parsed.get("needs_pipeline", False))
    except Exception as exc:
        logger.warning("Classifier LLM call failed (%s), using heuristic fallback", exc)
        return _heuristic_classify(user_message)


# ---------------------------------------------------------------------------
# CHAT AGENT — Step 2A (free-form text, dynamic reply)
# ---------------------------------------------------------------------------
async def _generate_chat_reply(
    user_message: str,
    history: List[Dict[str, str]],
    api_key: Optional[str],
) -> str:
    """
    Generates a dynamic, context-aware conversational reply.
    Uses full conversation history so replies are NEVER repetitive or static.
    """
    if not api_key:
        return _heuristic_reply(user_message, history)

    # Build full conversation context
    messages = [{"role": "system", "content": _CHAT_AGENT_PROMPT}]
    for h in history[-20:]:  # Last 10 exchanges (20 messages)
        role = h.get("role", "user")
        content = h.get("content", "")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": user_message})

    try:
        with httpx.Client() as http_client:
            client = Groq(api_key=api_key, http_client=http_client)
            completion = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=messages,
                temperature=0.75,   # Higher temp = more varied, natural responses
                max_tokens=400,
                # NO response_format here — free text, not JSON!
            )
        reply = completion.choices[0].message.content.strip()
        logger.debug("ChatAgent reply: %s", reply[:120])
        return reply
    except Exception as exc:
        logger.warning("ChatAgent LLM call failed (%s), using heuristic fallback", exc)
        return _heuristic_reply(user_message, history)


# ---------------------------------------------------------------------------
# Heuristic fallbacks (when Groq API is unavailable)
# ---------------------------------------------------------------------------
def _heuristic_classify(message: str) -> bool:
    """Returns True if message looks like a business problem description."""
    if not isinstance(message, str) or len(message.strip()) < 30:
        return False

    normalized = message.strip().lower()

    # Clear greeting patterns → not a pipeline
    if re.fullmatch(
        r"(?:hi|hey|hello|hii|hiya|yo|hola|howdy|greetings|good\s+\w+.*|"
        r"how are you.*|what can you do.*|who are you.*|what is dhandho.*)",
        normalized
    ):
        return False

    # Business problem keywords → pipeline
    business_keywords = [
        "manual", "wasting time", "bottleneck", "inefficient", "lose",
        "follow-up", "invoice", "data entry", "spreadsheet", "missed",
        "automate", "hours", "employees", "customer", "sales", "leads",
        "appointment", "booking", "inventory", "payroll", "report",
    ]
    return any(kw in normalized for kw in business_keywords)


def _heuristic_reply(message: str, history: List[Dict[str, str]]) -> str:
    """Varied fallback replies when LLM is unavailable."""
    normalized = message.strip().lower()
    history_count = len(history)

    if re.fullmatch(r"(?:hi+|hey+|hello+|hiya|yo)", normalized):
        if history_count == 0:
            return (
                "Hey there! I'm Dhandho AI — your personal business automation consultant. "
                "What kind of business are you running, and what's been taking up the most of your time lately?"
            )
        else:
            return "Hey again! What's on your mind? Any update on the challenges we were discussing?"

    if "how are you" in normalized:
        return "Doing great, thanks for asking! More importantly — how's your business going? Any operational headaches I can help you solve?"

    if "what can you do" in normalized or "how does this work" in normalized:
        return (
            "I analyze your business operations and recommend the best automation tools with ROI projections. "
            "Just tell me what's slowing you down — manual tasks, missed follow-ups, data entry — and I'll show you how to fix it."
        )

    if history_count > 0:
        return "Got it! Can you share more details? The more specific you are about the problem, the better I can tailor my recommendations."

    return (
        "I'm here to help you automate and scale your business. "
        "Tell me about a specific challenge you're facing — like manual data entry, missed leads, or time-consuming follow-ups — "
        "and I'll recommend the right automation solution with an ROI breakdown."
    )