"""
Dhandho AI — main.py
FastAPI application entry point.
"""

import logging
import os
import asyncio
import httpx
from contextlib import asynccontextmanager

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

from api.chat_routes import router as chat_router
from firebase_db import close_firebase_connection, connect_to_firebase
from database import connect_to_db, close_db_connection

# ---------------------------------------------------------------------------
# Background Task
# ---------------------------------------------------------------------------
async def ping_health():
    """Ping the health endpoint every 10 minutes (600 seconds) to keep the API awake."""
    while True:
        try:
            await asyncio.sleep(600)
            async with httpx.AsyncClient() as client:
                port = os.getenv("PORT", 8000)
                url = f"http://localhost:{port}/health"
                response = await client.get(url)
                logging.debug(f"Health ping status: {response.status_code}")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logging.error(f"Error pinging health endpoint: {e}")

# ---------------------------------------------------------------------------
# Lifespan — replaces deprecated startup / shutdown event handlers
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize Firebase Firestore and MongoDB on startup, close connections on shutdown."""
    await connect_to_firebase()
    # await connect_to_db()
    
    ping_task = asyncio.create_task(ping_health())
    
    yield
    
    ping_task.cancel()
    # await close_db_connection()
    await close_firebase_connection()


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------
def create_app() -> FastAPI:
    app = FastAPI(
        title="Dhandho AI API",
        description=(
            "AI-powered automation consulting backend powered by Firebase Firestore. "
            "Routes user messages through a multi-agent pipeline "
            "(Business Analyst → Solution → ROI) and stores results in Firestore. "
            "Supports Firebase Auth for secure per-user conversation history, "
            "profile management, and full conversation CRUD (like GPT/Claude/Gemini)."
        ),
        version="2.0.0",
        lifespan=lifespan,
    )

    # -----------------------------------------------------------------------
    # CORS — allow the Next.js dev server and any configured production origin
    # -----------------------------------------------------------------------
    allowed_origins = [
        "http://localhost:3000",    # Next.js default dev server
        "http://127.0.0.1:3000",
        "http://localhost:5173",    # Vite dev server
        "http://127.0.0.1:5173",
    ]

    # Optionally extend with production frontend URLs from env
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000").rstrip("/")
    if frontend_url:
        for url in frontend_url.split(","):
            url = url.strip()
            if url:
                allowed_origins.append(url)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,    # Required for Authorization header / cookies
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["*"],
    )

    # -----------------------------------------------------------------------
    # Routers
    # -----------------------------------------------------------------------
    app.include_router(chat_router)

    # -----------------------------------------------------------------------
    # Health-check (useful for Docker / load-balancer probes)
    # -----------------------------------------------------------------------
    @app.get("/health", tags=["Health"])
    async def health_check():
        return {
            "status": "ok",
            "service": "Dhandho AI API",
            "version": "2.0.0",
            "features": [
                "firebase_auth",
                "conversation_management",
                "multi_turn_context",
                "user_profiles",
                "roi_reports",
            ],
        }

    return app


app = create_app()

# ---------------------------------------------------------------------------
# Dev runner — `python main.py`
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8000)),
        reload=os.getenv("APP_ENV", "development") == "development",
    )
