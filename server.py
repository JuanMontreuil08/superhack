from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import asyncio
import httpx
import os
import sys
from dotenv import load_dotenv

load_dotenv(dotenv_path=".env.local")

SUPERMEMORY_URL = os.getenv("SUPERMEMORY_BASE_URL", "http://localhost:6767")
SUPERMEMORY_API_KEY = os.getenv("SUPERMEMORY_API_KEY", "")
SUPERMEMORY_CONTAINER = os.getenv("SUPERMEMORY_CONTAINER", "hackathon_test_user")
THRESHOLD = 0.82  # similaridad mínima para resaltar

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
            memory_text = top.get("memory") or top.get("chunk", "")
            # Filtra memorias genéricas que generan falsos positivos
            if len(memory_text) < 30:
                return None
            generic_patterns = [
                "user's name is",
                "The user has",
                "has public GitHub",
                "is a member of the GitHub organization",
                "belongs to the organization",
                "The user belongs",
                "user is located",
                "user works at",
                "The user's bio",
            ]
            if any(p in memory_text for p in generic_patterns):
                return None
            return {
                "text": chunk,
                "score": round(top["similarity"], 2),
                "memory": memory_text,
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


@app.post("/ingest-github")
async def ingest_github():
    """
    Corre la ingesta de GitHub → Supermemory en background.
    Devuelve las stats al terminar.
    """
    try:
        # Importa ingest.py como módulo y corre main()
        sys.path.insert(0, os.path.dirname(__file__))
        import ingest
        import importlib
        importlib.reload(ingest)  # por si el módulo ya estaba cargado

        # Corre la ingesta y captura stats
        stats = await ingest.main()

        return {
            "ok": True,
            "repos": stats.get("repos", 0) + stats.get("readmes", 0),
            "commits": stats.get("commits", 0),
            "readmes": stats.get("readmes", 0),
            "issues": stats.get("issues", 0),
            "prs": stats.get("prs", 0),
            "starred": stats.get("starred", 0),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/queue-status")
async def queue_status():
    """Retorna cuántos documentos están aún en cola de procesamiento para el container."""
    try:
        async with httpx.AsyncClient(
            headers={"Authorization": f"Bearer {SUPERMEMORY_API_KEY}"}
        ) as client:
            resp = await client.get(
                f"{SUPERMEMORY_URL}/v3/documents/processing",
                timeout=5.0,
            )
            docs = resp.json().get("documents", [])
            # Filtra solo los del container actual
            pending = [
                d for d in docs
                if SUPERMEMORY_CONTAINER in d.get("containerTags", [])
            ]
            queued = sum(1 for d in pending if d.get("status") == "queued")
            processing = sum(1 for d in pending if d.get("status") == "processing")
            return {"queued": queued, "processing": processing, "total_pending": len(pending)}
    except Exception as e:
        return {"queued": 0, "processing": 0, "total_pending": 0, "error": str(e)}


@app.get("/health")
async def health():
    return {"status": "ok"}
