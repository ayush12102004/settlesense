/* SettleSense Dashboard — app.js
   Fetches data from the API and renders the dashboard.
   All currency/number formatting in one utility function. */

// --- Formatting utilities ---------------------------------------------------

function formatCurrency(amount) {
  if (amount == null) return '—';
  const abs = Math.abs(amount);
  const formatted = abs.toLocaleString('en-IN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  const sign = amount < 0 ? '-' : '';
  return `${sign}\u20B9${formatted}`;
}

function formatPercent(value) {
  if (value == null) return '—';
  return `${(value * 100).toFixed(1)}%`;
}

function formatReasonCode(code) {
  const labels = {
    NO_CANDIDATE_IN_WINDOW: 'No candidate in window',
    AMOUNT_MISMATCH_BEYOND_TOLERANCE: 'Amount mismatch',
    SPLIT_SETTLEMENT_UNRESOLVED: 'Split settlement unresolved',
    DUPLICATE_CANDIDATES_AMBIGUOUS: 'Duplicate candidates',
    PENDING_NOT_YET_SETTLED: 'Pending settlement',
    LOW_CONFIDENCE_LLM_MATCH: 'Low confidence AI match',
  };
  return labels[code] || code;
}

function reasonChipClass(code) {
  return code === 'PENDING_NOT_YET_SETTLED' ? 'pending' : 'exception';
}

// --- Data fetching ----------------------------------------------------------

let DATA = null;

async function loadData() {
  try {
    const resp = await fetch('/api/dashboard');
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    DATA = await resp.json();
    render();
  } catch (err) {
    document.getElementById('match-sub').textContent =
      `Failed to load data: ${err.message}. Run "python src/main.py --serve" first.`;
  }
}

// --- Rendering --------------------------------------------------------------

function render() {
  renderHero();
  renderCashPosition();
  renderExceptions();
  renderMetrics();
  renderChart();
}

function renderHero() {
  const s = DATA.summary;
  const rate = s.match_rate;
  const el = document.getElementById('match-rate');
  el.textContent = formatPercent(rate);

  const matched = s.total_matched;
  const total = s.total_records - s.pending_count;
  document.getElementById('match-sub').textContent =
    `${matched} of ${total} records reconciled automatically`;

  // Layer breakdown
  const layers = s.by_layer || {};
  const exceptions = s.total_exceptions - s.pending_count;
  const pending = s.pending_count;
  const layerRow = document.getElementById('layer-row');
  layerRow.innerHTML = '';

  const items = [
    { class: 'exact', count: layers.exact || 0, label: 'exact' },
    { class: 'tolerant', count: layers.tolerant || 0, label: 'tolerant' },
    { class: 'llm', count: layers.llm_assisted || 0, label: 'AI-assisted' },
    { class: 'exception', count: exceptions, label: 'exceptions' },
    { class: 'pending', count: pending, label: 'pending' },
  ];

  items.forEach(item => {
    if (item.count === 0) return;
    const div = document.createElement('div');
    div.className = 'layer-item';
    div.innerHTML = `
      <span class="layer-dot ${item.class}"></span>
      <span class="layer-count">${item.count}</span>
      <span class="layer-label">${item.label}</span>
    `;
    layerRow.appendChild(div);
  });
}

function renderCashPosition() {
  const cash = DATA.cash_position;
  document.getElementById('cash-reconciled').textContent =
    formatCurrency(cash.reconciled_inflow);
  document.getElementById('cash-pending').textContent =
    formatCurrency(cash.pending_total);
}

function renderExceptions() {
  const exceptions = DATA.exceptions || [];
  const real = exceptions.filter(e => e.reason_code !== 'PENDING_NOT_YET_SETTLED');
  const pending = exceptions.filter(e => e.reason_code === 'PENDING_NOT_YET_SETTLED');

  document.getElementById('exception-badge').textContent = real.length;
  document.getElementById('pending-badge').textContent = pending.length;

  const tbody = document.getElementById('exceptions-body');
  tbody.innerHTML = '';

  // Show real exceptions first, then pending
  const all = [...real, ...pending];
  all.forEach((exc, idx) => {
    const tr = document.createElement('tr');
    tr.tabIndex = 0;
    tr.setAttribute('role', 'button');
    tr.setAttribute('aria-label', `View audit trail for ${exc.gateway_order_ids.join(', ') || exc.ledger_order_ids.join(', ')}`);

    const orderRef = exc.gateway_order_ids.length
      ? exc.gateway_order_ids.join(', ')
      : exc.ledger_order_ids.join(', ');

    const chipClass = reasonChipClass(exc.reason_code);

    tr.innerHTML = `
      <td>
        <div class="mono">${escapeHtml(orderRef)}</div>
        ${exc.gateway_payment_ids.length ? `<div class="caption mono">${escapeHtml(exc.gateway_payment_ids[0])}</div>` : ''}
      </td>
      <td class="tabular">${exc.bank_amount ? formatCurrency(exc.bank_amount) : '—'}</td>
      <td>
        <span class="reason-chip ${chipClass}">${formatReasonCode(exc.reason_code)}</span>
        <div class="caption" style="margin-top:4px">${escapeHtml(exc.reason)}</div>
      </td>
      <td>
        <div class="suggested">${escapeHtml(exc.suggested_step)}</div>
      </td>
      <td class="arrow-icon">›</td>
    `;

    tr.addEventListener('click', () => openDrawer(exc.trace_id));
    tr.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        openDrawer(exc.trace_id);
      }
    });

    tbody.appendChild(tr);
  });
}

