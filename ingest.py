"""
ingest.py — Ingesta actividad de GitHub en Supermemory Local.

Arquitectura:
  Por cada repo propio (no fork, no perfil):
    1. Fetch commits del usuario + README
    2. Gemini sintetiza hasta 3 memorias de skills específicas
    3. Se guardan en Supermemory

Uso:
  python3 ingest.py
"""

import asyncio
import base64
import json
import os
import re
from datetime import datetime

import httpx
from dotenv import load_dotenv
from supermemory import Supermemory

load_dotenv(dotenv_path=".env.local")

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_USERNAME = os.getenv("GITHUB_USERNAME", "")
SUPERMEMORY_URL = os.getenv("SUPERMEMORY_BASE_URL", "http://localhost:6767")
SUPERMEMORY_API_KEY = os.getenv("SUPERMEMORY_API_KEY", "")
CONTAINER_TAG = os.getenv("SUPERMEMORY_CONTAINER", "hackathon_test_user")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

GITHUB_HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

memory_client = Supermemory(api_key=SUPERMEMORY_API_KEY, base_url=SUPERMEMORY_URL)

GENERIC_COMMITS = {
    "fix", "update", "wip", "init", "merge", "chore", "bump", "minor",
    "typo", "cleanup", "fix bug", "update readme", "initial commit",
    "first commit", "add files", "test", "temp", "todo", "refactor",
    "clean", "remove", "delete",
}


def sanitize_id(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-_:" else "-" for c in s)


def strip_markdown(text: str) -> str:
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    text = re.sub(r'#{1,6}\s*', '', text)
    text = re.sub(r'[-*_]{3,}', '', text)
    text = re.sub(r'`{1,3}[^`]*`{1,3}', '', text)
    text = re.sub(r'!\[[^\]]*\]\([^)]*\)', '', text)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def save_memory(content: str, custom_id: str) -> bool:
    try:
        memory_client.add(
            content=content,
            container_tag=CONTAINER_TAG,
            custom_id=sanitize_id(custom_id),
        )
        return True
    except Exception as e:
        print(f"  ✗ Error guardando {custom_id}: {e}")
        return False


async def fetch_repos(client: httpx.AsyncClient) -> list[dict]:
    resp = await client.get(
        "https://api.github.com/user/repos",
        params={"sort": "pushed", "per_page": 100, "affiliation": "owner"},
    )
    resp.raise_for_status()
    return resp.json()


async def fetch_commits(client: httpx.AsyncClient, repo_full_name: str) -> list[str]:
    try:
        resp = await client.get(
            f"https://api.github.com/repos/{repo_full_name}/commits",
            params={"per_page": 50, "author": GITHUB_USERNAME},
        )
        if resp.status_code == 409:
            return []
        resp.raise_for_status()
        msgs = []
        for c in resp.json():
            msg = c.get("commit", {}).get("message", "").split("\n")[0][:150]
            if msg and len(msg) >= 15 and msg.lower().strip() not in GENERIC_COMMITS:
                msgs.append(msg)
        return msgs
    except Exception:
        return []


async def fetch_readme(client: httpx.AsyncClient, repo_full_name: str) -> str:
    try:
        resp = await client.get(f"https://api.github.com/repos/{repo_full_name}/readme")
        if resp.status_code != 200:
            return ""
        data = resp.json()
        content = base64.b64decode(data.get("content", "")).decode("utf-8", errors="ignore")
        return strip_markdown(content)[:1200].strip()
    except Exception:
        return ""


def format_date(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%Y-%m-%d")
    except Exception:
        return iso[:10] if iso else "unknown"


async def gemini_synthesize(repo_name: str, lang: str, readme: str, commits: list[str]) -> list[str]:
    """
    Llama a Gemini para sintetizar hasta 3 memorias de skills desde README + commits.
    Retorna lista de strings (memorias limpias).
    """
    if not GEMINI_API_KEY:
        # Fallback sin LLM: 1 memoria básica
        parts = [f"{GITHUB_USERNAME} has experience building {repo_name}"]
        if lang and lang.lower() not in ("desconocido", "unknown"):
            parts.append(f" using {lang}")
        if readme:
            parts.append(f". {readme[:200]}")
        if commits:
            parts.append(f" Recent commits: {', '.join(commits[:3])}.")
        return ["".join(parts)]

    commits_text = "\n".join(f"- {c}" for c in commits[:15]) if commits else "No commits available"
    readme_text = readme[:800] if readme else "No README available"

    prompt = f"""You are extracting skill evidence from a developer's GitHub repository for semantic search.

Developer: {GITHUB_USERNAME}
Repository: {repo_name}
Primary language: {lang or "unknown"}

README:
{readme_text}

Commits by the developer:
{commits_text}

Write 1 to 3 short skill memories (plain sentences, no markdown, no bullets).
Each memory should focus on a DIFFERENT technical skill or aspect of this project.
Use third person starting with "{GITHUB_USERNAME}".
Be specific: name technologies, frameworks, patterns, problems solved.
Ignore non-technical content (achievements, awards, personal info).
If there is not enough technical content, write only 1 memory.

Return ONLY a JSON array of strings, no explanation. Example:
["memory 1", "memory 2", "memory 3"]"""

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}",
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"temperature": 0.2, "maxOutputTokens": 8192},
                },
            )
            data = resp.json()
            if "error" in data:
                print(f"  ⚠ Gemini API error para {repo_name}: {data['error'].get('message', data['error'])}")
            elif "candidates" not in data:
                print(f"  ⚠ Gemini respuesta inesperada para {repo_name}: {str(data)[:200]}")
            else:
                text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                # Strip markdown code fences if present
                text_clean = re.sub(r'```(?:json)?\s*', '', text).strip()
                match = re.search(r'\[.*\]', text_clean, re.DOTALL)
                if match:
                    try:
                        memories = json.loads(match.group())
                        result = [m.strip() for m in memories if isinstance(m, str) and len(m) > 20][:3]
                        if result:
                            return result
                    except json.JSONDecodeError:
                        pass
                print(f"  ⚠ Gemini no retornó JSON válido para {repo_name}: {text[:100]}")
    except Exception as e:
        print(f"  ⚠ Gemini exception para {repo_name}: {e}")

    # Fallback si Gemini falla
    fallback = f"{GITHUB_USERNAME} has experience building {repo_name}"
    if lang and lang.lower() not in ("desconocido", "unknown"):
        fallback += f" using {lang}"
    if commits:
        fallback += f". Recent work: {commits[0]}"
    return [fallback]


