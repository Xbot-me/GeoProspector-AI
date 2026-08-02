/**
 * GeoProspector AI — Manual Outreach Field-Log & Workbench Engine
 */

let state = {
  activeTab: 'potential', // 'potential' | 'queue'
  leads: [],
  activeRunId: null,
  ws: null,
};

// ── DOM Element References ──────────────────────────────────────────────
const searchForm = document.getElementById('searchForm');
const queryInput = document.getElementById('query');
const locationInput = document.getElementById('location');
const radiusInput = document.getElementById('radius');
const maxResultsInput = document.getElementById('maxResults');
const searchBtn = document.getElementById('searchBtn');
const exportBtn = document.getElementById('exportBtn');
const suggestBtn = document.getElementById('suggestBtn');
const logoutBtn = document.getElementById('logoutBtn');

const tabPotentialBtn = document.getElementById('tabPotentialBtn');
const tabQueueBtn = document.getElementById('tabQueueBtn');
const tabPotentialContent = document.getElementById('tabPotentialContent');
const tabQueueContent = document.getElementById('tabQueueContent');

const badgePotential = document.getElementById('badgePotential');
const badgeQueue = document.getElementById('badgeQueue');
const potentialTableBody = document.getElementById('potentialTableBody');
const queueList = document.getElementById('queueList');

const progressSection = document.getElementById('progressSection');
const progressStatus = document.getElementById('progressStatus');
const progressBar = document.getElementById('progressBar');
const eventFeed = document.getElementById('eventFeed');
const toastContainer = document.getElementById('toastContainer');


// ── Initialization ─────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  setupEventListeners();
  fetchLeads();
});


function setupEventListeners() {
  // Tabs
  tabPotentialBtn.addEventListener('click', () => switchTab('potential'));
  tabQueueBtn.addEventListener('click', () => switchTab('queue'));

  // Search
  searchForm.addEventListener('submit', handleSearchSubmit);
  exportBtn.addEventListener('click', handleExportCSV);
  suggestBtn.addEventListener('click', handleSuggestTarget);
  logoutBtn.addEventListener('click', handleLogout);
}


// ── Tab Management ──────────────────────────────────────────────────────
function switchTab(tabName) {
  state.activeTab = tabName;
  if (tabName === 'potential') {
    tabPotentialBtn.classList.add('active');
    tabQueueBtn.classList.remove('active');
    tabPotentialContent.classList.remove('hidden');
    tabQueueContent.classList.add('hidden');
  } else {
    tabQueueBtn.classList.add('active');
    tabPotentialBtn.classList.remove('active');
    tabQueueContent.classList.remove('hidden');
    tabPotentialContent.classList.add('hidden');
  }
}


// ── Data Fetching & Rendering ───────────────────────────────────────────
async function fetchLeads() {
  try {
    const res = await fetch('/api/leads');
    if (res.status === 401) {
      window.location.href = '/login';
      return;
    }
    const data = await res.json();
    // Handle both raw Array response and { leads: [...] } object wrapper
    state.leads = Array.isArray(data) ? data : (data.leads || []);
    renderLeads();
  } catch (err) {
    showToast('Error loading leads: ' + err.message, 'error');
  }
}


function renderLeads() {
  // Filter leads by send_status and kit presence
  const potentialLeads = state.leads.filter(l => 
    l.send_status !== 'sent' && l.send_status !== 'unsubscribed' && (!l.pitch_body || l.pitch_body.trim() === '')
  );

  const queueLeads = state.leads.filter(l => 
    l.send_status !== 'sent' && l.send_status !== 'unsubscribed' && l.pitch_body && l.pitch_body.trim() !== ''
  );

  badgePotential.textContent = potentialLeads.length;
  badgeQueue.textContent = queueLeads.length;

  renderPotentialTable(potentialLeads);
  renderQueueCards(queueLeads);
}


