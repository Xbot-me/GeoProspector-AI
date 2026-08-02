/**
 * GeoProspector AI — Manual Outreach Field-Log & Workbench Engine
 */

let state = {
  activeTab: 'potential', // 'potential' | 'queue' | 'good'
  leads: [],
  activeRunId: null,
  ws: null,
  sortColumn: 'score', // 'score' | 'date' | 'name'
  sortDirection: 'desc', // 'desc' | 'asc'
  filters: {
    search: '',
    category: '',
    condition: '',
    minScore: 0,
  }
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

// Filter Inputs
const filterSearch = document.getElementById('filterSearch');
const filterCategory = document.getElementById('filterCategory');
const filterCondition = document.getElementById('filterCondition');
const filterMinScore = document.getElementById('filterMinScore');
const resetFiltersBtn = document.getElementById('resetFiltersBtn');

// Tabs
const tabPotentialBtn = document.getElementById('tabPotentialBtn');
const tabQueueBtn = document.getElementById('tabQueueBtn');
const tabGoodBtn = document.getElementById('tabGoodBtn');

const tabPotentialContent = document.getElementById('tabPotentialContent');
const tabQueueContent = document.getElementById('tabQueueContent');
const tabGoodContent = document.getElementById('tabGoodContent');

const badgePotential = document.getElementById('badgePotential');
const badgeQueue = document.getElementById('badgeQueue');
const badgeGood = document.getElementById('badgeGood');

const potentialTableBody = document.getElementById('potentialTableBody');
const goodTableBody = document.getElementById('goodTableBody');
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
  tabGoodBtn.addEventListener('click', () => switchTab('good'));

  // Search & Actions
  searchForm.addEventListener('submit', handleSearchSubmit);
  exportBtn.addEventListener('click', handleExportCSV);
  suggestBtn.addEventListener('click', handleSuggestTarget);
  logoutBtn.addEventListener('click', handleLogout);

  // Filters
  filterSearch.addEventListener('input', (e) => { state.filters.search = e.target.value; renderLeads(); });
  filterCategory.addEventListener('change', (e) => { state.filters.category = e.target.value; renderLeads(); });
  filterCondition.addEventListener('change', (e) => { state.filters.condition = e.target.value; renderLeads(); });
  filterMinScore.addEventListener('input', (e) => { state.filters.minScore = parseInt(e.target.value) || 0; renderLeads(); });
  resetFiltersBtn.addEventListener('click', resetFilters);

  // Table Column Sort Headers
  document.querySelectorAll('th.sortable').forEach(th => {
    th.addEventListener('click', () => {
      const col = th.getAttribute('data-sort');
      if (state.sortColumn === col) {
        state.sortDirection = state.sortDirection === 'desc' ? 'asc' : 'desc';
      } else {
        state.sortColumn = col;
        state.sortDirection = 'desc';
      }
      updateSortIndicators();
      renderLeads();
    });
  });
}


function resetFilters() {
  state.filters.search = '';
  state.filters.category = '';
  state.filters.condition = '';
  state.filters.minScore = 0;

  filterSearch.value = '';
  filterCategory.value = '';
  filterCondition.value = '';
  filterMinScore.value = 0;

  renderLeads();
}


function updateSortIndicators() {
  ['score', 'date', 'name'].forEach(col => {
    const el = document.getElementById(`sort-indicator-${col}`);
    if (el) {
      if (state.sortColumn === col) {
        el.textContent = state.sortDirection === 'desc' ? '▼' : '▲';
      } else {
        el.textContent = '';
      }
    }
  });
}


