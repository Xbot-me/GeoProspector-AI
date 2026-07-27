(function() {
  const filterInput = document.getElementById('filterInput');
  const btnRefresh = document.getElementById('btnRefresh');
  const runsContainer = document.getElementById('runsContainer');
  const runsCount = document.getElementById('runsCount');
  const leadsSection = document.getElementById('leadsSection');
  const leadsTitle = document.getElementById('leadsTitle');
  const leadsContent = document.getElementById('leadsContent');
  const btnExportRunCsv = document.getElementById('btnExportRunCsv');
  const btnCloseLeads = document.getElementById('btnCloseLeads');

  let allRuns = [];
  let currentSelectedRunId = null;

  // ── Init ───────────────────────────────────────────────────
  fetchRuns();

  btnRefresh.addEventListener('click', () => {
    btnRefresh.textContent = '🔄 Loading...';
    fetchRuns().finally(() => {
      btnRefresh.textContent = '🔄 Refresh';
    });
  });

  filterInput.addEventListener('input', () => {
    renderRuns(allRuns);
  });

  btnCloseLeads.addEventListener('click', () => {
    leadsSection.classList.add('hidden');
  });

  btnExportRunCsv.addEventListener('click', () => {
    if (currentSelectedRunId) {
      window.location.href = `/api/runs/${currentSelectedRunId}/csv`;
    }
  });

  // ── Fetch Runs ─────────────────────────────────────────────
  async function fetchRuns() {
    try {
      const res = await fetch('/api/runs');
      allRuns = await res.json();
      renderRuns(allRuns);
    } catch (err) {
      runsContainer.innerHTML = `
        <div class="empty-state">
          <div class="empty-state__icon">❌</div>
          <div class="empty-state__text">Failed to load search history</div>
        </div>`;
    }
  }

  // ── Render Runs ────────────────────────────────────────────
  function renderRuns(runs) {
    const filterText = (filterInput.value || '').toLowerCase().trim();

    const filtered = runs.filter(r => {
      if (!filterText) return true;
      const q = (r.query || '').toLowerCase();
      const loc = (r.location || '').toLowerCase();
      const ip = (r.ip_address || '').toLowerCase();
      return q.includes(filterText) || loc.includes(filterText) || ip.includes(filterText);
    });

    runsCount.textContent = `${filtered.length} search run${filtered.length === 1 ? '' : 's'} recorded`;

    if (filtered.length === 0) {
      runsContainer.innerHTML = `
        <div class="empty-state">
          <div class="empty-state__icon">🔍</div>
          <div class="empty-state__text">No search runs match your filter</div>
        </div>`;
      return;
    }

function formatRunDate(dStr) {
  if (!dStr) return 'Recent';
  let d = new Date(dStr);
  if (isNaN(d.getTime()) && typeof dStr === 'string') {
    d = new Date(dStr.replace(' ', 'T'));
  }
  return isNaN(d.getTime()) ? 'Recent' : d.toLocaleString();
}

    runsContainer.innerHTML = filtered.map(r => {
      const dateStr = formatRunDate(r.created_at);
      const ip = r.ip_address || 'unknown';
      const statusCls = r.status === 'complete' ? 'approved' : (r.status === 'error' ? 'rejected' : 'pending');
      const statusLabel = r.status === 'complete' ? '✓ Completed' : (r.status === 'error' ? '✕ Failed' : '⏳ Running');

      return `
        <div class="run-card">
          <div class="run-card__info">
            <div class="run-card__title">
              <span>🔍 <strong>${esc(r.query)}</strong> in ${esc(r.location)}</span>
              <span class="quality-badge quality-badge--${statusCls}">${statusLabel}</span>
            </div>
            <div class="run-card__meta">
              <span class="ip-badge" title="Initiator IP Address">🌐 IP: ${esc(ip)}</span>
              <span>⚙️ Radius: ${r.radius || 5000}m | Max: ${r.max_results || 15}</span>
              <span>📊 Found: <strong style="color:var(--text-primary)">${r.result_count || 0}</strong> businesses</span>
              <span>🕒 ${dateStr}</span>
            </div>
          </div>
          <div class="run-card__actions">
            <button class="btn btn--primary btn--sm" onclick="window.__viewLeads('${esc(r.run_id)}', '${esc(r.query)}', '${esc(r.location)}', ${r.result_count || 0})">
              👁️ View Leads
            </button>
            <a href="/api/runs/${esc(r.run_id)}/csv" class="btn btn--skip btn--sm" style="text-decoration:none; display:inline-flex; align-items:center;" title="Download CSV">
              📥 CSV
            </a>
          </div>
        </div>
      `;
    }).join('');
  }

  // ── View Leads for Run ─────────────────────────────────────
  window.__viewLeads = async function(runId, query, location, count) {
    currentSelectedRunId = runId;
    leadsSection.classList.remove('hidden');
    leadsTitle.innerHTML = `Leads from: <strong>"${esc(query)}"</strong> in ${esc(location)} (${count} results)`;
    leadsContent.innerHTML = `
      <div class="empty-state" style="padding: 32px 0;">
        <div class="empty-state__icon">⏳</div>
        <div class="empty-state__text">Loading enriched business leads...</div>
      </div>`;

    leadsSection.scrollIntoView({ behavior: 'smooth', block: 'start' });

    try {
      const res = await fetch(`/api/runs/${runId}/leads`);
      const leads = await res.json();
      renderLeadsTable(leads);
    } catch (err) {
      leadsContent.innerHTML = `
        <div class="empty-state">
          <div class="empty-state__icon">❌</div>
          <div class="empty-state__text">Failed to load leads for this run</div>
        </div>`;
    }
  };

  // ── Render Leads Table ─────────────────────────────────────
  function renderLeadsTable(leads) {
    if (!leads || leads.length === 0) {
      leadsContent.innerHTML = `
        <div class="empty-state">
          <div class="empty-state__icon">📭</div>
          <div class="empty-state__text">No leads were saved for this search run</div>
        </div>`;
      return;
    }

    let rows = leads.map(l => {
      const websiteLink = l.website
        ? `<a href="${esc(l.website)}" target="_blank" style="color:var(--accent); text-decoration:none;" title="${esc(l.website)}">🌐 Visit</a>`
        : '<span style="color:var(--text-muted)">—</span>';

      const emailDisplay = l.email
        ? `<span class="leads-table__email" style="color: var(--text-accent); font-weight:500;">✉ ${esc(l.email)}</span>`
        : '<span style="color:var(--text-muted)">—</span>';

      let socialLinks = '';
      if (l.facebook_url) {
        socialLinks += `<a href="${esc(l.facebook_url)}" target="_blank" class="social-link">📘 FB</a>`;
      }
      if (l.instagram_url) {
        socialLinks += `<a href="${esc(l.instagram_url)}" target="_blank" class="social-link">📷 IG</a>`;
      }
      if (!socialLinks) {
        socialLinks = '<span style="color:var(--text-muted)">—</span>';
      }

      const ratingStr = l.rating
        ? `★ ${l.rating} <span style="color:var(--text-muted); font-size:0.75rem;">(${l.review_count || 0})</span>`
        : '<span style="color:var(--text-muted)">—</span>';

      const ownerStr = l.owner_name
        ? `<span style="color:var(--text-primary)">👤 ${esc(l.owner_name)}</span>`
        : '<span style="color:var(--text-muted)">—</span>';

      return `
      <tr>
        <td>
          <div class="leads-table__name">${esc(l.name || '')}</div>
          <div style="font-size:0.75rem; color:var(--text-muted);">${esc(l.category || '')}</div>
        </td>
        <td>${scoreBadge(l.lead_score)}</td>
        <td>
          <div style="margin-bottom: 2px;">${qualityBadge(l.website_quality)}</div>
          <div style="font-size:0.8rem;">${websiteLink}</div>
        </td>
        <td>${emailDisplay}</td>
        <td>${socialLinks}</td>
        <td>
          <div>${ownerStr}</div>
          <div style="font-size:0.75rem; color:var(--text-secondary); margin-top:2px;">📞 ${esc(l.phone || '—')}</div>
        </td>
        <td>${ratingStr}</td>
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
              <th>Email Address</th>
              <th>Social Profiles</th>
              <th>Contact / Phone</th>
              <th>Rating</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>`;
  }

  // ── Helpers ────────────────────────────────────────────────
  function scoreBadge(score) {
    if (score == null) return '<span style="color:var(--text-muted)">—</span>';
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
      none: 'No Site', dead: 'Dead Site', social_only: 'Social Only',
      outdated: 'Outdated Site', good: 'Good Site',
    };
    const cls = map[quality] || 'none';
    return `<span class="quality-badge quality-badge--${cls}">${labels[quality] || quality}</span>`;
  }

  function esc(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }
})();