function renderPotentialTable(leads) {
  if (leads.length === 0) {
    potentialTableBody.innerHTML = `
      <tr>
        <td colspan="6" style="text-align:center; padding:36px; color:var(--text-muted);">
          No uncontacted businesses in queue. Discover new leads using the search panel above!
        </td>
      </tr>
    `;
    return;
  }

  potentialTableBody.innerHTML = leads.map(l => {
    const condition = l.website_quality || 'none';
    let stampClass = 'stamp--rust';
    if (condition === 'outdated') stampClass = 'stamp--amber';
    if (condition === 'good') stampClass = 'stamp--teal';

    const dateStr = l.created_at ? new Date(l.created_at).toLocaleDateString() : '—';

    return `
      <tr>
        <td>
          <strong style="color:var(--text-ink);">${escapeHtml(l.name || 'Unnamed Business')}</strong>
          ${l.phone ? `<div class="mono" style="font-size:11px; color:var(--text-muted); margin-top:2px;">${escapeHtml(l.phone)}</div>` : ''}
        </td>
        <td style="color:var(--text-muted);">${escapeHtml(l.category || 'Local Business')}</td>
        <td style="font-size:12px; color:var(--text-muted);">${escapeHtml(l.address || '—')}</td>
        <td>
          <span class="stamp ${stampClass}">${condition.toUpperCase()}</span>
        </td>
        <td class="mono" style="font-size:12px; color:var(--text-muted);">${dateStr}</td>
        <td style="text-align:right;">
          <button class="btn btn--sm" onclick="buildOutreachKit('${l.place_id}')">
            Build Kit
          </button>
        </td>
      </tr>
    `;
  }).join('');
}