// ── Tab Management ──────────────────────────────────────────────────────
function switchTab(tabName) {
  state.activeTab = tabName;
  
  [tabPotentialBtn, tabQueueBtn, tabGoodBtn].forEach(b => b.classList.remove('active'));
  [tabPotentialContent, tabQueueContent, tabGoodContent].forEach(c => c.classList.add('hidden'));

  if (tabName === 'potential') {
    tabPotentialBtn.classList.add('active');
    tabPotentialContent.classList.remove('hidden');
  } else if (tabName === 'queue') {
    tabQueueBtn.classList.add('active');
    tabQueueContent.classList.remove('hidden');
  } else if (tabName === 'good') {
    tabGoodBtn.classList.add('active');
    tabGoodContent.classList.remove('hidden');
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
    state.leads = Array.isArray(data) ? data : (data.leads || []);
    populateCategoryFilter();
    renderLeads();
  } catch (err) {
    showToast('Error loading leads: ' + err.message, 'error');
  }
}


function populateCategoryFilter() {
  if (!filterCategory) return;
  const currentVal = state.filters.category;
  const categories = new Set();
  state.leads.forEach(l => {
    if (l.category && l.category.trim()) categories.add(l.category.trim());
  });
  const sortedCats = Array.from(categories).sort();
  filterCategory.innerHTML = '<option value="">All Categories</option>' +
    sortedCats.map(c => `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`).join('');
  filterCategory.value = currentVal;
}


function applyFiltersAndSort(leadList) {
  return leadList.filter(l => {
    // Text search (matches name, address, category, phone)
    if (state.filters.search) {
      const q = state.filters.search.toLowerCase();
      const nameMatch = (l.name || '').toLowerCase().includes(q);
      const addrMatch = (l.address || '').toLowerCase().includes(q);
      const catMatch = (l.category || '').toLowerCase().includes(q);
      const phoneMatch = (l.phone || '').toLowerCase().includes(q);
      if (!nameMatch && !addrMatch && !catMatch && !phoneMatch) return false;
    }

    // Category filter
    if (state.filters.category && (l.category || '') !== state.filters.category) {
      return false;
    }

    // Site condition filter
    if (state.filters.condition && (l.website_quality || 'none') !== state.filters.condition) {
      return false;
    }

    // Minimum score filter
    const score = l.lead_score || 0;
    if (score < state.filters.minScore) {
      return false;
    }

    return true;
  }).sort((a, b) => {
    let valA, valB;
    if (state.sortColumn === 'score') {
      valA = a.lead_score || 0;
      valB = b.lead_score || 0;
    } else if (state.sortColumn === 'date') {
      valA = a.created_at ? new Date(a.created_at).getTime() : 0;
      valB = b.created_at ? new Date(b.created_at).getTime() : 0;
    } else if (state.sortColumn === 'name') {
      valA = (a.name || '').toLowerCase();
      valB = (b.name || '').toLowerCase();
      return state.sortDirection === 'asc' ? valA.localeCompare(valB) : valB.localeCompare(valA);
    }

    if (state.sortDirection === 'asc') {
      return valA > valB ? 1 : valA < valB ? -1 : 0;
    } else {
      return valA < valB ? 1 : valA > valB ? -1 : 0;
    }
  });
}


function renderLeads() {
  // 1. Separate into raw categories
  // Potential: website_quality != 'good', not sent, no kit
  const rawPotential = state.leads.filter(l => 
    (l.website_quality || 'none') !== 'good' &&
    l.send_status !== 'sent' && l.send_status !== 'unsubscribed' &&
    (!l.pitch_body || l.pitch_body.trim() === '')
  );

  // Queue: website_quality != 'good', not sent, kit ready
  const rawQueue = state.leads.filter(l => 
    (l.website_quality || 'none') !== 'good' &&
    l.send_status !== 'sent' && l.send_status !== 'unsubscribed' &&
    l.pitch_body && l.pitch_body.trim() !== ''
  );

  // Good sites / Non-prospects: website_quality == 'good'
  const rawGood = state.leads.filter(l => (l.website_quality || 'none') === 'good');

  // 2. Apply composable filters and sort
  const filteredPotential = applyFiltersAndSort(rawPotential);
  const filteredQueue = applyFiltersAndSort(rawQueue);
  const filteredGood = applyFiltersAndSort(rawGood);

  // 3. Update badges to show filtered count
  badgePotential.textContent = filteredPotential.length;
  badgeQueue.textContent = filteredQueue.length;
  badgeGood.textContent = filteredGood.length;

  // 4. Render tables/cards
  renderPotentialTable(filteredPotential);
  renderQueueCards(filteredQueue);
  renderGoodTable(filteredGood);
}


