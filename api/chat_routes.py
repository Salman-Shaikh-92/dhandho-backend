"""
Dhandho AI — api/chat_routes.py
Simplified routes according to the requested 3 exact endpoints.
"""

import uuid
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
import google.generativeai as genai
import os
import groq
import httpx

import firebase_db
from api.auth import UserClaims, get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["Chat"])

# Initialize Gemini
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------
class Message(BaseModel):
    role: str
    text: str

from fastapi.responses import StreamingResponse
import json
import asyncio

class ChatRequest(BaseModel):
    session_id: Optional[str] = None
    message: str
    conversation_history: Optional[List[Message]] = []
    persona: Optional[str] = "Default Consultant"

# ---------------------------------------------------------------------------
# 1. GET /api/conversations
# ---------------------------------------------------------------------------
@router.get("/conversations")
async def api_get_conversations(user: UserClaims = Depends(get_current_user)):
    """Fetch all conversation sessions for the authenticated user."""
    try:
        convs = await firebase_db.get_user_conversations(user_id=user.uid)
        
        # Format explicitly to match the required spec
        formatted_convs = []
        for c in convs:
            formatted_convs.append({
                "id": c.get("id"),
                "title": c.get("title", "New Conversation"),
                "updated_at": c.get("updated_at")
            })
            
        return {"conversations": formatted_convs}
    except Exception as e:
        logger.error(f"Error fetching conversations: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch conversations")

# ---------------------------------------------------------------------------
# 2. GET /api/conversations/{session_id}/history
# ---------------------------------------------------------------------------
@router.get("/conversations/{session_id}/history")
async def api_get_history(session_id: str, user: UserClaims = Depends(get_current_user)):
    """Fetch all past messages for this specific session."""
    try:
        history = await firebase_db.get_conversation_history_formatted(session_id, user.uid)
        return {"history": history}
    except PermissionError:
        raise HTTPException(status_code=403, detail="Access denied")
    except Exception as e:
        logger.error(f"Error fetching history: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch history")

