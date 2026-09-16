/**
 * Alibaba Cloud DirectMail Automation Agent - Frontend SPA Logic
 * Complete 11-Section Enterprise Dashboard + Smart Agent Console
 */

// Global Application State
const state = {
  currentView: 'overview',
  activeRegion: 'singapore',
  activeSendRegion: 'singapore',
  activeBulkRegion: 'singapore',
  activeSchedRegion: 'singapore',
  regions: [],
  verifiedSenders: {}, // regionKey -> [senders]
  cachedTemplates: [],
  localTemplates: [],
  templateSubTab: 'local',
  cachedDomains: [],
  recipientsPool: [],
  selectedRecipientIds: new Set(),
  trackingEvents: [],
  deliveryRange: '7d',
  historyPage: 0,
  historyLimit: 15,
  historyTotal: 0,
  bulkValidRecipients: [],
  bulkInvalidRecipients: [],
  bulkExcludedRecipients: new Set(),
  auditLogs: [],
  settings: {},
  pollTimer: null,
  pendingDeleteAction: null
};

// --- INITIALIZATION ---

document.addEventListener('DOMContentLoaded', async () => {
  initIcons();
  await loadSettings();
  await loadHealth();
  await loadRegions();
  initScheduleDefaults();

  // Polling every 8 seconds for background job stats
  state.pollTimer = setInterval(pollBackgroundUpdates, 8000);

  // Hash-based routing
  window.addEventListener('hashchange', handleHashRoute);
  handleHashRoute();

  // Initial data load for default region
  await loadOverviewData();
});

function initIcons() {
  if (window.lucide) {
    window.lucide.createIcons();
  }
}

// --- ROUTING & NAVIGATION ---

function handleHashRoute() {
  const hash = window.location.hash.replace('#', '') || 'overview';
  navigateTo(hash);
}

function navigateTo(viewName) {
  // Aliases for seamless backward compatibility
  if (viewName === 'send') {
    navigateTo('tasks');
    setTasksTab('send');
    return;
  }
  if (viewName === 'bulk') {
    navigateTo('tasks');
    setTasksTab('bulk');
    return;
  }
  if (viewName === 'schedule') {
    navigateTo('scheduling');
    setSchedTab('new');
    return;
  }
  if (viewName === 'scheduled') {
    navigateTo('scheduling');
    setSchedTab('queue');
    return;
  }
  if (viewName === 'history') {
    navigateTo('tasks');
    setTasksTab('history');
    return;
  }
  if (viewName === 'regions') {
    navigateTo('domains');
    return;
  }

  const validViews = [
    'overview', 'domains', 'senders', 'templates', 'recipients', 'tags',
    'tasks', 'scheduling', 'delivery', 'tracking', 'analysis', 'audit', 'settings'
  ];
  const target = validViews.includes(viewName) ? viewName : 'overview';
  state.currentView = target;

  // Update navigation styling
  document.querySelectorAll('.nav-item').forEach(el => {
    el.classList.remove('bg-slate-800', 'text-white');
    el.classList.add('text-slate-300');
  });
  const activeNav = document.getElementById(`nav-${target}`);
  if (activeNav) {
    activeNav.classList.add('bg-slate-800', 'text-white');
    activeNav.classList.remove('text-slate-300');
  }

  // Switch view section visibility
  document.querySelectorAll('.view-section').forEach(sec => sec.classList.add('hidden'));
  const targetSec = document.getElementById(`view-${target}`);
  if (targetSec) {
    targetSec.classList.remove('hidden');
  }

  // View-specific data triggers
  if (target === 'overview') loadOverviewData();
  if (target === 'domains') loadDomainsTable();
  if (target === 'senders') loadSendersTable();
  if (target === 'templates') {
    if (state.templateSubTab === 'local') {
      loadLocalTemplatesTable();
    } else {
      loadTemplatesTable();
    }
  }
  if (target === 'recipients') loadRecipientsTable();
  if (target === 'tags') loadEmailTagsTable();
  if (target === 'tasks') {
    loadTemplatesDropdown();
    populateTagDropdowns();
    loadAlibabaTasksTable();
    loadHistoryJobs();
  }
  if (target === 'scheduling') {
    loadScheduledJobs();
    loadScheduledCampaignsTable();
  }
  if (target === 'delivery') {
    populateTagDropdowns();
    loadDeliveryStats();
  }
  if (target === 'tracking') loadTrackingFeed();
  if (target === 'analysis') loadAnalysisView();
  if (target === 'audit') loadAuditLogsTable();
  if (target === 'settings') loadSettings();

  initIcons();
}

// --- GLOBAL REGION SWITCHER ---

function setGlobalRegion(regionKey) {
  state.activeRegion = regionKey;
  state.activeSendRegion = regionKey;
  state.activeBulkRegion = regionKey;
  state.activeSchedRegion = regionKey;

  // Update top button styles
  ['singapore', 'germany', 'united_states'].forEach(k => {
    const btn = document.getElementById(`global-reg-${k}`);
    if (btn) {
      if (k === regionKey) {
        btn.className = 'px-2.5 py-1 rounded-lg font-medium text-white bg-brand shadow transition flex items-center gap-1';
      } else {
        btn.className = 'px-2.5 py-1 rounded-lg font-medium text-slate-400 hover:text-white transition flex items-center gap-1';
      }
    }
  });

  // Sync Send and Bulk region pills
  selectSendRegion(regionKey);
  selectBulkRegion(regionKey);

  // Update Overview Pill
  const regObj = state.regions.find(r => r.key === regionKey);
  const pill = document.getElementById('overview-region-pill');
  if (pill && regObj) {
    pill.textContent = `${regObj.display_name} (${regObj.region_id})`;
  }

  // Refresh active view
  navigateTo(state.currentView);
  showToast(`Active region set to ${regObj ? regObj.display_name : regionKey}`, 'info');
}

// --- API CLIENT & DYNAMIC HOST SUPPORT (Netlify / Localhost / Remote) ---

const DEFAULT_TUNNEL_URL = 'https://f4ece397dec203a9-106-195-71-196.serveousercontent.com';

function getApiBaseUrl() {
  const urlParam = new URLSearchParams(window.location.search).get('api');
  if (urlParam) {
    localStorage.setItem('custom_api_base_url', urlParam);
    return urlParam.replace(/\/+$/, '');
  }
  const stored = localStorage.getItem('custom_api_base_url');
  if (stored) return stored.replace(/\/+$/, '');

  // If running on Netlify or remote static hosting without custom config, default to active live tunnel
  const host = window.location.hostname;
  if (host.includes('netlify.app') || host.includes('web.app') || host.includes('github.io') || host.includes('pages.dev')) {
    return DEFAULT_TUNNEL_URL;
  }

  // Default to relative if running on same host or localhost
  return '';
}

async function apiFetch(endpoint, options = {}) {
  const base = getApiBaseUrl();
  const fullUrl = endpoint.startsWith('http') 
    ? endpoint 
    : (base ? `${base}${endpoint}` : endpoint);

  try {
    const res = await fetch(fullUrl, {
      headers: {
        'Content-Type': 'application/json',
        ...(options.headers || {})
      },
      ...options
    });

    const text = await res.text();
    let data;
    try {
      data = JSON.parse(text);
    } catch (parseErr) {
      // Netlify SPA fallback or static server returned HTML index page instead of JSON API response
      if (text.trim().startsWith('<')) {
        updateBackendStatusUI(false, 'Received HTML');
        const helpMessage = `Backend API disconnected. Netlify returned the HTML app shell instead of JSON data for ${endpoint}.\n\nClick the "Backend Settings" button in the top bar to connect to your live HTTPS backend tunnel (${DEFAULT_TUNNEL_URL}).`;
        console.error(helpMessage, text.substring(0, 300));
        throw new Error(helpMessage);
      }
      throw new Error(`Invalid JSON returned from ${endpoint}: ${text.substring(0, 100)}`);
    }

    if (!res.ok) {
      const errMsg = data.detail || data.message || `Request failed with status ${res.status}`;
      throw new Error(errMsg);
    }

    updateBackendStatusUI(true, 'Connected');
    return data;
  } catch (err) {
    console.error(`API Error [${endpoint}]:`, err);
    if (!err.message.includes('Backend API disconnected')) {
      updateBackendStatusUI(false, 'Error');
    }
    throw err;
  }
}

// --- BACKEND API CONNECTION CONTROLLER ---

function updateBackendStatusUI(isConnected, detailText) {
  const dot = document.getElementById('backend-status-dot');
  const text = document.getElementById('backend-status-text');
  if (!dot || !text) return;

  if (isConnected) {
    dot.className = 'w-2 h-2 rounded-full bg-emerald-400 animate-pulse';
    text.textContent = 'API: Live';
    text.className = 'hidden md:inline text-emerald-400 font-medium';
  } else {
    dot.className = 'w-2 h-2 rounded-full bg-rose-500 animate-ping';
    text.textContent = detailText ? `API: ${detailText}` : 'API: Disconnected';
    text.className = 'hidden md:inline text-rose-400 font-medium';
  }
}

function openBackendModal() {
  const current = getApiBaseUrl();
  const input = document.getElementById('input-backend-url');
  if (input) {
    input.value = current;
  }
  const statusEl = document.getElementById('backend-test-status');
  if (statusEl) {
    statusEl.classList.add('hidden');
    statusEl.innerHTML = '';
  }
  document.getElementById('backend-connect-modal')?.classList.remove('hidden');
  initIcons();
}

function closeBackendModal() {
  document.getElementById('backend-connect-modal')?.classList.add('hidden');
}

function setBackendUrlPreset(url) {
  const input = document.getElementById('input-backend-url');
  if (input) {
    input.value = url;
  }
}

async function testBackendConnection() {
  const input = document.getElementById('input-backend-url');
  const statusEl = document.getElementById('backend-test-status');
  const btn = document.getElementById('btn-test-backend');
  if (!input || !statusEl) return;

  const targetUrl = (input.value.trim() || '').replace(/\/+$/, '');
  const testEndpoint = targetUrl ? `${targetUrl}/api/health` : '/api/health';

  statusEl.classList.remove('hidden');
  statusEl.className = 'p-3 rounded-xl bg-slate-900 border border-slate-700 text-xs text-slate-300 flex items-center gap-2';
  statusEl.innerHTML = '<i data-lucide="loader-2" class="w-4 h-4 animate-spin text-brand"></i><span>Pinging backend at ' + escapeHtml(testEndpoint) + '...</span>';
  initIcons();

  if (btn) btn.disabled = true;

  try {
    const res = await fetch(testEndpoint, { headers: { 'Content-Type': 'application/json' } });
    const text = await res.text();
    let data;
    try { data = JSON.parse(text); } catch { }

    if (res.ok && data && data.status === 'healthy') {
      statusEl.className = 'p-3 rounded-xl bg-emerald-950/70 border border-emerald-500/50 text-xs text-emerald-300 flex items-start gap-2';
      statusEl.innerHTML = `
        <i data-lucide="check-circle-2" class="w-4 h-4 text-emerald-400 shrink-0 mt-0.5"></i>
        <div>
          <strong class="block font-bold">Connection Successful!</strong>
          <span>Backend responded healthy. Singapore DirectMail live link active.</span>
        </div>
      `;
    } else {
      statusEl.className = 'p-3 rounded-xl bg-rose-950/70 border border-rose-500/50 text-xs text-rose-300 flex items-start gap-2';
      statusEl.innerHTML = `
        <i data-lucide="alert-triangle" class="w-4 h-4 text-rose-400 shrink-0 mt-0.5"></i>
        <div>
          <strong class="block font-bold">Connection Failed (${res.status})</strong>
          <span class="text-[11px] block mt-0.5">${text.trim().startsWith('<') ? 'Endpoint returned HTML instead of JSON. Ensure your tunnel or server is active.' : escapeHtml(text.substring(0, 150))}</span>
        </div>
      `;
    }
  } catch (err) {
    statusEl.className = 'p-3 rounded-xl bg-rose-950/70 border border-rose-500/50 text-xs text-rose-300 flex items-start gap-2';
    statusEl.innerHTML = `
      <i data-lucide="wifi-off" class="w-4 h-4 text-rose-400 shrink-0 mt-0.5"></i>
      <div>
        <strong class="block font-bold">Unreachable</strong>
        <span class="text-[11px] block mt-0.5">${escapeHtml(err.message)}</span>
      </div>
    `;
  } finally {
    if (btn) btn.disabled = false;
    initIcons();
  }
}

async function saveBackendUrl() {
  const input = document.getElementById('input-backend-url');
  if (!input) return;
  const targetUrl = input.value.trim().replace(/\/+$/, '');

  if (targetUrl) {
    localStorage.setItem('custom_api_base_url', targetUrl);
  } else {
    localStorage.removeItem('custom_api_base_url');
  }

  showToast('Backend API URL saved! Re-testing connection...', 'info');
  closeBackendModal();

  try {
    await loadHealth();
    await refreshData();
    showToast('Connected to live backend successfully!', 'success');
  } catch (err) {
    showToast('Saved, but backend check failed: ' + err.message, 'error');
  }
}

// --- SYSTEM HEALTH & REGIONS ---

async function loadHealth() {
  try {
    const data = await apiFetch('/api/health');
    const pulse = document.getElementById('scheduler-pulse');
    const statusText = document.getElementById('scheduler-status-text');
    const testBadge = document.getElementById('global-test-badge');

    if (pulse && statusText) {
      if (data.scheduler_running) {
        pulse.className = 'w-2 h-2 rounded-full bg-emerald-500 animate-pulse';
        statusText.textContent = 'Active';
        statusText.className = 'text-emerald-400 font-medium';
      } else {
        pulse.className = 'w-2 h-2 rounded-full bg-rose-500';
        statusText.textContent = 'Stopped';
        statusText.className = 'text-rose-400 font-medium';
      }
    }

    if (testBadge) {
      if (data.test_mode) {
        testBadge.textContent = 'Test Sandbox';
        testBadge.className = 'px-2 py-0.5 text-[10px] font-semibold rounded bg-amber-500/20 text-amber-300 border border-amber-500/30';
      } else {
        testBadge.textContent = 'Live DirectMail';
        testBadge.className = 'px-2 py-0.5 text-[10px] font-semibold rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/30';
      }
    }
  } catch (e) {
    console.warn('Health check failed', e);
  }
}

async function loadRegions() {
  try {
    const data = await apiFetch('/api/regions');
    state.regions = data.regions || [];
    state.regions.forEach(r => {
      state.verifiedSenders[r.key] = r.verified_senders || [];
    });
    updateSendRegionUI(state.activeSendRegion);
    updateBulkRegionUI(state.activeBulkRegion);
    updateSchedSenders();
  } catch (err) {
    console.warn('Failed to load regions:', err);
  }
}

async function loadSettings() {
  try {
    const data = await apiFetch('/api/settings');
    state.settings = data.settings || {};
    
    const testMode = state.settings.test_mode === 'true';
    const testCheck = document.getElementById('setting-test-mode');
    if (testCheck) testCheck.checked = testMode;
    const rateEl = document.getElementById('setting-rate-limit');
    if (rateEl) rateEl.value = state.settings.rate_limit_qps || '5.0';
    const retriesEl = document.getElementById('setting-max-retries');
    if (retriesEl) retriesEl.value = state.settings.max_retries || '3';
    if (state.settings.default_timezone) {
      const tzEl = document.getElementById('setting-default-timezone');
      if (tzEl) tzEl.value = state.settings.default_timezone;
      const dispTz = document.getElementById('display-default-tz');
      if (dispTz) dispTz.textContent = state.settings.default_timezone;
      const schedTz = document.getElementById('sched-timezone');
      if (schedTz) schedTz.value = state.settings.default_timezone;
    }
  } catch (err) {
    console.warn('Could not load settings', err);
  }
}

async function pollBackgroundUpdates() {
  try {
    const sched = await apiFetch('/api/jobs?status=scheduled&limit=1');
    const badge = document.getElementById('badge-scheduled-count');
    if (badge) badge.textContent = sched.total || 0;
  } catch (e) {}
}

async function refreshData() {
  await loadHealth();
  await loadRegions();
  await syncLiveFromAlibaba(state.activeRegion);
  navigateTo(state.currentView);
  showToast('Refreshed data from Alibaba Cloud DirectMail', 'info');
}

// --- 1. OVERVIEW VIEW CONTROLLER ---

async function loadOverviewData() {
  const regKey = state.activeRegion;
  try {
    // 1. Account Summary
    const summaryRes = await apiFetch(`/api/account-summary/${regKey}`);
    const sumData = summaryRes.data || {};
    if (sumData.success) {
      const dailyQ = sumData.DailyQuota || 0;
      const monthQ = sumData.MonthQuota || 0;
      const level = sumData.QuotaLevel || 0;
      const maxLevel = sumData.MaxQuotaLevel || 10;
      const channel = sumData.IpChannelType || 'normal';
      const domainsCount = sumData.Domains || 0;
      const mailCount = sumData.MailAddresses || 0;
      const tplsCount = sumData.Templates || 0;

      document.getElementById('metric-daily-quota').textContent = dailyQ.toLocaleString();
      document.getElementById('metric-month-quota').textContent = monthQ.toLocaleString();
      document.getElementById('metric-quota-level').textContent = `${level} / ${maxLevel}`;
      document.getElementById('metric-channel-type').textContent = channel;
      document.getElementById('metric-domains-count').textContent = domainsCount;
      document.getElementById('metric-senders-count').textContent = mailCount;
      
      const badgeDom = document.getElementById('badge-domains-count');
      if (badgeDom) badgeDom.textContent = domainsCount;
      const badgeSend = document.getElementById('badge-senders-count');
      if (badgeSend) badgeSend.textContent = mailCount;
      const badgeTpl = document.getElementById('badge-templates-count');
      if (badgeTpl) badgeTpl.textContent = tplsCount;
      const quickQuota = document.getElementById('display-quota-quick');
      if (quickQuota) quickQuota.textContent = `${dailyQ.toLocaleString()}/d`;

      // Quota Level bar
      const barDaily = document.getElementById('metric-daily-bar');
      if (barDaily) barDaily.style.width = `${Math.min(100, Math.max(5, (level / maxLevel) * 100))}%`;
    }

    // 2. 7-Day Performance Strip
    const delivRes = await apiFetch(`/api/delivery-stats/${regKey}?range=7d`);
    const aggr = delivRes.aggregate || {};
    document.getElementById('overview-stat-sent').textContent = (aggr.total_requests || 0).toLocaleString();
    document.getElementById('overview-stat-rate').textContent = `${aggr.delivery_rate || 100}%`;
    document.getElementById('overview-stat-failed').textContent = (aggr.total_failed || 0).toLocaleString();
    document.getElementById('overview-stat-bounced').textContent = (aggr.total_unavailable || 0).toLocaleString();

    // 3. Batch Tasks & Dispatches
    loadOverviewTasks();
    loadOverviewActivity();
  } catch (err) {
    console.warn('Error loading overview data:', err);
  }
}