function renderPotentialTable(leads) {
  if (leads.length === 0) {
    potentialTableBody.innerHTML = `
      <tr>
        <td colspan="7" style="text-align:center; padding:36px; color:var(--text-muted);">
          No prospect businesses match current filters. Adjust search or filters above!
        </td>
      </tr>
    `;
    return;
  }

  potentialTableBody.innerHTML = leads.map(l => {
    const condition = l.website_quality || 'none';
    let stampClass = 'stamp--rust';
    if (condition === 'outdated') stampClass = 'stamp--amber';

    const score = l.lead_score || 0;
    let scoreStamp = 'stamp--rust';
    if (score >= 70) scoreStamp = 'stamp--teal';
    else if (score >= 40) scoreStamp = 'stamp--amber';

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
        <td>
          <span class="stamp ${scoreStamp}">${score}/100</span>
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


function renderGoodTable(leads) {
  if (leads.length === 0) {
    goodTableBody.innerHTML = `
      <tr>
        <td colspan="6" style="text-align:center; padding:36px; color:var(--text-muted);">
          No businesses with good websites match current filters.
        </td>
      </tr>
    `;
    return;
  }

  goodTableBody.innerHTML = leads.map(l => {
    const score = l.lead_score || 0;
    let scoreStamp = 'stamp--rust';
    if (score >= 70) scoreStamp = 'stamp--teal';
    else if (score >= 40) scoreStamp = 'stamp--amber';

    const dateStr = l.created_at ? new Date(l.created_at).toLocaleDateString() : '—';

    return `
      <tr>
        <td>
          <strong style="color:var(--text-ink);">${escapeHtml(l.name || 'Unnamed Business')}</strong>
          ${l.phone ? `<div class="mono" style="font-size:11px; color:var(--text-muted); margin-top:2px;">${escapeHtml(l.phone)}</div>` : ''}
        </td>
        <td style="color:var(--text-muted);">${escapeHtml(l.category || 'Local Business')}</td>
        <td style="font-size:12px; color:var(--text-muted);">${escapeHtml(l.address || '—')}</td>
        <td style="font-size:12px;">
          ${l.website ? `<a href="${escapeHtml(l.website)}" target="_blank" style="color:var(--accent-teal); text-decoration:none;">${escapeHtml(l.website.replace(/^https?:\/\//, ''))}</a>` : '—'}
        </td>
        <td>
          <span class="stamp ${scoreStamp}">${score}/100</span>
        </td>
        <td class="mono" style="font-size:12px; color:var(--text-muted);">${dateStr}</td>
      </tr>
    `;
  }).join('');
}


function renderQueueCards(leads) {
  if (leads.length === 0) {
    queueList.innerHTML = `
      <div style="text-align:center; padding:48px; color:var(--text-muted);">
        No outreach kits match current filters. Adjust filters or click <b>"Build Kit"</b> on a lead!
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

    const score = l.lead_score || 0;
    let scoreStamp = 'stamp--rust';
    if (score >= 70) scoreStamp = 'stamp--teal';
    else if (score >= 40) scoreStamp = 'stamp--amber';

    const mailtoUrl = `mailto:${encodeURIComponent(email)}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;

    return `
      <div class="queue-card" id="card-${l.place_id}">
        <div class="queue-card__header">
          <div>
            <div class="queue-card__title" style="display:flex; align-items:center; gap:10px;">
              <span>${escapeHtml(l.name || 'Unnamed Business')}</span>
              <span class="stamp ${scoreStamp}">${score}/100</span>
            </div>
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
