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
    history: Optional[List[Message]] = []
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
    history_in = request.history or request.conversation_history or []
    
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
        'gemini-1.5-flash',
        system_instruction=system_prompt
    )
    chat = model.start_chat(history=formatted_history)

    async def generate():
        full_reply = []
        try:
            # 1. Try Groq First
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
            logger.warning(f"Groq Error, falling back to Gemini: {e_groq}")
            try:
                # 2. Try Gemini
                response = await chat.send_message_async(request.message, stream=True)
                async for chunk in response:
                    text = chunk.text
                    if text:
                        full_reply.append(text)
                        yield f"data: {json.dumps({'chunk': text})}\n\n"
            except Exception as e_gemini:
                logger.error(f"All LLMs Failed. Gemini Error: {e_gemini}")
                error_msg = f"AI overloaded. Groq and Gemini failed."
                yield f"data: {json.dumps({'error': error_msg})}\n\n"
                return
            
            # --- DEEPSEEK CODE COMMENTED OUT ---
            # except Exception as e_groq:
            #     logger.warning(f"Groq Error, falling back to DeepSeek: {e_groq}")
            #     try:
            #         # 3. Fallback to DeepSeek
            #         ...
            #     except Exception as e_ds:
            #         ...
            # -----------------------------------
            
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

        # Detect recommendation format and trigger the frontend button
        if "- **" in ai_reply or "recommendation" in ai_reply.lower():
            yield f"data: {json.dumps({'chunk': ' ', 'recommendations': True})}\n\n"

        # Send a final event to let the client know the stream is complete
        yield f"data: {json.dumps({'done': True, 'session_id': session_id})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")

# ---------------------------------------------------------------------------
# 4. PUT /api/conversations/{session_id}
# ---------------------------------------------------------------------------
class RenameRequest(BaseModel):
    title: str

@router.put("/conversations/{session_id}")
async def api_rename_conversation(session_id: str, request: RenameRequest, user: UserClaims = Depends(get_current_user)):
    """Rename a conversation."""
    success = await firebase_db.rename_conversation(session_id, user.uid, request.title)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to rename conversation")
    return {"status": "success"}

# ---------------------------------------------------------------------------
# 5. DELETE /api/conversations/{session_id}
# ---------------------------------------------------------------------------
@router.delete("/conversations/{session_id}")
async def api_delete_conversation(session_id: str, user: UserClaims = Depends(get_current_user)):
    """Delete a conversation."""
    success = await firebase_db.delete_conversation(session_id, user.uid)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to delete conversation")
    return {"status": "success"}

# ---------------------------------------------------------------------------
# 6. POST /api/users/sync
# ---------------------------------------------------------------------------
@router.post("/users/sync")
async def api_sync_user(user: UserClaims = Depends(get_current_user)):
    """
    Syncs the authenticated user's profile with Firestore.
    Called by the Next.js frontend upon successful login.
    """
    try:
        result = await firebase_db.sync_user_profile(
            uid=user.uid,
            email=user.email,
            display_name=user.name
        )
        return result
    except Exception as e:
        logger.error(f"Error syncing user profile: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to sync user profile in Firestore."
        )