"""
ingest.py — Ingesta actividad de GitHub en Supermemory Local.

Qué guarda:
  - Repos: nombre, descripción, lenguaje, topics, estrellas, última actividad
  - Commits: últimos 20 por repo (mensaje + fecha)
  - Issues: últimas 30 abiertas del usuario
  - PRs: últimas 20 del usuario
  - READMEs: primeros 500 chars por repo

Uso:
  python3 ingest.py
"""

import asyncio
import base64
import os
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

GITHUB_HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

memory_client = Supermemory(api_key=SUPERMEMORY_API_KEY, base_url=SUPERMEMORY_URL)


def sanitize_id(s: str) -> str:
    """Reemplaza caracteres inválidos en custom_id con guiones."""
    return "".join(c if c.isalnum() or c in "-_:" else "-" for c in s)


def save_memory(content: str, custom_id: str) -> bool:
    """Guarda un texto en Supermemory. Retorna True si fue exitoso."""
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



async def fetch_starred(client: httpx.AsyncClient) -> list[dict]:
    try:
        resp = await client.get(
            f"https://api.github.com/users/{GITHUB_USERNAME}/starred",
            params={"per_page": 100},
        )
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return []


async def fetch_repos(client: httpx.AsyncClient) -> list[dict]:
    resp = await client.get(
        "https://api.github.com/user/repos",
        params={"sort": "pushed", "per_page": 100, "affiliation": "owner"},
    )
    resp.raise_for_status()
    return resp.json()


async def fetch_commits(client: httpx.AsyncClient, repo_full_name: str) -> list[dict]:
    try:
        resp = await client.get(
            f"https://api.github.com/repos/{repo_full_name}/commits",
            params={"per_page": 100, "author": GITHUB_USERNAME},
        )
        if resp.status_code == 409:  # empty repo
            return []
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return []


async def fetch_readme(client: httpx.AsyncClient, repo_full_name: str) -> str:
    try:
        resp = await client.get(
            f"https://api.github.com/repos/{repo_full_name}/readme"
        )
        if resp.status_code != 200:
            return ""
        data = resp.json()
        content = base64.b64decode(data.get("content", "")).decode("utf-8", errors="ignore")
        return content[:500].strip()
    except Exception:
        return ""


async def fetch_issues(client: httpx.AsyncClient) -> list[dict]:
    try:
        resp = await client.get(
            "https://api.github.com/issues",
            params={"state": "open", "per_page": 30, "filter": "created"},
        )
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return []


async def fetch_prs(client: httpx.AsyncClient) -> list[dict]:
    try:
        resp = await client.get(
            "https://api.github.com/search/issues",
            params={
                "q": f"author:{GITHUB_USERNAME} type:pr",
                "sort": "updated",
                "per_page": 20,
            },
        )
        resp.raise_for_status()
        return resp.json().get("items", [])
    except Exception:
        return []


