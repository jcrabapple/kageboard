// Kageboard popup script
// Handles UI interactions: auth state, clone flow, mirror listing

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
  // Auth elements
  authSection: document.getElementById('auth-section'),
  actionSection: document.getElementById('action-section'),
  loginUsername: document.getElementById('login-username'),
  loginPassword: document.getElementById('login-password'),
  loginBtn: document.getElementById('login-btn'),
  loginError: document.getElementById('login-error'),
  logoutLink: document.getElementById('logout-link'),
};

let currentTab = null;
let isAuthed = false;

// Initialize
async function init() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  currentTab = tab;
  els.title.textContent = tab.title || 'Untitled';
  els.url.textContent = tab.url || '';

  try {
    const u = new URL(tab.url);
    els.cloneSiteBtn.style.display = 'block';
  } catch (_) {}

  // Check auth state
  await checkAuth();
}

async function checkAuth() {
  try {
    const result = await chrome.runtime.sendMessage({ action: 'check-auth' });
    setAuthState(result.authenticated);
  } catch (_) {
    setAuthState(false);
  }
}

function setAuthState(authed) {
  isAuthed = authed;
  els.authSection.style.display = authed ? 'none' : 'block';
  els.actionSection.style.display = authed ? 'block' : 'none';
  els.logoutLink.style.display = authed ? 'inline' : 'none';

  if (authed) {
    loadRecent();
  }
}

// Login
els.loginBtn.addEventListener('click', async () => {
  const username = els.loginUsername.value.trim();
  const password = els.loginPassword.value.trim();
  if (!username || !password) return;

  els.loginBtn.disabled = true;
  els.loginBtn.textContent = 'Signing in…';
  els.loginError.style.display = 'none';

  try {
    // Save credentials and test them
    await chrome.runtime.sendMessage({
      action: 'save-credentials',
      username,
      password,
    });

    const result = await chrome.runtime.sendMessage({ action: 'check-auth' });
    if (result.authenticated) {
      setAuthState(true);
    } else {
      showLoginError('Invalid credentials');
    }
  } catch (e) {
    showLoginError(e.message || 'Connection failed');
  } finally {
    els.loginBtn.disabled = false;
    els.loginBtn.textContent = 'Sign In';
  }
});

function showLoginError(msg) {
  els.loginError.textContent = msg;
  els.loginError.style.display = 'block';
}

// Logout
els.logoutLink.addEventListener('click', async (e) => {
  e.preventDefault();
  await chrome.runtime.sendMessage({
    action: 'save-credentials',
    username: '',
    password: '',
  });
  setAuthState(false);
  els.recentList.innerHTML = '';
});

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
      if (result.error === 'auth_required') {
        setAuthState(false);
        showStatus('error', 'Authentication required. Please sign in.');
      } else {
        showStatus('error', `Failed: ${result.error}`);
      }
    } else {
      showStatus('success', `Clone started! <span class="link" id="view-dashboard">View in Kageboard →</span>`);
      document.getElementById('view-dashboard')?.addEventListener('click', () => {
        chrome.storage.sync.get(['server_url'], (data) => {
          chrome.tabs.create({ url: data.server_url || 'http://127.0.0.1:5000' });
        });
      });
      pollJob(result.job_id);
    }
  } catch (e) {
    showStatus('error', `Connection failed. Is Kageboard running?`);
  } finally {
    setLoading(false);
  }
}

// Poll job status
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
    } catch (_) {}
  };
  setTimeout(check, 2000);
}

// Load recent mirrors
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

init();