async function loadOverviewTasks() {
  const container = document.getElementById('overview-dm-tasks-list');
  if (!container) return;
  try {
    const res = await apiFetch(`/api/dm-tasks/${state.activeRegion}?page_size=5`);
    const tasks = res.tasks || [];
    if (tasks.length === 0) {
      container.innerHTML = `<div class="text-slate-500 italic py-4 text-center">No recent Alibaba Cloud DirectMail batch tasks recorded.</div>`;
      return;
    }
    let html = '';
    tasks.slice(0, 5).forEach(t => {
      html += `
        <div class="flex items-center justify-between p-2.5 rounded-xl bg-slate-900/60 border border-slate-800 text-xs">
          <div class="space-y-0.5">
            <span class="font-mono font-semibold text-white block">${escapeHtml(t.TemplateName || 'DirectMail Task')}</span>
            <span class="text-[11px] text-slate-400">List: <b class="text-slate-300 font-mono">${escapeHtml(t.ReceiversName || 'N/A')}</b></span>
          </div>
          <div class="text-right">
            <span class="px-2 py-0.5 rounded text-[10px] font-mono ${t.TaskStatus === 1 ? 'bg-emerald-500/20 text-emerald-300' : 'bg-blue-500/20 text-blue-300'}">Status: ${t.TaskStatus}</span>
            <span class="block text-[10px] text-slate-500 font-mono mt-0.5">${formatTimestamp(t.UtcCreateTime)}</span>
          </div>
        </div>
      `;
    });
    container.innerHTML = html;
  } catch (err) {
    container.innerHTML = `<div class="text-slate-500 italic py-3 text-center">Could not query DirectMail batch tasks.</div>`;
  }
}

async function loadOverviewActivity() {
  const container = document.getElementById('overview-recent-activity');
  if (!container) return;
  try {
    const res = await apiFetch(`/api/jobs?limit=5`);
    const items = res.items || [];
    if (items.length === 0) {
      container.innerHTML = `<div class="text-slate-500 italic py-4 text-center">No recent local dispatches recorded.</div>`;
      return;
    }
    let html = '';
    items.forEach(j => {
      html += `
        <div class="flex items-center justify-between p-2.5 rounded-xl bg-slate-900/60 border border-slate-800 text-xs">
          <div class="space-y-0.5">
            <span class="font-medium text-white block truncate max-w-[200px]">${escapeHtml(j.subject || 'No Subject')}</span>
            <span class="text-[11px] text-slate-400">To: <b class="text-slate-300 font-mono">${escapeHtml(j.recipient)}</b></span>
          </div>
          <div class="text-right">
            <span class="px-2 py-0.5 rounded text-[10px] font-medium badge-${j.status} capitalize">${j.status}</span>
            <span class="block text-[10px] text-slate-500 font-mono mt-0.5">${formatTimestamp(j.created_at)}</span>
          </div>
        </div>
      `;
    });
    container.innerHTML = html;
  } catch (err) {
    container.innerHTML = `<div class="text-slate-500 italic py-3 text-center">No logs found.</div>`;
  }
}

// --- 2. DOMAINS VIEW CONTROLLER ---

async function loadDomainsTable() {
  const tbody = document.getElementById('domains-table-body');
  if (!tbody) return;
  tbody.innerHTML = `<tr><td colspan="7" class="text-center py-6 text-slate-500 italic">Querying domains from Alibaba Cloud DirectMail...</td></tr>`;

  try {
    const res = await apiFetch(`/api/domains/${state.activeRegion}`);
    const domains = res.domains || [];
    state.cachedDomains = domains;
    const badge = document.getElementById('badge-domains-count');
    if (badge) badge.textContent = domains.length;

    if (domains.length === 0) {
      tbody.innerHTML = `<tr><td colspan="7" class="text-center py-6 text-slate-500 italic">No email domains configured in DirectMail for ${state.activeRegion}. Click "Add Domain" to register one.</td></tr>`;
      return;
    }

    let html = '';
    domains.forEach(d => {
      const cnameOk = d.CnameAuthStatus === 1;
      const spfOk = d.SpfAuthStatus === 1;
      const mxOk = d.MxAuthStatus === 1;
      html += `
        <tr class="hover:bg-slate-900/40 transition">
          <td class="py-3 px-4 font-mono font-bold text-white">${escapeHtml(d.DomainName)}</td>
          <td class="py-3 px-4 font-mono text-slate-400">${d.DomainId}</td>
          <td class="py-3 px-4">
            <span class="px-2 py-0.5 rounded text-[10px] font-semibold ${d.DomainStatus === 0 ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30' : 'bg-slate-800 text-slate-400'}">
              ${d.DomainStatus === 0 ? 'Normal / Active' : 'Inactive'}
            </span>
          </td>
          <td class="py-3 px-4">
            <span class="px-2 py-0.5 rounded text-[10px] font-medium ${cnameOk ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30' : 'bg-amber-500/20 text-amber-300'}">
              ${cnameOk ? '✓ Verified' : 'Pending'}
            </span>
          </td>
          <td class="py-3 px-4 font-mono text-[11px] ${spfOk ? 'text-emerald-400' : 'text-slate-500'}">${spfOk ? '✓ Configured' : 'Optional'}</td>
          <td class="py-3 px-4 font-mono text-[11px] ${mxOk ? 'text-emerald-400' : 'text-slate-500'}">${mxOk ? '✓ Configured' : 'Optional'}</td>
          <td class="py-3 px-4 text-right space-x-2">
            <button onclick="openDomainDnsModal(${d.DomainId}, '${escapeHtml(d.DomainName)}')" class="px-2.5 py-1 text-[11px] rounded bg-cyan-500/10 hover:bg-cyan-500/20 text-cyan-300 border border-cyan-500/30 font-medium">
              Inspect DNS
            </button>
            <button onclick="promptDeleteDomain(${d.DomainId}, '${escapeHtml(d.DomainName)}')" class="px-2.5 py-1 text-[11px] rounded bg-rose-500/10 hover:bg-rose-500/20 text-rose-300 border border-rose-500/30 font-medium">
              Delete
            </button>
          </td>
        </tr>
      `;
    });
    tbody.innerHTML = html;
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="7" class="text-center py-6 text-rose-400 italic">Error loading domains: ${escapeHtml(err.message)}</td></tr>`;
  }
}

async function openDomainDnsModal(domainId, domainName) {
  document.getElementById('domain-dns-title').textContent = domainName;
  const content = document.getElementById('domain-dns-content');
  content.innerHTML = `<div class="text-center py-8 text-slate-500 italic">Querying DNS records from Alibaba DirectMail...</div>`;
  document.getElementById('domain-dns-modal').classList.remove('hidden');

  try {
    const res = await apiFetch(`/api/domains/${state.activeRegion}/${domainId}`);
    const d = res.detail || {};
    
    content.innerHTML = `
      <div class="space-y-4">
        <!-- CNAME Record -->
        <div class="bg-slate-900/80 p-3.5 rounded-xl border border-slate-700/80 space-y-1.5">
          <div class="flex items-center justify-between">
            <span class="font-bold text-xs text-white flex items-center gap-1.5">
              <span class="px-1.5 py-0.5 rounded bg-blue-500/20 text-blue-300 font-mono text-[10px]">CNAME</span>
              Domain Tracking & Verification
            </span>
            <span class="text-[10px] px-2 py-0.5 rounded ${d.CnameAuthStatus === 1 ? 'bg-emerald-500/20 text-emerald-300' : 'bg-amber-500/20 text-amber-300'}">
              ${d.CnameAuthStatus === 1 ? 'Auth Pass' : 'Pending Verification'}
            </span>
          </div>
          <div class="text-[11px] space-y-1 text-slate-300 font-mono bg-slate-950 p-2.5 rounded-lg border border-slate-800">
            <div>Host / Subdomain: <b class="text-cyan-300">${d.CnameConfirmStatus || 'dmtrace'}</b></div>
            <div>Target Record: <b class="text-amber-300">${d.DomainRecord || 'tracedm.alibaba.com'}</b></div>
          </div>
        </div>

        <!-- SPF TXT Record -->
        <div class="bg-slate-900/80 p-3.5 rounded-xl border border-slate-700/80 space-y-1.5">
          <div class="flex items-center justify-between">
            <span class="font-bold text-xs text-white flex items-center gap-1.5">
              <span class="px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-300 font-mono text-[10px]">TXT</span>
              SPF Record (Anti-Spoofing)
            </span>
            <span class="text-[10px] px-2 py-0.5 rounded ${d.SpfAuthStatus === 1 ? 'bg-emerald-500/20 text-emerald-300' : 'bg-slate-800 text-slate-400'}">
              ${d.SpfAuthStatus === 1 ? 'Pass' : 'Optional'}
            </span>
          </div>
          <div class="text-[11px] space-y-1 text-slate-300 font-mono bg-slate-950 p-2.5 rounded-lg border border-slate-800">
            <div>Host: <b class="text-cyan-300">@</b></div>
            <div>Value: <b class="text-emerald-300">${d.SpfRecord || 'v=spf1 include:spfdm.aliyun.com -all'}</b></div>
          </div>
        </div>

        <!-- MX Record -->
        <div class="bg-slate-900/80 p-3.5 rounded-xl border border-slate-700/80 space-y-1.5">
          <div class="flex items-center justify-between">
            <span class="font-bold text-xs text-white flex items-center gap-1.5">
              <span class="px-1.5 py-0.5 rounded bg-purple-500/20 text-purple-300 font-mono text-[10px]">MX</span>
              Inbound Mail Routing Record
            </span>
            <span class="text-[10px] px-2 py-0.5 rounded ${d.MxAuthStatus === 1 ? 'bg-emerald-500/20 text-emerald-300' : 'bg-slate-800 text-slate-400'}">
              ${d.MxAuthStatus === 1 ? 'Pass' : 'Optional'}
            </span>
          </div>
          <div class="text-[11px] space-y-1 text-slate-300 font-mono bg-slate-950 p-2.5 rounded-lg border border-slate-800">
            <div>Host: <b class="text-cyan-300">@</b> | Priority: <b class="text-white">10</b></div>
            <div>Target: <b class="text-purple-300">${d.MxRecord || 'mxdm.aliyun.com'}</b></div>
          </div>
        </div>
      </div>
    `;
  } catch (err) {
    content.innerHTML = `<div class="text-rose-400 text-xs py-4 text-center">Failed to load DNS details: ${escapeHtml(err.message)}</div>`;
  }
}

function closeDomainDnsModal() {
  document.getElementById('domain-dns-modal').classList.add('hidden');
}

function openAddDomainModal() {
  document.getElementById('new-domain-name').value = '';
  document.getElementById('add-domain-modal').classList.remove('hidden');
}

function closeAddDomainModal() {
  document.getElementById('add-domain-modal').classList.add('hidden');
}

async function submitCreateDomain() {
  const domain = document.getElementById('new-domain-name').value.trim();
  if (!domain) {
    showToast('Domain name is required.', 'error');
    return;
  }
  try {
    await apiFetch(`/api/domains/${state.activeRegion}`, {
      method: 'POST',
      body: JSON.stringify({ domain_name: domain })
    });
    closeAddDomainModal();
    showToast(`Domain '${domain}' registered in Alibaba Cloud DirectMail!`, 'success');
    loadDomainsTable();
  } catch (err) {
    showToast(err.message, 'error');
  }
}

function promptDeleteDomain(domainId, domainName) {
  showDeleteConfirm({
    title: 'Delete Domain from Alibaba Cloud',
    message: `Are you sure you want to permanently delete domain <strong>${escapeHtml(domainName)}</strong> (ID: ${domainId}) from Alibaba Cloud DirectMail?`,
    onConfirm: async () => {
      try {
        await apiFetch(`/api/domains/${state.activeRegion}/${domainId}`, { method: 'DELETE' });
        showToast(`Domain ${domainName} deleted successfully.`, 'success');
        loadDomainsTable();
      } catch (err) {
        showToast(`Deletion error: ${err.message}`, 'error');
      }
    }
  });
}

// --- 3. SENDERS VIEW CONTROLLER ---

async function loadSendersTable() {
  const tbody = document.getElementById('senders-table-body');
  if (!tbody) return;
  tbody.innerHTML = `<tr><td colspan="7" class="text-center py-6 text-slate-500 italic">Querying verified senders from Alibaba Cloud...</td></tr>`;

  try {
    const res = await apiFetch(`/api/senders/${state.activeRegion}`);
    const senders = res.senders || [];
    state.cachedSenders = senders;
    const badge = document.getElementById('badge-senders-count');
    if (badge) badge.textContent = senders.length;

    if (senders.length === 0) {
      tbody.innerHTML = `<tr><td colspan="7" class="text-center py-6 text-slate-500 italic">No sender identities configured for ${state.activeRegion}. Click "Add Sender" to create one.</td></tr>`;
      return;
    }

    let html = '';
    senders.forEach(s => {
      html += `
        <tr class="hover:bg-slate-900/40 transition">
          <td class="py-3 px-4 font-mono font-bold text-white">${escapeHtml(s.AccountName)}</td>
          <td class="py-3 px-4 font-mono text-slate-400 text-xs">${s.MailAddressId}</td>
          <td class="py-3 px-4">
            <span class="px-2 py-0.5 rounded text-[10px] font-mono font-medium uppercase ${s.Sendtype === 'batch' ? 'bg-purple-500/20 text-purple-300 border border-purple-500/30' : 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/30'}">
              ${s.Sendtype || 'batch'}
            </span>
          </td>
          <td class="py-3 px-4 font-mono text-slate-400 text-xs">${s.ReplyAddress || 'None'}</td>
          <td class="py-3 px-4 font-mono text-xs text-slate-300">${s.DailyReqCount || 0} sent</td>
          <td class="py-3 px-4">
            <span class="px-2 py-0.5 rounded text-[10px] font-semibold ${s.AccountStatus === 0 ? 'bg-emerald-500/20 text-emerald-300' : 'bg-rose-500/20 text-rose-300'}">
              ${s.AccountStatus === 0 ? 'Active' : 'Disabled'}
            </span>
          </td>
          <td class="py-3 px-4 text-right space-x-2">
            <button onclick="useSenderInTask('${escapeHtml(s.AccountName)}')" class="px-2.5 py-1 text-[11px] rounded bg-brand/20 hover:bg-brand text-brand hover:text-white border border-brand/40 font-medium transition">
              Use in Task →
            </button>
            <button onclick="promptDeleteSender(${s.MailAddressId}, '${escapeHtml(s.AccountName)}')" class="px-2.5 py-1 text-[11px] rounded bg-rose-500/10 hover:bg-rose-500/20 text-rose-300 border border-rose-500/30 font-medium">
              Delete
            </button>
          </td>
        </tr>
      `;
    });
    tbody.innerHTML = html;
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="7" class="text-center py-6 text-rose-400 italic">Error loading senders: ${escapeHtml(err.message)}</td></tr>`;
  }
}

function openAddSenderModalFromSenders() {
  document.getElementById('add-sender-email').value = '';
  document.getElementById('add-sender-reply').value = '';
  document.getElementById('add-sender-modal').classList.remove('hidden');
}

function closeAddSenderModal() {
  document.getElementById('add-sender-modal').classList.add('hidden');
}

async function confirmAddSender() {
  const email = document.getElementById('add-sender-email').value.trim();
  const reply = document.getElementById('add-sender-reply').value.trim();
  const sendType = document.getElementById('add-sender-type').value;

  if (!email) {
    showToast('Sender email address is required.', 'error');
    return;
  }

  try {
    await apiFetch(`/api/directmail-senders/${state.activeRegion}`, {
      method: 'POST',
      body: JSON.stringify({
        account_name: email,
        reply_address: reply || null,
        send_type: sendType
      })
    });
    closeAddSenderModal();
    showToast(`Sender '${email}' created in Alibaba DirectMail!`, 'success');
    loadSendersTable();
    await loadRegions();
  } catch (err) {
    showToast(err.message, 'error');
  }
}

function promptDeleteSender(mailAddressId, accountName) {
  showDeleteConfirm({
    title: 'Delete Sender Identity',
    message: `Are you sure you want to delete verified sender address <strong>${escapeHtml(accountName)}</strong> (ID: ${mailAddressId}) from Alibaba Cloud DirectMail?`,
    onConfirm: async () => {
      try {
        await apiFetch(`/api/directmail-senders/${state.activeRegion}/${mailAddressId}`, { method: 'DELETE' });
        showToast(`Sender ${accountName} deleted.`, 'success');
        loadSendersTable();
        await loadRegions();
      } catch (err) {
        showToast(`Deletion error: ${err.message}`, 'error');
      }
    }
  });
}

function useSenderInTask(email) {
  state.activeSendRegion = state.activeRegion;
  navigateTo('tasks');
  setTasksTab('send');
  const select = document.getElementById('send-sender-select');
  if (select) select.value = email;
  showToast(`Selected verified sender: ${email}`, 'info');
}

// --- 4. TEMPLATES VIEW CONTROLLER ---

function setTemplateSubTab(tabKey) {
  state.templateSubTab = tabKey;
  const btnLocal = document.getElementById('btn-tpl-tab-local');
  const btnRemote = document.getElementById('btn-tpl-tab-remote');
  const contentLocal = document.getElementById('tpl-content-local');
  const contentRemote = document.getElementById('tpl-content-remote');

  if (tabKey === 'local') {
    if (btnLocal) btnLocal.className = 'px-3.5 py-1.5 rounded-lg font-semibold bg-purple-600 text-white shadow transition flex items-center gap-1.5';
    if (btnRemote) btnRemote.className = 'px-3.5 py-1.5 rounded-lg font-semibold text-slate-400 hover:text-white transition flex items-center gap-1.5';
    if (contentLocal) contentLocal.classList.remove('hidden');
    if (contentRemote) contentRemote.classList.add('hidden');
    loadLocalTemplatesTable();
  } else {
    if (btnLocal) btnLocal.className = 'px-3.5 py-1.5 rounded-lg font-semibold text-slate-400 hover:text-white transition flex items-center gap-1.5';
    if (btnRemote) btnRemote.className = 'px-3.5 py-1.5 rounded-lg font-semibold bg-purple-600 text-white shadow transition flex items-center gap-1.5';
    if (contentLocal) contentLocal.classList.add('hidden');
    if (contentRemote) contentRemote.classList.remove('hidden');
    const label = document.getElementById('remote-tpl-region-label');
    if (label) label.textContent = state.activeRegion;
    loadTemplatesTable();
  }
  initIcons();
}

let localTplSearchDebounce = null;
function debounceSearchLocalTemplates() {
  clearTimeout(localTplSearchDebounce);
  localTplSearchDebounce = setTimeout(() => {
    loadLocalTemplatesTable();
  }, 300);
}