# ---------------------------------------------------------------------------
# 3. POST /api/chat (SSE Streaming)
# ---------------------------------------------------------------------------
@router.post("/chat")
async def api_chat(request: ChatRequest, user: UserClaims = Depends(get_current_user)):
    """Handle chat messages, pass to LLM, stream via SSE, and save exchange."""
    session_id = request.session_id or str(uuid.uuid4())
    history_in = request.conversation_history or []
    
    # Map 'user' / 'ai' to Gemini's 'user' / 'model' roles
    formatted_history = []
    for msg in history_in:
        gemini_role = "user" if msg.role == "user" else "model"
        formatted_history.append({"role": gemini_role, "parts": [msg.text]})

    # Persona Selection
    persona_map = {
        "Default Consultant": "You are Dhandho AI, an expert business automation and AI implementation consultant.",
        "Strict Business Analyst": "You are a no-nonsense, highly analytical business consultant who focuses purely on numbers, ROI, and harsh truths.",
        "Creative Marketer": "You are an energetic, creative marketing automation expert who focuses on brand growth, viral campaigns, and creative AI use-cases."
    }
    persona_text = persona_map.get(request.persona, persona_map["Default Consultant"])

    system_prompt = (
        f"{persona_text}\n\n"
        "STRICT CONVERSATION FLOW:\n"
        "PHASE 1: GATHER INFORMATION. When a user first asks a question, DO NOT immediately give solutions. "
        "Crucially, DO NOT ask multiple questions at once. Ask exactly ONE single short question at a time. "
        "Wait for the user's answer, then ask the next single question if more info is needed. Keep responses extremely short (1-2 sentences).\n"
        "PHASE 2: RECOMMENDATIONS ONLY. Once you have gathered all necessary information iteratively, analyze it and provide a concise bulleted list of "
        "specific automations. Format as: `- **Name:** Description`. Do not provide step-by-step technical tutorials.\n\n"
        "GUARDRAILS: Refuse any questions unrelated to business, AI, automation, or software."
    )

    model = genai.GenerativeModel(
        'gemini-3.5-flash',
        system_instruction=system_prompt
    )
    chat = model.start_chat(history=formatted_history)

    async def generate():
        full_reply = []
        try:
            # 1. Try Gemini First
            response = await chat.send_message_async(request.message, stream=True)
            async for chunk in response:
                text = chunk.text
                if text:
                    full_reply.append(text)
                    yield f"data: {json.dumps({'chunk': text})}\n\n"
                    
        except Exception as e_gemini:
            logger.warning(f"Gemini Error, falling back to Groq: {e_gemini}")
            try:
                # 2. Fallback to Groq (using raw httpx to avoid SDK version conflicts)
                groq_api_key = os.getenv("GROQ_API_KEY")
                groq_history = [{"role": "system", "content": system_prompt}]
                for msg in history_in:
                    api_role = "assistant" if msg.role == "ai" else "user"
                    groq_history.append({"role": api_role, "content": msg.text})
                groq_history.append({"role": "user", "content": request.message})

                async with httpx.AsyncClient() as groq_client:
                    async with groq_client.stream(
                        "POST",
                        "https://api.groq.com/openai/v1/chat/completions",
                        headers={"Authorization": f"Bearer {groq_api_key}", "Content-Type": "application/json"},
                        json={"model": "llama-3.1-8b-instant", "messages": groq_history, "stream": True}
                    ) as groq_response:
                        if groq_response.status_code != 200:
                            raise Exception(f"Groq API Error {groq_response.status_code}")
                        async for line in groq_response.aiter_lines():
                            if line.startswith("data: "):
                                data_str = line[6:]
                                if data_str == "[DONE]": break
                                try:
                                    data = json.loads(data_str)
                                    text = data["choices"][0]["delta"].get("content", "")
                                    if text:
                                        full_reply.append(text)
                                        yield f"data: {json.dumps({'chunk': text})}\n\n"
                                except Exception as e:
                                    logger.error(f"Groq JSON decoding error: {e}")
                                    
            except Exception as e_groq:
                logger.warning(f"Groq Error, falling back to DeepSeek: {e_groq}")
                try:
                    # 3. Fallback to DeepSeek
                    ds_api_key = os.getenv("DEEPSEEK_API_KEY")
                    ds_history = [{"role": "system", "content": system_prompt}]
                    for msg in history_in:
                        api_role = "assistant" if msg.role == "ai" else "user"
                        ds_history.append({"role": api_role, "content": msg.text})
                    ds_history.append({"role": "user", "content": request.message})

                    async with httpx.AsyncClient() as ds_client:
                        async with ds_client.stream(
                            "POST", 
                            "https://api.deepseek.com/chat/completions",
                            headers={"Authorization": f"Bearer {ds_api_key}", "Content-Type": "application/json"},
                            json={"model": "deepseek-chat", "messages": ds_history, "stream": True}
                        ) as ds_response:
                            if ds_response.status_code == 402:
                                raise Exception("DeepSeek API Token has ZERO Balance (402 Payment Required).")
                            elif ds_response.status_code != 200:
                                raise Exception(f"DeepSeek API Error {ds_response.status_code}")
                                
                            async for line in ds_response.aiter_lines():
                                if line.startswith("data: "):
                                    data_str = line[6:]
                                    if data_str == "[DONE]": break
                                    try:
                                        data = json.loads(data_str)
                                        text = data["choices"][0]["delta"].get("content", "")
                                        if text:
                                            full_reply.append(text)
                                            yield f"data: {json.dumps({'chunk': text})}\n\n"
                                    except Exception as e:
                                        logger.error(f"DeepSeek JSON decoding error: {e}")
                except Exception as e_ds:
                    logger.error(f"All LLMs Failed. DeepSeek Error: {e_ds}")
                    error_msg = f"AI overloaded. DeepSeek Error: {e_ds}"
                    yield f"data: {json.dumps({'error': error_msg})}\n\n"
                    return
            
        ai_reply = "".join(full_reply)
        
        # Save to database AFTER the stream completes
        try:
            await firebase_db.save_exchange(
                user_id=user.uid,
                session_id=session_id,
                user_text=request.message,
                ai_text=ai_reply
            )
        except Exception as e:
            logger.error(f"DB Save Error: {e}")

        # Send a final event to let the client know the stream is complete
        yield f"data: {json.dumps({'done': True, 'session_id': session_id})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")