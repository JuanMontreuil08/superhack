from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import asyncio
import httpx
import os
from dotenv import load_dotenv

load_dotenv(dotenv_path=".env.local")

SUPERMEMORY_URL = os.getenv("SUPERMEMORY_BASE_URL", "http://localhost:6767")
SUPERMEMORY_API_KEY = os.getenv("SUPERMEMORY_API_KEY", "")
SUPERMEMORY_CONTAINER = os.getenv("SUPERMEMORY_CONTAINER", "hackathon_test_user")
THRESHOLD = 0.65  # similaridad mínima para resaltar

app = FastAPI()

# Permite que la Chrome extension llame al backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class EvaluateRequest(BaseModel):
    chunks: list[str]


async def evaluate_chunk(client: httpx.AsyncClient, chunk: str) -> dict | None:
    """Evalúa un chunk de texto contra el contexto del usuario en Supermemory."""
    try:
        resp = await client.post(
            f"{SUPERMEMORY_URL}/v4/search",
            json={
                "q": chunk,
                "limit": 1,
                "rerank": True,
                "searchMode": "hybrid",
                "containerTag": SUPERMEMORY_CONTAINER,
            },
            timeout=5.0,
        )
        results = resp.json().get("results", [])
        if results and results[0].get("similarity", 0) >= THRESHOLD:
            top = results[0]
            return {
                "text": chunk,
                "score": round(top["similarity"], 2),
                "memory": top.get("memory") or top.get("chunk", ""),
            }
    except Exception:
        pass
    return None


@app.post("/evaluate-page")
async def evaluate_page(request: EvaluateRequest):
    """
    Recibe hasta 50 chunks de texto de la página.
    Devuelve los que son relevantes para el contexto del usuario.
    """
    chunks = request.chunks[:50]  # cap para no sobrecargar
    async with httpx.AsyncClient(headers={"Authorization": f"Bearer {SUPERMEMORY_API_KEY}"}) as client:
        results = await asyncio.gather(
            *[evaluate_chunk(client, chunk) for chunk in chunks]
        )

    highlights = [r for r in results if r is not None]
    highlights.sort(key=lambda x: x["score"], reverse=True)
    return {"highlights": highlights}


@app.get("/health")
async def health():
    return {"status": "ok"}
