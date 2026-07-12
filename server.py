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
THRESHOLD = 0.65  # similaridad mínima para resaltar
_SEM = asyncio.Semaphore(5)  # máx 5 requests simultáneos a Supermemory

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


class PDFRequest(BaseModel):
    url: str


class ChatRequest(BaseModel):
    question: str
    page_context: str = ""  # título + extracto de la página actual


async def evaluate_chunk(client: httpx.AsyncClient, chunk: str) -> dict | None:
    """Evalúa un chunk de texto contra el contexto del usuario en Supermemory."""
    async with _SEM:
        try:
            resp = await client.post(
                f"{SUPERMEMORY_URL}/v4/search",
                json={
                    "q": chunk,
                    "limit": 1,
                    "rerank": True,
                    "rewriteQuery": False,
                    "searchMode": "hybrid",
                    "containerTag": SUPERMEMORY_CONTAINER,
                },
                timeout=10.0,
            )
            results = resp.json().get("results", [])
            if not results:
                return None
            top = results[0]
            score = top.get("similarity", 0)
            print(f"  score={score:.3f} | chunk={chunk[:60]!r}")
            if score < THRESHOLD:
                return None
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
                "score": round(score, 2),
                "memory": memory_text,
            }
        except Exception as e:
            print(f"  ERROR: {type(e).__name__}: {e!r}")
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
            "repos": stats.get("repos", 0),
            "memories": stats.get("memories", 0),
            "skipped_forks": stats.get("skipped_forks", 0),
            "skipped_empty": stats.get("skipped_empty", 0),
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


@app.post("/chat")
async def chat(request: ChatRequest):
    """
    Recibe una pregunta del usuario + contexto de la página actual.
    Busca memorias relevantes en Supermemory y las usa como contexto
    para que Gemini responda de forma personalizada.
    """
    # 1. Buscar memorias relevantes para la pregunta
    async with httpx.AsyncClient(
        headers={"Authorization": f"Bearer {SUPERMEMORY_API_KEY}"}
    ) as client:
        resp = await client.post(
            f"{SUPERMEMORY_URL}/v4/search",
            json={
                "q": request.question,
                "limit": 6,
                "rerank": True,
                "searchMode": "memories",
                "containerTag": SUPERMEMORY_CONTAINER,
            },
            timeout=10.0,
        )
        results = resp.json().get("results", [])

    memories = [r.get("memory") or r.get("chunk", "") for r in results if r.get("memory") or r.get("chunk")]
    memories = [m for m in memories if len(m) > 20]

    if not memories:
        return {"answer": "No encontré memorias relevantes en tu background para esta pregunta. Intenta hacer Sync GitHub Activity primero.", "memories_used": []}

    memories_text = "\n".join(f"- {m}" for m in memories)

    # 2. Llamar a Gemini con las memorias como contexto
    page_section = f"\nPágina actual:\n{request.page_context[:600]}\n" if request.page_context else ""

    prompt = f"""Eres un asistente personal. Tu única fuente de información sobre el developer son las memorias que se te dan a continuación. NO uses conocimiento propio ni de entrenamiento.

Memorias del developer (extraídas de su GitHub):
{memories_text}
{page_section}
Pregunta: {request.question}

REGLAS ESTRICTAS:
- Responde SOLO con lo que dicen las memorias anteriores.
- Si las memorias no contienen información relevante para la pregunta, responde exactamente: "No tengo memorias tuyas sobre ese tema. Intenta hacer Sync GitHub Activity para actualizar tu contexto."
- No uses conocimiento general tuyo. No inventes ni supongas.
- Cita las memorias concretas que usas ("según tus memorias, en el proyecto X...").
- Responde en el mismo idioma de la pregunta."""

    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={os.getenv('GEMINI_API_KEY', '')}",
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.3, "maxOutputTokens": 512},
            },
        )
        data = resp.json()

    if "error" in data:
        return {"answer": f"Error Gemini: {data['error'].get('message', 'desconocido')}", "memories_used": memories}

    answer = data["candidates"][0]["content"]["parts"][0]["text"].strip()
    return {"answer": answer, "memories_used": memories}


@app.post("/analyze-pdf")
async def analyze_pdf(request: PDFRequest):
    """
    Recibe la URL de un PDF, extrae el texto página a página,
    evalúa cada párrafo contra el contexto del usuario y devuelve
    los fragmentos más relevantes con número de página.
    """
    import io
    from pypdf import PdfReader

    async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as fetch_client:
        resp = await fetch_client.get(
            request.url,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        pdf_bytes = resp.content

    reader = PdfReader(io.BytesIO(pdf_bytes))
    all_chunks = []
    for page_num, page in enumerate(reader.pages, 1):
        text = page.extract_text() or ""
        # pypdf no conserva dobles saltos → agrupar líneas en ventanas de ~300 chars
        lines = [l.strip() for l in text.split("\n") if len(l.strip()) > 20]
        buf = ""
        for line in lines:
            buf += " " + line
            if len(buf) >= 300:
                all_chunks.append({"text": buf.strip(), "page": page_num})
                buf = ""
        if len(buf) >= 80:
            all_chunks.append({"text": buf.strip(), "page": page_num})

    chunks_to_eval = all_chunks[:150]  # PDFs suelen tener 50-200 chunks
    print(f"  PDF: {len(reader.pages)} páginas, {len(all_chunks)} párrafos → evaluando {len(chunks_to_eval)}")

    async with httpx.AsyncClient(headers={"Authorization": f"Bearer {SUPERMEMORY_API_KEY}"}) as client:
        results = await asyncio.gather(
            *[evaluate_chunk(client, c["text"]) for c in chunks_to_eval]
        )

    highlights = []
    for i, r in enumerate(results):
        if r is not None:
            r["page"] = chunks_to_eval[i]["page"]
            highlights.append(r)

    highlights.sort(key=lambda x: x["score"], reverse=True)
    return {"highlights": highlights[:10]}  # top 10 resultados


@app.get("/health")
async def health():
    return {"status": "ok"}
