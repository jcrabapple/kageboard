// Kageboard background service worker
// Handles API calls to the kageboard server and messaging from popup

const DEFAULT_SERVER = 'http://127.0.0.1:5000';

async function getServer() {
  const data = await chrome.storage.sync.get(['server_url']);
  return data.server_url || DEFAULT_SERVER;
}

async function apiCall(path, options = {}) {
  const server = await getServer();
  const url = `${server}${path}`;

  const resp = await fetch(url, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    },
    signal: AbortSignal.timeout(30000),
  });

  const body = await resp.json();
  if (!resp.ok) {
    throw new Error(body.error || `HTTP ${resp.status}`);
  }
  return body;
}

// Listen for messages from popup
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.action === 'clone') {
    handleClone(msg.url, msg.options || {}).then(sendResponse).catch(e => sendResponse({ error: e.message }));
    return true; // async sendResponse
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

// On install, set default config
chrome.runtime.onInstalled.addListener(() => {
  chrome.storage.sync.get(['server_url'], (data) => {
    if (!data.server_url) {
      chrome.storage.sync.set({ server_url: DEFAULT_SERVER });
    }
  });
});