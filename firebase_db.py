"""
Dhandho AI — firebase_db.py
Simplified Firebase Firestore logic for the 3 exact endpoints.
"""

import os
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone

import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore
from google.api_core.exceptions import PermissionDenied, GoogleAPIError

logger = logging.getLogger(__name__)

_firestore_ready: bool = False
_app: Optional[firebase_admin.App] = None
db: Optional[Any] = None

conversations_collection = None


async def connect_to_firebase() -> None:
    global _app, db, conversations_collection, _firestore_ready
    service_account_path = os.getenv("FIREBASE_SERVICE_ACCOUNT_PATH", "dhandho-ai-firebase-adminsdk-fbsvc-2e1af9a2b2.json")

    if not os.path.exists(service_account_path):
        logger.critical(f"Firebase service account key not found at: {service_account_path}")
        return

    try:
        cred = credentials.Certificate(service_account_path)
        if not firebase_admin._apps:
            _app = firebase_admin.initialize_app(cred)
        else:
            _app = firebase_admin.get_app()
    except Exception as exc:
        logger.critical(f"Firebase initialisation failed: {exc}")
        raise

    try:
        db = firestore.client()
        conversations_collection = db.collection("conversations")
        _firestore_ready = True
        logger.info("Firebase Firestore ready")
    except Exception as exc:
        logger.warning(f"Firestore connection failed: {exc}")
        _firestore_ready = False


async def close_firebase_connection() -> None:
    global _app
    if _app is not None:
        firebase_admin.delete_app(_app)
        _app = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_ready() -> bool:
    return _firestore_ready and db is not None and conversations_collection is not None


# ---------------------------------------------------------------------------
# 1. Get user conversations
# ---------------------------------------------------------------------------
async def get_user_conversations(user_id: str) -> List[Dict[str, Any]]:
    if not _is_ready():
        return []

    try:
        query = conversations_collection.where("user_id", "==", user_id)
        # Using stream without ordering if index is missing, or with ordering if index exists.
        # We'll fetch all and sort in memory to avoid missing index errors for simple use cases.
        docs = query.stream()
        
        results = []
        for doc in docs:
            data = doc.to_dict()
            data["id"] = doc.id
            results.append(data)
            
        # Sort in memory by updated_at descending
        results.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
        return results
    except Exception as e:
        logger.error(f"Error fetching conversations: {e}")
        return []


# ---------------------------------------------------------------------------
# 2. Get formatted conversation history
# ---------------------------------------------------------------------------
async def get_conversation_history_formatted(session_id: str, user_id: str) -> List[Dict[str, str]]:
    if not _is_ready():
        return []

    try:
        conv_ref = conversations_collection.document(session_id)
        conv_doc = conv_ref.get()
        
        if not conv_doc.exists:
            return []
            
        if conv_doc.to_dict().get("user_id") != user_id:
            raise PermissionError("Access denied")

        msgs_query = conv_ref.collection("messages").order_by("timestamp").stream()
        
        history = []
        for doc in msgs_query:
            msg = doc.to_dict()
            # Convert to required format {"role": "user"|"ai", "text": "..."}
            if msg.get("user_message"):
                history.append({"role": "user", "text": msg["user_message"]})
            if msg.get("ai_response"):
                history.append({"role": "ai", "text": msg["ai_response"]})
                
        return history
    except PermissionError:
        raise
    except Exception as e:
        logger.error(f"Error fetching history: {e}")
        return []


# ---------------------------------------------------------------------------
# 3. Save exchange and auto-title
# ---------------------------------------------------------------------------
async def save_exchange(user_id: str, session_id: str, user_text: str, ai_text: str) -> None:
    if not _is_ready():
        return

    try:
        conv_ref = conversations_collection.document(session_id)
        conv_doc = conv_ref.get()
        now = _now()
        
        if not conv_doc.exists:
            # Create new session with auto-generated title (first 5 words)
            title = " ".join(user_text.split()[:5])
            if len(user_text.split()) > 5:
                title += "..."
                
            conv_ref.set({
                "user_id": user_id,
                "title": title,
                "created_at": now,
                "updated_at": now
            })
        else:
            # Update existing session timestamp
            conv_ref.update({"updated_at": now})

        # Save the exchange
        conv_ref.collection("messages").add({
            "timestamp": now,
            "user_message": user_text,
            "ai_response": ai_text
        })
    except Exception as e:
        logger.error(f"Error saving exchange: {e}")
        raise

# ---------------------------------------------------------------------------
# 4. Sync user profile on login
# ---------------------------------------------------------------------------
async def sync_user_profile(uid: str, email: Optional[str], display_name: Optional[str]) -> Dict[str, Any]:
    if not _is_ready():
        logger.error("Firestore not ready for user sync")
        return {"status": "error", "detail": "Firestore not initialized"}
        
    try:
        users_collection = db.collection("users")
        user_ref = users_collection.document(uid)
        user_doc = user_ref.get()
        now = _now()
        
        if not user_doc.exists:
            # Initialize fresh business consultant profile
            profile_data = {
                "uid": uid,
                "email": email,
                "displayName": display_name,
                "initialized_at": now,
                "last_login": now,
                "automation_level": "Starter",
                "workflow_tokens_remaining": 100,
                "metrics_profile": "Surati Lala Mart"
            }
            user_ref.set(profile_data)
            return {"status": "created", "profile": profile_data}
        else:
            # Seamlessly update last_login without overwriting
            user_ref.update({"last_login": now})
            # Return updated profile
            updated_data = user_doc.to_dict()
            updated_data["last_login"] = now
            return {"status": "updated", "profile": updated_data}
            
    except Exception as e:
        logger.error(f"Error provisioning user {uid}: {e}")
        raise
