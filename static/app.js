/* ═══════════════════════════════════════════════════════════════
   Maps Outreach Agent — Dashboard Frontend Logic (Sniper Mode)
   ═══════════════════════════════════════════════════════════════ */

(() => {
  'use strict';

  // ── State ──────────────────────────────────────────────────
  let currentRunId = null;
  let ws = null;
  let allLeads = {};  // place_id -> data
  let currentModalPlaceId = null;

  // ── DOM refs ───────────────────────────────────────────────
  const $ = (sel) => document.querySelector(sel);
  const searchForm      = $('#searchForm');
  const searchBtn       = $('#searchBtn');
  const suggestBtn      = $('#suggestBtn');
  const autoPilotBtn    = $('#autoPilotBtn');
  const exportBtn       = $('#exportBtn');

  // ── Auto-Pilot Handler ─────────────────────────────────────
  if (autoPilotBtn) {
    autoPilotBtn.addEventListener('click', async () => {
      if (!confirm('Run daily auto-pilot? This will auto-send emails in queue up to 20/day and search the next city in rotation.')) return;
      
      autoPilotBtn.disabled = true;
      const originalHtml = autoPilotBtn.innerHTML;
      autoPilotBtn.innerHTML = '<span>⏳</span> Starting Auto-Pilot...';

      try {
        const resp = await fetch('/api/campaign/run_daily', { method: 'POST' });
        const data = await resp.json();
        
        if (data.success) {
          alert(`⚡ Auto-Pilot Started!\n\nDispatched from queue: ${data.dispatched_from_queue} emails\nToday's Total Sent: ${data.daily_sent_total}/20\n\nNext Rotation Target: ${data.target.display_name}`);
          window.location.reload();
        } else {
          alert('Error: ' + (data.error || 'Failed to start auto-pilot'));
        }
      } catch (e) {
        console.error('Auto-Pilot error:', e);
        alert('Network error starting auto-pilot.');
      } finally {
        autoPilotBtn.disabled = false;
        autoPilotBtn.innerHTML = originalHtml;
      }
    });
  }
  const progressSection = $('#progressSection');
  const progressBar     = $('#progressBar');
  const progressStatus  = $('#progressStatus');
  const eventFeed       = $('#eventFeed');
  const leadsContent    = $('#leadsContent');
  const approvalModal   = $('#approvalModal');
  const modalTitle      = $('#modalTitle');
  const modalDetails    = $('#modalDetails');
  const modalScoreBreakdown = $('#modalScoreBreakdown');
  const editSubject     = $('#editSubject');
  const editBody        = $('#editBody');

  // Stats
  const statFound     = $('#statFound');
  const statQualified = $('#statQualified');
  const statEmails    = $('#statEmails');
  const statApproved  = $('#statApproved');
  const statSent      = $('#statSent');
  const statSkipped   = $('#statSkipped');

  // ── Helpers ────────────────────────────────────────────────

  function scoreBadge(score) {
    if (score == null) return '';
    const cls = score >= 70 ? 'high' : score >= 50 ? 'mid' : 'low';
    return `<span class="score-badge score-badge--${cls}">${score}</span>`;
  }

  function qualityBadge(quality) {
    if (!quality) return '';
    const map = {
      none: 'none', dead: 'dead', social_only: 'social',
      outdated: 'outdated', good: 'good',
    };
    const labels = {
      none: 'No Site', dead: 'Dead', social_only: 'Social Only',
      outdated: 'Outdated', good: 'Good',
    };
    const cls = map[quality] || 'none';
    return `<span class="quality-badge quality-badge--${cls}">${labels[quality] || quality}</span>`;
  }

  function statusBadge(status) {
    if (!status) return '';
    const map = {
      pending: 'pending', approved: 'approved', sent: 'sent',
      rejected: 'rejected', skipped: 'skipped',
      not_sent: 'pending', no_email: 'skipped', failed: 'rejected',
      pending_auto_send: 'approved',
    };
    const labels = {
      pending: '⏳ Pending', approved: '✓ Approved', sent: '✉ Contacted',
      rejected: '✕ Rejected', skipped: '⏭ Skipped',
      not_sent: '⏳ Pending', no_email: '⏭ No Email', failed: '✕ Failed',
      pending_auto_send: '⚡ Auto-Queue',
    };
    const cls = map[status] || 'pending';
    const label = labels[status] || status;
    return `<span class="status-badge status-badge--${cls}">${label}</span>`;
  }

  function animateNumber(el, target) {
    const current = parseInt(el.textContent) || 0;
    if (current === target) return;
    const diff = target - current;
    const steps = Math.min(Math.abs(diff), 20);
    const increment = diff / steps;
    let step = 0;

    function tick() {
      step++;
      if (step >= steps) {
        el.textContent = target;
      } else {
        el.textContent = Math.round(current + increment * step);
        requestAnimationFrame(tick);
      }
    }
    requestAnimationFrame(tick);
  }

  function updateStats(stats) {
    if (!stats) return;
    animateNumber(statFound, stats.found || 0);
    animateNumber(statQualified, stats.qualified || 0);
    animateNumber(statEmails, stats.emails_found || 0);
    animateNumber(statApproved, stats.approved || 0);
    animateNumber(statSent, stats.sent || 0);
    animateNumber(statSkipped, (stats.good_website || 0) + (stats.low_score || 0));
  }

  // ── Event feed ─────────────────────────────────────────────

  function addEvent(iconClass, emoji, name, detail, actionHtml = '') {
    const item = document.createElement('div');
    item.className = 'event-item';
    item.innerHTML = `
      <div class="event-item__icon event-item__icon--${iconClass}">${emoji}</div>
      <div class="event-item__text">
        <div class="event-item__name">${name}</div>
        <div class="event-item__detail">${detail}</div>
      </div>
      ${actionHtml ? `<div class="event-item__actions">${actionHtml}</div>` : ''}
    `;
    eventFeed.prepend(item);
    return item;
  }

  // ── Leads table ────────────────────────────────────────────

  async function loadLeads() {
    try {
      const resp = await fetch('/api/leads');
      const leads = await resp.json();
      
      // Update global cache
      allLeads = {};
      leads.forEach(l => allLeads[l.place_id] = l);
      
      renderLeadsTable(leads);
    } catch (e) {
      console.error('Failed to load leads:', e);
    }
  }

  function renderLeadsTable(leads) {
    if (!leads || leads.length === 0) {
      leadsContent.innerHTML = `
        <div class="empty-state">
          <div class="empty-state__icon">🗺️</div>
          <div class="empty-state__text">Run a search to discover leads</div>
        </div>`;
      return;
    }

    let rows = leads.map(l => {
      // Show review button if it's not skipped/good website
      const showReview = l.website_quality !== 'good';
      
      return `
      <tr>
        <td><span class="leads-table__name">${esc(l.name || '')}</span></td>
        <td>${scoreBadge(l.lead_score)}</td>
        <td>${qualityBadge(l.website_quality)}</td>
        <td class="leads-table__email">${l.email ? esc(l.email) : '<span style="color:var(--text-muted)">—</span>'}</td>
        <td>${l.facebook_url ? '📘' : ''}${l.instagram_url ? ' 📷' : ''}</td>
        <td>${l.open_count > 0 ? `<span class="status-badge" style="background:rgba(16,185,129,0.15);color:#10b981;border:1px solid rgba(16,185,129,0.3)">👀 Opened (${l.open_count})</span>` : statusBadge(l.send_status === 'sent' ? 'sent' : (l.send_status === 'pending_auto_send' ? 'pending_auto_send' : l.approval_status))}</td>
        <td>
          ${showReview
            ? `<button class="btn btn--primary btn--sm" onclick="window.__openModal('${esc(l.place_id)}')">Review</button>`
            : ''
          }
        </td>
      </tr>
      `;
    }).join('');

    leadsContent.innerHTML = `
      <div class="leads-table-wrap">
        <table class="leads-table">
          <thead>
            <tr>
              <th>Business</th>
              <th>Score</th>
              <th>Website</th>
              <th>Email</th>
              <th>Social</th>
              <th>Status</th>
              <th></th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>`;
  }

  function esc(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  // ── Export ─────────────────────────────────────────────────
  exportBtn.addEventListener('click', () => {
    window.location.href = `/api/runs/${currentRunId || 'all'}/csv`;
  });

  // ── Modal ──────────────────────────────────────────────────

  window.__openModal = async function(placeId) {
    // If we don't have full details, fetch them
    let data = allLeads[placeId];
    if (!data || !data.pitch_body) {
      const resp = await fetch(`/api/leads/${placeId}`);
      data = await resp.json();
      allLeads[placeId] = data;
    }

    if (!data) return;
    currentModalPlaceId = placeId;

    modalTitle.textContent = `Review — ${data.name || 'Business'}`;

    // Build detail grid
    const details = [
      ['Score', scoreBadge(data.lead_score)],
      ['Website', qualityBadge(data.website_quality)],
      ['Email', data.email ? `<span class="leads-table__email">${esc(data.email)}</span>` : '<span style="color:var(--text-muted)">Not found</span>'],
      ['Language', data.email_language ? `<span style="color:#10b981;font-weight:600;">🗣️ ${esc(data.email_language)}</span>` : 'English'],
      ['Tracking', data.open_count > 0 ? `<span style="color:#10b981;font-weight:600;">👀 Opened ${data.open_count} time(s)</span>` : (data.sent_at ? `✉ Sent at ${data.sent_at}` : 'Not dispatched yet')],
      ['Phone', data.phone || '—'],
      ['Rating', data.rating ? `${data.rating}★ (${data.review_count || 0} reviews)` : '—'],
      ['Category', data.category || '—'],
      ['Facebook', data.facebook_url ? `<a href="${esc(data.facebook_url)}" target="_blank" style="color:var(--accent)">${esc(data.facebook_url)}</a>` : '—'],
      ['Instagram', data.instagram_url ? `<a href="${esc(data.instagram_url)}" target="_blank" style="color:var(--accent)">${esc(data.instagram_url)}</a>` : '—'],
      ['Owner', data.owner_name || '—'],
      ['Address', data.address || '—'],
    ];

    modalDetails.innerHTML = details.map(([label, value]) => `
      <div class="modal__detail">
        <div class="modal__detail-label">${label}</div>
        <div class="modal__detail-value">${value}</div>
      </div>
    `).join('');

    // Score breakdown
    modalScoreBreakdown.textContent = data.score_breakdown || 'No breakdown available';

    // Pitch fields
    editSubject.value = data.pitch_subject || '';
    editBody.value = data.pitch_body || '';
    editSubject.readOnly = false;
    editBody.readOnly = false;
    editSubject.style.opacity = '1';
    editBody.style.opacity = '1';

    approvalModal.classList.add('active');
  };

  function closeModal() {
    approvalModal.classList.remove('active');
    currentModalPlaceId = null;
  }

  async function copyPitch() {
    const text = `Subject: ${editSubject.value}\n\n${editBody.value}`;
    try {
      await navigator.clipboard.writeText(text);
      const btn = $('#btnCopy');
      const originalText = btn.textContent;
      btn.textContent = '✓ Copied!';
      setTimeout(() => btn.textContent = originalText, 2000);
    } catch (e) {
      console.error('Failed to copy', e);
    }
  }

  async function updateStatus(status) {
    if (!currentModalPlaceId) return;

    // Disable buttons while processing
    const buttons = approvalModal.querySelectorAll('.btn');
    buttons.forEach(b => b.disabled = true);

    try {
      await fetch(`/api/leads/${currentModalPlaceId}/status`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status }),
      });

      closeModal();
      
      addEvent('done', '✓', 'Status updated',
        `Lead marked as ${status}`, '');
        
      loadLeads();

    } catch (e) {
      console.error('Update failed:', e);
    } finally {
      buttons.forEach(b => b.disabled = false);
    }
  }

  // Modal event listeners
  $('#modalClose').addEventListener('click', closeModal);
  approvalModal.addEventListener('click', (e) => {
    if (e.target === approvalModal) closeModal();
  });
  
  $('#btnCopy').addEventListener('click', copyPitch);
  $('#btnContacted').addEventListener('click', () => updateStatus('sent'));
  $('#btnReject').addEventListener('click', () => updateStatus('rejected'));

  // ── WebSocket ──────────────────────────────────────────────

  function connectWS(runId) {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${protocol}//${location.host}/ws/${runId}`);

    ws.onmessage = (evt) => {
      const event = JSON.parse(evt.data);
      handleEvent(event);
    };

    ws.onerror = (err) => {
      console.error('WebSocket error:', err);
    };

    ws.onclose = () => {
      console.log('WebSocket closed');
    };
  }

  function handleEvent(event) {
    switch (event.type) {

      case 'status':
        progressStatus.textContent = event.message;
        break;

      case 'search_complete':
        updateStats({ found: event.count, qualified: 0, emails_found: 0, approved: 0, sent: 0 });
        progressStatus.textContent = `Found ${event.count} businesses. Processing...`;
        addEvent('processing', '🔍', `${event.count} businesses found`,
          'Starting enrichment pipeline');
        break;

      case 'processing':
        progressBar.style.width = `${(event.index / event.total) * 100}%`;
        progressStatus.textContent = `Processing ${event.index}/${event.total}: ${event.name}`;
        addEvent('processing', '⏳', event.name,
          `Enriching... (${event.index}/${event.total})`);
        break;

      case 'skipped': {
        const reason = event.reason === 'good_website'
          ? `Good website — not a prospect`
          : `Score ${event.lead_score} below threshold`;
        addEvent('skipped', '⏭', event.name, reason);
        // Refresh table
        loadLeads();
        break;
      }

      case 'drafted': {
        const actionHtml = event.has_pitch !== false
          ? `<button class="btn btn--primary btn--sm" onclick="window.__openModal('${esc(event.place_id)}')">Review</button>`
          : `<span style="font-size: 12px; color: var(--text-muted);">Data extracted</span>`;

        addEvent('approval', '⚡', event.name,
          `Score: ${event.lead_score} — ${event.has_pitch !== false ? 'Pitch drafted' : 'Data extracted'}`,
          actionHtml
        );
        // Refresh table
        loadLeads();
        break;
      }

      case 'business_error':
        addEvent('error', '⚠', event.name || event.place_id,
          `Error: ${event.error}`);
        break;

      case 'complete':
        progressBar.style.width = '100%';
        progressStatus.textContent = 'Pipeline complete!';
        if (event.stats) updateStats(event.stats);
        addEvent('done', '🎉', 'Run complete',
          `${event.stats?.qualified || 0} qualified leads, ${event.stats?.emails_found || 0} emails found`);
        searchBtn.disabled = false;
        searchBtn.innerHTML = `
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg>
          Start Search`;
        loadLeads();
        break;

      case 'error':
        progressStatus.textContent = `Error: ${event.message}`;
        addEvent('error', '❌', 'Error', event.message);
        searchBtn.disabled = false;
        searchBtn.innerHTML = `
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg>
          Start Search`;
        break;
    }
  }

  // ── Suggest Target Handler ─────────────────────────────────

  if (suggestBtn) {
    suggestBtn.addEventListener('click', async () => {
      suggestBtn.disabled = true;
      const originalText = suggestBtn.innerHTML;
      suggestBtn.innerHTML = '🤔 Thinking...';
      
      try {
        const resp = await fetch('/api/suggest-target');
        const data = await resp.json();
        
        if (data.query && data.location) {
          $('#query').value = data.query;
          $('#location').value = data.location;
        } else if (data.error) {
          console.error('Suggest error:', data.error);
          alert('Error: ' + data.error);
        }
      } catch (e) {
        console.error('Failed to fetch suggestion:', e);
      } finally {
        suggestBtn.disabled = false;
        suggestBtn.innerHTML = originalText;
      }
    });
  }

  // ── Search form ────────────────────────────────────────────

  searchForm.addEventListener('submit', async (e) => {
    e.preventDefault();

    const query = $('#query').value.trim();
    const location = $('#location').value.trim();
    const radius = parseInt($('#radius').value) || 5000;
    const maxResults = parseInt($('#maxResults').value) || 15;

    if (!query || !location) return;

    // Disable button
    searchBtn.disabled = true;
    searchBtn.innerHTML = `<span class="spinner"></span> Searching...`;

    // Show progress section
    progressSection.classList.remove('hidden');
    progressBar.style.width = '0%';
    eventFeed.innerHTML = '';

    // Reset stats
    updateStats({ found: 0, qualified: 0, emails_found: 0, approved: 0, sent: 0, good_website: 0, low_score: 0 });

    try {
      const resp = await fetch('/api/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query, location, radius, max_results: maxResults }),
      });
      const data = await resp.json();

      if (data.error) {
        progressStatus.textContent = `Error: ${data.error}`;
        searchBtn.disabled = false;
        searchBtn.textContent = 'Start Search';
        return;
      }

      currentRunId = data.run_id;
      connectWS(currentRunId);
      progressStatus.textContent = 'Connected. Waiting for results...';

    } catch (err) {
      progressStatus.textContent = `Connection error: ${err.message}`;
      searchBtn.disabled = false;
      searchBtn.textContent = 'Start Search';
    }
  });

  // ── Keyboard shortcuts ─────────────────────────────────────
  document.addEventListener('keydown', (e) => {
    if (!approvalModal.classList.contains('active')) return;

    if (e.key === 'Escape') closeModal();
  });

  // ── Init: load existing leads ──────────────────────────────
  loadLeads();

})();