def format_date(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%Y-%m-%d")
    except Exception:
        return iso[:10] if iso else "unknown"


async def main():
    if not GITHUB_TOKEN:
        print("✗ Falta GITHUB_TOKEN en .env.local")
        return
    if not GITHUB_USERNAME:
        print("✗ Falta GITHUB_USERNAME en .env.local")
        return

    print(f"Iniciando ingesta de GitHub para @{GITHUB_USERNAME}")
    print(f"Supermemory: {SUPERMEMORY_URL} | containerTag: {CONTAINER_TAG}\n")

    stats = {"repos": 0, "commits": 0, "issues": 0, "prs": 0, "readmes": 0}

    async with httpx.AsyncClient(headers=GITHUB_HEADERS, timeout=15.0) as client:
        # ── Repos ──────────────────────────────────────────────────────────
        print("\n📦 Fetching repos...")
        repos = await fetch_repos(client)
        print(f"   {len(repos)} repos encontrados\n")

        # Solo filtra si el mensaje COMPLETO es una de estas palabras (no si empieza con ellas)
        GENERIC_COMMITS = {"fix", "update", "wip", "init", "merge", "chore", "bump", "minor", "typo", "cleanup", "fix bug", "update readme", "initial commit", "first commit"}

        for repo in repos:
            name = repo["name"]
            full_name = repo["full_name"]  # "owner/repo"
            safe_name = sanitize_id(full_name.replace("/", "-"))
            desc = repo.get("description") or ""
            lang = repo.get("language") or "desconocido"
            topics = ", ".join(repo.get("topics", [])) or ""
            stars = repo.get("stargazers_count", 0)
            pushed = format_date(repo.get("pushed_at", ""))
            is_fork = repo.get("fork", False)

            # Sin descripción ni topics: intentar README antes de continuar
            if not desc and not topics:
                readme = await fetch_readme(client, full_name)
                if readme:
                    readme_text = f"README de {name}:\n{readme}"
                    if save_memory(readme_text, f"readme_{safe_name}"):
                        stats["readmes"] += 1
                        print(f"  ✓ readme: {full_name} (sin desc pero tiene README)")
                else:
                    print(f"  ✗ skip: {full_name} (sin desc, topics ni README)")
                commits = await fetch_commits(client, full_name)
                for commit in commits:
                    sha = commit.get("sha", "")[:7]
                    msg = commit.get("commit", {}).get("message", "").split("\n")[0][:150]
                    date = format_date(commit.get("commit", {}).get("author", {}).get("date", ""))
                    if not msg or len(msg) < 15 or msg.lower().strip() in GENERIC_COMMITS:
                        continue
                    commit_text = f"Commit en {name} ({date}): {msg}"
                    if save_memory(commit_text, f"commit_{safe_name}_{sha}"):
                        stats["commits"] += 1
                if commits:
                    print(f"    → commits guardados")
                continue

            # Repo base
            text = (
                f"GitHub repo: {full_name}. "
                f"Descripción: {desc}. "
                f"Lenguaje principal: {lang}. "
                f"Topics: {topics}. "
                f"Estrellas: {stars}. "
                f"Última actividad: {pushed}."
                + (" (fork)" if is_fork else "")
            )
            if save_memory(text, f"repo_{safe_name}"):
                stats["repos"] += 1
                print(f"  ✓ repo: {full_name} ({lang}){' [fork]' if is_fork else ''}")

            # Commits
            commits = await fetch_commits(client, full_name)
            for commit in commits:
                sha = commit.get("sha", "")[:7]
                msg = commit.get("commit", {}).get("message", "").split("\n")[0][:150]
                date = format_date(commit.get("commit", {}).get("author", {}).get("date", ""))
                if not msg or len(msg) < 15 or msg.lower().strip() in GENERIC_COMMITS:
                    continue
                commit_text = f"Commit en {name} ({date}): {msg}"
                if save_memory(commit_text, f"commit_{safe_name}_{sha}"):
                    stats["commits"] += 1

            if commits:
                print(f"    → {len(commits)} commits guardados")

            # README
            readme = await fetch_readme(client, full_name)
            if readme:
                readme_text = f"README de {name}:\n{readme}"
                if save_memory(readme_text, f"readme_{safe_name}"):
                    stats["readmes"] += 1
                    print(f"    → README guardado ({len(readme)} chars)")

        # ── Issues ─────────────────────────────────────────────────────────
        print("\n🐛 Fetching issues...")
        issues = await fetch_issues(client)
        for issue in issues:
            repo_url = issue.get("repository_url", "")
            repo_name = repo_url.split("/")[-1] if repo_url else "unknown"
            title = issue.get("title", "")
            labels = ", ".join(l["name"] for l in issue.get("labels", []))
            body = (issue.get("body") or "")[:200].replace("\n", " ")
            number = issue.get("number", "")

            text = f"Issue #{number} en {repo_name}: {title}."
            if labels:
                text += f" Labels: {labels}."
            if body:
                text += f" {body}"

            if save_memory(text, f"issue_{repo_name}_{number}"):
                stats["issues"] += 1

        print(f"   {stats['issues']} issues guardados")

        # ── PRs ────────────────────────────────────────────────────────────
        print("\n🔀 Fetching pull requests...")
        prs = await fetch_prs(client)
        for pr in prs:
            title = pr.get("title", "")
            state = pr.get("state", "")
            repo_url = pr.get("repository_url", "")
            repo_name = repo_url.split("/")[-1] if repo_url else "unknown"
            number = pr.get("number", "")
            body = (pr.get("body") or "")[:200].replace("\n", " ")

            text = f"Pull Request #{number} en {repo_name}: {title}. Estado: {state}."
            if body:
                text += f" {body}"

            if save_memory(text, f"pr_{repo_name}_{number}"):
                stats["prs"] += 1

        print(f"   {stats['prs']} PRs guardados")

        # ── Starred repos ──────────────────────────────────────────────────
        print("\n⭐ Fetching starred repos...")
        starred = await fetch_starred(client)
        for repo in starred[:20]:  # solo los 20 más recientes
            name = repo["full_name"]  # "owner/repo"
            desc = repo.get("description") or ""
            # Saltar starred sin descripción
            if not desc:
                continue
            lang = repo.get("language") or "desconocido"
            topics = ", ".join(repo.get("topics", [])) or ""
            stars = repo.get("stargazers_count", 0)

            text = (
                f"El usuario ha marcado con estrella el repo {name}. "
                f"Descripción: {desc}. "
                f"Lenguaje: {lang}. "
                + (f"Topics: {topics}. " if topics else "")
                + f"Estrellas totales: {stars}."
            )
            safe_name = sanitize_id(name.replace("/", "-"))
            if save_memory(text, f"starred_{safe_name}"):
                stats["starred"] = stats.get("starred", 0) + 1

        print(f"   {stats.get('starred', 0)} starred repos guardados")

    # ── Resumen ────────────────────────────────────────────────────────────
    print("\n" + "=" * 50)
    print("✅ Ingesta completa:")
    total_repos = stats['repos'] + stats['readmes']
    print(f"   📦 {total_repos} repositorios procesados ({stats['repos']} con desc + {stats['readmes']} via README)")
    print(f"   📝 {stats['commits']} commits almacenados")
    print(f"   📖 {stats['readmes']} READMEs guardados")
    print(f"   🐛 {stats['issues']} issues guardados")
    print(f"   🔀 {stats['prs']} pull requests guardados")
    print(f"   ⭐ {stats.get('starred', 0)} starred repos guardados")
    print(f"\n   containerTag: {CONTAINER_TAG}")
    print("=" * 50)

    return stats


if __name__ == "__main__":
    asyncio.run(main())
