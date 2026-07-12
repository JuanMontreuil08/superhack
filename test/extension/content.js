// MemoryLayer — content script
// Funciona en cualquier página. Toggle → extrae chunks → resalta relevantes → cita al hacer click.

const BACKEND = 'http://localhost:8000';
const TOGGLE_ID = 'ml-toggle';
const PANEL_ID = 'ml-panel';
const MODAL_ID = 'ml-modal';

// ── Estado ──────────────────────────────────────────────────────────────────
const IS_PDF = document.contentType === 'application/pdf'
  || window.location.href.toLowerCase().split('?')[0].endsWith('.pdf')
  || /^https?:\/\/arxiv\.org\/pdf\//i.test(window.location.href);

let active = false;
let highlighted = [];
let currentHighlightIndex = -1;

// ── Toggle button ────────────────────────────────────────────────────────────
function injectToggle() {
  if (document.getElementById(TOGGLE_ID)) return;

  const btn = document.createElement('button');
  btn.id = TOGGLE_ID;
  btn.textContent = '⚡';
  btn.title = 'MemoryLayer — activar contexto personal';
  btn.style.cssText = `
    position: fixed;
    bottom: 24px;
    right: 24px;
    z-index: 2147483647;
    width: 48px;
    height: 48px;
    border-radius: 50%;
    border: none;
    background: #1a1a2e;
    color: #fff;
    font-size: 20px;
    cursor: pointer;
    box-shadow: 0 4px 16px rgba(0,0,0,0.3);
    transition: transform 0.2s, background 0.2s;
  `;

  btn.addEventListener('mouseenter', () => btn.style.transform = 'scale(1.1)');
  btn.addEventListener('mouseleave', () => btn.style.transform = 'scale(1)');
  btn.addEventListener('click', handleToggle);

  document.body.appendChild(btn);
}

