// Kageboard background service worker
// Handles API calls to the kageboard server with Basic Auth

const DEFAULT_SERVER = 'http://127.0.0.1:5000';

async function getServer() {
  const data = await chrome.storage.sync.get(['server_url']);
  return data.server_url || DEFAULT_SERVER;
}

async function getCredentials() {
  const data = await chrome.storage.sync.get(['username', 'password']);
  return {
    username: data.username || 'kageboard',
    password: data.password || '',
  };
}

function basicAuthHeader(username, password) {
  return 'Basic ' + btoa(username + ':' + password);
}

async function apiCall(path, options = {}) {
  const server = await getServer();
  const url = `${server}${path}`;
  const creds = await getCredentials();

  const headers = {
    'Content-Type': 'application/json',
    ...(options.headers || {}),
  };

  // Attach Basic Auth if credentials stored
  if (creds.password) {
    headers['Authorization'] = basicAuthHeader(creds.username, creds.password);
  }

  const resp = await fetch(url, {
    ...options,
    headers,
    signal: AbortSignal.timeout(30000),
  });

  const body = await resp.json();
  if (!resp.ok) {
    // Surface auth requirement clearly
    if (resp.status === 401) {
      throw new Error('auth_required');
    }
    throw new Error(body.error || `HTTP ${resp.status}`);
  }
  return body;
}

// Listen for messages from popup
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.action === 'clone') {
    handleClone(msg.url, msg.options || {}).then(sendResponse).catch(e => sendResponse({ error: e.message }));
    return true;
  }
  if (msg.action === 'get-jobs') {
    apiCall('/api/jobs').then(sendResponse).catch(e => sendResponse({ error: e.message }));
    return true;
  }
  if (msg.action === 'get-job') {
    apiCall(`/api/jobs/${msg.jobId}`).then(sendResponse).catch(e => sendResponse({ error: e.message }));
    return true;
  }
  if (msg.action === 'get-mirrors') {
    apiCall('/api/mirrors').then(sendResponse).catch(e => sendResponse({ error: e.message }));
    return true;
  }
  if (msg.action === 'check-auth') {
    checkAuth().then(sendResponse).catch(e => sendResponse({ error: e.message }));
    return true;
  }
  if (msg.action === 'save-credentials') {
    saveCredentials(msg.username, msg.password).then(sendResponse).catch(e => sendResponse({ error: e.message }));
    return true;
  }
  if (msg.action === 'get-credentials') {
    getCredentials().then(sendResponse);
    return true;
  }
});

async function handleClone(url, options) {
  const body = { url };
  if (options.maxPages) body.max_pages = parseInt(options.maxPages);
  if (options.maxDepth) body.max_depth = parseInt(options.maxDepth);
  if (options.scroll) body.scroll = true;
  if (options.subdomains) body.subdomains = true;

  return await apiCall('/api/clone', {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

async function checkAuth() {
  try {
    const result = await apiCall('/api/auth/check');
    return result; // { authenticated: true }
  } catch (e) {
    return { authenticated: false, error: e.message };
  }
}

async function saveCredentials(username, password) {
  await chrome.storage.sync.set({ username, password });
  return { ok: true };
}

// On install, set default config
chrome.runtime.onInstalled.addListener(() => {
  chrome.storage.sync.get(['server_url'], (data) => {
    if (!data.server_url) {
      chrome.storage.sync.set({ server_url: DEFAULT_SERVER });
    }
  });
});