function renderMetrics() {
  const m = DATA.metrics;
  const bar = document.getElementById('metrics-bar');
  bar.innerHTML = '';

  const items = [
    { value: m.total_records_processed, label: 'Records processed' },
    { value: formatPercent(m.with_llm?.summary?.match_rate), label: 'Match rate (with AI)' },
    { value: formatPercent(m.without_llm?.summary?.match_rate), label: 'Match rate (without AI)' },
    { value: `+${formatPercent(m.ablation?.match_rate_lift)}`, label: 'AI contribution' },
    { value: formatPercent(m.with_llm?.evaluation?.auto_match_precision), label: 'Auto-match precision' },
    { value: formatPercent(m.with_llm?.evaluation?.reason_code_coverage), label: 'Reason code coverage' },
  ];

  items.forEach(item => {
    const div = document.createElement('div');
    div.className = 'metric-item';
    div.innerHTML = `
      <span class="metric-value">${item.value}</span>
      <span class="metric-label">${item.label}</span>
    `;
    bar.appendChild(div);
  });
}

function renderChart() {
  const canvas = document.getElementById('projection-chart');
  const ctx = canvas.getContext('2d');
  const daily = DATA.cash_position.daily_projection || [];

  if (!daily.length) return;

  // Set canvas resolution
  const rect = canvas.parentElement.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  ctx.scale(dpr, dpr);
  const W = rect.width;
  const H = rect.height;

  // Data
  const values = daily.map(d => d.cumulative_position);
  const min = Math.min(...values) * 0.98;
  const max = Math.max(...values) * 1.02;
  const range = max - min || 1;

  const padding = { left: 80, right: 20, top: 16, bottom: 32 };
  const plotW = W - padding.left - padding.right;
  const plotH = H - padding.top - padding.bottom;

  // Grid lines
  ctx.strokeStyle = '#E5E5E7';
  ctx.lineWidth = 0.5;
  for (let i = 0; i <= 4; i++) {
    const y = padding.top + (plotH * i / 4);
    ctx.beginPath();
    ctx.moveTo(padding.left, y);
    ctx.lineTo(W - padding.right, y);
    ctx.stroke();

    // Y-axis labels
    const val = max - (range * i / 4);
    ctx.fillStyle = '#6E6E73';
    ctx.font = '11px -apple-system, system-ui, sans-serif';
    ctx.textAlign = 'right';
    ctx.fillText(formatCompact(val), padding.left - 8, y + 4);
  }

  // X-axis labels
  ctx.fillStyle = '#6E6E73';
  ctx.font = '11px -apple-system, system-ui, sans-serif';
  ctx.textAlign = 'center';
  daily.forEach((d, i) => {
    if (i % 3 === 0 || i === daily.length - 1) {
      const x = padding.left + (plotW * i / (daily.length - 1));
      ctx.fillText(d.day_label, x, H - 8);
    }
  });

  // Today's reconciled position (solid line, first point)
  const todayX = padding.left;
  const todayY = padding.top + plotH * (1 - (values[0] - min) / range);

  // Dotted line for "today" marker
  ctx.strokeStyle = '#E5E5E7';
  ctx.lineWidth = 1;
  ctx.setLineDash([4, 4]);
  ctx.beginPath();
  ctx.moveTo(todayX, padding.top);
  ctx.lineTo(todayX, H - padding.bottom);
  ctx.stroke();
  ctx.setLineDash([]);

  // Projection line
  ctx.strokeStyle = '#3A5DFF';
  ctx.lineWidth = 2;
  ctx.beginPath();
  daily.forEach((d, i) => {
    const x = padding.left + (plotW * i / (daily.length - 1));
    const y = padding.top + plotH * (1 - (values[i] - min) / range);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();

  // Dots at each data point
  daily.forEach((d, i) => {
    const x = padding.left + (plotW * i / (daily.length - 1));
    const y = padding.top + plotH * (1 - (values[i] - min) / range);
    ctx.beginPath();
    ctx.arc(x, y, d.is_projected ? 3 : 5, 0, Math.PI * 2);
    ctx.fillStyle = d.is_projected ? '#3A5DFF' : '#1F8A5F';
    ctx.fill();
  });
}

function formatCompact(n) {
  if (n >= 100000) return `₹${(n / 100000).toFixed(1)}L`;
  if (n >= 1000) return `₹${(n / 1000).toFixed(0)}K`;
  return formatCurrency(n);
}

// --- Drawer -----------------------------------------------------------------

function openDrawer(traceId) {
  const record = (DATA.audit_trail || []).find(r => r.trace_id === traceId);
  if (!record) return;

  const content = document.getElementById('drawer-content');
  content.innerHTML = renderDrawerContent(record);

  document.getElementById('drawer-overlay').classList.add('open');
  document.getElementById('audit-drawer').classList.add('open');

  // Focus trap
  document.getElementById('drawer-close').focus();
}

function closeDrawer() {
  document.getElementById('drawer-overlay').classList.remove('open');
  document.getElementById('audit-drawer').classList.remove('open');
}

function renderDrawerContent(r) {
  const statusClass = r.status === 'matched' ? 'matched' : (
    r.reason_code === 'PENDING_NOT_YET_SETTLED' ? 'pending' : 'exception'
  );

  return `
    <div class="drawer-section">
      <h3>Decision</h3>
      ${field('Trace ID', `<span class="mono">${escapeHtml(r.trace_id)}</span>`)}
      ${field('Status', `<span class="status-chip ${statusClass}">${r.status}</span>`)}
      ${field('Layer', r.layer)}
      ${r.confidence != null ? field('Confidence', formatPercent(r.confidence)) : ''}
      ${field('Reason', escapeHtml(r.reason))}
      ${r.suggested_step ? field('Suggested step', escapeHtml(r.suggested_step)) : ''}
    </div>

    <div class="drawer-section">
      <h3>Bank statement</h3>
      ${field('Date', r.bank_date || '—')}
      ${field('Narration', `<span class="mono" style="font-size:12px">${escapeHtml(r.bank_narration || '—')}</span>`)}
      ${field('Amount', `<span class="tabular">${formatCurrency(r.bank_amount)}</span>`)}
      ${field('Extracted UTR', r.bank_utr ? `<span class="mono">${escapeHtml(r.bank_utr)}</span>` : '—')}
    </div>

    <div class="drawer-section">
      <h3>Gateway settlement</h3>
      ${field('Order ID(s)', (r.gateway_order_ids || []).map(id => `<span class="mono">${escapeHtml(id)}</span>`).join(', ') || '—')}
      ${field('Payment ID(s)', (r.gateway_payment_ids || []).map(id => `<span class="mono" style="font-size:12px">${escapeHtml(id)}</span>`).join(', ') || '—')}
      ${field('UTR(s)', (r.gateway_utrs || []).map(u => `<span class="mono">${escapeHtml(u)}</span>`).join(', ') || '—')}
      ${field('Net amount(s)', (r.gateway_net_amounts || []).map(a => `<span class="tabular">${formatCurrency(a)}</span>`).join(', ') || '—')}
      ${r.gateway_total_net != null ? field('Total net', `<span class="tabular">${formatCurrency(r.gateway_total_net)}</span>`) : ''}
    </div>

    <div class="drawer-section">
      <h3>Internal ledger</h3>
      ${field('Order ID(s)', (r.ledger_order_ids || []).join(', ') || '—')}
      ${field('Expected amount(s)', (r.ledger_expected_amounts || []).map(a => `<span class="tabular">${formatCurrency(a)}</span>`).join(', ') || '—')}
    </div>

    ${r.amount_diff != null ? `
    <div class="drawer-section">
      <h3>Verification</h3>
      ${field('Amount difference', `<span class="tabular">${formatCurrency(r.amount_diff)}</span>`)}
    </div>
    ` : ''}

    <div class="drawer-section">
      <h3>Metadata</h3>
      ${field('Timestamp', r.timestamp || '—')}
      ${field('Reason code', r.reason_code ? `<span class="mono">${escapeHtml(r.reason_code)}</span>` : '—')}
    </div>
  `;
}

function field(label, value) {
  return `
    <div class="drawer-field">
      <span class="field-label">${label}</span>
      <span class="field-value">${value}</span>
    </div>
  `;
}

function escapeHtml(str) {
  if (!str) return '';
  const div = document.createElement('div');
  div.textContent = String(str);
  return div.innerHTML;
}

// --- Event listeners --------------------------------------------------------

document.getElementById('drawer-overlay').addEventListener('click', closeDrawer);
document.getElementById('drawer-close').addEventListener('click', closeDrawer);

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') closeDrawer();
});

document.getElementById('export-json-btn').addEventListener('click', () => {
  window.open('/api/audit/export?format=json', '_blank');
});

// --- Init -------------------------------------------------------------------

loadData();