function renderQueueCards(leads) {
  if (leads.length === 0) {
    queueList.innerHTML = `
      <div style="text-align:center; padding:48px; color:var(--text-muted);">
        No outreach kits ready in queue. Click <b>"Build Kit"</b> on any lead in Potential Businesses!
      </div>
    `;
    return;
  }

  queueList.innerHTML = leads.map(l => {
    const email = l.email || '';
    const subject = l.pitch_subject || '';
    const body = l.pitch_body || '';
    const prompt = l.mockup_prompt || '';
    const analysis = l.analysis || 'Analysis pending.';

    const mailtoUrl = `mailto:${encodeURIComponent(email)}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;

    return `
      <div class="queue-card" id="card-${l.place_id}">
        <div class="queue-card__header">
          <div>
            <div class="queue-card__title">${escapeHtml(l.name || 'Unnamed Business')}</div>
            <div class="queue-card__meta">
              ${l.category ? escapeHtml(l.category) + ' &bull; ' : ''}
              ${l.email ? `📧 <span style="color:var(--accent-teal-dark);">${escapeHtml(l.email)}</span>` : '<span style="color:var(--stamp-rust);">No email found</span>'}
              ${l.phone ? ' &bull; 📞 ' + escapeHtml(l.phone) : ''}
            </div>
          </div>
          <span class="stamp stamp--amber">READY TO SEND</span>
        </div>

        <!-- Section 1: Analysis Summary -->
        <div class="queue-card__section">
          <div class="queue-card__section-label">1. Analysis Brief & Pitch Angle</div>
          <div class="analysis-box">${escapeHtml(analysis)}</div>
        </div>

        <!-- Section 2: Lovable Mockup Prompt -->
        <div class="queue-card__section">
          <div class="queue-card__section-label" style="display:flex; justify-content:space-between; align-items:center;">
            <span>2. Lovable.dev / AI Site Builder Mockup Prompt</span>
            <button class="btn btn--outline btn--sm" onclick="copyPrompt('${l.place_id}')">Copy Prompt</button>
          </div>
          <div class="prompt-box" id="prompt-${l.place_id}">${escapeHtml(prompt)}</div>
        </div>

        <!-- Section 3: Editable Email Draft -->
        <div class="queue-card__section">
          <div class="queue-card__section-label">3. Personalized Email Draft (Insert Mockup Link at [MOCKUP_LINK])</div>
          <input type="text" id="subject-${l.place_id}" value="${escapeHtml(subject)}" placeholder="Subject Line" style="width:100%; margin-bottom:8px; font-weight:600;">
          <textarea id="body-${l.place_id}" rows="6" style="width:100%;">${escapeHtml(body)}</textarea>
        </div>

        <!-- Card Actions -->
        <div class="queue-card__actions">
          <a href="${mailtoUrl}" target="_blank" class="btn" onclick="updateMailtoLink('${l.place_id}')" id="mailto-${l.place_id}">
            ✉️ Open in Email Client
          </a>
          <button class="btn btn--outline" onclick="markAsSent('${l.place_id}')">
            ✓ Mark as Sent
          </button>
          ${l.email ? `<button class="btn btn--outline btn--sm" style="margin-left:auto;" onclick="sendSingleEmailAPI('${l.place_id}')">Dispatch via API</button>` : ''}
        </div>
      </div>
    `;
  }).join('');
}


// ── Lead Actions ────────────────────────────────────────────────────────
async function buildOutreachKit(placeId) {
  showToast('Building outreach kit with Gemini...', 'info');
  try {
    const res = await fetch(`/api/leads/${placeId}/build-kit`, { method: 'POST' });
    if (!res.ok) throw new Error('Failed to generate outreach kit');
    const updated = await res.json();
    
    // Update local state
    const idx = state.leads.findIndex(l => l.place_id === placeId);
    if (idx !== -1) {
      state.leads[idx] = updated;
    }
    
    renderLeads();
    switchTab('queue');
    showToast('Outreach kit generated successfully!', 'success');
    
    const cardEl = document.getElementById(`card-${placeId}`);
    if (cardEl) {
      cardEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  } catch (err) {
    showToast('Error: ' + err.message, 'error');
  }
}


function copyPrompt(placeId) {
  const promptEl = document.getElementById(`prompt-${placeId}`);
  if (!promptEl) return;
  const text = promptEl.textContent;
  navigator.clipboard.writeText(text).then(() => {
    showToast('Lovable prompt copied to clipboard!', 'success');
  }).catch(err => {
    showToast('Copy failed: ' + err.message, 'error');
  });
}


function updateMailtoLink(placeId) {
  const emailObj = state.leads.find(l => l.place_id === placeId);
  const email = emailObj ? emailObj.email || '' : '';
  const subjEl = document.getElementById(`subject-${placeId}`);
  const bodyEl = document.getElementById(`body-${placeId}`);

  const subj = subjEl ? subjEl.value : '';
  const body = bodyEl ? bodyEl.value : '';

  const linkEl = document.getElementById(`mailto-${placeId}`);
  if (linkEl) {
    linkEl.href = `mailto:${encodeURIComponent(email)}?subject=${encodeURIComponent(subj)}&body=${encodeURIComponent(body)}`;
  }
}


async function markAsSent(placeId) {
  const subjEl = document.getElementById(`subject-${placeId}`);
  const bodyEl = document.getElementById(`body-${placeId}`);

  const payload = {
    status: 'sent',
    pitch_subject: subjEl ? subjEl.value : undefined,
    pitch_body: bodyEl ? bodyEl.value : undefined,
  };

  try {
    const res = await fetch(`/api/leads/${placeId}/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (!res.ok) throw new Error('Failed to mark as sent');
    
    // Update local lead state
    const idx = state.leads.findIndex(l => l.place_id === placeId);
    if (idx !== -1) {
      state.leads[idx].send_status = 'sent';
    }
    renderLeads();
    showToast('Lead marked as sent!', 'success');
  } catch (err) {
    showToast('Error: ' + err.message, 'error');
  }
}


async function sendSingleEmailAPI(placeId) {
  const biz = state.leads.find(l => l.place_id === placeId);
  if (!biz || !biz.email) {
    showToast('No valid email for lead', 'error');
    return;
  }

  if (!confirm(`Send email to ${biz.email} via API now?`)) return;

  try {
    const res = await fetch(`/api/leads/${placeId}/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: 'sent' })
    });
    if (!res.ok) throw new Error('Dispatch failed');
    biz.send_status = 'sent';
    renderLeads();
    showToast(`Email dispatched to ${biz.email}`, 'success');
  } catch (err) {
    showToast('Dispatch error: ' + err.message, 'error');
  }
}


// ── Search & Telemetry Live Progress ────────────────────────────────────
async function handleSearchSubmit(e) {
  e.preventDefault();
  const query = queryInput.value.trim();
  const location = locationInput.value.trim();
  const radius = parseInt(radiusInput.value) || 5000;
  const maxResults = parseInt(maxResultsInput.value) || 15;

  if (!query || !location) {
    showToast('Query and Location are required', 'error');
    return;
  }

  searchBtn.disabled = true;
  searchBtn.textContent = 'Searching...';
  progressSection.classList.remove('hidden');
  eventFeed.innerHTML = '';
  if (progressBar) progressBar.style.width = '5%';
  progressStatus.textContent = 'Starting discovery pipeline...';

  try {
    const res = await fetch('/api/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, location, radius, max_results: maxResults })
    });
    const data = await res.json();
    if (data.error) throw new Error(data.error);

    state.activeRunId = data.run_id;
    connectWebSocket(data.run_id);
  } catch (err) {
    showToast('Search failed: ' + err.message, 'error');
    searchBtn.disabled = false;
    searchBtn.textContent = 'Discover Leads';
  }
}


function connectWebSocket(runId) {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${protocol}//${window.location.host}/ws/${runId}`;
  state.ws = new WebSocket(wsUrl);

  state.ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    handleWebSocketEvent(data);
  };

  state.ws.onerror = () => {
    searchBtn.disabled = false;
    searchBtn.textContent = 'Discover Leads';
  };
}


function handleWebSocketEvent(data) {
  const now = new Date();
  const timeStr = now.toTimeString().split(' ')[0]; // HH:MM:SS
  const eventType = data.type;

  let lineText = '';
  let colorStyle = 'color: var(--text-ink);';

  if (eventType === 'search_start') {
    lineText = `${timeStr} — searching "${data.query || 'businesses'}" in ${data.location || 'target area'}...`;
    progressStatus.textContent = lineText;
    if (progressBar) progressBar.style.width = '10%';
  } else if (eventType === 'status') {
    lineText = `${timeStr} — ${data.message}`;
    progressStatus.textContent = lineText;
  } else if (eventType === 'search_complete') {
    lineText = `${timeStr} — found ${data.count} businesses`;
    progressStatus.textContent = lineText;
    if (progressBar) progressBar.style.width = '25%';
  } else if (eventType === 'skipped') {
    lineText = `${timeStr} — skipped ${data.name || 'business'}: ${data.reason || 'duplicate'}`;
    colorStyle = 'color: var(--stamp-amber);';
  } else if (eventType === 'processing') {
    const pct = data.total ? Math.round((data.index / data.total) * 75) + 20 : 50;
    if (progressBar) progressBar.style.width = `${pct}%`;
    lineText = `${timeStr} — processing ${data.index}/${data.total}: ${data.name}`;
    progressStatus.textContent = lineText;
  } else if (eventType === 'drafted') {
    lineText = `${timeStr} — enriched ${data.name} (score: ${data.lead_score || 0})`;
    colorStyle = 'color: var(--accent-teal);';
  } else if (eventType === 'business_error') {
    lineText = `${timeStr} — error processing ${data.name}: ${data.error}`;
    colorStyle = 'color: var(--stamp-rust);';
  } else if (eventType === 'complete') {
    const stats = data.stats || {};
    lineText = `${timeStr} — run complete (${stats.qualified || 0} qualified, ${stats.emails_found || 0} emails found)`;
    colorStyle = 'color: var(--stamp-green); font-weight: 600;';
    progressStatus.textContent = lineText;
    if (progressBar) progressBar.style.width = '100%';

    searchBtn.disabled = false;
    searchBtn.textContent = 'Discover Leads';
    
    // Immediately fetch updated leads backlog into tabs
    fetchLeads();
  } else if (eventType === 'error') {
    lineText = `${timeStr} — error: ${data.message}`;
    colorStyle = 'color: var(--stamp-rust); font-weight: 600;';
    progressStatus.textContent = lineText;
    searchBtn.disabled = false;
    searchBtn.textContent = 'Discover Leads';
  } else {
    lineText = `${timeStr} — ${data.message || eventType}`;
  }

  if (lineText) {
    const div = document.createElement('div');
    div.style.cssText = `padding: 4px 0; border-bottom: 1px solid var(--border-hairline); ${colorStyle}`;
    div.textContent = lineText;
    eventFeed.appendChild(div);
    eventFeed.scrollTop = eventFeed.scrollHeight;
  }
}


async function handleSuggestTarget() {
  suggestBtn.disabled = true;
  suggestBtn.textContent = 'Thinking...';
  try {
    const res = await fetch('/api/suggest-target');
    const data = await res.json();
    if (data.location) {
      queryInput.value = data.query || 'local businesses';
      locationInput.value = data.location;
      showToast(`Suggested: ${data.location}`, 'info');
    }
  } catch (err) {
    showToast('Failed to get suggestion', 'error');
  } finally {
    suggestBtn.disabled = false;
    suggestBtn.textContent = 'Suggest Location Target';
  }
}


function handleExportCSV() {
  window.location.href = '/api/export';
}


function handleLogout() {
  document.cookie = 'admin_session=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/;';
  window.location.href = '/login';
}


// ── Utilities ───────────────────────────────────────────────────────────
function showToast(message, type = 'info') {
  const toast = document.createElement('div');
  toast.className = 'toast';
  toast.textContent = message;
  if (type === 'error') toast.style.borderLeft = '4px solid var(--stamp-rust)';
  if (type === 'success') toast.style.borderLeft = '4px solid var(--accent-teal)';

  toastContainer.appendChild(toast);
  setTimeout(() => {
    toast.remove();
  }, 4000);
}


function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}