async function loadLocalTemplatesTable() {
  const tbody = document.getElementById('local-templates-table-body');
  if (!tbody) return;
  tbody.innerHTML = `<tr><td colspan="7" class="text-center py-6 text-slate-500 italic">Loading application templates...</td></tr>`;

  const fmt = document.getElementById('local-tpl-format-filter') ? document.getElementById('local-tpl-format-filter').value : '';
  const status = document.getElementById('local-tpl-status-filter') ? document.getElementById('local-tpl-status-filter').value : '';
  const sync = document.getElementById('local-tpl-sync-filter') ? document.getElementById('local-tpl-sync-filter').value : '';
  const search = document.getElementById('local-tpl-search') ? document.getElementById('local-tpl-search').value.trim() : '';

  let url = `/api/app-templates?limit=100`;
  if (fmt) url += `&format_type=${encodeURIComponent(fmt)}`;
  if (status) url += `&status=${encodeURIComponent(status)}`;
  if (sync) url += `&sync_status=${encodeURIComponent(sync)}`;
  if (search) url += `&search=${encodeURIComponent(search)}`;

  try {
    const res = await apiFetch(url);
    const templates = res.templates || [];
    state.localTemplates = templates;
    const badge = document.getElementById('badge-templates-count');
    if (badge) badge.textContent = templates.length;

    if (templates.length === 0) {
      tbody.innerHTML = `<tr><td colspan="7" class="text-center py-6 text-slate-500 italic">No application templates found matching your filters. Click "Create Template" to add one.</td></tr>`;
      return;
    }

    let html = '';
    templates.forEach(t => {
      // Review state badge
      let reviewBadge = '';
      if (t.status === 'approved' || t.dm_status === 1) {
        reviewBadge = `<span class="px-2 py-0.5 rounded text-[10px] font-semibold bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 flex items-center gap-1 w-fit"><i data-lucide="check-circle" class="w-3 h-3"></i> Approved</span>`;
      } else if (t.status === 'pending_review' || t.dm_status === 0) {
        reviewBadge = `<span class="px-2 py-0.5 rounded text-[10px] font-semibold bg-amber-500/20 text-amber-300 border border-amber-500/30 flex items-center gap-1 w-fit"><i data-lucide="clock" class="w-3 h-3"></i> Pending Review</span>`;
      } else if (t.status === 'rejected' || t.dm_status === 2) {
        reviewBadge = `<span class="px-2 py-0.5 rounded text-[10px] font-semibold bg-rose-500/20 text-rose-300 border border-rose-500/30 flex items-center gap-1 w-fit"><i data-lucide="x-circle" class="w-3 h-3"></i> Rejected</span>`;
      } else {
        reviewBadge = `<span class="px-2 py-0.5 rounded text-[10px] font-semibold bg-slate-800 text-slate-300">Draft</span>`;
      }

      // Rejection reason banner if rejected
      let rejectionHtml = '';
      if (t.rejection_reason) {
        rejectionHtml = `
          <div class="mt-1 text-[11px] text-rose-300 bg-rose-950/50 p-1.5 rounded border border-rose-500/30 flex items-start gap-1 max-w-[280px]">
            <i data-lucide="alert-circle" class="w-3 h-3 text-rose-400 shrink-0 mt-0.5"></i>
            <span><strong>Rejection:</strong> ${escapeHtml(t.rejection_reason)}</span>
          </div>
        `;
      }

      // Sync state badge
      let syncBadge = '';
      if (t.sync_status === 'synchronized') {
        syncBadge = `<span class="px-2 py-0.5 rounded text-[10px] font-mono bg-emerald-500/20 text-emerald-300 flex items-center gap-1 w-fit"><i data-lucide="check" class="w-3 h-3"></i> Synced (${t.dm_template_id})</span>`;
      } else if (t.sync_status === 'sync_failed') {
        syncBadge = `<span class="px-2 py-0.5 rounded text-[10px] font-mono bg-rose-500/20 text-rose-300 flex items-center gap-1 w-fit" title="${escapeHtml(t.sync_error || '')}"><i data-lucide="alert-circle" class="w-3 h-3"></i> Sync Failed</span>`;
      } else {
        syncBadge = `<span class="px-2 py-0.5 rounded text-[10px] font-mono bg-blue-500/20 text-blue-300 flex items-center gap-1 w-fit"><i data-lucide="clock" class="w-3 h-3"></i> Sync Pending</span>`;
      }

      const isRejected = t.status === 'rejected' || t.dm_status === 2;

      html += `
        <tr class="hover:bg-slate-900/40 transition">
          <td class="py-3 px-4">
            <span class="font-bold text-white block">${escapeHtml(t.name)}</span>
            <span class="text-[11px] text-slate-400 block truncate max-w-[240px]">${escapeHtml(t.subject)}</span>
            ${rejectionHtml}
          </td>
          <td class="py-3 px-4 font-mono text-xs">
            <span class="px-2 py-0.5 rounded text-[10px] ${t.format === 'html' ? 'bg-purple-500/20 text-purple-300' : 'bg-slate-700 text-slate-300'}">
              ${(t.format || 'html').toUpperCase()}
            </span>
          </td>
          <td class="py-3 px-4 font-mono text-xs text-slate-400">${t.template_type === 1 ? 'Trigger' : 'Batch'}</td>
          <td class="py-3 px-4">${reviewBadge}</td>
          <td class="py-3 px-4">${syncBadge}</td>
          <td class="py-3 px-4 font-mono text-xs text-slate-400">${formatTimestamp(t.updated_at || t.created_at)}</td>
          <td class="py-3 px-4 text-right space-x-1 whitespace-nowrap">
            <button onclick="previewLocalTemplate(${t.id})" class="px-2 py-1 text-[11px] rounded bg-purple-500/10 hover:bg-purple-500/20 text-purple-300 border border-purple-500/30">Preview</button>
            <button onclick="openEditTemplateModal(${t.id})" class="px-2 py-1 text-[11px] rounded bg-slate-800 hover:bg-slate-700 text-slate-200">Edit</button>
            <button onclick="submitTemplateToProviderReview(${t.id})" class="px-2 py-1 text-[11px] rounded bg-amber-500/10 hover:bg-amber-500/20 text-amber-300 border border-amber-500/30" title="Submit to DirectMail for Review">Review →</button>
            <button onclick="checkTemplateProviderStatus(${t.id})" class="px-2 py-1 text-[11px] rounded bg-teal-500/10 hover:bg-teal-500/20 text-teal-300 border border-teal-500/30" title="Query live review status from DirectMail">Check Status</button>
            ${isRejected ? `<button onclick="resubmitTemplateToProviderReview(${t.id})" class="px-2 py-1 text-[11px] rounded bg-rose-500/20 hover:bg-rose-500/30 text-rose-200 border border-rose-500/40 font-semibold" title="Resubmit rejected template to DirectMail">Resubmit</button>` : ''}
            <button onclick="syncLocalTemplateToDirectMail(${t.id})" class="px-2 py-1 text-[11px] rounded bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-300 border border-emerald-500/30" title="Synchronize template with Alibaba Cloud DirectMail">Sync</button>
            <button onclick="promptDeleteLocalTemplate(${t.id}, '${escapeHtml(t.name)}')" class="px-2 py-1 text-[11px] rounded bg-rose-500/10 hover:bg-rose-500/20 text-rose-300 border border-rose-500/30">Delete</button>
          </td>
        </tr>
      `;
    });
    tbody.innerHTML = html;
    initIcons();
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="7" class="text-center py-6 text-rose-400 italic">Error loading templates: ${escapeHtml(err.message)}</td></tr>`;
  }
}

function toggleTemplateFormatEditor() {
  const fmt = document.getElementById('tpl-format').value;
  const label = document.getElementById('tpl-body-label');
  const textarea = document.getElementById('tpl-html');
  if (fmt === 'text') {
    if (label) label.textContent = 'Plain-Text Email Body *';
    if (textarea) textarea.placeholder = 'Write plain-text email message...';
  } else {
    if (label) label.textContent = 'HTML Template Body *';
    if (textarea) textarea.placeholder = '<h1>Thank you!</h1><p>Your order details...</p>';
  }
}

function setTplEditorTab(tab) {
  const btnSrc = document.getElementById('btn-tpl-edit-src');
  const btnPrev = document.getElementById('btn-tpl-edit-prev');
  const srcCont = document.getElementById('tpl-source-container');
  const prevCont = document.getElementById('tpl-preview-container');
  const prevRender = document.getElementById('tpl-preview-render');

  if (tab === 'source') {
    if (btnSrc) { btnSrc.className = 'px-2 py-0.5 rounded font-medium bg-purple-600 text-white'; }
    if (btnPrev) { btnPrev.className = 'px-2 py-0.5 rounded font-medium text-slate-400 hover:text-white'; }
    if (srcCont) srcCont.classList.remove('hidden');
    if (prevCont) prevCont.classList.add('hidden');
  } else {
    if (btnSrc) { btnSrc.className = 'px-2 py-0.5 rounded font-medium text-slate-400 hover:text-white'; }
    if (btnPrev) { btnPrev.className = 'px-2 py-0.5 rounded font-medium bg-purple-600 text-white'; }
    if (srcCont) srcCont.classList.add('hidden');
    if (prevCont) prevCont.classList.remove('hidden');

    const fmt = document.getElementById('tpl-format').value;
    const bodyVal = document.getElementById('tpl-html').value;
    if (fmt === 'text') {
      prevRender.innerHTML = `<pre style="font-family:sans-serif;white-space:pre-wrap;">${escapeHtml(bodyVal || '(No content)')}</pre>`;
    } else {
      prevRender.innerHTML = bodyVal || '<p style="color:#888;">(No HTML content)</p>';
    }
  }
}

function openCreateTemplateModal(tplId = null) {
  document.getElementById('tpl-edit-id').value = '';
  document.getElementById('tpl-modal-title').innerHTML = '<i data-lucide="file-code" class="w-4 h-4 text-purple-400"></i><span>Create Email Template</span>';
  document.getElementById('tpl-name').value = '';
  document.getElementById('tpl-subject').value = '';
  document.getElementById('tpl-nickname').value = '';
  document.getElementById('tpl-html').value = '';
  document.getElementById('tpl-format').value = 'html';
  document.getElementById('tpl-type').value = '0';
  document.getElementById('tpl-region').value = state.activeRegion || 'singapore';
  toggleTemplateFormatEditor();
  setTplEditorTab('source');
  document.getElementById('create-template-modal').classList.remove('hidden');
  initIcons();
}

async function openEditTemplateModal(tplId) {
  try {
    const tpl = await apiFetch(`/api/app-templates/${tplId}`);
    document.getElementById('tpl-edit-id').value = tpl.id;
    document.getElementById('tpl-modal-title').innerHTML = `<i data-lucide="edit-3" class="w-4 h-4 text-purple-400"></i><span>Edit Template #${tpl.id}</span>`;
    document.getElementById('tpl-name').value = tpl.name || '';
    document.getElementById('tpl-subject').value = tpl.subject || '';
    document.getElementById('tpl-nickname').value = tpl.from_alias || '';
    document.getElementById('tpl-format').value = tpl.format || 'html';
    document.getElementById('tpl-type').value = String(tpl.template_type || 0);
    document.getElementById('tpl-region').value = tpl.dm_region || state.activeRegion;
    document.getElementById('tpl-html').value = (tpl.format === 'text' ? tpl.text_body : tpl.html_body) || '';
    toggleTemplateFormatEditor();
    setTplEditorTab('source');
    document.getElementById('create-template-modal').classList.remove('hidden');
    initIcons();
  } catch (err) {
    showToast(`Failed to load template: ${err.message}`, 'error');
  }
}

function closeCreateTemplateModal() {
  document.getElementById('create-template-modal').classList.add('hidden');
}

async function saveTemplate(intent = 'draft') {
  const editId = document.getElementById('tpl-edit-id').value;
  const name = document.getElementById('tpl-name').value.trim();
  const subject = document.getElementById('tpl-subject').value.trim();
  const nickname = document.getElementById('tpl-nickname').value.trim();
  const format = document.getElementById('tpl-format').value;
  const templateType = parseInt(document.getElementById('tpl-type').value) || 0;
  const region = document.getElementById('tpl-region').value;
  const bodyContent = document.getElementById('tpl-html').value;

  if (!name || !subject) {
    showToast('Template name and subject line are required.', 'error');
    return;
  }

  const payload = {
    name: name,
    subject: subject,
    from_alias: nickname || null,
    format: format,
    template_type: templateType,
    dm_region: region,
    html_body: format === 'html' ? bodyContent : null,
    text_body: format === 'text' ? bodyContent : null
  };

  try {
    let tplId = editId;
    if (editId) {
      await apiFetch(`/api/app-templates/${editId}`, {
        method: 'PUT',
        body: JSON.stringify(payload)
      });
    } else {
      const res = await apiFetch('/api/app-templates', {
        method: 'POST',
        body: JSON.stringify(payload)
      });
      tplId = res.template_id;
    }

    // Handle intent
    if (intent === 'pending_review') {
      await apiFetch(`/api/app-templates/${tplId}/review`, {
        method: 'POST',
        body: JSON.stringify({ status: 'pending_review' })
      });
      showToast(`Template '${name}' saved and submitted for review.`, 'info');
    } else if (intent === 'approved_sync') {
      await apiFetch(`/api/app-templates/${tplId}/review`, {
        method: 'POST',
        body: JSON.stringify({ status: 'approved' })
      });
      const syncRes = await apiFetch(`/api/app-templates/${tplId}/sync`, { method: 'POST' });
      showToast(syncRes.message || `Template '${name}' saved and synced to DirectMail!`, 'success');
    } else {
      showToast(`Template '${name}' saved as Draft.`, 'success');
    }

    closeCreateTemplateModal();
    loadLocalTemplatesTable();
  } catch (err) {
    showToast(`Template Save Error: ${err.message}`, 'error');
  }
}

function promptReviewTemplate(templateId, currentStatus) {
  showDeleteConfirm({
    title: 'Update Template Review Status',
    message: `
      <p class="mb-3 text-slate-300">Set the governance review state for Template <strong>#${templateId}</strong> (currently: <em>${currentStatus}</em>):</p>
      <div class="flex flex-col gap-2 text-xs">
        <button type="button" onclick="executeReviewStatus(${templateId}, 'approved')" class="px-3 py-2 bg-emerald-600/20 hover:bg-emerald-600 text-emerald-200 hover:text-white rounded-lg border border-emerald-500/30 text-left font-semibold transition">✓ Approve Template (Ready for DirectMail Sync)</button>
        <button type="button" onclick="executeReviewStatus(${templateId}, 'rejected')" class="px-3 py-2 bg-rose-600/20 hover:bg-rose-600 text-rose-200 hover:text-white rounded-lg border border-rose-500/30 text-left font-semibold transition">✗ Reject Template (Requires Revision)</button>
        <button type="button" onclick="executeReviewStatus(${templateId}, 'pending_review')" class="px-3 py-2 bg-amber-600/20 hover:bg-amber-600 text-amber-200 hover:text-white rounded-lg border border-amber-500/30 text-left font-semibold transition">⏳ Mark Pending Review</button>
        <button type="button" onclick="executeReviewStatus(${templateId}, 'draft')" class="px-3 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-left transition">Reset to Draft</button>
      </div>
    `,
    onConfirm: async () => {} // handled by buttons
  });
  // Hide confirm delete button for this custom modal
  document.getElementById('btn-confirm-delete-action').style.display = 'none';
}

async function executeReviewStatus(templateId, newStatus) {
  closeDeleteConfirmModal();
  document.getElementById('btn-confirm-delete-action').style.display = 'inline-block';
  try {
    await apiFetch(`/api/app-templates/${templateId}/review`, {
      method: 'POST',
      body: JSON.stringify({ status: newStatus })
    });
    showToast(`Template #${templateId} status updated to '${newStatus}'.`, 'success');
    loadLocalTemplatesTable();
  } catch (err) {
    showToast(err.message, 'error');
  }
}

async function syncLocalTemplateToDirectMail(templateId) {
  try {
    showToast(`Synchronizing template #${templateId} with Alibaba Cloud DirectMail...`, 'info');
    const res = await apiFetch(`/api/app-templates/${templateId}/sync`, { method: 'POST' });
    showToast(res.message, 'success');
    loadLocalTemplatesTable();
    loadTemplatesTable();
  } catch (err) {
    showToast(`Sync Failed: ${err.message}`, 'error');
  }
}

async function submitTemplateToProviderReview(templateId) {
  try {
    showToast(`Submitting template #${templateId} to DirectMail for review...`, 'info');
    const res = await apiFetch(`/api/app-templates/${templateId}/submit-review`, { method: 'POST' });
    showToast(res.message || 'Template submitted to DirectMail for review!', 'success');
    loadLocalTemplatesTable();
  } catch (err) {
    showToast(`Submit Review Error: ${err.message}`, 'error');
  }
}

async function checkTemplateProviderStatus(templateId) {
  try {
    const res = await apiFetch(`/api/app-templates/${templateId}/provider-status`);
    showToast(`DirectMail Status: ${res.provider_status || res.status} (Code: ${res.provider_status_code})`, 'info');
    loadLocalTemplatesTable();
  } catch (err) {
    showToast(`Provider Status Error: ${err.message}`, 'error');
  }
}

async function resubmitTemplateToProviderReview(templateId) {
  try {
    showToast(`Resubmitting template #${templateId} to DirectMail...`, 'info');
    const res = await apiFetch(`/api/app-templates/${templateId}/resubmit`, { method: 'POST' });
    showToast(res.message || 'Template resubmitted for review!', 'success');
    loadLocalTemplatesTable();
  } catch (err) {
    showToast(`Resubmit Error: ${err.message}`, 'error');
  }
}

function promptDeleteLocalTemplate(templateId, templateName) {
  showDeleteConfirm({
    title: 'Delete Template',
    message: `Are you sure you want to delete template <strong>${escapeHtml(templateName)}</strong> (#${templateId})? If previously synchronized, it will also be cleaned up from DirectMail.`,
    onConfirm: async () => {
      try {
        await apiFetch(`/api/app-templates/${templateId}`, { method: 'DELETE' });
        showToast(`Template '${templateName}' deleted.`, 'success');
        loadLocalTemplatesTable();
      } catch (err) {
        showToast(`Deletion Error: ${err.message}`, 'error');
      }
    }
  });
}

