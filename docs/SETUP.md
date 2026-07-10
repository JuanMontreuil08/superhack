# PRD — Proyecto Hackathon "Localhost 6767"

> Documento de contexto técnico para dar de comer a Claude Code / cualquier agente que trabaje en este repo. Última actualización: julio 2026.

---

## 1. Contexto de la hackathon

**Nombre:** Localhost 6767
**Reto:** Construir algo que use **Supermemory Local** de forma significativa — memoria persistente, agentes o contexto corriendo 100% en la máquina del usuario.

**Ideas sugeridas por la organización** (no obligatorias, sirven de inspiración):
- Asistente personal de IA local y privado con memoria persistente
- CLI que recuerda tu contexto entre sesiones
- "Segundo cerebro" que vive enteramente en tu máquina
- Plugin de Supermemory para una herramienta que aún no lo tenga
- Agentes / memoria / contexto corriendo localmente
- Bonus por ideas sorprendentes

**Criterio implícito de evaluación:** el uso de Supermemory debe ser central al producto, no decorativo.

---

## 2. Concepto de producto

> ⚠️ **PENDIENTE DE DEFINIR.** Las ideas iniciales exploradas (diario de sueños, "ghost writer" de estilo, tracker de decisiones de arquitectura, segundo cerebro de voz, detector de contradicciones) no convencieron. Esta sección debe completarse antes de empezar a construir features — todo lo de abajo es la base técnica ya lista para soportar cualquier dirección que se elija.

Campos a llenar cuando se decida:
- **Problema que resuelve:**
- **Usuario objetivo:**
- **Flujo principal (happy path):**
- **Por qué Supermemory es central (no solo un CRUD con IA encima):**
- **Qué lo hace "sorprendente":**

---

## 3. Qué es Supermemory Local (resumen técnico)

- Un solo binario, corre en la máquina del usuario, cero config inicial.
- Motor de grafo de memoria + embeddings locales incluidos (el vector search siempre es local).
- La extracción/entendimiento de memoria requiere un LLM: puede ser una API key de terceros (OpenAI/Anthropic/Gemini/Groq) o un modelo 100% local vía Ollama — decisión de este proyecto: **API key de proveedor tercero**.
- Habla el mismo API que la plataforma hosted (`api.supermemory.ai`) — todo lo construido aquí es portable a producción con solo cambiar el `baseURL`.
- Server local expone la API en `http://localhost:6767`.

### Categorías de la API (de mayor a menor probabilidad de uso en este proyecto)
| Categoría | Qué hace |
|---|---|
| **Ingest** | Agregar documentos/memorias (texto, URL, archivo, batch) |
| **Recall (Search)** | Búsqueda semántica — modo `hybrid` (memorias + chunks) o `memories` |
| **Profiles** | Perfiles de entidad (usuarios/participantes) con contexto acumulado automático |
| **Knowledge Graph** | Grafo de entidades y relaciones — pieza diferenciadora vs. RAG plano |
| **Spaces** | Organización de contenido en espacios (container tags) |
| **Content Management** | Listar/obtener/actualizar/borrar documentos y memorias |
| **Documents** | Listar/filtrar documentos (filtros AND/OR anidados, metadata, numéricos) |
| Connections / Settings / Analytics | Integraciones externas, config de org, uso — probablemente no relevantes para el hackathon |

---

## 4. Entorno — estado actual (ya resuelto)

### Instalación y arranque
```bash
curl -fsSL https://supermemory.ai/install | bash   # instala el binario (macOS Apple Silicon)
supermemory-server                                   # arranca el server, wizard interactivo la 1ra vez
```
- Server corre en `http://localhost:6767`
- Credenciales (API key, auth secret) guardadas en `~/.supermemory/env` y en `.supermemory/` dentro del repo (ver Decisión de datos, abajo)
- LLM provider: API key de terceros (Anthropic/OpenAI/Gemini/Groq — la que se configuró en el wizard)

### Verificación de funcionamiento
- ✅ Ingesta de documentos vía `curl` y SDK Python confirmada (memory agent procesando y extrayendo memorias correctamente, logs de `[Workflow]` visibles en consola del server)
- ✅ SDK de Python instalado y probado (`pip install supermemory`)
- ✅ Plugin de Claude Code (`supermemory`) instalado desde el marketplace `supermemoryai/claude-supermemory` — nombre real del plugin en el manifest: `supermemory` (no `claude-supermemory`, que es solo el nombre del repo)

### Variables de entorno (en `~/.zshrc`)
```bash
export SUPERMEMORY_BASE_URL="http://localhost:6767"
export SUPERMEMORY_CC_API_KEY="sm_..."   # para el plugin de Claude Code
```
Para scripts Python (vía `.env.local`, no versionado):
```
SUPERMEMORY_API_KEY=sm_...
SUPERMEMORY_BASE_URL=http://localhost:6767
```

---

## 5. Patrones de código confirmados (SDK Python)

### Guardar memoria
```python
from supermemory import Supermemory

client = Supermemory(
    api_key=os.environ.get("SUPERMEMORY_API_KEY"),
    base_url=os.environ.get("SUPERMEMORY_BASE_URL", "https://api.supermemory.ai"),
)

client.add(
    content="texto o URL",
    container_tag="mi_tag",       # STRING, no lista
    custom_id="id_unico",          # recomendado: evita duplicados en reintentos
)
```

### Buscar memoria
```python
response = client.search.memories(
    q="query de búsqueda",
    container_tag="mi_tag",
    search_mode="hybrid",   # "hybrid" (memorias + chunks) o "memories"
    limit=5,
)

for result in response.results:
    text = result.memory or result.chunk
    print(result.similarity, text)
```

### Gotchas ya identificados
- `container_tag` es **singular, string** — no `container_tags` como lista (ese parámetro existe pero está deprecado)
- El método correcto es `client.add(...)`, no `client.memories.add(...)`
- Búsqueda es `client.search.memories(...)`, no `client.search.documents(...)`
- El nombre del plugin de Claude Code en `/plugin install` es `supermemory`, no el nombre del repo completo

---

## 6. Claude Code — integración

- Plugin instalado y conectado al server local (no al hosted/Pro)
- Config por proyecto disponible vía `/claude-supermemory:project-config` → genera `.claude/.supermemory-claude/config.json` con `repoContainerTag` para aislar memoria de este repo vs. otros
- Recomendación pendiente de ejecutar: generar `docs/supermemory-capabilities.md` haciendo que Claude Code lea el OpenAPI spec real de `localhost:6767` y lo destile, luego referenciarlo desde `CLAUDE.md`

---