// ── Panel lateral ─────────────────────────────────────────────────────────────
function injectPanel() {
  if (document.getElementById(PANEL_ID)) return;

  const panel = document.createElement('div');
  panel.id = PANEL_ID;
  panel.innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
      <span style="font-weight:700;font-size:15px">⚡ MemoryLayer</span>
      <button id="ml-panel-close" style="background:none;border:none;color:#aaa;font-size:18px;cursor:pointer">✕</button>
    </div>
    <div id="ml-github-status" style="margin-bottom:16px;padding:10px;background:#0d1117;border-radius:8px;font-size:12px;color:#8b949e">
      Verificando GitHub...
    </div>
    <button id="ml-sync-btn" style="
      width:100%;padding:10px;background:#238636;color:#fff;
      border:none;border-radius:8px;font-size:13px;font-weight:600;
      cursor:pointer;margin-bottom:12px;transition:background 0.2s
    ">🔄 Sync GitHub Activity</button>
    <div id="ml-sync-status" style="font-size:12px;color:#8b949e;min-height:20px"></div>
    <hr style="border-color:#30363d;margin:12px 0">
    <div id="ml-messages" style="
      height:260px;overflow-y:auto;display:flex;flex-direction:column;gap:10px;
      padding-right:4px;margin-bottom:10px;
    ">
      <div style="font-size:12px;color:#8b949e;text-align:center;margin-top:8px">
        Pregúntame sobre esta página o sobre tu background
      </div>
    </div>
    <div style="display:flex;gap:6px">
      <input id="ml-chat-input" placeholder="¿Qué quieres saber?" style="
        flex:1;background:#0d1117;border:1px solid #30363d;border-radius:8px;
        color:#e6edf3;font-size:13px;padding:8px 10px;outline:none;
        font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
      "/>
      <button id="ml-send-btn" style="
        background:#1f6feb;border:none;border-radius:8px;color:#fff;
        font-size:16px;padding:8px 12px;cursor:pointer;flex-shrink:0;
      ">→</button>
    </div>
  `;
  panel.style.cssText = `
    position: fixed;
    bottom: 84px;
    right: 24px;
    z-index: 2147483646;
    width: 300px;
    background: #161b22;
    color: #e6edf3;
    border: 1px solid #30363d;
    border-radius: 12px;
    padding: 20px;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    box-shadow: 0 8px 32px rgba(0,0,0,0.5);
    opacity: 0;
    transform: translateY(8px);
    transition: opacity 0.2s, transform 0.2s;
  `;

  document.body.appendChild(panel);

  document.getElementById('ml-panel-close').addEventListener('click', closePanel);
  document.getElementById('ml-sync-btn').addEventListener('click', handleSync);
  document.getElementById('ml-send-btn').addEventListener('click', handleChat);
  document.getElementById('ml-chat-input').addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleChat(); }
  });

  // Animar entrada
  requestAnimationFrame(() => {
    panel.style.opacity = '1';
    panel.style.transform = 'translateY(0)';
  });

  checkGithubStatus();
}

function closePanel() {
  const panel = document.getElementById(PANEL_ID);
  if (!panel) return;
  panel.style.opacity = '0';
  panel.style.transform = 'translateY(8px)';
  setTimeout(() => panel.remove(), 200);
  active = false;
  document.getElementById(TOGGLE_ID).style.background = '#1a1a2e';
}

// ── Toggle handler ────────────────────────────────────────────────────────────
function handleToggle() {
  const btn = document.getElementById(TOGGLE_ID);
  active = !active;

  if (active) {
    btn.style.background = '#1f6feb';
    injectPanel();
  } else {
    closePanel();
    clearHighlights();
  }
}

// ── GitHub status ─────────────────────────────────────────────────────────────
async function checkGithubStatus() {
  const el = document.getElementById('ml-github-status');
  if (!el) return;
  try {
    const r = await fetch(`${BACKEND}/health`);
    if (r.ok) {
      el.innerHTML = '✅ <strong style="color:#3fb950">Backend activo</strong> · Supermemory conectado';
    }
  } catch {
    el.innerHTML = '❌ <strong style="color:#f85149">Backend offline</strong> — corre uvicorn server:app';
  }
}

// ── Sync GitHub ───────────────────────────────────────────────────────────────
async function handleSync() {
  const btn = document.getElementById('ml-sync-btn');
  const status = document.getElementById('ml-sync-status');
  if (!btn || !status) return;

  btn.disabled = true;
  btn.textContent = '⏳ Sincronizando...';
  status.textContent = 'Conectando con GitHub API...';

  try {
    const r = await fetch(`${BACKEND}/ingest-github`, { method: 'POST' });
    const data = await r.json();

    if (data.ok) {
      const total = data.memories || 0;
      btn.textContent = '⏳ Procesando memorias...';
      // Expandir panel para mostrar progreso
      const panel = document.getElementById(PANEL_ID);
      if (panel) panel.style.width = '300px';
      status.innerHTML = `
        <div style="color:#3fb950;line-height:1.8;margin-bottom:10px;font-size:12px">
          📦 ${data.repos} repos procesados<br>
          🧠 ${data.memories} memorias generadas por Gemini<br>
          <span style="color:#8b949e">⏭ ${data.skipped_forks || 0} forks saltados</span>
        </div>
        <div style="font-size:11px;color:#8b949e;margin-bottom:6px">Supermemory indexando ${total} memorias...</div>
        <div style="background:#21262d;border-radius:4px;height:8px;overflow:hidden;margin-bottom:4px">
          <div id="ml-queue-fill" style="background:#1f6feb;height:100%;width:5%;transition:width 0.8s ease"></div>
        </div>
        <div id="ml-queue-label" style="color:#8b949e;font-size:11px">Iniciando procesamiento...</div>
      `;
      pollQueueStatus(total);
    } else {
      throw new Error(data.error || 'Error desconocido');
    }
  } catch (e) {
    btn.textContent = '❌ Error en sync';
    btn.style.background = '#da3633';
    status.textContent = e.message;
  } finally {
    btn.disabled = false;
    setTimeout(() => {
      if (btn) btn.textContent = '🔄 Sync GitHub Activity';
      if (btn) btn.style.background = '#238636';
    }, 5000);
  }
}

// ── Extracción de chunks ──────────────────────────────────────────────────────
function extractChunks() {
  // Selectores site-specific para SPAs que no usan HTML semántico estándar
  const siteSelectors = {
    'twitter.com': '[data-testid="tweetText"]',
    'x.com': '[data-testid="tweetText"]',
    // Job detail pages + search results right panel + feed
    'linkedin.com': [
      '.jobs-description__content',
      '.jobs-description-content__text',
      '.jobs-description-content__text--stretch',
      '#job-details',
      '#job-details p, #job-details li, #job-details h2, #job-details h3',
      '.description__text--rich',
      '.jobs-box__html-content',
      '.jobs-unified-top-card__job-title',
      '.jobs-unified-top-card__primary-description',
      '.job-details-jobs-unified-top-card__primary-description',
      '.jobs-search__job-details--container p, .jobs-search__job-details--container li',
      '.scaffold-layout__detail p, .scaffold-layout__detail li',
      '.feed-shared-update-v2__description',
      '.feed-shared-text',
    ].join(', '),
    'reddit.com': '[data-click-id="text"] p, .Post h3',
  };
  const GENERIC = 'p, h1, h2, h3, li, td, blockquote, article';
  const host = window.location.hostname.replace('www.', '');
  const siteSelector = Object.entries(siteSelectors).find(([k]) => host.includes(k))?.[1];
  let elements = siteSelector ? document.querySelectorAll(siteSelector) : null;
  // Si los selectores site-specific no matchean nada, caer a genéricos
  if (!elements || elements.length === 0) {
    elements = document.querySelectorAll(GENERIC);
  }
  const seen = new Set();
  const chunks = [];

  for (const el of elements) {
    // Saltar elementos de MemoryLayer
    if (el.closest(`#${TOGGLE_ID}, #${PANEL_ID}, #${MODAL_ID}`)) continue;
    // Saltar scripts/styles embebidos
    if (el.closest('script, style, noscript')) continue;

    const text = el.innerText?.trim();
    if (!text || text.length < 60 || seen.has(text)) continue;
    seen.add(text);
    chunks.push({ text, el });
  }

  return chunks;
}