async def main():
    if not GITHUB_TOKEN:
        print("✗ Falta GITHUB_TOKEN en .env.local")
        return
    if not GITHUB_USERNAME:
        print("✗ Falta GITHUB_USERNAME en .env.local")
        return
    if not GEMINI_API_KEY:
        print("⚠ GEMINI_API_KEY no configurado — usando fallback sin LLM")

    print(f"Iniciando ingesta de GitHub para @{GITHUB_USERNAME}")
    print(f"Supermemory: {SUPERMEMORY_URL} | containerTag: {CONTAINER_TAG}\n")

    stats = {"repos": 0, "memories": 0, "skipped_forks": 0, "skipped_empty": 0}

    async with httpx.AsyncClient(headers=GITHUB_HEADERS, timeout=15.0) as client:
        print("📦 Fetching repos...")
        repos = await fetch_repos(client)
        print(f"   {len(repos)} repos encontrados\n")

        for repo in repos:
            name = repo["name"]
            full_name = repo["full_name"]
            safe_name = sanitize_id(full_name.replace("/", "-"))
            is_fork = repo.get("fork", False)
            lang = repo.get("language") or "desconocido"
            pushed = format_date(repo.get("pushed_at", ""))

            # Saltar forks y repo de perfil
            if is_fork or name.lower() == GITHUB_USERNAME.lower():
                stats["skipped_forks"] += 1
                print(f"  ⏭ skip: {full_name}")
                continue

            # Fetch commits + README en paralelo
            commits, readme = await asyncio.gather(
                fetch_commits(client, full_name),
                fetch_readme(client, full_name),
            )

            # Saltar repos sin ningún contexto útil
            if not commits and not readme:
                stats["skipped_empty"] += 1
                print(f"  ✗ skip: {full_name} (sin commits ni README)")
                continue

            print(f"  🤖 Procesando: {full_name} ({lang}, {len(commits)} commits, README: {'sí' if readme else 'no'})")

            # Gemini sintetiza hasta 3 memorias
            memories = await gemini_synthesize(name, lang, readme, commits)
            # gemini_synthesize retorna lista vacía solo si usó fallback
            source = "Gemini ✨" if len(memories) > 1 or (memories and "Recent work" not in memories[0]) else "fallback"
            print(f"    → {len(memories)} memorias via {source}")

            for i, mem in enumerate(memories):
                custom_id = f"mem_{safe_name}_{i}"
                if save_memory(mem, custom_id):
                    stats["memories"] += 1
                    print(f"    ✓ [{i+1}] {mem[:100]}")

            stats["repos"] += 1

    print("\n" + "=" * 50)
    print("✅ Ingesta completa:")
    print(f"   📦 {stats['repos']} repos procesados")
    print(f"   🧠 {stats['memories']} memorias generadas por Gemini")
    print(f"   ⏭ {stats['skipped_forks']} forks/perfil saltados")
    print(f"   ✗  {stats['skipped_empty']} repos sin contexto saltados")
    print(f"\n   containerTag: {CONTAINER_TAG}")
    print("=" * 50)

    return stats


if __name__ == "__main__":
    asyncio.run(main())