async function previewLocalTemplate(templateId) {
  try {
    const tpl = await apiFetch(`/api/app-templates/${templateId}`);
    document.getElementById('template-preview-name').textContent = tpl.name;
    document.getElementById('template-preview-subject').innerHTML = `
      Subject: <b class="text-slate-200">${escapeHtml(tpl.subject || '(None)')}</b> | 
      Format: <b class="text-slate-200 uppercase">${tpl.format}</b> |
      Review State: <b class="text-emerald-300 capitalize">${tpl.status}</b>
    `;
    const iframe = document.getElementById('template-preview-iframe');
    if (tpl.format === 'text') {
      iframe.srcdoc = `<pre style="font-family:sans-serif;white-space:pre-wrap;padding:16px;color:#222;">${escapeHtml(tpl.text_body || '')}</pre>`;
    } else {
      iframe.srcdoc = tpl.html_body || '<p style="padding:16px;color:#888;">(Empty HTML template)</p>';
    }

    document.getElementById('btn-use-previewed-template').onclick = () => {
      closeTemplatePreviewModal();
      navigateTo('tasks');
      setTasksTab('send');
      document.getElementById('send-subject').value = tpl.subject || '';
      if (tpl.format === 'text') {
        document.getElementById('send-text-body').value = tpl.text_body || '';
        document.getElementById('send-html-body').value = '';
      } else {
        document.getElementById('send-html-body').value = tpl.html_body || '';
      }
      showToast(`Loaded template '${tpl.name}' into compose form.`, 'info');
    };

    document.getElementById('template-preview-modal').classList.remove('hidden');
    initIcons();
  } catch (err) {
    showToast(`Preview Error: ${err.message}`, 'error');
  }
}

// Preserved Alibaba Remote Templates Controller
async function loadTemplatesTable() {
  const tbody = document.getElementById('templates-table-body');
  if (!tbody) return;
  tbody.innerHTML = `<tr><td colspan="6" class="text-center py-6 text-slate-500 italic">Querying templates from Alibaba Cloud DirectMail...</td></tr>`;

  try {
    const res = await apiFetch(`/api/templates/${state.activeRegion}`);
    const templates = res.templates || [];
    state.cachedTemplates = templates;

    if (templates.length === 0) {
      tbody.innerHTML = `<tr><td colspan="6" class="text-center py-6 text-slate-500 italic">No email templates created for ${state.activeRegion}. Click "Create Template" to add one.</td></tr>`;
      return;
    }

    let html = '';
    templates.forEach(t => {
      html += `
        <tr class="hover:bg-slate-900/40 transition">
          <td class="py-3 px-4 font-bold text-white">${escapeHtml(t.TemplateName)}</td>
          <td class="py-3 px-4 font-mono text-slate-400 text-xs">${t.TemplateId}</td>
          <td class="py-3 px-4 font-mono text-xs">
            <span class="px-2 py-0.5 rounded text-[10px] ${t.TemplateType === 0 ? 'bg-purple-500/20 text-purple-300' : 'bg-cyan-500/20 text-cyan-300'}">
              ${t.TemplateType === 0 ? 'Batch' : 'Trigger'}
            </span>
          </td>
          <td class="py-3 px-4">
            <span class="px-2 py-0.5 rounded text-[10px] font-semibold ${t.TemplateStatus === '0' || t.TemplateStatus === 0 ? 'bg-emerald-500/20 text-emerald-300' : 'bg-slate-800 text-slate-400'}">
              ${t.TemplateStatus === '0' || t.TemplateStatus === 0 ? 'Normal' : 'Status ' + t.TemplateStatus}
            </span>
          </td>
          <td class="py-3 px-4 font-mono text-xs text-slate-400">${formatTimestamp(t.UtcCreateTime)}</td>
          <td class="py-3 px-4 text-right space-x-2">
            <button onclick="previewTemplate(${t.TemplateId}, '${escapeHtml(t.TemplateName)}')" class="px-2.5 py-1 text-[11px] rounded bg-purple-500/10 hover:bg-purple-500/20 text-purple-300 border border-purple-500/30 font-medium">
              Preview HTML
            </button>
            <button onclick="useTemplateInTask(${t.TemplateId}, '${escapeHtml(t.TemplateName)}')" class="px-2.5 py-1 text-[11px] rounded bg-brand/20 hover:bg-brand text-brand hover:text-white border border-brand/40 font-medium transition">
              Use in Task →
            </button>
            <button onclick="promptDeleteTemplate(${t.TemplateId}, '${escapeHtml(t.TemplateName)}')" class="px-2.5 py-1 text-[11px] rounded bg-rose-500/10 hover:bg-rose-500/20 text-rose-300 border border-rose-500/30 font-medium">
              Delete
            </button>
          </td>
        </tr>
      `;
    });
    tbody.innerHTML = html;
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="6" class="text-center py-6 text-rose-400 italic">Error loading templates: ${escapeHtml(err.message)}</td></tr>`;
  }
}

async function previewTemplate(templateId, templateName) {
  document.getElementById('template-preview-name').textContent = templateName;
  document.getElementById('template-preview-subject').textContent = 'Loading template content from Alibaba Cloud...';
  const iframe = document.getElementById('template-preview-iframe');
  iframe.srcdoc = '<p style="font-family:sans-serif;color:#666;padding:20px;">Fetching HTML template...</p>';
  document.getElementById('template-preview-modal').classList.remove('hidden');

  try {
    const res = await apiFetch(`/api/templates/${state.activeRegion}/${templateId}`);
    const d = res.detail || {};
    document.getElementById('template-preview-subject').innerHTML = `
      Subject: <b class="text-slate-200">${escapeHtml(d.TemplateSubject || '(None)')}</b> | 
      Nickname: <b class="text-slate-200">${escapeHtml(d.TemplateNickName || '(None)')}</b>
    `;
    iframe.srcdoc = d.TemplateText || '<p style="font-family:sans-serif;color:#888;">(Empty template body)</p>';

    document.getElementById('btn-use-previewed-template').onclick = () => {
      closeTemplatePreviewModal();
      useTemplateInTask(templateId, templateName);
    };
  } catch (err) {
    document.getElementById('template-preview-subject').textContent = 'Failed to load details: ' + err.message;
  }
}

function closeTemplatePreviewModal() {
  document.getElementById('template-preview-modal').classList.add('hidden');
}

function promptDeleteTemplate(templateId, templateName) {
  showDeleteConfirm({
    title: 'Delete DirectMail Template',
    message: `Are you sure you want to delete template <strong>${escapeHtml(templateName)}</strong> (ID: ${templateId}) from Alibaba Cloud DirectMail?`,
    onConfirm: async () => {
      try {
        await apiFetch(`/api/templates/${state.activeRegion}/${templateId}`, { method: 'DELETE' });
        showToast(`Template ${templateName} deleted.`, 'success');
        loadTemplatesTable();
      } catch (err) {
        showToast(`Deletion error: ${err.message}`, 'error');
      }
    }
  });
}

async function useTemplateInTask(templateId, templateName) {
  try {
    const res = await apiFetch(`/api/templates/${state.activeRegion}/${templateId}`);
    const d = res.detail || {};
    navigateTo('tasks');
    setTasksTab('send');
    if (d.TemplateSubject) document.getElementById('send-subject').value = d.TemplateSubject;
    if (d.TemplateText) {
      document.getElementById('send-html-body').value = d.TemplateText;
      document.getElementById('send-text-body').value = '';
    }
    if (d.TemplateNickName) document.getElementById('send-from-alias').value = d.TemplateNickName;
    showToast(`Loaded template '${templateName}' into compose form.`, 'info');
  } catch (err) {
    showToast(`Failed to load template content: ${err.message}`, 'error');
  }
}

// --- 5. RECIPIENTS POOL VIEW CONTROLLER ---

async function loadRecipientsTable() {
  const tbody = document.getElementById('recipients-table-body');
  if (!tbody) return;

  try {
    const res = await apiFetch('/api/recipients');
    state.recipientsPool = res.recipients || [];
    state.selectedRecipientIds.clear();
    updateRecipientsSelectionUI();

    const badge = document.getElementById('badge-recipients-count');
    if (badge) badge.textContent = state.recipientsPool.length;

    renderRecipientsRows(state.recipientsPool);
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="6" class="text-center py-6 text-rose-400 italic">Error loading recipients: ${escapeHtml(err.message)}</td></tr>`;
  }
}

function renderRecipientsRows(list) {
  const tbody = document.getElementById('recipients-table-body');
  if (list.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" class="text-center py-6 text-slate-500 italic">No recipients found in pool. Click "Add Recipient(s)" to build your audience.</td></tr>`;
    return;
  }

  let html = '';
  list.forEach(r => {
    const checked = state.selectedRecipientIds.has(r.id) ? 'checked' : '';
    html += `
      <tr class="hover:bg-slate-900/40 transition">
        <td class="py-3 px-4">
          <input type="checkbox" onchange="toggleSelectRecipient(${r.id}, this.checked)" ${checked} class="accent-brand rounded cursor-pointer">
        </td>
        <td class="py-3 px-4 font-mono font-medium text-white">${escapeHtml(r.email)}</td>
        <td class="py-3 px-4 text-slate-300 text-xs">${escapeHtml(r.name || '—')}</td>
        <td class="py-3 px-4">
          <span class="px-2 py-0.5 rounded text-[10px] bg-slate-800 text-pink-300 border border-slate-700 font-mono">
            ${escapeHtml(r.tags || 'general')}
          </span>
        </td>
        <td class="py-3 px-4 font-mono text-slate-400 text-xs">${formatTimestamp(r.created_at)}</td>
        <td class="py-3 px-4 text-right">
          <button onclick="promptDeleteSingleRecipient(${r.id}, '${escapeHtml(r.email)}')" class="text-slate-400 hover:text-rose-400 text-xs">
            <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
          </button>
        </td>
      </tr>
    `;
  });
  tbody.innerHTML = html;
  initIcons();
}

function toggleSelectRecipient(id, isChecked) {
  if (isChecked) {
    state.selectedRecipientIds.add(id);
  } else {
    state.selectedRecipientIds.delete(id);
  }
  updateRecipientsSelectionUI();
}

function toggleSelectAllRecipients(isChecked) {
  selectAllRecipients(isChecked);
}

function selectAllRecipients(select) {
  if (select) {
    state.recipientsPool.forEach(r => state.selectedRecipientIds.add(r.id));
  } else {
    state.selectedRecipientIds.clear();
  }
  const checkAll = document.getElementById('recipients-check-all');
  if (checkAll) checkAll.checked = select;
  renderRecipientsRows(state.recipientsPool);
  updateRecipientsSelectionUI();
}

function updateRecipientsSelectionUI() {
  const count = state.selectedRecipientIds.size;
  const selEl = document.getElementById('recipients-selected-count');
  const totEl = document.getElementById('recipients-total-count');
  if (selEl) selEl.textContent = count;
  if (totEl) totEl.textContent = state.recipientsPool.length;

  const btnDel = document.getElementById('btn-delete-selected-recipients');
  const btnText = document.getElementById('btn-delete-recipients-text');
  if (btnDel && btnText) {
    btnDel.disabled = (count === 0);
    btnText.textContent = `Delete Selected (${count})`;
  }
}

function filterRecipientsTable() {
  const q = document.getElementById('recipients-search-input').value.toLowerCase().trim();
  if (!q) {
    renderRecipientsRows(state.recipientsPool);
    return;
  }
  const filtered = state.recipientsPool.filter(r => 
    r.email.toLowerCase().includes(q) ||
    (r.name && r.name.toLowerCase().includes(q)) ||
    (r.tags && r.tags.toLowerCase().includes(q))
  );
  renderRecipientsRows(filtered);
}

function openAddRecipientsModal() {
  document.getElementById('app-recipients-paste').value = '';
  document.getElementById('app-recipients-tags').value = '';
  document.getElementById('add-recipients-modal').classList.remove('hidden');
}

function closeAddRecipientsModal() {
  document.getElementById('add-recipients-modal').classList.add('hidden');
}

async function submitAddRecipients() {
  const text = document.getElementById('app-recipients-paste').value.trim();
  const tags = document.getElementById('app-recipients-tags').value.trim() || 'pool';

  if (!text) {
    showToast('Please enter at least one recipient email.', 'error');
    return;
  }

  // Parse lines or commas
  const entries = text.split(/[\n,;]+/).map(s => s.trim()).filter(Boolean);
  const recipients = [];

  entries.forEach(item => {
    // Check if format is "Name <email@domain.com>"
    const angleMatch = item.match(/^(.*?)\s*<([^>]+)>$/);
    if (angleMatch) {
      recipients.push({ email: angleMatch[2].trim(), name: angleMatch[1].trim() || null, tags });
    } else {
      recipients.push({ email: item, name: null, tags });
    }
  });

  if (recipients.length === 0) {
    showToast('No valid recipients detected.', 'error');
    return;
  }

  try {
    const res = await apiFetch('/api/recipients', {
      method: 'POST',
      body: JSON.stringify({ recipients })
    });
    closeAddRecipientsModal();
    showToast(`Added ${res.added_count} recipient(s) to application pool!`, 'success');
    loadRecipientsTable();
  } catch (err) {
    showToast(err.message, 'error');
  }
}

function promptDeleteSingleRecipient(id, email) {
  showDeleteConfirm({
    title: 'Delete Recipient',
    message: `Remove <strong>${escapeHtml(email)}</strong> from the local application pool?`,
    onConfirm: async () => {
      try {
        await apiFetch('/api/recipients', {
          method: 'DELETE',
          body: JSON.stringify({ ids: [id] })
        });
        showToast('Recipient removed.', 'success');
        loadRecipientsTable();
      } catch (err) {
        showToast(err.message, 'error');
      }
    }
  });
}

function confirmDeleteSelectedRecipients() {
  const count = state.selectedRecipientIds.size;
  if (count === 0) return;

  showDeleteConfirm({
    title: `Delete ${count} Selected Recipient(s)`,
    message: `Are you sure you want to permanently delete <strong>${count}</strong> recipient(s) from your local application pool?`,
    onConfirm: async () => {
      try {
        const ids = Array.from(state.selectedRecipientIds);
        await apiFetch('/api/recipients', {
          method: 'DELETE',
          body: JSON.stringify({ ids })
        });
        showToast(`Deleted ${count} recipient(s).`, 'success');
        loadRecipientsTable();
      } catch (err) {
        showToast(err.message, 'error');
      }
    }
  });
}

function useSelectedInCampaign() {
  const count = state.selectedRecipientIds.size;
  let emails = [];
  if (count > 0) {
    emails = state.recipientsPool.filter(r => state.selectedRecipientIds.has(r.id)).map(r => r.email);
  } else {
    emails = state.recipientsPool.map(r => r.email);
  }

  if (emails.length === 0) {
    showToast('No recipients available in pool.', 'error');
    return;
  }

  navigateTo('tasks');
  setTasksTab('bulk');
  const txt = document.getElementById('bulk-recipients-text');
  if (txt) {
    txt.value = emails.join('\n');
    debounceValidateRecipients();
  }
  showToast(`Loaded ${emails.length} recipient(s) into Bulk Campaign!`, 'success');
}

function importFromAppPoolToBulk() {
  useSelectedInCampaign();
}

// --- 6. EMAIL TASKS VIEW CONTROLLER ---

function setTasksTab(tabKey) {
  const tabs = ['send', 'bulk', 'dmtasks', 'history'];
  tabs.forEach(t => {
    const btn = document.getElementById(`tasks-tab-${t}`);
    const content = document.getElementById(`tasks-content-${t}`);
    if (btn && content) {
      if (t === tabKey) {
        btn.className = 'px-4 py-2 rounded-xl text-xs font-semibold bg-brand text-white shadow transition flex items-center gap-2';
        content.classList.remove('hidden');
      } else {
        btn.className = 'px-4 py-2 rounded-xl text-xs font-semibold text-slate-400 hover:text-white transition flex items-center gap-2';
        content.classList.add('hidden');
      }
    }
  });

  if (tabKey === 'dmtasks') loadAlibabaTasksTable();
  if (tabKey === 'history') loadHistoryJobs();
  initIcons();
}

async function loadTemplatesDropdown() {
  const singleSel = document.getElementById('send-template-select');
  const bulkSel = document.getElementById('bulk-template-select');
  if (!singleSel && !bulkSel) return;

  try {
    const res = await apiFetch('/api/app-templates?limit=100');
    const appTemplates = res.templates || [];
    state.localTemplates = appTemplates;

    const populate = (sel) => {
      if (!sel) return;
      sel.innerHTML = '<option value="">-- Custom Compose --</option>';
      if (appTemplates.length > 0) {
        const appGroup = document.createElement('optgroup');
        appGroup.label = 'Application Templates';
        appTemplates.forEach(t => {
          const opt = document.createElement('option');
          opt.value = t.id;
          const isApproved = t.status === 'approved' || t.dm_status === 1;
          const statusIcon = isApproved ? '✓ [Approved]' : `⏳ [${t.status || 'draft'}]`;
          opt.textContent = `${statusIcon} ${t.name} - "${t.subject || ''}"`;
          appGroup.appendChild(opt);
        });
        sel.appendChild(appGroup);
      }
    };

    populate(singleSel);
    populate(bulkSel);
  } catch (e) {
    console.warn('Failed loading app templates for dropdown:', e);
  }
}

async function handleSelectSendTemplate(templateId) {
  if (!templateId) return;
  const t = (state.localTemplates || []).find(x => String(x.id) === String(templateId));
  if (t) {
    const isApproved = t.status === 'approved' || t.dm_status === 1;
    if (!isApproved) {
      showToast(`Template '${t.name}' has review status '${t.status || 'draft'}'. DirectMail requires provider approval before sending.`, 'warning');
    } else {
      showToast(`Template '${t.name}' attached (DirectMail Approved).`, 'success');
    }

    if (t.subject) document.getElementById('send-subject').value = t.subject;
    if (t.html_content) {
      document.getElementById('send-html-body').value = t.html_content;
      setBodyTab('html');
    } else if (t.text_content) {
      document.getElementById('send-text-body').value = t.text_content;
      setBodyTab('text');
    }
    if (t.from_alias) document.getElementById('send-from-alias').value = t.from_alias;
    return;
  }

  // Fallback to remote directmail template query if numeric ID
  try {
    const res = await apiFetch(`/api/templates/${state.activeSendRegion}/${templateId}`);
    const d = res.detail || {};
    if (d.TemplateSubject) document.getElementById('send-subject').value = d.TemplateSubject;
    if (d.TemplateText) {
      document.getElementById('send-html-body').value = d.TemplateText;
      setBodyTab('html');
    }
    if (d.TemplateNickName) document.getElementById('send-from-alias').value = d.TemplateNickName;
    showToast(`Applied remote template: ${d.TemplateName || templateId}`, 'info');
  } catch (err) {
    showToast('Failed to load template: ' + err.message, 'error');
  }
}

async function handleSelectBulkTemplate(templateId) {
  if (!templateId) return;
  const t = (state.localTemplates || []).find(x => String(x.id) === String(templateId));
  if (t) {
    const isApproved = t.status === 'approved' || t.dm_status === 1;
    if (!isApproved) {
      showToast(`Template '${t.name}' has review status '${t.status || 'draft'}'. DirectMail requires provider approval before dispatch.`, 'warning');
    } else {
      showToast(`Template '${t.name}' attached to campaign (DirectMail Approved).`, 'success');
    }

    if (t.subject) document.getElementById('bulk-subject').value = t.subject;
    if (t.html_content) {
      document.getElementById('bulk-body').value = t.html_content;
    } else if (t.text_content) {
      document.getElementById('bulk-body').value = t.text_content;
    }
  }
}