// ── Analizar página ───────────────────────────────────────────────────────────
async function analyzePage() {
  const btn = document.getElementById('ml-analyze-btn');
  const status = document.getElementById('ml-analyze-status');
  if (!btn || !status) return;

  clearHighlights();
  btn.disabled = true;
  btn.textContent = '⏳ Analizando...';
  status.textContent = 'Extrayendo contenido...';

  const chunks = extractChunks();
  if (!chunks.length) {
    status.textContent = 'No se encontró contenido para analizar.';
    btn.disabled = false;
    btn.textContent = '🔍 Analizar esta página';
    return;
  }

  status.textContent = `Evaluando ${chunks.length} fragmentos...`;

  try {
    const r = await fetch(`${BACKEND}/evaluate-page`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ chunks: chunks.map(c => c.text) }),
    });
    const data = await r.json();
    const hits = data.highlights || [];

    if (!hits.length) {
      status.textContent = 'Sin contenido relevante para tu contexto en esta página.';
    } else {
      status.textContent = `✨ ${hits.length} fragmentos relevantes encontrados`;
      applyHighlights(chunks, hits);
      // Show navigation
      const nav = document.getElementById('ml-nav');
      const label = document.getElementById('ml-nav-label');
      if (nav && label) {
        label.textContent = `0 / ${hits.length}`;
        nav.style.display = 'flex';
      }
    }
  } catch (e) {
    status.textContent = '❌ Error conectando al backend';
  } finally {
    btn.disabled = false;
    btn.textContent = '🔍 Analizar esta página';
  }
}

// ── Highlights ────────────────────────────────────────────────────────────────
function applyHighlights(chunks, hits) {
  const hitMap = new Map(hits.map(h => [h.text, h]));

  for (const { text, el } of chunks) {
    if (!hitMap.has(text)) continue;
    const hit = hitMap.get(text);

    const opacity = 0.3 + (hit.score - 0.65) * 1.4; // más score → más opaco
    const mark = document.createElement('mark');
    mark.style.cssText = `
      background: rgba(255, 200, 0, ${Math.min(opacity, 0.7)});
      border-radius: 3px;
      cursor: pointer;
      padding: 1px 2px;
    `;
    mark.title = `Score: ${hit.score} · Click para ver memoria`;
    mark.dataset.memory = hit.memory;
    mark.dataset.score = hit.score;

    // Envuelve el contenido del elemento
    mark.innerHTML = el.innerHTML;
    el.innerHTML = '';
    el.appendChild(mark);

    mark.addEventListener('click', (e) => {
      e.stopPropagation();
      showModal(hit);
    });

    highlighted.push(el);
  }
}

function clearHighlights() {
  for (const el of highlighted) {
    const mark = el.querySelector('mark[data-memory]');
    if (mark) {
      el.innerHTML = mark.innerHTML;
    }
  }
  highlighted = [];
  currentHighlightIndex = -1;
  const modal = document.getElementById(MODAL_ID);
  if (modal) modal.remove();
  const nav = document.getElementById('ml-nav');
  if (nav) nav.style.display = 'none';
}

