// Kageboard popup script
// Handles UI interactions and message passing to background service worker

const els = {
  title: document.getElementById('page-title'),
  url: document.getElementById('page-url'),
  cloneBtn: document.getElementById('clone-btn'),
  cloneSiteBtn: document.getElementById('clone-site-btn'),
  btnText: document.getElementById('btn-text'),
  btnSpinner: document.getElementById('btn-spinner'),
  status: document.getElementById('status'),
  optWholeSite: document.getElementById('opt-whole-site'),
  optScroll: document.getElementById('opt-scroll'),
  optMaxPages: document.getElementById('opt-max-pages'),
  optMaxDepth: document.getElementById('opt-max-depth'),
  advancedOptions: document.getElementById('advanced-options'),
  recentList: document.getElementById('recent-list'),
  openOptions: document.getElementById('open-options'),
};

let currentTab = null;

// Get current tab info
async function init() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  currentTab = tab;
  els.title.textContent = tab.title || 'Untitled';
  els.url.textContent = tab.url || '';

  // Show site clone button if URL has a host
  try {
    const u = new URL(tab.url);
    els.cloneSiteBtn.style.display = 'block';
  } catch (_) {}

  // Load recent mirrors
  loadRecent();
}

// Toggle advanced options
els.optWholeSite.addEventListener('change', () => {
  els.advancedOptions.style.display = els.optWholeSite.checked ? 'flex' : 'none';
});

// Clone button
els.cloneBtn.addEventListener('click', () => startClone(false));
els.cloneSiteBtn.addEventListener('click', () => startClone(true));

async function startClone(wholeSite) {
  if (!currentTab || !currentTab.url) return;

  const url = wholeSite
    ? extractHost(currentTab.url)
    : currentTab.url;

  const options = {};
  if (wholeSite || els.optWholeSite.checked) {
    if (els.optMaxPages.value) options.maxPages = els.optMaxPages.value;
    if (els.optMaxDepth.value) options.maxDepth = els.optMaxDepth.value;
    if (els.optScroll.checked) options.scroll = true;
  }

  setLoading(true);
  showStatus('info', 'Starting clone…');

  try {
    const result = await chrome.runtime.sendMessage({
      action: 'clone',
      url,
      options,
    });

    if (result.error) {
      showStatus('error', `Failed: ${result.error}`);
    } else {
      showStatus('success', `Clone started! <span class="link" id="view-dashboard">View in Kageboard →</span>`);
      document.getElementById('view-dashboard')?.addEventListener('click', () => {
        chrome.storage.sync.get(['server_url'], (data) => {
          chrome.tabs.create({ url: data.server_url || 'http://127.0.0.1:5000' });
        });
      });
      // Poll for completion
      pollJob(result.job_id);
    }
  } catch (e) {
    showStatus('error', `Connection failed. Is Kageboard running?`);
  } finally {
    setLoading(false);
  }
}

async function pollJob(jobId) {
  const check = async () => {
    try {
      const job = await chrome.runtime.sendMessage({ action: 'get-job', jobId });
      if (job.status === 'done') {
        showStatus('success', `Done! ${job.pages} pages mirrored. <span class="link" id="view-dashboard">View →</span>`);
        document.getElementById('view-dashboard')?.addEventListener('click', () => {
          chrome.storage.sync.get(['server_url'], (data) => {
            chrome.tabs.create({ url: data.server_url || 'http://127.0.0.1:5000' });
          });
        });
        loadRecent();
        return;
      }
      if (job.status === 'error') {
        showStatus('error', 'Clone failed. Check Kageboard for details.');
        return;
      }
      showStatus('info', `Cloning… ${job.pages || 0} pages`);
      setTimeout(check, 2000);
    } catch (_) {
      // Job might have been cleaned up
    }
  };
  setTimeout(check, 2000);
}

async function loadRecent() {
  try {
    const data = await chrome.runtime.sendMessage({ action: 'get-mirrors' });
    if (!Array.isArray(data)) {
      els.recentList.innerHTML = '<span style="color:#6b7280;font-size:0.8rem">Could not connect</span>';
      return;
    }
    if (data.length === 0) {
      els.recentList.innerHTML = '<span style="color:#6b7280;font-size:0.8rem">No mirrors yet</span>';
      return;
    }
    els.recentList.innerHTML = '';
    data.forEach(m => {
      const sizeStr = m.size_bytes > 1048576
        ? (m.size_bytes / 1048576).toFixed(1) + ' MB'
        : (m.size_bytes / 1024).toFixed(0) + ' KB';
      const div = document.createElement('div');
      div.className = 'recent-item';
      div.innerHTML = `<span class="host">${escapeHtml(m.host)}</span><span class="count">${m.page_count} pages · ${sizeStr}</span>`;
      div.addEventListener('click', () => {
        chrome.storage.sync.get(['server_url'], (d) => {
          const server = d.server_url || 'http://127.0.0.1:5000';
          chrome.tabs.create({ url: `${server}/mirrors/${m.host}` });
        });
      });
      div.style.cursor = 'pointer';
      els.recentList.appendChild(div);
    });
  } catch (_) {
    els.recentList.innerHTML = '<span style="color:#6b7280;font-size:0.8rem">Connection failed</span>';
  }
}

// Settings link
els.openOptions.addEventListener('click', (e) => {
  e.preventDefault();
  chrome.runtime.openOptionsPage();
});

// Helpers
function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

function setLoading(loading) {
  els.cloneBtn.disabled = loading;
  els.cloneSiteBtn.disabled = loading;
  els.btnText.style.display = loading ? 'none' : 'inline';
  els.btnSpinner.style.display = loading ? 'inline-block' : 'none';
}

function showStatus(kind, msg) {
  els.status.className = `status show ${kind}`;
  els.status.innerHTML = msg;
}

function extractHost(url) {
  try {
    const u = new URL(url);
    return u.hostname;
  } catch (_) {
    return url;
  }
}

// Init on load
init();