function selectSendRegion(regionKey) {
  state.activeSendRegion = regionKey;
  document.querySelectorAll('#send-region-selector .region-pill').forEach(btn => {
    if (btn.getAttribute('data-region') === regionKey) {
      btn.className = 'region-pill px-3 py-1.5 rounded-lg text-xs font-medium transition flex items-center gap-1.5 bg-brand text-white shadow';
    } else {
      btn.className = 'region-pill px-3 py-1.5 rounded-lg text-xs font-medium text-slate-400 hover:text-white transition flex items-center gap-1.5';
    }
  });
  updateSendRegionUI(regionKey);
  loadTemplatesDropdown();
}

function updateSendRegionUI(regionKey) {
  const reg = state.regions.find(r => r.key === regionKey);
  if (!reg) return;

  const hint = document.getElementById('send-endpoint-hint');
  if (hint) hint.textContent = `(Endpoint: ${reg.endpoint})`;

  const select = document.getElementById('send-sender-select');
  if (!select) return;
  select.innerHTML = '';
  const senders = reg.verified_senders || [];
  if (senders.length === 0) {
    select.innerHTML = '<option value="">No verified senders configured for this region</option>';
  } else {
    senders.forEach(s => {
      const opt = document.createElement('option');
      opt.value = s.email;
      opt.textContent = s.alias ? `${s.alias} <${s.email}>` : s.email;
      if (s.is_default) opt.selected = true;
      select.appendChild(opt);
    });
  }
}

function setBodyTab(tab) {
  ['html', 'text', 'preview'].forEach(t => {
    const btn = document.getElementById(`tab-btn-${t}`);
    const el = document.getElementById(`body-tab-${t}`);
    if (btn && el) {
      if (t === tab) {
        btn.className = 'px-2.5 py-1 rounded-md font-medium text-brand bg-brand/10 border border-brand/20';
        el.classList.remove('hidden');
      } else {
        btn.className = 'px-2.5 py-1 rounded-md font-medium text-slate-400 hover:text-white';
        el.classList.add('hidden');
      }
    }
  });

  if (tab === 'preview') {
    const htmlVal = document.getElementById('send-html-body').value;
    const txtVal = document.getElementById('send-text-body').value;
    const container = document.getElementById('html-preview-content');
    if (htmlVal.trim()) {
      container.innerHTML = htmlVal;
    } else if (txtVal.trim()) {
      container.innerHTML = `<pre class="whitespace-pre-wrap font-sans text-xs text-slate-800">${escapeHtml(txtVal)}</pre>`;
    } else {
      container.innerHTML = '<p class="text-slate-400 italic text-center py-4">No content entered to preview.</p>';
    }
  }
}

function toggleSingleSchedFields() {
  const toggle = document.getElementById('single-sched-toggle');
  const fields = document.getElementById('single-sched-fields');
  const pill = document.getElementById('single-sched-status-pill');
  const btnLabel = document.getElementById('btn-send-now-label');
  if (!toggle) return;

  if (toggle.checked) {
    fields?.classList.remove('hidden');
    if (pill) {
      pill.textContent = 'Scheduled Send';
      pill.className = 'text-[11px] px-2 py-0.5 rounded bg-blue-500/20 text-blue-300 border border-blue-500/30';
    }
    if (btnLabel) btnLabel.textContent = 'Schedule Email';

    const dateInput = document.getElementById('single-sched-date');
    const timeInput = document.getElementById('single-sched-time');
    if (dateInput && !dateInput.value) {
      const tomorrow = new Date();
      tomorrow.setDate(tomorrow.getDate() + 1);
      dateInput.value = tomorrow.toISOString().split('T')[0];
    }
    if (timeInput && !timeInput.value) {
      timeInput.value = '09:00';
    }
  } else {
    fields?.classList.add('hidden');
    if (pill) {
      pill.textContent = 'Send Immediately';
      pill.className = 'text-[11px] px-2 py-0.5 rounded bg-slate-800 text-slate-400';
    }
    if (btnLabel) btnLabel.textContent = 'Send Now';
  }
}

async function handleSendSubmit(e) {
  e.preventDefault();
  const btn = document.getElementById('btn-send-now');
  const isSched = document.getElementById('single-sched-toggle')?.checked;

  btn.disabled = true;
  btn.innerHTML = `<i data-lucide="loader-2" class="w-4 h-4 animate-spin"></i><span>${isSched ? 'Scheduling...' : 'Sending...'}</span>`;
  initIcons();

  let scheduledAt = null;
  let timezoneName = 'Asia/Kolkata';
  if (isSched) {
    const dateVal = document.getElementById('single-sched-date')?.value;
    const timeVal = document.getElementById('single-sched-time')?.value;
    if (!dateVal || !timeVal) {
      showToast('Please specify both Date and Time for scheduled execution.', 'error');
      btn.disabled = false;
      btn.innerHTML = '<i data-lucide="send" class="w-4 h-4"></i><span>Schedule Email</span>';
      initIcons();
      return;
    }
    scheduledAt = `${dateVal} ${timeVal}`;
    timezoneName = document.getElementById('single-sched-tz')?.value || 'Asia/Kolkata';
  }

  const tmplVal = document.getElementById('send-template-select')?.value;
  const templateId = tmplVal ? parseInt(tmplVal) : null;
  const tagVal = document.getElementById('send-tag-select')?.value;
  const tagName = tagVal || (document.getElementById('send-tag-name')?.value.trim() || null);

  const payload = {
    region: state.activeSendRegion,
    sender: document.getElementById('send-sender-select').value,
    recipient: document.getElementById('send-recipient').value.trim(),
    subject: document.getElementById('send-subject').value.trim(),
    html_body: document.getElementById('send-html-body').value,
    text_body: document.getElementById('send-text-body').value,
    from_alias: document.getElementById('send-from-alias').value.trim() || null,
    tag_name: tagName,
    template_id: templateId,
    address_type: parseInt(document.getElementById('send-address-type').value) || 1,
    reply_to: document.getElementById('send-reply-to').value === 'true',
    scheduled_at: scheduledAt,
    timezone_name: timezoneName
  };

  try {
    const res = await apiFetch('/api/send', {
      method: 'POST',
      body: JSON.stringify(payload)
    });

    if (isSched) {
      showToast(res.message || 'Email successfully scheduled!', 'success');
    } else {
      showToast(`Email dispatched! DirectMail RequestId: ${res.request_id || res.id}`, 'success');
    }
    document.getElementById('send-recipient').value = '';
    loadHistoryJobs();
    loadScheduledJobs();
  } catch (err) {
    showToast(`Send Error: ${err.message}`, 'error');
  } finally {
    btn.disabled = false;
    btn.innerHTML = `<i data-lucide="send" class="w-4 h-4"></i><span id="btn-send-now-label">${isSched ? 'Schedule Email' : 'Send Now'}</span>`;
    initIcons();
  }
}

// Bulk Campaign Controller
function selectBulkRegion(regKey) {
  state.activeBulkRegion = regKey;
  document.querySelectorAll('.bulk-region-pill').forEach(btn => {
    if (btn.getAttribute('data-region') === regKey) {
      btn.className = 'bulk-region-pill px-3 py-1.5 rounded-lg text-xs font-medium transition bg-brand text-white shadow';
    } else {
      btn.className = 'bulk-region-pill px-3 py-1.5 rounded-lg text-xs font-medium text-slate-400 hover:text-white transition';
    }
  });
  updateBulkRegionUI(regKey);
}

function updateBulkRegionUI(regKey) {
  const select = document.getElementById('bulk-sender-select');
  if (!select) return;
  select.innerHTML = '';
  const senders = state.verifiedSenders[regKey] || [];
  senders.forEach(s => {
    const opt = document.createElement('option');
    opt.value = s.email;
    opt.textContent = s.alias ? `${s.alias} <${s.email}>` : s.email;
    if (s.is_default) opt.selected = true;
    select.appendChild(opt);
  });
}

function handleDragOver(e) {
  e.preventDefault();
  document.getElementById('csv-drop-zone').classList.add('border-purple-400', 'bg-purple-950/20');
}
function handleDragLeave(e) {
  e.preventDefault();
  document.getElementById('csv-drop-zone').classList.remove('border-purple-400', 'bg-purple-950/20');
}
function handleFileDrop(e) {
  e.preventDefault();
  handleDragLeave(e);
  if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
    processUploadedFile(e.dataTransfer.files[0]);
  }
}
function handleFileSelect(e) {
  if (e.target.files && e.target.files.length > 0) {
    processUploadedFile(e.target.files[0]);
  }
}
function processUploadedFile(file) {
  const reader = new FileReader();
  reader.onload = async (event) => {
    const content = event.target.result;
    try {
      const res = await apiFetch('/api/validate-recipients', {
        method: 'POST',
        body: JSON.stringify({ csv_content: content })
      });
      applyValidationReport(res);
      showToast(`Loaded ${res.valid.length} valid recipient(s) from ${file.name}`, 'info');
    } catch (err) {
      showToast('CSV Parsing Error: ' + err.message, 'error');
    }
  };
  reader.readAsText(file);
}

let debounceTimer = null;
function debounceValidateRecipients() {
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(async () => {
    const rawText = document.getElementById('bulk-recipients-text').value;
    if (!rawText.trim()) {
      applyValidationReport({ total: 0, valid: [], invalid: [], duplicates: [] });
      return;
    }
    try {
      const res = await apiFetch('/api/validate-recipients', {
        method: 'POST',
        body: JSON.stringify({ raw_text: rawText })
      });
      applyValidationReport(res);
    } catch (e) {}
  }, 400);
}

function applyValidationReport(report) {
  state.bulkValidRecipients = report.valid || [];
  state.bulkInvalidRecipients = report.invalid || [];
  state.bulkExcludedRecipients.clear();
  document.getElementById('stat-valid-count').textContent = report.valid.length;
  document.getElementById('stat-invalid-count').textContent = report.invalid.length;
  document.getElementById('stat-duplicate-count').textContent = report.duplicates.length;
  document.getElementById('stat-total-count').textContent = report.total;

  renderBulkExclusionUI();
}

function renderBulkExclusionUI() {
  const panel = document.getElementById('bulk-exclusion-panel');
  if (!panel) return;

  const total = state.bulkValidRecipients.length;
  if (total === 0) {
    panel.classList.add('hidden');
    return;
  }
  panel.classList.remove('hidden');

  const excluded = state.bulkExcludedRecipients.size;
  const queued = Math.max(0, total - excluded);

  const summary = document.getElementById('bulk-exclusion-summary');
  if (summary) {
    summary.textContent = `${total} selected • ${excluded} excluded • ${queued} queued to send`;
  }

  // Excluded chips container
  const excludedCont = document.getElementById('bulk-excluded-container');
  const excludedChips = document.getElementById('bulk-excluded-chips');
  const excludedBadge = document.getElementById('bulk-excluded-count-badge');
  if (excludedBadge) excludedBadge.textContent = excluded;

  if (excluded > 0 && excludedCont && excludedChips) {
    excludedCont.classList.remove('hidden');
    let chipsHtml = '';
    state.bulkExcludedRecipients.forEach(email => {
      chipsHtml += `
        <span class="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-mono bg-rose-950/80 border border-rose-500/30 text-rose-300">
          <span>${escapeHtml(email)}</span>
          <button type="button" onclick="restoreExcludedRecipient('${escapeHtml(email)}')" class="hover:text-white font-bold ml-1" title="Restore to campaign">×</button>
        </span>
      `;
    });
    excludedChips.innerHTML = chipsHtml;
  } else if (excludedCont) {
    excludedCont.classList.add('hidden');
  }

  // Active recipients list preview
  const activeList = document.getElementById('bulk-active-recipient-list');
  if (activeList) {
    const searchVal = (state.bulkAudienceSearch || '').toLowerCase().trim();
    let activeEmails = state.bulkValidRecipients.filter(r => !state.bulkExcludedRecipients.has(r.toLowerCase().trim()));
    if (searchVal) {
      activeEmails = activeEmails.filter(e => e.toLowerCase().includes(searchVal));
    }

    if (activeEmails.length === 0) {
      activeList.innerHTML = `<p class="text-slate-500 italic text-[11px] p-2">No matching recipients in queue.</p>`;
    } else {
      let listHtml = '';
      activeEmails.forEach(email => {
        listHtml += `
          <div class="flex items-center justify-between py-1 px-2 hover:bg-slate-900 rounded transition">
            <label class="flex items-center gap-2 cursor-pointer font-mono text-slate-200 text-[11px]">
              <input type="checkbox" class="audience-select-check accent-purple-500 rounded" value="${escapeHtml(email)}">
              <span>${escapeHtml(email)}</span>
            </label>
            <button type="button" onclick="excludeRecipientFromBulk('${escapeHtml(email)}')" class="px-2 py-0.5 text-[10px] rounded bg-rose-500/10 hover:bg-rose-500/20 text-rose-300 border border-rose-500/30 font-medium">
              Exclude
            </button>
          </div>
        `;
      });
      activeList.innerHTML = listHtml;
    }
  }
}

function filterAudiencePreview() {
  const searchInput = document.getElementById('bulk-audience-search');
  state.bulkAudienceSearch = searchInput ? searchInput.value : '';
  renderBulkExclusionUI();
}

function excludeSelectedAudience() {
  const checkedBoxes = document.querySelectorAll('.audience-select-check:checked');
  if (checkedBoxes.length === 0) {
    showToast('Please check one or more recipients to exclude.', 'info');
    return;
  }
  let count = 0;
  checkedBoxes.forEach(cb => {
    state.bulkExcludedRecipients.add(cb.value.toLowerCase().trim());
    count++;
  });
  renderBulkExclusionUI();
  showToast(`Excluded ${count} recipient(s) from campaign. They remain safe in the Recipient Pool.`, 'info');
}

function excludeRecipientFromBulk(email) {
  state.bulkExcludedRecipients.add(email.toLowerCase().trim());
  renderBulkExclusionUI();
  showToast(`Excluded ${email} from this campaign (remains safe in master pool).`, 'info');
}

function restoreExcludedRecipient(email) {
  state.bulkExcludedRecipients.delete(email.toLowerCase().trim());
  renderBulkExclusionUI();
}

function restoreAllExcludedRecipients() {
  state.bulkExcludedRecipients.clear();
  renderBulkExclusionUI();
  showToast('Restored all recipients to this task.', 'info');
}

function toggleAudienceListVisibility() {
  const list = document.getElementById('bulk-active-recipient-list');
  const btn = document.getElementById('btn-toggle-audience');
  if (!list || !btn) return;
  if (list.classList.contains('hidden')) {
    list.classList.remove('hidden');
    btn.textContent = 'Hide recipient details';
  } else {
    list.classList.add('hidden');
    btn.textContent = 'Show recipient details';
  }
}

function toggleBulkSchedFields() {
  const toggle = document.getElementById('bulk-sched-toggle');
  const fields = document.getElementById('bulk-sched-fields');
  const pill = document.getElementById('bulk-sched-status-pill');
  if (!toggle) return;

  if (toggle.checked) {
    fields?.classList.remove('hidden');
    if (pill) {
      pill.textContent = 'Scheduled Campaign';
      pill.className = 'text-[11px] px-2 py-0.5 rounded bg-purple-500/20 text-purple-300 border border-purple-500/30';
    }
    const dateInput = document.getElementById('bulk-sched-date');
    const timeInput = document.getElementById('bulk-sched-time');
    if (dateInput && !dateInput.value) {
      const tomorrow = new Date();
      tomorrow.setDate(tomorrow.getDate() + 1);
      dateInput.value = tomorrow.toISOString().split('T')[0];
    }
    if (timeInput && !timeInput.value) {
      timeInput.value = '10:00';
    }
  } else {
    fields?.classList.add('hidden');
    if (pill) {
      pill.textContent = 'Send Immediately';
      pill.className = 'text-[11px] px-2 py-0.5 rounded bg-slate-800 text-slate-400';
    }
  }
}

function triggerBulkSafetyModal() {
  const validCount = state.bulkValidRecipients.length;
  const excludedCount = state.bulkExcludedRecipients.size;
  const queuedCount = validCount - excludedCount;

  if (validCount === 0 || queuedCount <= 0) {
    showToast('Please ensure at least one active recipient is queued to send.', 'error');
    return;
  }
  const subject = document.getElementById('bulk-subject').value.trim();
  if (!subject) {
    showToast('Please enter an email subject.', 'error');
    return;
  }
  const body = document.getElementById('bulk-body').value.trim();
  if (!body) {
    showToast('Please enter campaign email content.', 'error');
    return;
  }

  const isSched = document.getElementById('bulk-sched-toggle')?.checked;
  let scheduleText = 'Immediate Dispatch (Rate-Limited)';
  if (isSched) {
    const dateVal = document.getElementById('bulk-sched-date')?.value;
    const timeVal = document.getElementById('bulk-sched-time')?.value;
    const tzVal = document.getElementById('bulk-sched-tz')?.value || 'Asia/Kolkata';
    if (!dateVal || !timeVal) {
      showToast('Please enter execution date and time for scheduled campaign.', 'error');
      return;
    }
    scheduleText = `Scheduled for ${dateVal} at ${timeVal} (${tzVal})`;
  }

  document.getElementById('confirm-recipient-count').textContent = `${queuedCount} Active (${excludedCount} Excluded)`;
  document.getElementById('confirm-region').textContent = state.activeBulkRegion.toUpperCase();
  document.getElementById('confirm-sender').textContent = document.getElementById('bulk-sender-select').value;
  document.getElementById('confirm-subject').textContent = subject;
  document.getElementById('confirm-schedule').textContent = scheduleText;
  document.getElementById('bulk-safety-modal').classList.remove('hidden');
}

function closeBulkSafetyModal() {
  document.getElementById('bulk-safety-modal').classList.add('hidden');
}

async function confirmAndDispatchBulk() {
  closeBulkSafetyModal();

  const isSched = document.getElementById('bulk-sched-toggle')?.checked;
  let scheduledAt = null;
  let tzName = state.settings.default_timezone || 'Asia/Kolkata';
  if (isSched) {
    const dateVal = document.getElementById('bulk-sched-date')?.value;
    const timeVal = document.getElementById('bulk-sched-time')?.value;
    if (!dateVal || !timeVal) {
      showToast('Please enter both date and time for scheduled campaign.', 'error');
      return;
    }
    scheduledAt = `${dateVal} ${timeVal}`;
    tzName = document.getElementById('bulk-sched-tz')?.value || tzName;
  }

  const tmplVal = document.getElementById('bulk-template-select')?.value;
  const templateId = tmplVal ? parseInt(tmplVal) : null;
  const tagVal = document.getElementById('bulk-tag-select')?.value;
  const tagName = tagVal || null;

  const payload = {
    campaign_name: document.getElementById('bulk-campaign-name').value.trim() || null,
    region: state.activeBulkRegion,
    sender: document.getElementById('bulk-sender-select').value,
    recipients: state.bulkValidRecipients,
    excluded_recipients: Array.from(state.bulkExcludedRecipients),
    subject: document.getElementById('bulk-subject').value.trim(),
    html_body: document.getElementById('bulk-body').value,
    template_id: templateId,
    tag_name: tagName,
    scheduled_at: scheduledAt,
    timezone_name: tzName
  };

  try {
    const res = await apiFetch('/api/send-bulk', {
      method: 'POST',
      body: JSON.stringify(payload)
    });
    showToast(res.message, 'success');
    loadScheduledCampaignsTable();
    setTasksTab('history');
  } catch (err) {
    showToast(`Bulk Dispatch Error: ${err.message}`, 'error');
  }
}