function navigateHighlight(direction) {
  if (!highlighted.length) return;
  // Remove focus ring from current
  if (currentHighlightIndex >= 0) {
    const prev = highlighted[currentHighlightIndex].querySelector('mark[data-memory]');
    if (prev) prev.style.outline = 'none';
  }
  currentHighlightIndex = (currentHighlightIndex + direction + highlighted.length) % highlighted.length;
  const el = highlighted[currentHighlightIndex];
  const mark = el.querySelector('mark[data-memory]');
  if (mark) {
    mark.style.outline = '2px solid #1f6feb';
    mark.style.outlineOffset = '2px';
    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    // Update nav label
    const label = document.getElementById('ml-nav-label');
    if (label) label.textContent = `${currentHighlightIndex + 1} / ${highlighted.length}`;
    // Show modal for this hit
    showModal({ memory: mark.dataset.memory, score: parseFloat(mark.dataset.score) });
  }
}

// ── Modal de cita ─────────────────────────────────────────────────────────────
function showModal(hit) {
  const existing = document.getElementById(MODAL_ID);
  if (existing) existing.remove();

  const modal = document.createElement('div');
  modal.id = MODAL_ID;
  modal.innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:12px">
      <span style="font-size:12px;font-weight:700;color:#8b949e;text-transform:uppercase;letter-spacing:1px">¿Por qué te muestro esto?</span>
      <button id="ml-modal-close" style="background:none;border:none;color:#8b949e;font-size:16px;cursor:pointer;padding:0;margin-left:8px">✕</button>
    </div>
    <div style="font-size:14px;color:#e6edf3;line-height:1.6;margin-bottom:12px">
      "${(hit.memory || '').replace(/#+\s*/g, '').replace(/\[([^\]]+)\]\([^)]+\)/g, '$1').slice(0, 220)}${(hit.memory || '').length > 220 ? '...' : ''}"
    </div>
    <div style="font-size:11px;color:#8b949e;display:flex;align-items:center;gap:8px">
      <span style="background:#1f6feb;color:#fff;padding:2px 8px;border-radius:12px;font-weight:600">
        ${Math.round(hit.score * 100)}% relevante
      </span>
      <span>· Supermemory Local</span>
    </div>
  `;
  modal.style.cssText = `
    position: fixed;
    bottom: 84px;
    right: 320px;
    z-index: 2147483647;
    width: 260px;
    background: #161b22;
    color: #e6edf3;
    border: 1px solid #1f6feb;
    border-radius: 12px;
    padding: 16px;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    box-shadow: 0 8px 32px rgba(31,111,235,0.3);
    animation: mlFadeIn 0.15s ease;
  `;

  // Inyectar keyframe si no existe
  if (!document.getElementById('ml-styles')) {
    const style = document.createElement('style');
    style.id = 'ml-styles';
    style.textContent = `@keyframes mlFadeIn { from { opacity:0; transform:translateY(4px) } to { opacity:1; transform:translateY(0) } }`;
    document.head.appendChild(style);
  }

  document.body.appendChild(modal);
  document.getElementById('ml-modal-close').addEventListener('click', () => modal.remove());
}

// ── Queue polling ─────────────────────────────────────────────────────────
async function pollQueueStatus(total) {
  let attempts = 0;
  const maxAttempts = 40; // máx 2 minutos

  const interval = setInterval(async () => {
    attempts++;
    const fill = document.getElementById('ml-queue-fill');
    const label = document.getElementById('ml-queue-label');
    const btn = document.getElementById('ml-sync-btn');
    if (!fill || !label) { clearInterval(interval); return; }

    try {
      const r = await fetch(`${BACKEND}/queue-status`);
      const data = await r.json();
      const pending = data.total_pending || 0;
      const done = Math.max(0, total - pending);
      const pct = total > 0 ? Math.min(Math.round((done / total) * 100), 99) : 0;

      fill.style.width = `${pct}%`;

      if (pending === 0 || attempts >= maxAttempts) {
        clearInterval(interval);
        fill.style.width = '100%';
        fill.style.background = '#3fb950';
        label.innerHTML = `✅ <strong style="color:#3fb950">${total} memorias listas</strong> · Analiza la página ahora`;
        if (btn) { btn.textContent = '🔄 Sync GitHub Activity'; btn.disabled = false; }
      } else {
        label.textContent = `Procesando... ${done}/${total} listos (${pending} en cola)`;
      }
    } catch {
      clearInterval(interval);
    }
  }, 3000);
}

// ── Chat ──────────────────────────────────────────────────────────────────────
function addMessage(role, text) {
  const messages = document.getElementById('ml-messages');
  if (!messages) return;

  const isUser = role === 'user';
  const bubble = document.createElement('div');
  bubble.style.cssText = `
    max-width:90%;align-self:${isUser ? 'flex-end' : 'flex-start'};
    background:${isUser ? '#1f6feb' : '#21262d'};
    color:#e6edf3;border-radius:${isUser ? '12px 12px 4px 12px' : '12px 12px 12px 4px'};
    padding:8px 12px;font-size:13px;line-height:1.5;word-break:break-word;
  `;
  bubble.textContent = text;
  messages.appendChild(bubble);
  messages.scrollTop = messages.scrollHeight;
}

function getPageContext() {
  if (IS_PDF) return `PDF: ${window.location.href}`;
  const title = document.title || '';
  const chunks = extractChunks().slice(0, 5).map(c => c.text).join(' ');
  return `${title}\n${chunks}`.slice(0, 600);
}

async function handleChat() {
  const input = document.getElementById('ml-chat-input');
  const sendBtn = document.getElementById('ml-send-btn');
  if (!input) return;

  const question = input.value.trim();
  if (!question) return;

  input.value = '';
  addMessage('user', question);

  // Placeholder de typing
  const messages = document.getElementById('ml-messages');
  const typing = document.createElement('div');
  typing.style.cssText = 'align-self:flex-start;color:#8b949e;font-size:13px;padding:4px 8px;';
  typing.textContent = '⏳ Buscando en tu memoria...';
  if (messages) messages.appendChild(typing);
  if (sendBtn) sendBtn.disabled = true;

  try {
    const r = await fetch(`${BACKEND}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, page_context: getPageContext() }),
    });
    const data = await r.json();
    typing.remove();
    addMessage('assistant', data.answer || 'Sin respuesta');
  } catch (e) {
    typing.remove();
    addMessage('assistant', '❌ Error conectando al backend');
  } finally {
    if (sendBtn) sendBtn.disabled = false;
  }
}

// ── Analizar PDF ──────────────────────────────────────────────────────────────
async function analyzePDF() {
  const btn = document.getElementById('ml-analyze-btn');
  const status = document.getElementById('ml-analyze-status');
  const resultsEl = document.getElementById('ml-pdf-results');
  if (!btn || !status) return;

  btn.disabled = true;
  btn.textContent = '⏳ Extrayendo texto...';
  status.textContent = 'El backend descarga y parsea el PDF...';
  if (resultsEl) { resultsEl.innerHTML = ''; resultsEl.style.display = 'none'; }

  try {
    const r = await fetch(`${BACKEND}/analyze-pdf`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url: window.location.href }),
    });
    const data = await r.json();
    const hits = data.highlights || [];

    if (!hits.length) {
      status.textContent = 'Sin fragmentos relevantes para tu contexto en este PDF.';
    } else {
      status.textContent = `✨ ${hits.length} fragmentos relevantes`;
      showPDFResults(hits);
    }
  } catch (e) {
    status.textContent = '❌ Error conectando al backend';
  } finally {
    btn.disabled = false;
    btn.textContent = '📄 Analizar este PDF';
  }
}

function showPDFResults(hits) {
  const resultsEl = document.getElementById('ml-pdf-results');
  if (!resultsEl) return;

  resultsEl.innerHTML = '';
  resultsEl.style.display = 'flex';

  for (const hit of hits) {
    const memText = (hit.memory || '')
      .replace(/#+\s*/g, '')
      .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
      .slice(0, 180);
    const excerpt = (hit.text || '').slice(0, 140);

    const card = document.createElement('div');
    card.style.cssText = `
      background:#0d1117;border:1px solid #30363d;border-radius:8px;
      padding:10px 12px;font-size:12px;line-height:1.5;
    `;
    card.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
        <span style="color:#8b949e;font-size:11px">Pág. ${hit.page}</span>
        <span style="background:#1f6feb;color:#fff;padding:1px 7px;border-radius:10px;font-size:11px;font-weight:600">
          ${Math.round(hit.score * 100)}%
        </span>
      </div>
      <div style="color:#c9d1d9;margin-bottom:8px;font-style:italic">"${excerpt}${hit.text.length > 140 ? '…' : ''}"</div>
      <div style="color:#3fb950;font-size:11px">💡 ${memText}${hit.memory.length > 180 ? '…' : ''}</div>
    `;
    resultsEl.appendChild(card);
  }
}

// ── Init ──────────────────────────────────────────────────────────────────────
injectToggle();
console.log('[MemoryLayer] loaded on', window.location.href);