// Alibaba DirectMail Batch Tasks
async function loadAlibabaTasksTable() {
  const tbody = document.getElementById('dmtasks-table-body');
  if (!tbody) return;
  tbody.innerHTML = `<tr><td colspan="6" class="text-center py-6 text-slate-500 italic">Querying tasks from Alibaba Cloud DirectMail...</td></tr>`;

  try {
    const res = await apiFetch(`/api/dm-tasks/${state.activeRegion}?page_size=20`);
    const tasks = res.tasks || [];
    if (tasks.length === 0) {
      tbody.innerHTML = `<tr><td colspan="6" class="text-center py-6 text-slate-500 italic">No batch tasks found on Alibaba Cloud infrastructure for ${state.activeRegion}.</td></tr>`;
      return;
    }

    let html = '';
    tasks.forEach(t => {
      html += `
        <tr class="hover:bg-slate-900/40 transition">
          <td class="py-3 px-4 font-mono font-bold text-cyan-400">${t.TaskId}</td>
          <td class="py-3 px-4 font-medium text-white">${escapeHtml(t.TemplateName || 'N/A')}</td>
          <td class="py-3 px-4 font-mono text-slate-300 text-xs">${escapeHtml(t.ReceiversName || 'N/A')}</td>
          <td class="py-3 px-4 font-mono text-xs text-slate-400">${t.AddressType === 1 ? 'Console Sender' : 'Random'}</td>
          <td class="py-3 px-4">
            <span class="px-2 py-0.5 rounded text-[10px] font-mono ${t.TaskStatus === 1 ? 'bg-emerald-500/20 text-emerald-300' : 'bg-blue-500/20 text-blue-300'}">
              Status ${t.TaskStatus}
            </span>
          </td>
          <td class="py-3 px-4 font-mono text-slate-400 text-xs">${formatTimestamp(t.UtcCreateTime)}</td>
        </tr>
      `;
    });
    tbody.innerHTML = html;
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="6" class="text-center py-6 text-rose-400 italic">Error loading tasks: ${escapeHtml(err.message)}</td></tr>`;
  }
}

// Local History Jobs
let historyFilterDebounce = null;
function handleHistoryFilterChange() {
  clearTimeout(historyFilterDebounce);
  historyFilterDebounce = setTimeout(() => {
    state.historyPage = 0;
    loadHistoryJobs();
  }, 300);
}

function changeHistoryPage(delta) {
  const newPage = state.historyPage + delta;
  if (newPage < 0 || newPage * state.historyLimit >= state.historyTotal) return;
  state.historyPage = newPage;
  loadHistoryJobs();
}

async function loadHistoryJobs() {
  const status = document.getElementById('history-status-filter') ? document.getElementById('history-status-filter').value : '';
  const search = document.getElementById('history-search') ? document.getElementById('history-search').value.trim() : '';
  const offset = state.historyPage * state.historyLimit;

  let url = `/api/jobs?limit=${state.historyLimit}&offset=${offset}`;
  if (status) url += `&status=${encodeURIComponent(status)}`;
  if (search) url += `&search=${encodeURIComponent(search)}`;

  try {
    const data = await apiFetch(url);
    state.historyTotal = data.total || 0;
    const tbody = document.getElementById('history-table-body');
    if (!tbody) return;
    tbody.innerHTML = '';

    if (!data.items || data.items.length === 0) {
      tbody.innerHTML = `<tr><td colspan="7" class="text-center py-8 text-slate-500 italic">No email logs found.</td></tr>`;
      const pInfo = document.getElementById('history-pagination-info');
      if (pInfo) pInfo.textContent = 'Showing 0 of 0 logs';
      return;
    }

    data.items.forEach(job => {
      const tr = document.createElement('tr');
      tr.className = 'hover:bg-slate-900/50 transition cursor-pointer';
      tr.onclick = () => openJobDetail(job.id);
      tr.innerHTML = `
        <td class="py-3 px-4 font-mono text-slate-400 whitespace-nowrap">${formatTimestamp(job.created_at)}</td>
        <td class="py-3 px-4 font-medium text-white">${escapeHtml(job.recipient)}</td>
        <td class="py-3 px-4 text-slate-400 max-w-[150px] truncate">${escapeHtml(job.sender)}</td>
        <td class="py-3 px-4">
          <span class="px-2 py-0.5 rounded text-[10px] font-medium region-${job.region} capitalize">${job.region}</span>
        </td>
        <td class="py-3 px-4 text-slate-300 max-w-[180px] truncate">${escapeHtml(job.subject)}</td>
        <td class="py-3 px-4">
          <span class="px-2 py-0.5 rounded text-[10px] font-medium badge-${job.status} capitalize">${job.status}</span>
        </td>
        <td class="py-3 px-4 text-right">
          <button onclick="event.stopPropagation(); openJobDetail('${job.id}')" class="text-brand hover:underline">Inspect</button>
        </td>
      `;
      tbody.appendChild(tr);
    });

    const start = offset + 1;
    const end = Math.min(offset + data.items.length, data.total);
    const pInfo = document.getElementById('history-pagination-info');
    if (pInfo) pInfo.textContent = `Showing ${start}-${end} of ${data.total} logs`;
  } catch (err) {
    console.warn('History load error:', err);
  }
}

// --- 7. SCHEDULING VIEW CONTROLLER ---

function setSchedTab(tabKey) {
  const tabs = ['new', 'queue'];
  tabs.forEach(t => {
    const btn = document.getElementById(`sched-tab-${t}`);
    const content = document.getElementById(`sched-content-${t}`);
    if (btn && content) {
      if (t === tabKey) {
        btn.className = 'px-4 py-2 rounded-xl text-xs font-semibold bg-blue-600 text-white shadow transition flex items-center gap-2';
        content.classList.remove('hidden');
      } else {
        btn.className = 'px-4 py-2 rounded-xl text-xs font-semibold text-slate-400 hover:text-white transition flex items-center gap-2';
        content.classList.add('hidden');
      }
    }
  });

  if (tabKey === 'queue') loadScheduledJobs();
  initIcons();
}

function initScheduleDefaults() {
  const now = new Date();
  now.setMinutes(now.getMinutes() + 15);
  const dateStr = now.toISOString().split('T')[0];
  const hours = String(now.getHours()).padStart(2, '0');
  const minutes = String(now.getMinutes()).padStart(2, '0');
  
  const dateInput = document.getElementById('sched-date');
  const timeInput = document.getElementById('sched-time');
  if (dateInput) dateInput.value = dateStr;
  if (timeInput) timeInput.value = `${hours}:${minutes}`;
}

function updateSchedSenders() {
  const select = document.getElementById('sched-sender-select');
  if (!select) return;
  const regKey = document.getElementById('sched-region-select').value;
  state.activeSchedRegion = regKey;
  select.innerHTML = '';
  const senders = state.verifiedSenders[regKey] || [];
  senders.forEach(s => {
    const opt = document.createElement('option');
    opt.value = s.email;
    opt.textContent = s.alias ? `${s.alias} <${s.email}>` : s.email;
    if (s.is_default) opt.selected = true;
    select.appendChild(opt);
  });
}

async function handleDedicatedSchedule(e) {
  e.preventDefault();
  const dateVal = document.getElementById('sched-date').value;
  const timeVal = document.getElementById('sched-time').value;
  const tzVal = document.getElementById('sched-timezone').value;

  const payload = {
    region: document.getElementById('sched-region-select').value,
    sender: document.getElementById('sched-sender-select').value,
    recipient: document.getElementById('sched-recipient').value.trim(),
    subject: document.getElementById('sched-subject').value.trim(),
    text_body: document.getElementById('sched-body').value,
    scheduled_at: `${dateVal} ${timeVal}`,
    timezone_name: tzVal
  };

  try {
    const res = await apiFetch('/api/send', {
      method: 'POST',
      body: JSON.stringify(payload)
    });
    showToast(res.message || 'Email scheduled successfully!', 'success');
    setSchedTab('queue');
  } catch (err) {
    showToast(`Scheduling error: ${err.message}`, 'error');
  }
}

function openScheduleModalFromSendForm() {
  navigateTo('scheduling');
  setSchedTab('new');
  const rec = document.getElementById('send-recipient').value;
  const sub = document.getElementById('send-subject').value;
  const body = document.getElementById('send-html-body').value || document.getElementById('send-text-body').value;
  if (rec) document.getElementById('sched-recipient').value = rec;
  if (sub) document.getElementById('sched-subject').value = sub;
  if (body) document.getElementById('sched-body').value = body;
}

async function loadScheduledJobs() {
  try {
    const res = await apiFetch('/api/jobs?status=scheduled&limit=50');
    const tbody = document.getElementById('scheduled-table-body');
    if (!tbody) return;
    tbody.innerHTML = '';
    const badge = document.getElementById('badge-scheduled-count');
    if (badge) badge.textContent = res.total || 0;

    if (!res.items || res.items.length === 0) {
      tbody.innerHTML = `<tr><td colspan="6" class="text-center py-8 text-slate-500 italic">No scheduled emails waiting in queue.</td></tr>`;
      return;
    }

    res.items.forEach(job => {
      const tr = document.createElement('tr');
      tr.className = 'hover:bg-slate-900/40 transition';
      tr.innerHTML = `
        <td class="py-3 px-4 font-mono text-cyan-400">
          ${formatTimestamp(job.scheduled_at)}
          <span class="block text-[10px] text-slate-500">${job.timezone_name || 'UTC'}</span>
        </td>
        <td class="py-3 px-4">
          <span class="px-2 py-0.5 rounded text-[10px] font-medium region-${job.region} capitalize">${job.region}</span>
        </td>
        <td class="py-3 px-4 font-medium text-white">${escapeHtml(job.recipient)}</td>
        <td class="py-3 px-4 text-slate-300 max-w-[200px] truncate">${escapeHtml(job.subject)}</td>
        <td class="py-3 px-4"><span class="px-2 py-0.5 rounded text-[10px] font-medium badge-scheduled">Scheduled</span></td>
        <td class="py-3 px-4 text-right space-x-2">
          <button onclick="openRescheduleModal('${job.id}')" class="px-2.5 py-1 text-[11px] rounded bg-blue-500/10 hover:bg-blue-500/20 text-blue-300 border border-blue-500/30">Reschedule</button>
          <button onclick="cancelJob('${job.id}')" class="px-2.5 py-1 text-[11px] rounded bg-rose-500/10 hover:bg-rose-500/20 text-rose-300 border border-rose-500/30">Cancel</button>
        </td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {
    console.warn('Error loading scheduled jobs', err);
  }
}

async function cancelJob(jobId) {
  showDeleteConfirm({
    title: 'Cancel Scheduled Job',
    message: `Are you sure you want to cancel scheduled email job <strong>${jobId}</strong>?`,
    onConfirm: async () => {
      try {
        await apiFetch(`/api/jobs/${jobId}/cancel`, { method: 'POST' });
        showToast('Scheduled job cancelled.', 'info');
        loadScheduledJobs();
      } catch (err) {
        showToast(err.message, 'error');
      }
    }
  });
}

function openRescheduleModal(jobId) {
  document.getElementById('resched-job-id').value = jobId;
  const now = new Date();
  now.setHours(now.getHours() + 1);
  document.getElementById('resched-new-date').value = now.toISOString().split('T')[0];
  document.getElementById('resched-new-time').value = `${String(now.getHours()).padStart(2, '0')}:00`;
  document.getElementById('reschedule-modal').classList.remove('hidden');
}

function closeRescheduleModal() {
  document.getElementById('reschedule-modal').classList.add('hidden');
}

async function confirmReschedule() {
  const jobId = document.getElementById('resched-job-id').value;
  const d = document.getElementById('resched-new-date').value;
  const t = document.getElementById('resched-new-time').value;
  const tz = document.getElementById('resched-new-tz').value;

  try {
    await apiFetch(`/api/jobs/${jobId}/reschedule`, {
      method: 'POST',
      body: JSON.stringify({ scheduled_at: `${d} ${t}`, timezone_name: tz })
    });
    closeRescheduleModal();
    showToast('Job rescheduled successfully!', 'success');
    loadScheduledJobs();
  } catch (err) {
    showToast(err.message, 'error');
  }
}

// --- 8. DELIVERY VIEW CONTROLLER ---

function setDeliveryRange(rangePreset) {
  state.deliveryRange = rangePreset;
  ['today', 'yesterday', '7d', '30d'].forEach(k => {
    const btn = document.getElementById(`btn-deliv-${k}`);
    if (btn) {
      if (k === rangePreset) {
        btn.className = 'px-3 py-1.5 rounded-lg font-medium bg-teal-600 text-white shadow transition';
      } else {
        btn.className = 'px-3 py-1.5 rounded-lg font-medium text-slate-400 hover:text-white transition';
      }
    }
  });
  const sInput = document.getElementById('deliv-custom-start');
  const eInput = document.getElementById('deliv-custom-end');
  if (sInput) sInput.value = '';
  if (eInput) eInput.value = '';
  loadDeliveryStats();
}

function applyDeliveryCustomDateRange() {
  const startVal = document.getElementById('deliv-custom-start') ? document.getElementById('deliv-custom-start').value : '';
  const endVal = document.getElementById('deliv-custom-end') ? document.getElementById('deliv-custom-end').value : '';
  if (!startVal || !endVal) {
    showToast('Please select both start and end dates.', 'error');
    return;
  }
  ['today', 'yesterday', '7d', '30d'].forEach(k => {
    const btn = document.getElementById(`btn-deliv-${k}`);
    if (btn) {
      btn.className = 'px-3 py-1.5 rounded-lg font-medium text-slate-400 hover:text-white transition';
    }
  });
  loadDeliveryStats(startVal, endVal);
}

async function loadDeliveryStats(customStart = null, customEnd = null) {
  const range = state.deliveryRange || '7d';
  const regBadge = document.getElementById('deliv-region-badge');
  if (regBadge) regBadge.textContent = state.activeRegion.toUpperCase();

  let url = `/api/delivery-stats/${state.activeRegion}`;
  if (customStart && customEnd) {
    url += `?start_date=${encodeURIComponent(customStart)}&end_date=${encodeURIComponent(customEnd)}`;
  } else {
    url += `?range=${range}`;
  }

  const tagVal = document.getElementById('deliv-tag-filter')?.value;
  if (tagVal) {
    url += `&tag_name=${encodeURIComponent(tagVal)}`;
  }

  try {
    const res = await apiFetch(url);
    const aggr = res.aggregate || {};
    const statsList = res.daily_breakdown || [];

    const setTxt = (id, txt) => {
      const el = document.getElementById(id);
      if (el) el.textContent = txt;
    };

    setTxt('deliv-stat-requests', (aggr.total_requests || 0).toLocaleString());
    setTxt('deliv-stat-delivery-rate', `${aggr.delivery_rate || 0}%`);
    setTxt('deliv-stat-success-count', `(${aggr.total_success || 0} ok)`);
    setTxt('deliv-stat-failure-rate', `${aggr.failure_rate || 0}%`);
    setTxt('deliv-stat-failed-count', `(${aggr.total_failed || 0} failed)`);
    setTxt('deliv-stat-bounce-rate', `${aggr.bounce_rate || 0}%`);
    setTxt('deliv-stat-unavailable-count', `(${aggr.total_unavailable || 0} unavail)`);

    // Engagement & Suppression Metrics
    setTxt('deliv-stat-invalid-count', (aggr.total_invalid || 0).toLocaleString());
    setTxt('deliv-stat-open-rate', `${aggr.open_rate || 0}%`);
    setTxt('deliv-stat-unique-open-rate', `(${aggr.unique_open_rate || 0}% uniq)`);
    setTxt('deliv-stat-open-count', (aggr.total_open_count || 0).toLocaleString());
    setTxt('deliv-stat-unique-open-count', (aggr.total_unique_open_count || 0).toLocaleString());
    setTxt('deliv-stat-click-rate', `${aggr.click_rate || 0}%`);
    setTxt('deliv-stat-unique-click-rate', `(${aggr.unique_click_rate || 0}% uniq)`);
    setTxt('deliv-stat-click-count', (aggr.total_click_count || 0).toLocaleString());
    setTxt('deliv-stat-unique-click-count', (aggr.total_unique_click_count || 0).toLocaleString());

    const tbody = document.getElementById('delivery-stats-tbody');
    if (!tbody) return;

    if (statsList.length === 0) {
      tbody.innerHTML = `<tr><td colspan="6" class="text-center py-6 text-slate-500 italic">No delivery statistics recorded for ${state.activeRegion} in this date range.</td></tr>`;
      return;
    }

    let html = '';
    statsList.forEach(s => {
      html += `
        <tr class="hover:bg-slate-900/40 transition">
          <td class="py-3 px-4 font-mono font-medium text-white">${s.CreateTime || 'Date'}</td>
          <td class="py-3 px-4 font-mono text-slate-200">${(s.requestCount || 0).toLocaleString()}</td>
          <td class="py-3 px-4 font-mono text-emerald-400">${(s.successCount || 0).toLocaleString()}</td>
          <td class="py-3 px-4 font-mono text-rose-400">${(s.faildCount || 0).toLocaleString()}</td>
          <td class="py-3 px-4 font-mono text-amber-400">${(s.unavailableCount || 0).toLocaleString()}</td>
          <td class="py-3 px-4 font-mono text-right font-bold text-teal-300">${s.succeededPercent || '100%'}</td>
        </tr>
      `;
    });
    tbody.innerHTML = html;
  } catch (err) {
    console.warn('Error loading delivery stats:', err);
  }
}

// Reconcile DirectMail Engine Trigger
async function triggerReconciliation() {
  const btns = [document.getElementById('btn-reconcile-deliv')].filter(Boolean);
  btns.forEach(b => {
    b.disabled = true;
    b.innerHTML = '<i data-lucide="loader-2" class="w-3.5 h-3.5 animate-spin"></i><span>Reconciling...</span>';
  });
  initIcons();

  try {
    const res = await apiFetch(`/api/reconciliation/${state.activeRegion}`, { method: 'POST' });
    showToast(`Reconciliation complete: ${res.updated_count} jobs updated with DirectMail timestamps (${res.matched_count} matched).`, 'success');
    if (state.currentView === 'delivery') loadDeliveryStats();
    if (state.currentView === 'tracking') loadTrackingFeed();
    if (state.currentView === 'audit') loadAuditLogsTable();
    loadHistoryJobs();
  } catch (err) {
    showToast(`Reconciliation failed: ${err.message}`, 'error');
  } finally {
    btns.forEach(b => {
      b.disabled = false;
      b.innerHTML = '<i data-lucide="refresh-cw" class="w-3.5 h-3.5"></i><span>Reconcile DirectMail</span>';
    });
    initIcons();
  }
}

// --- RECIPIENT DELIVERY DRILL-DOWN CONTROLLER ---

state.drilldownStatus = '';
state.drilldownPage = 1;
state.drilldownSearch = '';

function openDeliveryDrillDown(status = '') {
  state.drilldownStatus = status;
  state.drilldownPage = 1;
  state.drilldownSearch = '';

  const badge = document.getElementById('drilldown-status-badge');
  if (badge) {
    badge.textContent = status ? status.toUpperCase() : 'ALL STATUSES';
  }
  const statusFilter = document.getElementById('drilldown-status-filter');
  if (statusFilter) {
    statusFilter.value = status;
  }
  const searchInput = document.getElementById('drilldown-search-input');
  if (searchInput) searchInput.value = '';

  document.getElementById('modal-delivery-drilldown').classList.remove('hidden');
  initIcons();
  loadDrilldownRecords();
}

function closeDeliveryDrillDown() {
  document.getElementById('modal-delivery-drilldown').classList.add('hidden');
}

function changeDrilldownStatus(val) {
  state.drilldownStatus = val;
  state.drilldownPage = 1;
  const badge = document.getElementById('drilldown-status-badge');
  if (badge) badge.textContent = val ? val.toUpperCase() : 'ALL STATUSES';
  loadDrilldownRecords();
}

let drilldownSearchTimer = null;
function debounceDrilldownSearch() {
  clearTimeout(drilldownSearchTimer);
  drilldownSearchTimer = setTimeout(() => {
    state.drilldownSearch = document.getElementById('drilldown-search-input').value.trim();
    state.drilldownPage = 1;
    loadDrilldownRecords();
  }, 250);
}

function prevDrilldownPage() {
  if (state.drilldownPage > 1) {
    state.drilldownPage--;
    loadDrilldownRecords();
  }
}

function nextDrilldownPage() {
  state.drilldownPage++;
  loadDrilldownRecords();
}

async function loadDrilldownRecords() {
  const tbody = document.getElementById('drilldown-table-body');
  if (!tbody) return;
  tbody.innerHTML = `<tr><td colspan="9" class="text-center py-8 text-slate-500 italic">Loading recipient delivery records...</td></tr>`;

  const limit = 25;
  const offset = (state.drilldownPage - 1) * limit;

  let url = `/api/delivery/records/${state.activeRegion}?limit=${limit}&offset=${offset}`;
  if (state.drilldownStatus) url += `&status=${encodeURIComponent(state.drilldownStatus)}`;
  if (state.drilldownSearch) url += `&search=${encodeURIComponent(state.drilldownSearch)}`;

  const tagVal = document.getElementById('deliv-tag-filter')?.value;
  if (tagVal) url += `&tag_name=${encodeURIComponent(tagVal)}`;

  const startVal = document.getElementById('deliv-custom-start')?.value;
  const endVal = document.getElementById('deliv-custom-end')?.value;
  if (startVal && endVal) {
    url += `&start_date=${encodeURIComponent(startVal)}&end_date=${encodeURIComponent(endVal)}`;
  }

  try {
    const res = await apiFetch(url);
    const records = res.records || [];
    const total = res.total || 0;

    const summary = document.getElementById('drilldown-count-summary');
    if (summary) {
      summary.textContent = `Showing ${records.length} of ${total} records`;
    }

    const pageInfo = document.getElementById('drilldown-page-info');
    if (pageInfo) {
      const maxPage = Math.max(1, Math.ceil(total / limit));
      pageInfo.textContent = `Page ${state.drilldownPage} of ${maxPage} (${total} total)`;
    }

    const prevBtn = document.getElementById('btn-drilldown-prev');
    if (prevBtn) prevBtn.disabled = state.drilldownPage <= 1;

    const nextBtn = document.getElementById('btn-drilldown-next');
    if (nextBtn) nextBtn.disabled = (state.drilldownPage * limit) >= total;

    if (records.length === 0) {
      tbody.innerHTML = `<tr><td colspan="9" class="text-center py-8 text-slate-500 italic">No recipient records found matching this filter.</td></tr>`;
      return;
    }

    let html = '';
    records.forEach(r => {
      let statusClass = 'bg-slate-800 text-slate-300';
      if (r.status === 'successful' || r.status === 'sent') statusClass = 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30';
      else if (r.status === 'failed') statusClass = 'bg-rose-500/20 text-rose-300 border border-rose-500/30';
      else if (r.status === 'bounced') statusClass = 'bg-amber-500/20 text-amber-300 border border-amber-500/30';
      else if (r.status === 'invalid') statusClass = 'bg-red-500/20 text-red-300 border border-red-500/30';
      else if (r.status === 'opened') statusClass = 'bg-blue-500/20 text-blue-300 border border-blue-500/30';
      else if (r.status === 'clicked') statusClass = 'bg-purple-500/20 text-purple-300 border border-purple-500/30';

      html += `
        <tr class="hover:bg-slate-900/60 transition">
          <td class="py-2.5 px-3 font-mono font-medium text-white">${escapeHtml(r.recipient_email || '-')}</td>
          <td class="py-2.5 px-3 text-slate-300 truncate max-w-[140px]">${escapeHtml(r.campaign_name || r.email_task || '-')}</td>
          <td class="py-2.5 px-3 font-mono text-amber-400 text-[11px]">${escapeHtml(r.email_tag || '-')}</td>
          <td class="py-2.5 px-3"><span class="px-2 py-0.5 rounded text-[10px] font-semibold font-mono capitalize ${statusClass}">${escapeHtml(r.status || 'unknown')}</span></td>
          <td class="py-2.5 px-3 font-mono text-[11px] text-slate-400">${formatTimestamp(r.send_time)}</td>
          <td class="py-2.5 px-3 font-mono text-[11px] text-emerald-400">${formatTimestamp(r.delivery_time)}</td>
          <td class="py-2.5 px-3 font-mono text-blue-300">${r.open_count || 0}</td>
          <td class="py-2.5 px-3 font-mono text-purple-300">${r.click_count || 0}</td>
          <td class="py-2.5 px-3 text-[11px] text-slate-400 truncate max-w-[160px]" title="${escapeHtml(r.failure_reason || r.bounce_reason || '')}">
            ${escapeHtml(r.failure_reason || r.bounce_reason || (r.status === 'successful' ? 'Delivered' : '-'))}
          </td>
        </tr>
      `;
    });
    tbody.innerHTML = html;
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="9" class="text-center py-8 text-rose-400 italic">Error loading drill-down records: ${escapeHtml(err.message)}</td></tr>`;
  }
}

function exportDeliveryCsv(status = '') {
  let url = `/api/delivery/export-csv/${state.activeRegion}?status=${encodeURIComponent(status || '')}`;
  const tagVal = document.getElementById('deliv-tag-filter')?.value;
  if (tagVal) url += `&tag_name=${encodeURIComponent(tagVal)}`;

  const startVal = document.getElementById('deliv-custom-start')?.value;
  const endVal = document.getElementById('deliv-custom-end')?.value;
  if (startVal && endVal) {
    url += `&start_date=${encodeURIComponent(startVal)}&end_date=${encodeURIComponent(endVal)}`;
  }

  const a = document.createElement('a');
  a.href = url;
  a.download = `directmail_delivery_${state.activeRegion}_${status || 'all'}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  showToast(`Downloading ${status || 'all'} delivery CSV...`, 'info');
}

function exportCurrentDrilldownCsv() {
  exportDeliveryCsv(state.drilldownStatus || '');
}

// --- SCHEDULED CAMPAIGNS CONTROLLER ---

async function loadScheduledCampaignsTable() {
  const tbody = document.getElementById('scheduled-campaigns-table-body');
  if (!tbody) return;
  tbody.innerHTML = `<tr><td colspan="8" class="text-center py-6 text-slate-500 italic">Loading scheduled campaigns...</td></tr>`;

  try {
    const res = await apiFetch('/api/scheduled-campaigns?limit=50');
    const campaigns = res.scheduled_campaigns || [];
    if (campaigns.length === 0) {
      tbody.innerHTML = `<tr><td colspan="8" class="text-center py-6 text-slate-500 italic">No scheduled bulk campaigns found.</td></tr>`;
      return;
    }

    let html = '';
    campaigns.forEach(c => {
      html += `
        <tr class="hover:bg-slate-900/40 transition">
          <td class="py-3 px-4 font-semibold text-white">${escapeHtml(c.name || c.id)}</td>
          <td class="py-3 px-4 font-mono text-amber-400">${escapeHtml(c.tag_name || '-')}</td>
          <td class="py-3 px-4 text-purple-300 font-mono text-xs">${escapeHtml(c.template_name || c.template_id || '-')}</td>
          <td class="py-3 px-4 font-mono text-xs text-slate-300">${escapeHtml(c.sender || '-')}</td>
          <td class="py-3 px-4 font-mono text-xs text-slate-200">${c.total_recipients || 0}</td>
          <td class="py-3 px-4 font-mono text-xs text-blue-300">${formatTimestamp(c.scheduled_at)}</td>
          <td class="py-3 px-4 font-mono text-xs text-slate-400">${escapeHtml(c.timezone_name || 'Asia/Kolkata')}</td>
          <td class="py-3 px-4 text-right">
            <span class="px-2 py-0.5 rounded text-[10px] font-semibold font-mono uppercase bg-blue-500/20 text-blue-300 border border-blue-500/30">
              ${escapeHtml(c.status || 'scheduled')}
            </span>
          </td>
        </tr>
      `;
    });
    tbody.innerHTML = html;
    initIcons();
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="8" class="text-center py-6 text-rose-400 italic">Error loading scheduled campaigns: ${escapeHtml(err.message)}</td></tr>`;
  }
}

// --- EMAIL TAGS CONTROLLER ---

async function loadEmailTagsTable() {
  const tbody = document.getElementById('email-tags-table-body');
  if (!tbody) return;
  tbody.innerHTML = `<tr><td colspan="6" class="text-center py-6 text-slate-500 italic">Loading email tags...</td></tr>`;

  try {
    const res = await apiFetch('/api/tags');
    const tags = res.tags || [];
    state.emailTags = tags;

    const badge = document.getElementById('badge-tags-count');
    if (badge) badge.textContent = tags.length;

    // Filter by search input
    const searchVal = document.getElementById('tag-search-input')?.value.toLowerCase().trim() || '';
    const filtered = searchVal ? tags.filter(t => t.name.toLowerCase().includes(searchVal) || (t.description || '').toLowerCase().includes(searchVal)) : tags;

    if (filtered.length === 0) {
      tbody.innerHTML = `<tr><td colspan="6" class="text-center py-6 text-slate-500 italic">No email tags found. Click "Create Email Tag" to add one.</td></tr>`;
      populateTagDropdowns();
      return;
    }

    let html = '';
    filtered.forEach(t => {
      html += `
        <tr class="hover:bg-slate-900/40 transition">
          <td class="py-3 px-4">
            <span class="font-bold text-white block flex items-center gap-1.5">
              <i data-lucide="tag" class="w-3.5 h-3.5 text-amber-400"></i>
              <span>${escapeHtml(t.name)}</span>
            </span>
          </td>
          <td class="py-3 px-4 text-slate-300 text-xs">${escapeHtml(t.description || '-')}</td>
          <td class="py-3 px-4 font-mono text-xs text-slate-400 capitalize">${escapeHtml(t.region || 'All')}</td>
          <td class="py-3 px-4 font-mono text-xs text-amber-300">${escapeHtml(t.dm_tag_id || 'Local')}</td>
          <td class="py-3 px-4 font-mono text-xs text-slate-400">${formatTimestamp(t.created_at)}</td>
          <td class="py-3 px-4 text-right space-x-1.5 whitespace-nowrap">
            <button onclick="openEditTagModal(${t.id})" class="px-2 py-1 text-[11px] rounded bg-slate-800 hover:bg-slate-700 text-slate-200">Edit</button>
            <button onclick="promptDeleteTag(${t.id}, '${escapeHtml(t.name)}')" class="px-2 py-1 text-[11px] rounded bg-rose-500/10 hover:bg-rose-500/20 text-rose-300 border border-rose-500/30">Delete</button>
          </td>
        </tr>
      `;
    });
    tbody.innerHTML = html;
    initIcons();
    populateTagDropdowns();
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="6" class="text-center py-6 text-rose-400 italic">Error loading email tags: ${escapeHtml(err.message)}</td></tr>`;
  }
}

let tagSearchTimer = null;
function debounceSearchTags() {
  clearTimeout(tagSearchTimer);
  tagSearchTimer = setTimeout(() => {
    loadEmailTagsTable();
  }, 250);
}

function openCreateTagModal() {
  document.getElementById('new-tag-name').value = '';
  document.getElementById('new-tag-desc').value = '';
  document.getElementById('create-tag-modal').classList.remove('hidden');
}

function closeCreateTagModal() {
  document.getElementById('create-tag-modal').classList.add('hidden');
}

async function submitCreateTag() {
  const name = document.getElementById('new-tag-name').value.trim();
  const region = document.getElementById('new-tag-region').value;
  const desc = document.getElementById('new-tag-desc').value.trim();

  if (!name) {
    showToast('Tag name is required.', 'error');
    return;
  }

  try {
    await apiFetch('/api/tags', {
      method: 'POST',
      body: JSON.stringify({ name: name, region: region, description: desc })
    });
    showToast(`Email Tag '${name}' created successfully!`, 'success');
    closeCreateTagModal();
    loadEmailTagsTable();
  } catch (err) {
    showToast(`Create Tag Error: ${err.message}`, 'error');
  }
}

function openEditTagModal(tagId) {
  const tag = (state.emailTags || []).find(t => t.id === tagId);
  if (!tag) return;
  document.getElementById('edit-tag-id').value = tag.id;
  document.getElementById('edit-tag-name').value = tag.name;
  document.getElementById('edit-tag-desc').value = tag.description || '';
  document.getElementById('edit-tag-modal').classList.remove('hidden');
}

function closeEditTagModal() {
  document.getElementById('edit-tag-modal').classList.add('hidden');
}

async function submitUpdateTag() {
  const tagId = document.getElementById('edit-tag-id').value;
  const desc = document.getElementById('edit-tag-desc').value.trim();

  try {
    await apiFetch(`/api/tags/${tagId}`, {
      method: 'PUT',
      body: JSON.stringify({ description: desc })
    });
    showToast('Email Tag updated successfully!', 'success');
    closeEditTagModal();
    loadEmailTagsTable();
  } catch (err) {
    showToast(`Update Tag Error: ${err.message}`, 'error');
  }
}

function promptDeleteTag(tagId, tagName) {
  showDeleteConfirm({
    title: 'Delete Email Tag',
    message: `Are you sure you want to delete email tag <strong>${tagName}</strong>? This action will remove the tag from local tracking and Alibaba DirectMail.`,
    onConfirm: async () => {
      try {
        await apiFetch(`/api/tags/${tagId}`, { method: 'DELETE' });
        showToast(`Tag '${tagName}' deleted.`, 'success');
        loadEmailTagsTable();
      } catch (err) {
        showToast(`Delete Error: ${err.message}`, 'error');
      }
    }
  });
}

function populateTagDropdowns() {
  const tags = state.emailTags || [];
  ['send-tag-select', 'bulk-tag-select', 'deliv-tag-filter'].forEach(elemId => {
    const el = document.getElementById(elemId);
    if (!el) return;
    const currentVal = el.value;
    const isFilter = elemId === 'deliv-tag-filter';
    el.innerHTML = isFilter ? '<option value="">All Email Tags</option>' : '<option value="">-- None --</option>';
    tags.forEach(t => {
      const opt = document.createElement('option');
      opt.value = t.name;
      opt.textContent = `${t.name}${t.description ? ` (${t.description})` : ''}`;
      if (t.name === currentVal) opt.selected = true;
      el.appendChild(opt);
    });
  });
}

// --- 9. TRACKING VIEW CONTROLLER ---

async function loadTrackingFeed() {
  const tbody = document.getElementById('tracking-table-body');
  if (!tbody) return;
  tbody.innerHTML = `<tr><td colspan="5" class="text-center py-6 text-slate-500 italic">Querying granular events from Alibaba DirectMail...</td></tr>`;

  try {
    const res = await apiFetch(`/api/tracking/events/${state.activeRegion}`);
    const items = res.events || [];
    state.trackingEvents = items;
    renderTrackingRows(items);
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="5" class="text-center py-6 text-rose-400 italic">Error loading tracking feed: ${escapeHtml(err.message)}</td></tr>`;
  }
}

function renderTrackingRows(items) {
  const tbody = document.getElementById('tracking-table-body');
  if (!tbody) return;

  if (items.length === 0) {
    tbody.innerHTML = `<tr><td colspan="5" class="text-center py-6 text-slate-500 italic">No individual tracking events found in DirectMail for ${state.activeRegion}.</td></tr>`;
    return;
  }

  let html = '';
  items.forEach(e => {
    const isOk = e.Status === 0 || e.Status === '0' || String(e.Message || '').includes('250');
    html += `
      <tr class="hover:bg-slate-900/40 transition">
        <td class="py-3 px-4 font-mono text-slate-400 text-xs">${formatTimestamp(e.LastUpdateTime)}</td>
        <td class="py-3 px-4 font-mono font-medium text-cyan-300">${escapeHtml(e.ToAddress)}</td>
        <td class="py-3 px-4 font-mono text-slate-400 text-xs">${escapeHtml(e.AccountName)}</td>
        <td class="py-3 px-4">
          <span class="px-2 py-0.5 rounded text-[10px] font-semibold ${isOk ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30' : 'bg-rose-500/20 text-rose-300 border border-rose-500/30'}">
            ${isOk ? 'Delivered (250 OK)' : 'Status ' + e.Status}
          </span>
        </td>
        <td class="py-3 px-4 font-mono text-xs text-slate-300">
          <span class="text-slate-400">${escapeHtml(e.Message || '250 Send Mail OK')}</span>
          ${e.ErrorClassification ? `<span class="ml-2 px-1.5 py-0.2 rounded bg-slate-800 text-[10px] text-amber-300 font-mono">${escapeHtml(e.ErrorClassification)}</span>` : ''}
        </td>
      </tr>
    `;
  });
  tbody.innerHTML = html;
}

function filterTrackingFeed() {
  const q = document.getElementById('tracking-search').value.toLowerCase().trim();
  if (!q) {
    renderTrackingRows(state.trackingEvents);
    return;
  }
  const filtered = state.trackingEvents.filter(e => 
    (e.ToAddress && e.ToAddress.toLowerCase().includes(q)) ||
    (e.AccountName && e.AccountName.toLowerCase().includes(q)) ||
    (e.Message && e.Message.toLowerCase().includes(q))
  );
  renderTrackingRows(filtered);
}

// --- 10. ANALYSIS VIEW CONTROLLER ---

async function loadAnalysisView() {
  try {
    const summaryRes = await apiFetch(`/api/account-summary/${state.activeRegion}`);
    const s = summaryRes.data || {};

    const level = s.QuotaLevel || 5;
    const maxLevel = s.MaxQuotaLevel || 10;
    document.getElementById('analysis-level').textContent = level;
    document.getElementById('analysis-level-bar').style.width = `${Math.min(100, (level / maxLevel) * 100)}%`;
    document.getElementById('analysis-channel').textContent = s.IpChannelType || 'normal';
    document.getElementById('analysis-daily-quota').textContent = `${(s.DailyQuota || 0).toLocaleString()} / day`;
    document.getElementById('analysis-month-quota').textContent = `${(s.MonthQuota || 0).toLocaleString()} / month`;
    document.getElementById('analysis-free-quota').textContent = (s.DailyRemainFreeQuota || 0).toLocaleString();

    // Domain checklist
    const domRes = await apiFetch(`/api/domains/${state.activeRegion}`);
    const domains = domRes.domains || [];
    const container = document.getElementById('analysis-domain-checklist');
    if (!container) return;

    if (domains.length === 0) {
      container.innerHTML = `<div class="p-3 bg-slate-900/60 rounded-xl border border-slate-800 text-slate-400 italic">No domains configured.</div>`;
      return;
    }

    let html = '';
    domains.forEach(d => {
      html += `
        <div class="bg-slate-900/70 p-4 rounded-xl border border-slate-800 flex flex-wrap items-center justify-between gap-3">
          <div>
            <span class="font-bold text-white font-mono text-sm">${escapeHtml(d.DomainName)}</span>
            <span class="ml-2 text-slate-500 font-mono text-xs">(ID: ${d.DomainId})</span>
          </div>
          <div class="flex items-center gap-3">
            <span class="flex items-center gap-1 ${d.CnameAuthStatus === 1 ? 'text-emerald-400' : 'text-amber-400'} font-medium">
              <i data-lucide="${d.CnameAuthStatus === 1 ? 'check-circle' : 'alert-circle'}" class="w-3.5 h-3.5"></i> CNAME
            </span>
            <span class="flex items-center gap-1 ${d.SpfAuthStatus === 1 ? 'text-emerald-400' : 'text-slate-400'}">
              <i data-lucide="${d.SpfAuthStatus === 1 ? 'check-circle' : 'minus'}" class="w-3.5 h-3.5"></i> SPF
            </span>
            <span class="flex items-center gap-1 ${d.MxAuthStatus === 1 ? 'text-emerald-400' : 'text-slate-400'}">
              <i data-lucide="${d.MxAuthStatus === 1 ? 'check-circle' : 'minus'}" class="w-3.5 h-3.5"></i> MX
            </span>
          </div>
        </div>
      `;
    });
    container.innerHTML = html;
    initIcons();
  } catch (err) {
    console.warn('Analysis load error:', err);
  }
}

// --- 11. SETTINGS VIEW CONTROLLER ---

async function handleSettingsSave(e) {
  e.preventDefault();
  const testMode = document.getElementById('setting-test-mode').checked ? 'true' : 'false';
  const qps = document.getElementById('setting-rate-limit').value;
  const retries = document.getElementById('setting-max-retries').value;
  const tz = document.getElementById('setting-default-timezone').value;

  try {
    await apiFetch('/api/settings', {
      method: 'PUT',
      body: JSON.stringify({
        test_mode: testMode,
        rate_limit_qps: qps,
        max_retries: retries,
        default_timezone: tz
      })
    });
    showToast('Settings saved successfully!', 'success');
    await loadSettings();
    await loadHealth();
  } catch (err) {
    showToast(err.message, 'error');
  }
}

// --- 12. AUDIT TRAIL CONTROLLER ---

let auditSearchDebounce = null;
function debounceAuditSearch() {
  clearTimeout(auditSearchDebounce);
  auditSearchDebounce = setTimeout(() => {
    loadAuditLogsTable();
  }, 350);
}

function applyAuditFilters() {
  loadAuditLogsTable();
}

async function loadAuditLogsTable() {
  const tbody = document.getElementById('audit-logs-table-body');
  if (!tbody) return;
  tbody.innerHTML = `<tr><td colspan="6" class="text-center py-6 text-slate-500 italic">Loading audit trail records...</td></tr>`;

  const sDate = document.getElementById('audit-start-date') ? document.getElementById('audit-start-date').value : '';
  const eDate = document.getElementById('audit-end-date') ? document.getElementById('audit-end-date').value : '';
  const action = document.getElementById('audit-action-filter') ? document.getElementById('audit-action-filter').value : '';
  const result = document.getElementById('audit-result-filter') ? document.getElementById('audit-result-filter').value : '';
  const search = document.getElementById('audit-search-input') ? document.getElementById('audit-search-input').value.trim() : '';

  let url = `/api/audit-logs?limit=50&offset=0`;
  if (sDate) url += `&start_date=${encodeURIComponent(sDate)}`;
  if (eDate) url += `&end_date=${encodeURIComponent(eDate)}`;
  if (action) url += `&action=${encodeURIComponent(action)}`;
  if (result) url += `&result=${encodeURIComponent(result)}`;
  if (search) url += `&search=${encodeURIComponent(search)}`;

  try {
    const res = await apiFetch(url);
    const items = res.items || [];
    state.auditLogs = items;

    if (items.length === 0) {
      tbody.innerHTML = `<tr><td colspan="6" class="text-center py-8 text-slate-500 italic">No audit records match the current filter criteria.</td></tr>`;
      return;
    }

    let html = '';
    items.forEach(log => {
      const isSuccess = log.result === 'success';
      const isFailed = log.result === 'failed';
      const badgeClass = isSuccess 
        ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30' 
        : isFailed 
        ? 'bg-rose-500/20 text-rose-300 border border-rose-500/30' 
        : 'bg-amber-500/20 text-amber-300 border border-amber-500/30';

      html += `
        <tr class="hover:bg-slate-900/50 transition">
          <td class="py-3 px-4 font-mono text-slate-400 whitespace-nowrap text-xs">${formatTimestamp(log.timestamp)}</td>
          <td class="py-3 px-4 font-mono font-medium text-white text-xs">${escapeHtml(log.action)}</td>
          <td class="py-3 px-4 font-mono text-slate-300 text-xs">
            <span class="text-purple-300">${escapeHtml(log.object_type)}</span>
            ${log.object_id ? `<span class="text-slate-500 ml-1 font-sans">#${escapeHtml(log.object_id)}</span>` : ''}
          </td>
          <td class="py-3 px-4 font-mono text-slate-400 text-xs">${escapeHtml(log.actor || 'system')}</td>
          <td class="py-3 px-4">
            <span class="px-2 py-0.5 rounded text-[10px] font-semibold uppercase font-mono ${badgeClass}">
              ${escapeHtml(log.result)}
            </span>
          </td>
          <td class="py-3 px-4 text-xs text-slate-300 max-w-xs">
            <div>${escapeHtml(log.details || '—')}</div>
            ${log.error ? `<div class="text-[11px] text-rose-400 font-mono mt-0.5">${escapeHtml(log.error)}</div>` : ''}
          </td>
        </tr>
      `;
    });
    tbody.innerHTML = html;
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="6" class="text-center py-6 text-rose-400 italic">Error loading audit logs: ${escapeHtml(err.message)}</td></tr>`;
  }
}

// --- SMART AGENT CONSOLE CONTROLLER ---

async function handleSmartAgentSubmit(e) {
  e.preventDefault();
  const input = document.getElementById('smart-agent-input');
  const query = input.value.trim();
  if (!query) return;

  const btn = document.getElementById('btn-smart-agent-ask');
  btn.disabled = true;
  btn.innerHTML = '<i data-lucide="loader-2" class="w-3 h-3 animate-spin"></i>';
  initIcons();

  try {
    const res = await apiFetch('/api/smart-agent/query', {
      method: 'POST',
      body: JSON.stringify({ prompt: query, region: state.activeRegion })
    });

    document.getElementById('smart-agent-modal-title').textContent = res.title || 'Smart Agent Query Result';
    document.getElementById('smart-agent-markdown-content').innerHTML = renderMarkdown(res.markdown || '');
    document.getElementById('smart-agent-raw-data').textContent = JSON.stringify(res.data || {}, null, 2);

    // Setup action buttons based on intent
    const actionsContainer = document.getElementById('smart-agent-actions');
    actionsContainer.innerHTML = '';
    
    if (res.intent === 'list_domains') {
      actionsContainer.innerHTML = `<button onclick="closeSmartAgentModal(); navigateTo('domains')" class="px-3 py-1.5 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white text-xs font-semibold">Open Domains Table →</button>`;
    } else if (res.intent === 'list_senders') {
      actionsContainer.innerHTML = `<button onclick="closeSmartAgentModal(); navigateTo('senders')" class="px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold">Open Senders Table →</button>`;
    } else if (res.intent === 'list_templates') {
      actionsContainer.innerHTML = `<button onclick="closeSmartAgentModal(); navigateTo('templates')" class="px-3 py-1.5 rounded-lg bg-purple-600 hover:bg-purple-500 text-white text-xs font-semibold">Open Templates Table →</button>`;
    } else if (res.intent === 'delivery_report') {
      actionsContainer.innerHTML = `<button onclick="closeSmartAgentModal(); navigateTo('delivery')" class="px-3 py-1.5 rounded-lg bg-teal-600 hover:bg-teal-500 text-white text-xs font-semibold">Open Delivery Dashboard →</button>`;
    } else {
      actionsContainer.innerHTML = `<button onclick="closeSmartAgentModal(); navigateTo('overview')" class="px-3 py-1.5 rounded-lg bg-brand hover:bg-brand-hover text-white text-xs font-semibold">Open Control Center →</button>`;
    }

    document.getElementById('smart-agent-modal').classList.remove('hidden');
    initIcons();
  } catch (err) {
    showToast(`Agent Error: ${err.message}`, 'error');
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<span>Ask</span><i data-lucide="arrow-right" class="w-3 h-3"></i>';
    initIcons();
  }
}

function closeSmartAgentModal() {
  document.getElementById('smart-agent-modal').classList.add('hidden');
}

// Mini markdown renderer for Smart Agent
function renderMarkdown(md) {
  if (!md) return '';
  let html = md
    .replace(/^### (.*$)/gim, '<h3>$1</h3>')
    .replace(/^## (.*$)/gim, '<h2>$1</h2>')
    .replace(/^# (.*$)/gim, '<h1>$1</h1>')
    .replace(/\*\*(.*?)\*\*/gim, '<strong>$1</strong>')
    .replace(/\*(.*?)\*/gim, '<em>$1</em>')
    .replace(/`([^`]+)`/gim, '<code>$1</code>')
    .replace(/^\s*-\s+(.*$)/gim, '<li>$1</li>')
    .replace(/(<li>.*<\/li>)/gim, '<ul>$1</ul>');
  return html.replace(/\n\n/g, '<p></p>');
}

// --- STRICT DELETE CONFIRMATION SYSTEM ---

function showDeleteConfirm({ title, message, onConfirm }) {
  document.getElementById('delete-modal-title').textContent = title || 'Confirm Deletion';
  document.getElementById('delete-modal-message').innerHTML = message || 'Are you sure you want to delete this resource?';
  state.pendingDeleteAction = onConfirm;

  const btn = document.getElementById('btn-confirm-delete-action');
  btn.onclick = async () => {
    btn.disabled = true;
    btn.textContent = 'Deleting...';
    try {
      if (state.pendingDeleteAction) await state.pendingDeleteAction();
    } finally {
      btn.disabled = false;
      btn.textContent = 'Confirm Delete';
      closeDeleteConfirmModal();
    }
  };

  document.getElementById('delete-confirm-modal').classList.remove('hidden');
}

function closeDeleteConfirmModal() {
  document.getElementById('delete-confirm-modal').classList.add('hidden');
  state.pendingDeleteAction = null;
}

// --- JOB INSPECTOR MODAL ---

async function openJobDetail(jobId) {
  try {
    const job = await apiFetch(`/api/jobs/${jobId}`);
    document.getElementById('modal-job-id').textContent = job.id;
    
    let rawJsonStr = '{}';
    try {
      rawJsonStr = JSON.stringify(JSON.parse(job.api_response_raw || '{}'), null, 2);
    } catch {
      rawJsonStr = job.api_response_raw || '{}';
    }

    const container = document.getElementById('job-detail-content');
    container.innerHTML = `
      <div class="grid grid-cols-2 gap-3 bg-slate-900/60 p-3.5 rounded-xl border border-slate-800 text-xs">
        <div><span class="text-slate-500">Status:</span> <span class="badge-${job.status} px-2 py-0.5 rounded capitalize font-medium">${job.status}</span></div>
        <div><span class="text-slate-500">Region:</span> <span class="text-white font-medium capitalize">${job.region}</span></div>
        <div><span class="text-slate-500">Recipient:</span> <span class="text-cyan-400 font-mono">${escapeHtml(job.recipient)}</span></div>
        <div><span class="text-slate-500">Sender:</span> <span class="text-slate-300 font-mono">${escapeHtml(job.sender)}</span></div>
        <div><span class="text-slate-500">Created:</span> <span class="text-slate-300 font-mono">${job.created_at}</span></div>
        <div><span class="text-slate-500">Sent At:</span> <span class="text-slate-300 font-mono">${job.sent_at || 'N/A'}</span></div>
        <div><span class="text-slate-500">Delivered At:</span> <span class="text-emerald-400 font-mono font-medium">${job.delivered_at || 'Awaiting Confirmation'}</span></div>
        <div><span class="text-slate-500">Reconciled At:</span> <span class="text-slate-300 font-mono">${job.reconciled_at || 'Pending'}</span></div>
        <div><span class="text-slate-500">DirectMail RequestId:</span> <span class="text-amber-400 font-mono">${job.api_request_id || 'N/A'}</span></div>
        <div><span class="text-slate-500">DirectMail EnvId:</span> <span class="text-purple-400 font-mono">${job.api_env_id || 'N/A'}</span></div>
        <div class="col-span-2"><span class="text-slate-500">Provider Status / Response:</span> <span class="text-slate-200 font-mono">${escapeHtml(job.provider_event_message || job.provider_status || '250 Send Mail OK')}</span></div>
        ${job.template_id ? `<div class="col-span-2"><span class="text-slate-500">Associated Template:</span> <span class="text-purple-400 font-mono font-medium">#${job.template_id}</span></div>` : ''}
      </div>

      <div>
        <label class="block text-slate-400 mb-1 font-medium text-xs">Subject</label>
        <div class="p-2.5 rounded-lg bg-slate-900 border border-slate-800 text-white font-medium text-xs">${escapeHtml(job.subject)}</div>
      </div>

      ${job.error_message ? `
        <div class="bg-rose-500/10 border border-rose-500/30 p-3 rounded-xl">
          <span class="text-rose-400 font-bold block mb-1 text-xs">Error [${job.error_code || 'API Error'}]:</span>
          <p class="text-rose-200 text-xs">${escapeHtml(job.error_message)}</p>
        </div>
      ` : ''}

      <div>
        <label class="block text-slate-400 mb-1 font-medium text-xs">Raw DirectMail Gateway Response</label>
        <pre class="code-json text-xs">${escapeHtml(rawJsonStr)}</pre>
      </div>

      <div class="flex items-center justify-between pt-3 border-t border-slate-800">
        <button type="button" onclick="triggerReconciliation(); closeJobDetailModal();" class="px-3 py-1.5 rounded-lg bg-amber-500/20 hover:bg-amber-500 text-amber-300 hover:text-white border border-amber-500/30 text-xs font-semibold flex items-center gap-1.5 transition">
          <i data-lucide="refresh-cw" class="w-3 h-3"></i>
          <span>Reconcile DirectMail for ${job.region}</span>
        </button>
        <button type="button" onclick="closeJobDetailModal()" class="px-4 py-1.5 rounded-lg text-xs font-medium text-slate-300 hover:text-white bg-slate-800">
          Close
        </button>
      </div>
    `;
    document.getElementById('job-detail-modal').classList.remove('hidden');
    initIcons();
  } catch (err) {
    showToast('Failed to load job details: ' + err.message, 'error');
  }
}

function closeJobDetailModal() {
  document.getElementById('job-detail-modal').classList.add('hidden');
}

// --- LIVE SYNC HELPER ---

async function syncLiveFromAlibaba(regionKey = 'singapore') {
  try {
    const data = await apiFetch(`/api/live-infrastructure/${regionKey}`);
    if (data.live) {
      const domainBadge = document.getElementById('live-domain-badge');
      const domainStatus = document.getElementById('live-domain-status');
      if (domainBadge && data.domains && data.domains.length > 0) {
        const dom = data.domains[0];
        domainBadge.textContent = dom.DomainName || 'Configured';
        domainStatus.textContent = dom.CnameAuthStatus === 1 ? 'CNAME Verified' : 'Domain Active';
      }

      if (data.verified_senders && data.verified_senders.length > 0) {
        state.verifiedSenders[regionKey] = data.verified_senders;
        updateSendRegionUI(state.activeSendRegion);
        updateBulkRegionUI(state.activeBulkRegion);
        updateSchedSenders();
      }
    }
  } catch (err) {
    console.warn('Live sync failed:', err);
  }
}

// --- TOAST NOTIFICATIONS ---

function showToast(message, type = 'info') {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const toast = document.createElement('div');
  
  const colors = {
    success: 'bg-emerald-950/90 border border-emerald-500/50 text-emerald-200',
    error: 'bg-rose-950/90 border border-rose-500/50 text-rose-200',
    info: 'bg-slate-900/95 border border-slate-700 text-slate-200'
  };
  const icons = {
    success: '<i data-lucide="check-circle" class="w-4 h-4 text-emerald-400 shrink-0"></i>',
    error: '<i data-lucide="alert-circle" class="w-4 h-4 text-rose-400 shrink-0"></i>',
    info: '<i data-lucide="info" class="w-4 h-4 text-brand shrink-0"></i>'
  };

  toast.className = `toast ${colors[type] || colors.info}`;
  toast.innerHTML = `
    ${icons[type] || icons.info}
    <div class="flex-1 font-medium leading-tight">${escapeHtml(message)}</div>
  `;
  container.appendChild(toast);
  initIcons();

  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(10px) scale(0.95)';
    setTimeout(() => toast.remove(), 200);
  }, 4000);
}

// --- UTILITIES ---

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function formatTimestamp(isoStr) {
  if (!isoStr) return 'N/A';
  try {
    const d = new Date(isoStr);
    return d.toISOString().replace('T', ' ').substring(0, 19);
  } catch {
    return isoStr;
  }
}
